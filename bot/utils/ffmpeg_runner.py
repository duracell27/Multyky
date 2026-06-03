import asyncio
import json
import math
import os

_TELEGRAM_SIZE_LIMIT = 1_900_000_000  # 1.9 GB — safe margin under Telegram's 2 GB cap
_AUDIO_BITRATE_BPS = 192_000          # reserved for audio track


async def run_ffmpeg(m3u8_url: str, output_path: str) -> bool:
    """
    Downloads m3u8 stream and produces a faststart-enabled mp4.
    Steps: download (copy) → faststart → compress if > 1.9 GB.
    Returns True if the file was re-encoded due to size, False otherwise.
    Raises RuntimeError if ffmpeg exits with non-zero code or times out.
    """
    raw_path = output_path + ".raw.mp4"

    try:
        # Step 1: download from m3u8
        await _run_cmd(
            ["ffmpeg", "-y", "-i", m3u8_url, "-c", "copy", raw_path],
            timeout=7200,
        )

        # Step 2: apply faststart (moves moov atom to front for instant playback)
        await _run_cmd(
            ["ffmpeg", "-y", "-i", raw_path, "-c", "copy", "-movflags", "+faststart", output_path],
            timeout=600,
        )
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)

    # Step 3: re-encode if file exceeds Telegram's upload limit
    if os.path.getsize(output_path) > _TELEGRAM_SIZE_LIMIT:
        await _compress_to_limit(output_path)
        return True
    return False


async def _compress_to_limit(path: str) -> None:
    """Re-encode file to fit under _TELEGRAM_SIZE_LIMIT using calculated video bitrate."""
    duration, _, _ = await get_video_info(path)
    if not duration:
        raise RuntimeError("Cannot determine video duration for compression")

    # target total bitrate in bps, subtract audio
    target_video_bps = int(_TELEGRAM_SIZE_LIMIT * 8 / duration) - _AUDIO_BITRATE_BPS
    if target_video_bps <= 0:
        raise RuntimeError(
            f"File is too long ({duration}s) to fit under "
            f"{_TELEGRAM_SIZE_LIMIT // 1_000_000} MB even at minimum bitrate"
        )

    compressed_path = path + ".compressed.mp4"
    try:
        await _run_cmd(
            [
                "ffmpeg", "-y", "-i", path,
                "-c:v", "libx264", "-b:v", str(target_video_bps),
                "-c:a", "aac", "-b:a", str(_AUDIO_BITRATE_BPS),
                "-movflags", "+faststart",
                compressed_path,
            ],
            timeout=7200,
        )
        os.replace(compressed_path, path)
    finally:
        if os.path.exists(compressed_path):
            os.remove(compressed_path)


async def get_video_info(path: str) -> tuple[int, int, int]:
    """Returns (duration_sec, width, height) via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-of", "json", path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    data = json.loads(stdout)
    streams = data.get("streams", [])
    if not streams:
        return 0, 0, 0
    s = streams[0]
    w = int(s.get("width", 0))
    h = int(s.get("height", 0))
    duration = math.ceil(float(s.get("duration", 0)))
    return duration, w, h


async def create_thumbnail(video_path: str, thumb_path: str) -> bool:
    """Extracts a frame at 5s as JPEG thumbnail. Returns True on success."""
    cmd = [
        "ffmpeg", "-y", "-ss", "5", "-i", video_path,
        "-vframes", "1", "-vf", "scale=320:-1",
        thumb_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return proc.returncode == 0 and os.path.exists(thumb_path)


async def _run_cmd(cmd: list[str], timeout: int) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"ffmpeg timed out after {timeout}s: {' '.join(cmd[:3])}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (code {proc.returncode}): {stderr.decode(errors='replace')[-500:]}"
        )

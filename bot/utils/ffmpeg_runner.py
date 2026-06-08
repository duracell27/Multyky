import asyncio
import json
import math
import os
import re
import shutil

_TELEGRAM_SIZE_LIMIT = 1_980_000_000
_AUDIO_BITRATE_BPS = 192_000
_TIME_RE = re.compile(r"out_time=(\d+):(\d+):(\d+\.\d+)")


def format_quality(width: int, height: int) -> str:
    """Return a human-readable quality label, e.g. '1080p' or '1920×1080'."""
    if not height:
        return "невідомо"
    if height >= 2160:
        return f"4K ({width}×{height})"
    if height >= 1080:
        return f"1080p ({width}×{height})"
    if height >= 720:
        return f"720p ({width}×{height})"
    if height >= 480:
        return f"480p ({width}×{height})"
    return f"{width}×{height}"


_MIN_FREE_BYTES = 8 * 1024 ** 3  # require at least 8 GB free (faststart needs ~2× file size)


async def run_ffmpeg(m3u8_url: str, output_path: str, on_compress_progress=None) -> bool:
    """
    Downloads m3u8 stream and produces a faststart-enabled mp4.
    Steps: download + faststart in one pass → compress if > limit.
    on_compress_progress: optional async callable(pct: int) called every ~5% during re-encode.
    Returns True if the file was re-encoded due to size, False otherwise.
    Raises RuntimeError if ffmpeg exits with non-zero code or times out.
    """
    free = shutil.disk_usage(os.path.dirname(output_path) or "/tmp").free
    if free < _MIN_FREE_BYTES:
        raise RuntimeError(
            f"Недостатньо місця на диску: {free // 1024**3} ГБ вільно, "
            f"потрібно мінімум {_MIN_FREE_BYTES // 1024**3} ГБ "
            f"(faststart потребує ~2× розмір файлу)"
        )

    await _run_cmd(
        ["ffmpeg", "-y", "-i", m3u8_url, "-c", "copy", "-movflags", "+faststart", output_path],
        timeout=7200,
    )

    if os.path.getsize(output_path) > _TELEGRAM_SIZE_LIMIT:
        await _compress_to_limit(output_path, on_compress_progress)
        return True
    return False


async def _compress_to_limit(path: str, progress_cb=None) -> None:
    """Re-encode file to fit under _TELEGRAM_SIZE_LIMIT using calculated video bitrate."""
    duration, _, _ = await get_video_info(path)
    if not duration:
        raise RuntimeError("Cannot determine video duration for compression")

    target_video_bps = int(_TELEGRAM_SIZE_LIMIT * 8 / duration) - _AUDIO_BITRATE_BPS
    if target_video_bps <= 0:
        raise RuntimeError(
            f"File is too long ({duration}s) to fit under "
            f"{_TELEGRAM_SIZE_LIMIT // 1_000_000} MB even at minimum bitrate"
        )

    compressed_path = path + ".compressed.mp4"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", path,
            "-c:v", "libx264", "-b:v", str(target_video_bps),
            "-c:a", "aac", "-b:a", str(_AUDIO_BITRATE_BPS),
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            compressed_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stderr_task = asyncio.create_task(proc.stderr.read())
        last_reported = -1

        try:
            async with asyncio.timeout(7200):
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    if progress_cb:
                        m = _TIME_RE.match(line.decode(errors="replace").strip())
                        if m:
                            elapsed = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                            pct = min(99, int(elapsed / duration * 100))
                            if pct >= last_reported + 5:
                                last_reported = pct
                                try:
                                    await progress_cb(pct)
                                except Exception:
                                    pass
                await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("ffmpeg compression timed out after 7200s")

        stderr = await stderr_task
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (code {proc.returncode}): {stderr.decode(errors='replace')[-500:]}"
            )

        if progress_cb:
            try:
                await progress_cb(100)
            except Exception:
                pass

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

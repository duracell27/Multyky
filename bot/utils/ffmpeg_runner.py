import asyncio
import os


async def run_ffmpeg(m3u8_url: str, output_path: str) -> None:
    """
    Downloads m3u8 stream and produces a faststart-enabled mp4.
    Two-step process: download → apply faststart (ensures seekable playback).
    Raises RuntimeError if ffmpeg exits with non-zero code or times out.
    """
    raw_path = output_path + ".raw.mp4"

    try:
        # Step 1: download from m3u8 (copy streams, no transcoding yet)
        await _run_cmd(
            ["ffmpeg", "-y", "-i", m3u8_url, "-c", "copy", raw_path],
            timeout=300,
        )

        # Step 2: transcode to H.264 + faststart for Telegram streaming compatibility
        await _run_cmd(
            [
                "ffmpeg", "-y", "-i", raw_path,
                "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path,
            ],
            timeout=600,
        )
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)


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

import asyncio
import os


async def run_ffmpeg(m3u8_url: str, output_path: str) -> None:
    """
    Downloads and remuxes an m3u8 stream to output_path using ffmpeg.
    Raises RuntimeError if ffmpeg exits with non-zero code.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", m3u8_url,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (code {proc.returncode}): {stderr.decode()[-500:]}"
        )

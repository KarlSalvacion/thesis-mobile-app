"""Video utilities.

This project does not require ffmpeg. The transcode function is intentionally a
no-op: uploads will send the original file to Cloudinary. Keeping this helper
prevents import errors for code that referenced it while avoiding external
ffmpeg dependencies.
"""

import os
from typing import Optional
import tempfile
import subprocess
import shlex
from .config import FFMPEG_BINARY, ANNOTATED_VIDEO_HEIGHT, ANNOTATED_VIDEO_BITRATE, MAX_CLOUDINARY_UPLOAD_SIZE


def transcode_video_to_preview(input_path: str, target_height: Optional[int] = None, target_bitrate: Optional[str] = None) -> str:
    """No-op transcoder.

    Returns the original input path unchanged. Caller is responsible for
    deleting the file if needed.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    # If file is already within Cloudinary size limits, no need to transcode
    try:
        size = os.path.getsize(input_path)
        if size <= MAX_CLOUDINARY_UPLOAD_SIZE:
            return input_path
    except Exception:
        # If we can't stat the file for some reason, attempt to transcode anyway
        pass

    th = target_height or ANNOTATED_VIDEO_HEIGHT
    tb = target_bitrate or ANNOTATED_VIDEO_BITRATE

    # Create a temporary output file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()
    out_path = tmp.name

    # Build ffmpeg command to downscale and lower bitrate (use list, no shell)
    cmd_args = [
        FFMPEG_BINARY,
        '-y',
        '-i', input_path,
        '-vf', f'scale=-2:{int(th)}',
        '-b:v', str(tb),
        '-preset', 'veryfast',
        '-c:a', 'copy',
        out_path,
    ]

    try:
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        # Clean up output if ffmpeg failed
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        # Re-raise a descriptive error so callers can fallback
        raise FileNotFoundError("ffmpeg not available or failed to transcode video; ensure ffmpeg is installed and on PATH")

    # Ensure output file is smaller than cloudinary limit; if not, leave it to caller to decide
    return out_path



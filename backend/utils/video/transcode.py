import os
import subprocess
import tempfile
from typing import Optional

from config.settings import ANNOTATED_VIDEO_BITRATE, ANNOTATED_VIDEO_HEIGHT, FFMPEG_BINARY, MAX_CLOUDINARY_UPLOAD_SIZE


def transcode_video_to_preview(input_path: str, target_height: Optional[int] = None, target_bitrate: Optional[str] = None) -> str:
    """Transcode/downscale video if it exceeds Cloudinary size limits."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f'Input video not found: {input_path}')

    try:
        size = os.path.getsize(input_path)
        if size <= MAX_CLOUDINARY_UPLOAD_SIZE:
            return input_path
    except Exception:
        pass

    th = target_height or ANNOTATED_VIDEO_HEIGHT
    tb = target_bitrate or ANNOTATED_VIDEO_BITRATE

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    tmp.close()
    out_path = tmp.name

    cmd_args = [
        FFMPEG_BINARY,
        '-y',
        '-i',
        input_path,
        '-vf',
        f'scale=-2:{int(th)}',
        '-b:v',
        str(tb),
        '-preset',
        'veryfast',
        '-c:a',
        'copy',
        out_path,
    ]

    try:
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        raise FileNotFoundError('ffmpeg not available or failed to transcode video; ensure ffmpeg is installed and on PATH')

    return out_path

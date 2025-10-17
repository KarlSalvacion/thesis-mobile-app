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


def get_video_fps(video_path: str) -> float:
    """Get the FPS (frames per second) of a video file using ffprobe.
    
    Returns the video FPS, or DEFAULT_VIDEO_FPS if unable to detect.
    """
    try:
        from .config import DEFAULT_VIDEO_FPS
        # Use ffprobe to get video metadata
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        
        # Parse the frame rate (usually in format "30/1" or "30000/1001")
        if '/' in result:
            num, den = result.split('/')
            fps = float(num) / float(den)
        else:
            fps = float(result)
        
        # Sanity check: FPS should be between 1 and 120
        if 1 <= fps <= 120:
            print(f'Detected original video FPS: {fps:.2f}')
            return fps
        else:
            print(f'Unusual FPS detected ({fps}), using default: {DEFAULT_VIDEO_FPS}')
            return float(DEFAULT_VIDEO_FPS)
            
    except Exception as e:
        print(f'Could not detect video FPS: {e}, using default: {DEFAULT_VIDEO_FPS}')
        from .config import DEFAULT_VIDEO_FPS
        return float(DEFAULT_VIDEO_FPS)


def get_video_duration(video_path: str) -> Optional[float]:
    """Get the duration of a video file in seconds using ffprobe.
    
    Returns the video duration in seconds, or None if unable to detect.
    """
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        duration = float(result)
        print(f'Detected video duration: {duration:.2f} seconds')
        return duration
    except Exception as e:
        print(f'Could not detect video duration: {e}')
        return None


def get_video_frame_count(video_path: str) -> Optional[int]:
    """Get the total number of frames in a video using ffprobe.
    
    Returns the frame count, or None if unable to detect.
    """
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-count_frames',
            '-show_entries', 'stream=nb_read_frames',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        frame_count = int(result)
        print(f'Detected video frame count: {frame_count} frames')
        return frame_count
    except Exception as e:
        # Fallback: calculate from duration and FPS
        print(f'Could not count frames directly: {e}, calculating from duration and FPS')
        try:
            duration = get_video_duration(video_path)
            fps = get_video_fps(video_path)
            if duration and fps:
                frame_count = int(duration * fps)
                print(f'Calculated frame count: {frame_count} frames')
                return frame_count
        except Exception:
            pass
        return None

import subprocess
from typing import Optional

try:
    import cv2 as _cv2

    _HAS_OPENCV = True
except ImportError:
    _HAS_OPENCV = False
    _cv2 = None


def get_video_codec(video_path: str) -> str:
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        codec = result.lower()
        print(f'Detected video codec: {codec}')
        return codec
    except Exception as e:
        print(f'Could not detect video codec: {e}')
        return 'unknown'


def needs_reencoding(video_path: str) -> bool:
    codec = get_video_codec(video_path)
    incompatible_codecs = ['hevc', 'h265', 'vp9', 'av1', 'mpeg2video']

    if codec in incompatible_codecs:
        print(f'Video codec {codec} is incompatible with Roboflow, re-encoding required')
        return True

    print(f'Video codec {codec} is compatible with Roboflow')
    return False


def get_video_fps(video_path: str) -> float:
    if _HAS_OPENCV and _cv2 is not None:
        try:
            cap = _cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(_cv2.CAP_PROP_FPS)
                cap.release()
                if 1 <= fps <= 120:
                    print(f'Detected original video FPS (OpenCV): {fps:.2f}')
                    return fps
        except Exception as e:
            print(f'OpenCV FPS detection failed: {e}, trying ffprobe...')

    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()

        if '/' in result:
            num, den = result.split('/')
            fps = float(num) / float(den)
        else:
            fps = float(result)

        if 1 <= fps <= 120:
            print(f'Detected original video FPS (ffprobe): {fps:.2f}')
            return fps

        print(f'Unusual FPS detected ({fps}), using fallback: 30.0')
        return 30.0

    except Exception as e:
        print(f'Could not detect video FPS: {e}, using fallback: 30.0')
        return 30.0


def get_video_duration(video_path: str) -> Optional[float]:
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        duration = float(result)
        print(f'Detected video duration: {duration:.2f} seconds')
        return duration
    except Exception as e:
        print(f'Could not detect video duration: {e}')
        return None


def get_video_frame_count(video_path: str) -> Optional[int]:
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-count_frames',
            '-show_entries', 'stream=nb_read_frames',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        frame_count = int(result)
        print(f'Detected video frame count: {frame_count} frames')
        return frame_count
    except Exception as e:
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

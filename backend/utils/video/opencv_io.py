import os
import tempfile
from typing import List, Optional

try:
    import cv2 as _cv2
    import numpy as _np

    HAS_OPENCV = True
    print('OpenCV (cv2) successfully imported for video processing')
except ImportError:
    HAS_OPENCV = False
    _cv2 = None
    _np = None
    print('OpenCV not available, will use FFmpeg fallback for video processing')


def extract_frames_cv2(video_path: str, target_fps: Optional[float] = None, max_frames: int = 10000) -> Optional[List[str]]:
    """Extract frames via OpenCV. Returns None when OpenCV is unavailable."""
    if not HAS_OPENCV or _cv2 is None:
        print('OpenCV not available, caller should use FFmpeg fallback')
        return None

    try:
        cap = _cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f'Failed to open video with OpenCV: {video_path}')
            return None

        video_fps = cap.get(_cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
        print(f'OpenCV video info: {video_fps:.2f} FPS, {total_frames} total frames')

        if target_fps is None or target_fps >= video_fps:
            frame_indices = list(range(min(total_frames, max_frames)))
            effective_fps = video_fps
        else:
            video_duration = total_frames / video_fps
            num_frames = int(video_duration * target_fps)
            num_frames = min(num_frames, max_frames)

            frame_indices = []
            for i in range(num_frames):
                timestamp = i / target_fps
                frame_idx = round(timestamp * video_fps)
                if frame_idx < total_frames:
                    frame_indices.append(frame_idx)
            effective_fps = target_fps

        print(f'Extracting frames at {effective_fps:.2f} FPS ({len(frame_indices)} frames total)')

        tmpdir = tempfile.mkdtemp(prefix='cv2_frames_')
        frame_paths = []

        frame_idx = 0
        extracted_count = 0
        frame_indices_set = set(frame_indices)

        while cap.isOpened() and extracted_count < len(frame_indices):
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx in frame_indices_set:
                frame_path = os.path.join(tmpdir, f'frame_{extracted_count + 1:06d}.jpg')
                _cv2.imwrite(frame_path, frame, [_cv2.IMWRITE_JPEG_QUALITY, 95])
                frame_paths.append(frame_path)
                extracted_count += 1

            frame_idx += 1

        cap.release()
        print(f'OpenCV extracted {extracted_count} frames to {tmpdir}')
        return frame_paths

    except Exception as e:
        print(f'Error in OpenCV frame extraction: {e}')
        import traceback

        traceback.print_exc()
        return None


def stitch_video_cv2(frames_dir: str, fps: float, output_path: str, frame_pattern: str = 'ann_%06d.jpg', target_size_mb: int = 80) -> bool:
    """Stitch frame images into video via OpenCV with adaptive scaling."""
    if not HAS_OPENCV or _cv2 is None:
        print('OpenCV not available for video stitching')
        return False

    try:
        import re

        pattern_regex = frame_pattern.replace('%06d', r'(\d{6})')
        frame_files = []
        for filename in os.listdir(frames_dir):
            if re.match(pattern_regex.replace('.jpg', r'\.jpg$'), filename):
                frame_files.append(filename)

        frame_files = sorted(frame_files)
        frame_count = len(frame_files)
        if frame_count == 0:
            print(f'No frames found matching pattern {frame_pattern} in {frames_dir}')
            return False

        print(f'OpenCV stitching {frame_count} frames at {fps:.2f} FPS')

        first_frame_path = os.path.join(frames_dir, frame_files[0])
        first_frame = _cv2.imread(first_frame_path)
        if first_frame is None:
            print(f'Failed to read first frame: {first_frame_path}')
            return False

        height, width = first_frame.shape[:2]
        estimated_size_mb = (frame_count * 165) / 1024

        if estimated_size_mb > target_size_mb:
            scale_factor = ((target_size_mb * 0.80) / estimated_size_mb) ** 0.5
            width = int(width * scale_factor)
            height = int(height * scale_factor)
            print(f'Scaling down to {width}x{height} to stay under {target_size_mb}MB (estimated: {estimated_size_mb:.1f}MB)')
        else:
            print(f'No scaling needed, estimated size: {estimated_size_mb:.1f}MB')

        if width % 2 != 0:
            width = width - 1
        if height % 2 != 0:
            height = height - 1

        os.environ['OPENCV_VIDEOIO_DEBUG'] = '0'

        codecs_to_try = [
            ('mp4v', 'MPEG-4 (mp4v)'),
            ('avc1', 'H.264 (avc1)'),
        ]

        out = None
        used_codec = None

        for codec_fourcc, codec_name in codecs_to_try:
            try:
                fourcc = _cv2.VideoWriter_fourcc(*codec_fourcc)
                test_out = _cv2.VideoWriter(output_path, fourcc, fps, (width, height))
                if test_out.isOpened():
                    out = test_out
                    used_codec = codec_name
                    break
                test_out.release()
            except Exception:
                pass

        if out is None or not out.isOpened():
            fourcc = _cv2.VideoWriter_fourcc(*'mp4v')
            out = _cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            used_codec = 'MPEG-4 (mp4v)'

        if not out.isOpened():
            print('Failed to open VideoWriter')
            return False

        for i, filename in enumerate(frame_files):
            frame_path = os.path.join(frames_dir, filename)
            frame = _cv2.imread(frame_path)

            if frame is None:
                print(f'Warning: Failed to read frame {filename}, skipping')
                continue

            frame = _cv2.resize(frame, (width, height))
            out.write(frame)

            if (i + 1) % 100 == 0:
                print(f'Stitched {i + 1}/{frame_count} frames...')

        out.release()
        print(f'OpenCV video stitching completed: {output_path}')

        if os.path.exists(output_path):
            compressed_size = os.path.getsize(output_path)
            size_mb = compressed_size / (1024 * 1024)
            if size_mb <= target_size_mb:
                print(f'Compressed video: {size_mb:.2f} MB (under {target_size_mb}MB limit)')
            else:
                print(f'Video size: {size_mb:.2f} MB (over {target_size_mb}MB, may need further compression)')

            print(f'Codec: {used_codec}, Resolution: {width}x{height}, FPS: {fps}')
            return True

        print('Output video file not created')
        return False

    except Exception as e:
        print(f'Error in OpenCV video stitching: {e}')
        import traceback

        traceback.print_exc()
        return False

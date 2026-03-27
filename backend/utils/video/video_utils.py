"""Compatibility facade for video utilities.

Implementation modules:
- utils.video.transcode
- utils.video.compression
- utils.video.opencv_io
- utils.video_probe
- utils.video_tracking
"""

from backend.utils.video.transcode import transcode_video_to_preview
from backend.utils.video.compression import compress_for_inference
from backend.utils.video.opencv_io import extract_frames_cv2, stitch_video_cv2
from backend.utils.video.video_probe import (
    get_video_codec,
    needs_reencoding,
    get_video_fps,
    get_video_duration,
    get_video_frame_count,
)
from backend.utils.video.video_tracking import (
    MotionDetectionSkipper,
    ObjectTracker,
    TemporalConsistencyFilter,
    BackgroundSubtractor,
)

__all__ = [
    'transcode_video_to_preview',
    'compress_for_inference',
    'get_video_codec',
    'needs_reencoding',
    'get_video_fps',
    'get_video_duration',
    'get_video_frame_count',
    'extract_frames_cv2',
    'stitch_video_cv2',
    'MotionDetectionSkipper',
    'ObjectTracker',
    'TemporalConsistencyFilter',
    'BackgroundSubtractor',
]

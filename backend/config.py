# Roboflow & Cloudinary configuration (no environment variables needed)
"""
Fill in your own Roboflow and Cloudinary credentials below.
"""

# Your Roboflow API key
ROBOFLOW_API_KEY = "RpeaIrOXAbnFIfwEbbdB"

# Your Roboflow project name
ROBOFLOW_PROJECT = "thesis-online-gathered-ds-y6uy4"

# Optional: specify workspace explicitly if API key has multiple workspaces
# Leave blank to use default workspace associated with the API key
# Roboflow workspace slug (not numeric id). If unknown, leave empty.
ROBOFLOW_WORKSPACE = ""

# Model version to use (e.g., 9 for "thesis-online-gathered-ds-y6uy4/9")
ROBOFLOW_VERSION = "13"

# Default inference parameters
DEFAULT_CONFIDENCE = 0.3  # Match Roboflow preview defaults
DEFAULT_OVERLAP = 0.7  # Higher overlap threshold = more aggressive NMS, fewer duplicate boxes (Roboflow preview uses ~0.7)
DEFAULT_VIDEO_FPS = 30  # Balanced FPS for API stability (too high causes API timeouts)

# Inference optimization settings
USE_LOCAL_INFERENCE = False  # Use Roboflow hosted API (no local inference package needed on Render)
COMPRESS_FRAMES_BEFORE_INFERENCE = True  # Reduce image size before sending (faster upload)
INFERENCE_IMAGE_SIZE = 640  # Resize to this width/height before inference (640 is optimal for YOLO)

# Frame interval for video detection (process every Nth frame for speed)
# 1 = detect on every frame, 2 = detect every 2nd frame, 3 = every 3rd frame, etc.
# Higher values = faster processing but may skip objects that stay in frame
# NOTE: The output video will still contain ALL frames at original FPS
FRAME_INTERVAL = 1  # Process every frame for maximum accuracy (no skipping)

# Smart frame skipping: Skip frames only if no recent detections
# Helps avoid missing objects that stay in frame
ENABLE_SMART_SKIP = True  # Enable adaptive frame skipping
SMART_SKIP_WINDOW = 15  # If detection found, process next N frames fully

# Video annotation optimization mode
# 'fast' = Only process frames at detection FPS, use FFmpeg drawtext overlay (10-20x faster)
# 'quality' = Extract all frames, annotate individually, stitch back (slower, higher quality)
VIDEO_ANNOTATION_MODE = 'quality'  # Use 'quality' for better compatibility with long videos

# Maximum annotations to show (prevent FFmpeg command line overflow on Windows)
MAX_ANNOTATIONS_FAST_MODE = 50  # Limit annotations in fast mode to prevent command line overflow

# Maximum frames to process (set high to avoid truncating videos)
MAX_VIDEO_FRAMES = 10000  # Support videos up to 5+ minutes at 30 FPS

# Use original video FPS for annotated output (RECOMMENDED)
# True = Output video has same FPS, length, and smoothness as original
# False = Output video plays at detection FPS (slower, choppy playback)
USE_ORIGINAL_FPS = True  # Keep True for full-length video with annotations

# Force local frame sampling for videos (bypass Roboflow video API)
# Set to True only if Roboflow video API consistently returns 0 frames
FORCE_LOCAL_VIDEO_PROCESSING = False

# ============================================================================
# Advanced OpenCV Features (require opencv-python-headless installed)
# ============================================================================

# Object tracking - Track detected objects across frames for smoother bounding boxes
# Reduces jitter and helps maintain consistent detection of the same object
ENABLE_OBJECT_TRACKING = True  # Uses OpenCV KCF tracker
TRACKING_CONFIDENCE_DECAY = 0.95  # How quickly confidence decays when object not detected (0.9-0.99)

# Temporal consistency filtering - Require objects to appear in multiple frames
# Helps reduce false positives from one-frame detection errors
ENABLE_TEMPORAL_FILTER = True
TEMPORAL_MIN_APPEARANCES = 2  # Object must appear in at least N frames to be valid
TEMPORAL_MAX_GAP = 5  # Maximum frames between appearances

# Background subtraction - Identify moving vs static objects
# Useful for filtering out static background elements (e.g., posts, fences)
ENABLE_BACKGROUND_SUBTRACTION = True
BG_LEARNING_RATE = 0.01  # How quickly background model adapts (0.001-0.1)
BG_VAR_THRESHOLD = 16  # Foreground detection sensitivity (lower = more sensitive)

# Motion-based frame skipping - Skip frames with no scene changes
# More sophisticated than FRAME_INTERVAL - detects actual motion
ENABLE_MOTION_DETECTION = True
MOTION_PIXEL_THRESHOLD = 3.0  # Pixel difference threshold (0-255)
MOTION_MIN_CHANGED_PIXELS = 1500  # Minimum pixels changed to consider as motion

# ============================================================================
# Video Processing Backend
# ============================================================================
# OpenCV is now the PRIMARY video processing engine (no FFmpeg required for detection)
# - Frame extraction: cv2.VideoCapture (2-3x faster than FFmpeg)
# - Video stitching: cv2.VideoWriter (2-3x faster than FFmpeg)
# FFmpeg is only used for:
#   - Video metadata (FPS, duration) - falls back to OpenCV if unavailable
#   - Video compression (transcode_video_to_preview) - optional feature
# 
# To use this system: pip install opencv-python-headless (already in requirements.txt)
# FFmpeg is NO LONGER REQUIRED for object detection workflows

# Path to ffmpeg binary (OPTIONAL - only needed for video compression)
# Leave as "ffmpeg" if you have it installed, or set to None to skip FFmpeg entirely
FFMPEG_BINARY = "ffmpeg"  # e.g. "C:/ffmpeg/bin/ffmpeg.exe" or None

# Cloudinary configuration
CLOUDINARY_URL = ""  # Optional: e.g. cloudinary://<api_key>:<api_secret>@<cloud_name>
# Or specify discrete credentials if CLOUDINARY_URL is blank
CLOUDINARY_CLOUD_NAME = "dl8ifxbsd"
CLOUDINARY_API_KEY = "867463359734984"
CLOUDINARY_API_SECRET = "ScOI-O32MQU8EkSOdS8yMPfLA_g"

# Compression / Delivery preferences
# Max width for annotated images
ANNOTATED_IMAGE_MAX_WIDTH = 1280
# JPEG quality for annotated images
ANNOTATED_IMAGE_JPEG_QUALITY = 70
# Target video height and bitrate for annotated previews
ANNOTATED_VIDEO_HEIGHT = 1080  # 1080p for better quality
ANNOTATED_VIDEO_BITRATE = "8000k"  # 8 Mbps for high quality

# Path to ffmpeg binary (leave as "ffmpeg" if added to PATH)
FFMPEG_BINARY = "ffmpeg"  # e.g. "C:/ffmpeg/bin/ffmpeg.exe"

# Tip: If you don't want to modify the system PATH, set the absolute ffmpeg
# executable path here. Example on Windows:
#
# FFMPEG_BINARY = r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
#
# Or add ffmpeg to your PATH (recommended) and leave FFMPEG_BINARY as "ffmpeg".

# Maximum upload size allowed by Cloudinary accounts (bytes). Default: 100 MB
MAX_CLOUDINARY_UPLOAD_SIZE = 104_857_600
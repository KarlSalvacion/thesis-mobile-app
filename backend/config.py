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
ROBOFLOW_VERSION = "12"

# Default inference parameters
DEFAULT_CONFIDENCE = 0.1  # Match Roboflow preview defaults
DEFAULT_OVERLAP = 0.45
DEFAULT_VIDEO_FPS = 3  # fps for video frame sampling for detection (lower = faster)

# Inference optimization settings
USE_LOCAL_INFERENCE = False  # Use Roboflow hosted API (no local inference package needed on Render)
COMPRESS_FRAMES_BEFORE_INFERENCE = True  # Reduce image size before sending (faster upload)
INFERENCE_IMAGE_SIZE = 640  # Resize to this width/height before inference (640 is optimal for YOLO)

# Frame interval for video detection (process every Nth frame for speed)
# 1 = detect on every frame, 2 = detect every 2nd frame, 3 = every 3rd frame, etc.
# Higher values = faster processing but may skip objects that stay in frame
# NOTE: The output video will still contain ALL frames at original FPS
FRAME_INTERVAL = 2  # Process every 3rd frame for 3x speedup (balanced accuracy/speed)

# Smart frame skipping: Skip frames only if no recent detections
# Helps avoid missing objects that stay in frame
ENABLE_SMART_SKIP = True  # Enable adaptive frame skipping
SMART_SKIP_WINDOW = 5  # If detection found, process next N frames fully

# Video annotation optimization mode
# 'fast' = Only process frames at detection FPS, use FFmpeg drawtext overlay (10-20x faster)
# 'quality' = Extract all frames, annotate individually, stitch back (slower, higher quality)
VIDEO_ANNOTATION_MODE = 'fast'  # Use 'fast' for production, 'quality' for demos

# Maximum frames to process (set high to avoid truncating videos)
MAX_VIDEO_FRAMES = 10000  # Support videos up to 5+ minutes at 30 FPS

# Use original video FPS for annotated output (RECOMMENDED)
# True = Output video has same FPS, length, and smoothness as original
# False = Output video plays at detection FPS (slower, choppy playback)
USE_ORIGINAL_FPS = True  # Keep True for full-length video with annotations

# Force local frame sampling for videos (bypass Roboflow video API)
# Set to True only if Roboflow video API consistently returns 0 frames
FORCE_LOCAL_VIDEO_PROCESSING = False

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
ANNOTATED_VIDEO_HEIGHT = 720
ANNOTATED_VIDEO_BITRATE = "4000k"

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
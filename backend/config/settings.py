import os
from dotenv import load_dotenv

load_dotenv()  

# Detect deployment environment
IS_RENDER = os.getenv('RENDER') is not None
IS_LOCAL = not IS_RENDER

# Your Roboflow API key
ROBOFLOW_API_KEY = os.getenv('ROBOFLOW_API_KEY')

# Your Roboflow project name
ROBOFLOW_PROJECT = os.getenv('ROBOFLOW_PROJECT') 

# Optional: specify workspace explicitly if API key has multiple workspaces
# Leave blank to use default workspace associated with the API key
# Roboflow workspace slug (not numeric id). If unknown, leave empty.
ROBOFLOW_WORKSPACE = ""

# Model version to use (e.g., 2 for "thesis_testing-gf8bn/2")
ROBOFLOW_VERSION = "1"

# Default inference parameters
DEFAULT_CONFIDENCE = 0.35  # Match Roboflow preview defaults
DEFAULT_OVERLAP = 0.7  # Higher overlap threshold = more aggressive NMS, fewer duplicate boxes (Roboflow preview uses ~0.7)
DEFAULT_VIDEO_FPS = 10  # 10 FPS for good balance between speed and smoothness. Set to None to auto-detect.

# Inference optimization settings
USE_LOCAL_INFERENCE = False  # Use Roboflow hosted API (no local inference package needed on Render)
COMPRESS_FRAMES_BEFORE_INFERENCE = True  # Reduce image size before sending (faster upload)
INFERENCE_IMAGE_SIZE = 640  # Resize to this width/height before inference (640 is optimal for YOLO)

# Compression strategy (environment-aware)
ENABLE_PRECOMPRESSION = True  # Enable FFmpeg compression for large files
MAX_VIDEO_SIZE_WITHOUT_COMPRESSION_MB = 100  # Files >100 MB will be compressed with FFmpeg
FRAME_INTERVAL = 1  # Process every frame for maximum accuracy (no skipping)

# Smart frame skipping: Skip frames only if no recent detections
# Helps avoid missing objects that stay in frame
ENABLE_SMART_SKIP = True  # Enable adaptive frame skipping
SMART_SKIP_WINDOW = 15  # If detection found, process next N frames fully

# Video annotation optimization mode
VIDEO_ANNOTATION_MODE = 'quality' # Choose 'fast' or 'quality' based on your needs

# Detection persistence for video annotations (how long bounding boxes stay visible)
DETECTION_PERSISTENCE_FRAMES = None  # Auto-calculate based on FPS (original_fps / detection_fps)
DETECTION_PERSISTENCE_MULTIPLIER = 1.0  # Multiply by this for overlap (1.0 = seamless, 1.5 = 50% overlap)


# Maximum frames to process (set high to avoid truncating videos)
MAX_VIDEO_FRAMES = 10000  # Support videos up to 5+ minutes at 30 FPS

# Use original video FPS for annotated output (RECOMMENDED)
USE_ORIGINAL_FPS = True  # Keep True for full-length video with annotations

# Force local frame sampling for videos (bypass Roboflow video API)
# Set to True only if Roboflow video API consistently returns 0 frames
FORCE_LOCAL_VIDEO_PROCESSING = False

# ============================================================================
# Advanced OpenCV Features (require opencv-python-headless installed)
# ============================================================================

ENABLE_OBJECT_TRACKING = False  # Disabled for static weed detection
TRACKING_CONFIDENCE_DECAY = 0.95  # How quickly confidence decays when object not detected (0.9-0.99)

# Temporal consistency filtering - Require objects to appear in multiple frames
# Helps reduce false positives from one-frame detection errors
ENABLE_TEMPORAL_FILTER = True
TEMPORAL_MIN_APPEARANCES = 2  # Object must appear in at least N frames to be valid
TEMPORAL_MAX_GAP = 5  # Maximum frames between appearances

# Background subtraction - Identify moving vs static objects
# NOTE: Disabled for drone weed detection since weeds ARE the static background
# This feature is for filtering out static objects when detecting moving ones
ENABLE_BACKGROUND_SUBTRACTION = False  # Disabled - weeds are part of the ground/background
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

FFMPEG_BINARY = "ffmpeg"  # e.g. "C:/ffmpeg/bin/ffmpeg.exe" or None

# Cloudinary configuration
CLOUDINARY_URL = ""  # Optional: e.g. cloudinary://<api_key>:<api_secret>@<cloud_name>
# Or specify discrete credentials if CLOUDINARY_URL is blank
CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')

# ============================================================================
# Video Compression Configuration
# ============================================================================

ANNOTATED_IMAGE_MAX_WIDTH = 1280
ANNOTATED_IMAGE_JPEG_QUALITY = 70
ANNOTATED_VIDEO_HEIGHT = 1080  # 1080p for better quality
ANNOTATED_VIDEO_BITRATE = "8000k"  # 8 Mbps for high quality

FFMPEG_BINARY = "ffmpeg"  # e.g. "C:/ffmpeg/bin/ffmpeg.exe"

# Maximum upload size allowed by Cloudinary accounts (bytes). Default: 100 MB
MAX_CLOUDINARY_UPLOAD_SIZE = 104_857_600

# Render.com Standard Plan Optimizations (2GB RAM, 1 CPU)
MAX_UPLOAD_SIZE_MB = 200  # Reduced from unlimited to 200MB
MAX_CONCURRENT_JOBS = 1   # Process one job at a time to avoid OOM
ENABLE_MEMORY_MONITORING = True  # Monitor memory usage
MEMORY_CLEANUP_INTERVAL = 300  # Clean up temp files every 5 minutes

# Video processing limits for Render.com
MAX_VIDEO_DURATION_SECONDS = 300  # 5 minutes max
MAX_VIDEO_RESOLUTION = 1080  # 1080p max (down from 1440p)
COMPRESSION_AGGRESSIVE_MODE = True  # More aggressive compression

# ============================================================================
# PostgreSQL Database Configuration
# ============================================================================

DATABASE_URL = os.getenv('DATABASE_URL')  # e.g., 'postgresql://user:password@host:port/dbname'


DB_POOL_MIN_CONN = 1  # Minimum connections in pool
DB_POOL_MAX_CONN = 10  # Maximum connections in pool
DB_POOL_TIMEOUT = 30  # Connection timeout in seconds
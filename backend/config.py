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
ROBOFLOW_WORKSPACE = ""

# Model version to use
ROBOFLOW_VERSION = "11"

# Default inference parameters
DEFAULT_CONFIDENCE = 0.1  # Extremely low threshold to catch any detections
DEFAULT_OVERLAP = 0.1
DEFAULT_VIDEO_FPS = 2  # fps for Roboflow video inference (batch-video)

# Maximum frames to process when post-processing results locally
MAX_VIDEO_FRAMES = 120

# Force local frame sampling for videos (bypass Roboflow video API)
# Set to True if Roboflow video API consistently returns 0 frames
FORCE_LOCAL_VIDEO_PROCESSING = True  # Enable this to bypass Roboflow video API

# Video preprocessing options to improve detection (similar to Roboflow's preprocessing)
ENABLE_VIDEO_PREPROCESSING = True  # Enable preprocessing to improve detection
PREPROCESSING_DENOISE = True  # Apply denoising filter
PREPROCESSING_SHARPEN = True  # Apply sharpening filter
PREPROCESSING_CONTRAST = True  # Apply contrast enhancement
PREPROCESSING_BRIGHTNESS = 1.1  # Brightness multiplier (1.0 = no change)
PREPROCESSING_CONTRAST_FACTOR = 1.2  # Contrast factor (1.0 = no change)

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
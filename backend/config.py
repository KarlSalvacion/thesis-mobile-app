# Roboflow & Cloudinary configuration (no environment variables needed)
"""
Fill in your own Roboflow and Cloudinary credentials below.
"""

# Your Roboflow API key
ROBOFLOW_API_KEY = "RpeaIrOXAbnFIfwEbbdB"

# Your Roboflow project name
ROBOFLOW_PROJECT = "thesis-online-gathered-ds-y6uy4"

# Model version to use
ROBOFLOW_VERSION = "9"

# Default inference parameters
DEFAULT_CONFIDENCE = 13
DEFAULT_OVERLAP = 50
DEFAULT_VIDEO_FPS = 0.25  # frames per second (lower for faster processing)

# Maximum frames to process for video inference (to reduce memory usage)
MAX_VIDEO_FRAMES = 60  # restore default cap to improve recall

# Video optimization settings
ENABLE_SMART_SAMPLING = True
SAMPLE_INTERVAL = 30

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
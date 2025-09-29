# Roboflow API Configuration
# Update these values with your Roboflow project details

# Your Roboflow API key
ROBOFLOW_API_KEY = "RpeaIrOXAbnFIfwEbbdB"

# Your Roboflow project name
ROBOFLOW_PROJECT = "thesis-online-gathered-ds-y6uy4"

# Model version to use
ROBOFLOW_VERSION = "1"

# Default inference parameters
DEFAULT_CONFIDENCE = 40
DEFAULT_OVERLAP = 30
DEFAULT_VIDEO_FPS = 0.5  # Process only 1 frame every 2 seconds (was 2 fps)

# Maximum frames to process for video inference (to reduce memory usage)
MAX_VIDEO_FRAMES = 60  # Process maximum 60 frames (was 300)

# Video optimization settings
ENABLE_SMART_SAMPLING = True  # Enable intelligent frame sampling
SAMPLE_INTERVAL = 30  # Sample every 30th frame (roughly 1 frame per second at 30fps video)
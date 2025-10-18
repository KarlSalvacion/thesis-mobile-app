import os
import time
import tempfile
import subprocess
import shutil
from typing import Any, Dict, List, Optional, Tuple

# Import config early and expose API key to environment before importing inference SDK
from .config import (
    ROBOFLOW_API_KEY,
    ROBOFLOW_PROJECT,
    ROBOFLOW_VERSION,
    ROBOFLOW_WORKSPACE,
    DEFAULT_CONFIDENCE,
    DEFAULT_OVERLAP,
    DEFAULT_VIDEO_FPS,
    MAX_VIDEO_FRAMES,
    FORCE_LOCAL_VIDEO_PROCESSING,
    FRAME_INTERVAL,
    USE_ORIGINAL_FPS,
    USE_LOCAL_INFERENCE,
    COMPRESS_FRAMES_BEFORE_INFERENCE,
    INFERENCE_IMAGE_SIZE,
    ENABLE_SMART_SKIP,
    SMART_SKIP_WINDOW,
)
try:
    from .config import (
        ENABLE_OBJECT_TRACKING,
        TRACKING_CONFIDENCE_DECAY,
        ENABLE_TEMPORAL_FILTER,
        TEMPORAL_MIN_APPEARANCES,
        TEMPORAL_MAX_GAP,
        ENABLE_BACKGROUND_SUBTRACTION,
        BG_LEARNING_RATE,
        BG_VAR_THRESHOLD,
        ENABLE_MOTION_DETECTION,
        MOTION_PIXEL_THRESHOLD,
        MOTION_MIN_CHANGED_PIXELS,
    )
except ImportError:
    # Default values if not in config
    ENABLE_OBJECT_TRACKING = True
    TRACKING_CONFIDENCE_DECAY = 0.95
    ENABLE_TEMPORAL_FILTER = True
    TEMPORAL_MIN_APPEARANCES = 2
    TEMPORAL_MAX_GAP = 5
    ENABLE_BACKGROUND_SUBTRACTION = True
    BG_LEARNING_RATE = 0.01
    BG_VAR_THRESHOLD = 16
    ENABLE_MOTION_DETECTION = True
    MOTION_PIXEL_THRESHOLD = 3.0
    MOTION_MIN_CHANGED_PIXELS = 1500

try:
    from .config import VIDEO_ANNOTATION_MODE
except ImportError:
    VIDEO_ANNOTATION_MODE = 'fast'  # Default to fast mode
from .config import FFMPEG_BINARY
from .video_utils import get_video_fps, get_video_duration, get_video_frame_count
from .video_utils import extract_frames_cv2, stitch_video_cv2, MotionDetectionSkipper
from .video_utils import ObjectTracker, TemporalConsistencyFilter, BackgroundSubtractor

# Ensure the RF API key is in environment for any downstream SDKs
if ROBOFLOW_API_KEY and not os.environ.get('ROBOFLOW_API_KEY'):
    os.environ['ROBOFLOW_API_KEY'] = ROBOFLOW_API_KEY

from roboflow import Roboflow
# Disable optional InferencePipeline path to avoid missing import warnings
_HAS_RF_INFERENCE = False

# Initialize local inference if enabled
_local_model = None
if USE_LOCAL_INFERENCE:
    try:
        print("Initializing local inference server...")
        from inference import get_model
        # Build model ID correctly (no leading slash if workspace is empty)
        if ROBOFLOW_WORKSPACE:
            model_id = f"{ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT}/{ROBOFLOW_VERSION}"
        else:
            model_id = f"{ROBOFLOW_PROJECT}/{ROBOFLOW_VERSION}"
        _local_model = get_model(model_id=model_id, api_key=ROBOFLOW_API_KEY)
        print(f"Local inference model loaded: {model_id}")
        _HAS_RF_INFERENCE = True
    except ImportError as e:
        print(f"Warning: Could not import 'inference' package: {e}")
        print("Install with: pip install inference")
        print("Falling back to Roboflow cloud API...")
    except Exception as e:
        print(f"Warning: Could not initialize local inference: {e}")
        print("Falling back to Roboflow cloud API...")


# Initialize Roboflow client (for cloud API fallback or when local inference disabled)
rf = Roboflow(api_key=ROBOFLOW_API_KEY)
try:
    ws = rf.workspace(ROBOFLOW_WORKSPACE) if ROBOFLOW_WORKSPACE else rf.workspace()
except Exception:
    ws = rf.workspace()
project = ws.project(ROBOFLOW_PROJECT)
# Ensure we target the specified version (YOLOv11 Object Detection hosted)
_selected_version: str = ROBOFLOW_VERSION
model = project.version(_selected_version).model


# ---------- Shared helper functions ----------
def calculate_iou(box1, box2):
    """Calculate Intersection over Union (IoU) between two bounding boxes.
    
    Boxes are in format: {'bbox': [x, y, width, height]} where x,y is top-left corner
    """
    # Extract bbox coordinates [x, y, width, height]
    x1, y1, w1, h1 = box1['bbox']
    x2, y2, w2, h2 = box2['bbox']
    
    # Calculate box boundaries (x,y is top-left, so max is x+w, y+h)
    x1_min, y1_min, x1_max, y1_max = x1, y1, x1 + w1, y1 + h1
    x2_min, y2_min, x2_max, y2_max = x2, y2, x2 + w2, y2 + h2
    
    # Calculate intersection area
    inter_x_min = max(x1_min, x2_min)
    inter_y_min = max(y1_min, y2_min)
    inter_x_max = min(x1_max, x2_max)
    inter_y_max = min(y1_max, y2_max)
    
    if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
        return 0.0
    
    inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
    box1_area = w1 * h1
    box2_area = w2 * h2
    union_area = box1_area + box2_area - inter_area
    
    return inter_area / union_area if union_area > 0 else 0.0


def merge_detections(existing_dets, new_dets):
    """Merge new detections into existing ones, replacing overlapping boxes.
    
    Uses low IoU threshold to aggressively replace boxes for smooth tracking.
    """
    IOU_THRESHOLD = 0.15  # If boxes overlap >15%, they're the same object (more aggressive merging)
    merged = []
    used_new = set()
    
    for exist_det in existing_dets:
        # Check if this existing detection overlaps with any new detection
        replaced = False
        for i, new_det in enumerate(new_dets):
            if i in used_new:
                continue
            if exist_det['class'] == new_det['class']:  # Same class
                iou = calculate_iou(exist_det, new_det)
                if iou > IOU_THRESHOLD:
                    # New detection replaces old one (use newer, more confident detection)
                    merged.append(new_det)
                    used_new.add(i)
                    replaced = True
                    break
        
        if not replaced:
            # No replacement found, keep the old detection
            merged.append(exist_det)
    
    # Add completely new detections that didn't overlap with existing ones
    for i, new_det in enumerate(new_dets):
        if i not in used_new:
            merged.append(new_det)
    
    return merged


def _parse_roboflow_video_response(results: Any) -> List[Any]:
    """Parse Roboflow video API response and extract frames list.
    
    Handles multiple response formats from different API versions.
    """
    frames: List[Any] = []
    
    if isinstance(results, list):
        return results
    
    if not isinstance(results, dict):
        return frames
    
    # Try various known response formats
    # Format 1: Roboflow-specific (project-specific key)
    if 'frame_offset' in results and 'thesis-online-gathered-ds-y6uy4' in results:
        predictions_data = results['thesis-online-gathered-ds-y6uy4']
        if isinstance(predictions_data, list):
            return predictions_data
    
    # Format 2: Standard predictions key
    if 'predictions' in results and isinstance(results['predictions'], list):
        return results['predictions']
    
    # Format 3: Frames key
    if 'frames' in results and isinstance(results['frames'], list):
        return results['frames']
    
    # Format 4: Nested in video object
    if 'video' in results and isinstance(results['video'], dict):
        video_data = results['video']
        if 'frames' in video_data and isinstance(video_data['frames'], list):
            return video_data['frames']
        if 'predictions' in video_data and isinstance(video_data['predictions'], list):
            return video_data['predictions']
    
    # Format 5: Search for any list that looks like frame data
    for key, value in results.items():
        if isinstance(value, list) and len(value) > 0:
            first_item = value[0]
            if isinstance(first_item, dict):
                # Check if it has prediction-like keys
                if any(k in first_item for k in ['predictions', 'detections', 'objects', 'class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                    return value
    
    return frames


# ---------- Annotation helpers ----------
try:
    from PIL import Image as _PILImage
    from PIL import ImageDraw as _PILDraw
    from PIL import ImageFont as _PILFont
    _HAS_PIL = True
    print("PIL/Pillow successfully imported for image annotation")
except Exception as e:
    _HAS_PIL = False
    print(f"Warning: PIL/Pillow not available for image annotation: {e}")

def _annotate_image_file(input_path: str, detections: List[Dict[str, Any]]) -> Optional[bytes]:
    """Draw boxes, labels, and confidence on an image; return JPEG bytes."""
    if not _HAS_PIL:
        print("Warning: PIL/Pillow is not available, cannot annotate image")
        return None
    if not detections:
        print("Warning: No detections to annotate")
        return None
    try:
        img = _PILImage.open(input_path).convert('RGB')
        draw = _PILDraw.Draw(img)
        try:
            font = _PILFont.load_default()
        except Exception:
            font = None
        for det in detections:
            x, y, w, h = det.get('bbox', [0, 0, 0, 0])
            cls = str(det.get('class', ''))
            conf = det.get('confidence', 0.0)
            box = [x, y, x + w, y + h]
            draw.rectangle(box, outline=(255, 0, 0), width=3)
            label = f"{cls} {conf:.2f}"
            # Use modern Pillow API for text size (textsize is deprecated)
            if font:
                try:
                    # Try modern API first (Pillow >= 8.0.0)
                    bbox = font.getbbox(label)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except AttributeError:
                    # Fall back to deprecated method for older Pillow
                    tw, th = draw.textsize(label, font=font)
            else:
                tw, th = (len(label) * 6, 10)
            bx0, by0 = x, y - th - 4
            bx1, by1 = x + tw + 6, y
            draw.rectangle([bx0, by0, bx1, by1], fill=(255, 0, 0))
            draw.text((x + 3, y - th - 2), label, fill=(255, 255, 255), font=font)
        import io
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return buf.getvalue()
    except Exception as e:
        print(f"Error in _annotate_image_file: {e}")
        import traceback
        traceback.print_exc()
        return None


def _compress_frame_for_inference(frame_path: str, target_size: int = 640) -> Optional[str]:
    """Compress and resize frame for faster inference."""
    if not _HAS_PIL or not COMPRESS_FRAMES_BEFORE_INFERENCE:
        return frame_path
    
    try:
        img = _PILImage.open(frame_path)
        # Resize to target size while maintaining aspect ratio
        img.thumbnail((target_size, target_size), _PILImage.Resampling.LANCZOS)
        
        # Save compressed version
        compressed_path = frame_path.replace('.jpg', '_compressed.jpg')
        img.save(compressed_path, format='JPEG', quality=85, optimize=True)
        print(f"Compressed frame from {os.path.getsize(frame_path)} to {os.path.getsize(compressed_path)} bytes")
        return compressed_path
    except Exception as e:
        print(f"Warning: Frame compression failed: {e}")
        return frame_path


class SmartFrameSkipper:
    """Manages smart frame skipping logic to avoid missing stationary objects."""
    
    def __init__(self, skip_window: int = 5, frame_interval: int = 1):
        self.skip_window = skip_window
        self.frame_interval = frame_interval
        self.frames_since_detection = skip_window + 1  # Start in skip mode
        self.total_processed = 0
        self.total_skipped = 0
    
    def on_detection_found(self):
        """Call this when detections are found in a frame."""
        self.frames_since_detection = 0
    
    def should_process_frame(self, frame_idx: int) -> bool:
        """Returns True if this frame should be processed."""
        if not ENABLE_SMART_SKIP:
            # No smart skip - use simple frame interval
            should_process = (frame_idx % FRAME_INTERVAL) == 0
        else:
            # Smart skip: process all frames within window after detection
            if self.frames_since_detection < self.skip_window:
                should_process = True
                self.frames_since_detection += 1
            else:
                # Outside window - apply frame interval
                should_process = (frame_idx % self.frame_interval) == 0
                if not should_process:
                    self.frames_since_detection += 1
        
        if should_process:
            self.total_processed += 1
        else:
            self.total_skipped += 1
        
        return should_process
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        total = self.total_processed + self.total_skipped
        return {
            'total_frames': total,
            'processed': self.total_processed,
            'skipped': self.total_skipped,
            'skip_rate': f"{(self.total_skipped / total * 100) if total > 0 else 0:.1f}%"
        }


def _create_annotated_video_fast(
    video_path: str,
    detections_by_frame: List[List[Dict[str, Any]]],
    output_path: str,
    detection_fps: float,
    original_fps: float,
) -> bool:
    """Create annotated video using FFmpeg drawbox filter - MUCH faster than frame extraction.
    
    This approach:
    1. Only processes frames at detection_fps (e.g., 3 FPS)
    2. Uses FFmpeg's built-in drawbox/drawtext filters
    3. No frame extraction or stitching needed
    4. 10-20x faster than traditional method
    """
    try:
        print(f'Creating annotated video using fast FFmpeg overlay method...')
        print(f'Detection FPS: {detection_fps}, Original FPS: {original_fps}')
        
        # Build FFmpeg filter for drawing boxes and labels
        # We'll create a complex filter that draws all detections
        filter_parts = []
        
        # For smooth tracking: persist detections across frames
        persistence_frames = max(1, int(original_fps / detection_fps))
        
        total_annotations = 0
        for frame_idx, frame_dets in enumerate(detections_by_frame):
            if not frame_dets:
                continue
            
            # Map API frame index to actual video frame using time-based calculation
            # API frame frame_idx represents time: frame_idx / detection_fps seconds
            # Video frame at that time: (frame_idx / detection_fps) * original_fps
            start_frame = round((frame_idx / detection_fps) * original_fps)
            end_frame = start_frame + persistence_frames
            start_time = start_frame / original_fps
            end_time = end_frame / original_fps
            
            for det in frame_dets:
                bbox = det.get('bbox', [0, 0, 0, 0])
                x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
                cls = det.get('class', 'unknown')
                conf = det.get('confidence', 0.0)
                
                # Sanitize class name for FFmpeg (remove spaces and special chars)
                cls_safe = cls.replace(' ', '_').replace("'", '').replace('"', '').replace(':', '')
                
                # FFmpeg drawbox syntax: drawbox=x=X:y=Y:w=W:h=H:color=red:t=3:enable='between(t,START,END)'
                filter_parts.append(
                    f"drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}:color=red@0.8:t=3:enable='between(t,{start_time:.3f},{end_time:.3f})'"
                )
                
                # Add text label (simplified to avoid FFmpeg parsing issues)
                label = f"{cls_safe}_{conf:.2f}".replace('.', 'p')  # Replace dot to avoid issues
                text_y = max(10, int(y) - 5)
                filter_parts.append(
                    f"drawtext=text={label}:x={int(x)+2}:y={text_y}:fontsize=16:fontcolor=white:box=1:boxcolor=red@0.8:enable='between(t,{start_time:.3f},{end_time:.3f})'"
                )
                total_annotations += 1
        
        if not filter_parts:
            print('No detections to annotate')
            return False
        
        print(f'Creating {total_annotations} annotations across {len([d for d in detections_by_frame if d])} frames')
        
        # Combine all filters
        vf_filter = ','.join(filter_parts)
        
        # Run FFmpeg with filter
        cmd_args = [
            FFMPEG_BINARY,
            '-y',
            '-i', video_path,
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'copy',
            output_path,
        ]
        
        print('Running FFmpeg annotation (this may take a moment for complex filters)...')
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT, timeout=300)
        print('FFmpeg annotation completed successfully')
        
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            print(f'Annotated video created: {output_size / (1024*1024):.2f} MB')
        
        return True
        
    except subprocess.TimeoutExpired:
        print('FFmpeg annotation timed out after 5 minutes')
        return False
    except subprocess.CalledProcessError as e:
        print(f'FFmpeg annotation failed: {e}')
        if e.output:
            error_output = e.output.decode() if isinstance(e.output, bytes) else str(e.output)
            # Only show last 1000 chars to avoid flooding logs
            print(f'FFmpeg error (last 1000 chars): {error_output[-1000:]}')
        return False
    except Exception as e:
        print(f'Error in fast video annotation: {e}')
        import traceback
        traceback.print_exc()
        return False


def _extract_annotated_from_response(obj: Any) -> Optional[str]:
    """Try common keys in Roboflow responses to locate an annotated image/video URL."""
    if not isinstance(obj, dict):
        return None
    candidates = (
        'annotated',
        'annotated_image',
        'annotated_url',
        'image',
        'image_url',
        'video_url',
        'annotated_video',
        'video_signed_url',
        'signed_url',
    )
    for k in candidates:
        v = obj.get(k)
        if isinstance(v, str) and v.startswith('http'):
            return v
    # sometimes nested under 'result' or similar
    for k in ('result', 'data', 'outputs'):
        nested = obj.get(k)
        if isinstance(nested, dict):
            v = _extract_annotated_from_response(nested)
            if v:
                return v
    return None


def _normalize_prediction(pred: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize prediction from various Roboflow response formats."""
    # Handle confidence in different formats
    raw_conf = pred.get('confidence', pred.get('score', pred.get('conf', 0.0)))
    conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
    
    # Handle class names in different formats
    class_name = pred.get('class', pred.get('label', pred.get('name', pred.get('class_name', 'unknown'))))
    
    # Handle bounding box coordinates in various formats
    x, y, w, h = 0, 0, 0, 0
    
    # Format 1: Roboflow returns center x,y with width,height under keys 'x','y','width','height'
    if all(key in pred for key in ['x', 'y', 'width', 'height']):
        cx, cy = float(pred['x']), float(pred['y'])
        w, h = float(pred['width']), float(pred['height'])
        x = cx - w / 2.0
        y = cy - h / 2.0
    
    # Format 2: Bbox object with x, y, width, height
    elif 'bbox' in pred and isinstance(pred['bbox'], dict):
        bbox = pred['bbox']
        x = bbox.get('x', 0)
        y = bbox.get('y', 0)
        w = bbox.get('width', 0)
        h = bbox.get('height', 0)
    
    # Format 3: Bbox as array [x, y, width, height]
    elif 'bbox' in pred and isinstance(pred['bbox'], list) and len(pred['bbox']) >= 4:
        bbox = pred['bbox']
        x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
    
    # Format 4: Coordinates as array [x1, y1, x2, y2] (convert to x, y, w, h)
    elif 'coordinates' in pred and isinstance(pred['coordinates'], list) and len(pred['coordinates']) >= 4:
        coords = pred['coordinates']
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
        x, y = x1, y1
        w, h = x2 - x1, y2 - y1
    
    # Format 5: Center coordinates with width/height
    elif all(key in pred for key in ['center_x', 'center_y', 'width', 'height']):
        x = pred['center_x'] - pred['width'] / 2
        y = pred['center_y'] - pred['height'] / 2
        w, h = pred['width'], pred['height']
    
    # Format 6: Try to extract from any coordinate-like keys
    else:
        coord_keys = ['x', 'y', 'width', 'height', 'w', 'h', 'x1', 'y1', 'x2', 'y2']
        found_coords = {k: pred.get(k, 0) for k in coord_keys if k in pred}
        if 'x' in found_coords and 'y' in found_coords:
            x, y = found_coords['x'], found_coords['y']
            w = found_coords.get('width', found_coords.get('w', 0))
            h = found_coords.get('height', found_coords.get('h', 0))
    
    return {
        'class': str(class_name),
        'confidence': round(float(conf), 3),
        'bbox': [round(float(x), 1), round(float(y), 1), round(float(w), 1), round(float(h), 1)],
    }


def run_inference(image_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run inference on a single image using local inference or cloud API.

    Returns (detections_list, annotated_url_or_none)
    """
    try:
        # Use float thresholds as expected by Roboflow (range 0.0 - 1.0).
        # Accept either 0-1 or 0-100 inputs and normalize accordingly.
        conf = DEFAULT_CONFIDENCE if confidence is None else float(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else float(overlap)
        if conf > 1.0:
            conf = conf / 100.0
        if ovlp > 1.0:
            ovlp = ovlp / 100.0
        # Clamp to valid range to avoid SDK/server-side rejection
        conf = max(0.0, min(1.0, conf))
        ovlp = max(0.0, min(1.0, ovlp))
        
        # Debug: Log the confidence being used
        if not hasattr(run_inference, '_debug_count'):
            run_inference._debug_count = 0
        run_inference._debug_count += 1
        if run_inference._debug_count <= 3:
            inference_type = "local" if (_local_model is not None and USE_LOCAL_INFERENCE) else "cloud"
            print(f'  Image inference ({inference_type}): confidence={conf}, overlap={ovlp}, image={os.path.basename(image_path)}')
        
        # Choose inference method
        if _local_model is not None and USE_LOCAL_INFERENCE:
            # Use local inference
            resp = _local_model.infer(image_path, confidence=conf, iou_threshold=1.0-ovlp)
            # Local inference returns dict directly
            result = resp[0] if isinstance(resp, list) and len(resp) > 0 else resp
        else:
            # Use cloud API
            resp = model.predict(image_path, confidence=conf, overlap=ovlp)
            # SDK may return an object with .json() or be directly dict-like
            try:
                result = resp.json() if hasattr(resp, 'json') else dict(resp)
            except Exception:
                result = resp if isinstance(resp, dict) else {}

        if run_inference._debug_count <= 3:
            print(f'  Raw result keys: {list(result.keys()) if isinstance(result, dict) else "not dict"}')
            if isinstance(result, dict) and 'predictions' in result:
                print(f'  Raw predictions count: {len(result.get("predictions", []))}')

        detections: List[Dict[str, Any]] = []
        if isinstance(result, dict) and 'predictions' in result:
            for pred in result.get('predictions', []):
                normalized = _normalize_prediction(pred)
                if run_inference._debug_count <= 3:
                    print(f'  Raw prediction: {pred}')
                    print(f'  Normalized prediction: {normalized}')
                detections.append(normalized)

        annotated = _extract_annotated_from_response(result)
        # Prefer locally-rendered annotated image bytes if we have detections
        if detections and _HAS_PIL:
            try:
                ann_bytes = _annotate_image_file(image_path, detections)
                if ann_bytes:
                    return detections, ann_bytes
            except Exception:
                pass
        return detections, annotated
    except Exception as e:
        print(f'Error in image inference: {e}')
        return [], None


def run_video_inference(
    video_path: str,
    fps: int = DEFAULT_VIDEO_FPS,
    confidence: Optional[int] = None,
    overlap: Optional[int] = None,
    frame_interval: Optional[int] = None,
    max_frames: Optional[int] = None,
) -> Tuple[List[List[Dict[str, Any]]], Optional[str]]:
    """Run inference on a video file using Roboflow batch-video API.
    
    Note: Frame-by-frame fallback has been DISABLED to prevent excessive credit usage.

    Returns (list_of_frame_detections, annotated_url_or_none)
    """
    # Get original video FPS and metadata
    original_fps = get_video_fps(video_path) if USE_ORIGINAL_FPS else float(DEFAULT_VIDEO_FPS)
    original_duration = get_video_duration(video_path)
    original_frame_count = get_video_frame_count(video_path)
    
    print(f'Starting Roboflow video inference with fps={fps}...')
    print(f'Original video: FPS={original_fps:.2f}, Duration={original_duration:.2f}s, Frames={original_frame_count}')
    
    # Prepare thresholds and frame limits up-front so they are available in all paths
    try:
        # Use configured frame interval if not explicitly provided
        interval = max(1, int(frame_interval)) if frame_interval else FRAME_INTERVAL
        print(f'Processing every {interval} frame(s) for speed optimization')
        
        max_allowed = int(max_frames) if max_frames is not None else MAX_VIDEO_FRAMES

        # Check if we should skip Roboflow batch-video API entirely
        skip_roboflow_video = (
            os.getenv('SKIP_ROBOFLOW_VIDEO', 'false').lower() == 'true' or 
            FORCE_LOCAL_VIDEO_PROCESSING
        )
        if skip_roboflow_video:
            print('Skipping Roboflow video API, using local frame sampling...')
            raise RuntimeError('Skipping Roboflow video API')
        api_fps = max(1, int(round(fps if fps else DEFAULT_VIDEO_FPS)))
        # Normalize thresholds for hosted YOLOv11; apply locally when parsing
        conf = DEFAULT_CONFIDENCE if confidence is None else float(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else float(overlap)
        if conf > 1.0:
            conf = conf / 100.0
        if ovlp > 1.0:
            ovlp = ovlp / 100.0
        conf = max(0.0, min(1.0, conf))
        ovlp = max(0.0, min(1.0, ovlp))
        
        # Try batch-video first
        # Prefer batch-video for efficient hosted processing on YOLOv11
        # Note: Roboflow SDK predict_video does not accept confidence/overlap
        job_id, signed_url, expire_time = model.predict_video(
            video_path,
            fps=api_fps,
            prediction_type="batch-video",
        )

        results = model.poll_until_video_results(job_id)
        
        # Parse response using helper function
        frames = _parse_roboflow_video_response(results)
        print(f'Roboflow returned {len(frames)} frames at {api_fps} FPS')

        all_detections: List[List[Dict[str, Any]]] = []
        # Optional interval and max frames applied during parsing to reduce load
        for i, frame in enumerate(frames):
            if (i % interval) != 0:
                continue
            
            # Extract predictions from frame (handle various formats)
            raw_preds = []
            if isinstance(frame, dict):
                # Skip metadata-only frames
                if all(key in ['frame_offset', 'time_offset', 'timestamp', 'frame_number'] for key in frame.keys()):
                    continue
                
                # Try standard prediction keys
                if 'predictions' in frame and isinstance(frame['predictions'], list):
                    raw_preds = frame['predictions']
                elif 'detections' in frame and isinstance(frame['detections'], list):
                    raw_preds = frame['detections']
                elif 'objects' in frame and isinstance(frame['objects'], list):
                    raw_preds = frame['objects']
                # Check if frame itself is a single prediction
                elif any(key in frame for key in ['class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                    raw_preds = [frame]
            elif isinstance(frame, list):
                raw_preds = frame
            
            # Normalize predictions and filter by confidence
            parsed = []
            for p in raw_preds:
                try:
                    normalized = _normalize_prediction(p)
                    if normalized['confidence'] >= conf:
                        parsed.append(normalized)
                except Exception as e:
                    if i < 3:  # Log errors for first few frames only
                        print(f'Error normalizing prediction in frame {i}: {e}')
                    continue
            
            if len(all_detections) < max_allowed:
                all_detections.append(parsed)
            else:
                break
            
            # Progress update every 100 frames + first frame
            if i == 0 or (i + 1) % 100 == 0:
                total_dets = sum(len(dets) for dets in all_detections)
                print(f'Processed {i+1}/{len(frames)} frames, {total_dets} total detections')

        annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})

        if len(all_detections) == 0:
            print('Video API returned 0 frames; trying alternative prediction method...')
            
            # Try without prediction_type parameter
            try:
                job_id2, signed_url2, expire_time2 = model.predict_video(video_path, fps=api_fps)
                results2 = model.poll_until_video_results(job_id2)
                
                # Use same parsing helper
                frames2 = _parse_roboflow_video_response(results2)
                print(f'Retry returned {len(frames2)} frames')
                
                # Process retry results with same logic
                for i, frame in enumerate(frames2):
                    if isinstance(frame, dict):
                        raw_preds = frame.get('predictions', frame.get('detections', frame.get('objects', [])))
                        if not isinstance(raw_preds, list):
                            raw_preds = [frame] if any(k in frame for k in ['class', 'bbox', 'confidence']) else []
                    elif isinstance(frame, list):
                        raw_preds = frame
                    else:
                        raw_preds = []
                    
                    parsed = []
                    for p in raw_preds:
                        try:
                            normalized = _normalize_prediction(p)
                            if normalized['confidence'] >= conf:
                                parsed.append(normalized)
                        except Exception:
                            continue
                    
                    if len(all_detections) < max_allowed:
                        all_detections.append(parsed)
                    else:
                        break
                
                annotated = _extract_annotated_from_response(results2 if isinstance(results2, dict) else {})
            except Exception as e:
                print(f'Retry failed: {e}')

        if len(all_detections) == 0:
            print('Video API returned 0 frames after retry.')
            print('GIVING UP: No detections found. Expensive frame-by-frame fallback is disabled.')
            raise RuntimeError('Zero frames returned by video API - check video format/size')
        
        # Create annotated video locally if detections exist and PIL is available
        if _HAS_PIL and len(all_detections) > 0 and any(len(frame_dets) > 0 for frame_dets in all_detections):
            print('Creating annotated video from Roboflow API results...')
            
            # Choose annotation method based on VIDEO_ANNOTATION_MODE
            use_fast_mode = VIDEO_ANNOTATION_MODE == 'fast'
            
            if use_fast_mode:
                print('Using FAST annotation mode (FFmpeg overlay)')
                try:
                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    if _create_annotated_video_fast(video_path, all_detections, ann_video_path, api_fps, original_fps):
                        print(f'Successfully created annotated video: {ann_video_path}')
                        try:
                            from .cloudinary_utils import upload_video_streaming
                            from .config import MAX_CLOUDINARY_UPLOAD_SIZE
                            from .video_utils import transcode_video_to_preview
                            
                            # Check file size and compress if needed
                            video_size = os.path.getsize(ann_video_path)
                            upload_path = ann_video_path
                            
                            if video_size > MAX_CLOUDINARY_UPLOAD_SIZE:
                                print(f'Annotated video too large ({video_size / (1024*1024):.2f} MB), compressing...')
                                try:
                                    upload_path = transcode_video_to_preview(ann_video_path)
                                    compressed_size = os.path.getsize(upload_path)
                                    print(f'Compressed to {compressed_size / (1024*1024):.2f} MB')
                                except Exception as compress_err:
                                    print(f'Compression failed: {compress_err}, uploading original')
                                    upload_path = ann_video_path
                            
                            uploaded = upload_video_streaming(upload_path, os.path.basename(video_path), folder="weed-detections/annotated", annotate=False)
                            annotated = uploaded.get('secure_url')
                            print(f'Annotated video uploaded to Cloudinary: {annotated}')
                            
                            # Cleanup compressed file if different
                            if upload_path != ann_video_path and os.path.exists(upload_path):
                                try:
                                    os.remove(upload_path)
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f'Failed to upload annotated video: {e}')
                        
                        # Cleanup
                        try:
                            if os.path.exists(ann_video_path):
                                os.remove(ann_video_path)
                        except Exception:
                            pass
                    else:
                        print('Fast annotation failed, falling back to quality mode')
                        use_fast_mode = False  # Fallback
                except Exception as e:
                    print(f'Error in fast annotation: {e}')
                    import traceback
                    traceback.print_exc()
                    use_fast_mode = False  # Fallback
            
            # Quality mode or fallback from fast mode
            if not use_fast_mode:
                print('Using QUALITY annotation mode (OpenCV frame extraction)')
                try:
                    # Use OpenCV for frame extraction (no FFmpeg dependency)
                    print(f'Extracting frames with OpenCV at {original_fps:.2f} FPS...')
                    frame_paths = extract_frames_cv2(video_path, target_fps=original_fps, max_frames=MAX_VIDEO_FRAMES)
                    
                    if frame_paths is None:
                        # OpenCV not available - cannot proceed without FFmpeg
                        raise RuntimeError('OpenCV not available for frame extraction. Please install opencv-python-headless.')
                    
                    # OpenCV extraction successful
                    print(f'OpenCV extracted {len(frame_paths)} frames successfully')
                    files = frame_paths
                    tmpdir = os.path.dirname(frame_paths[0]) if frame_paths else None
                    
                    total_frames = len(files)
                    print(f'Extracted {total_frames} frames from original video')
                    
                    # Create a mapping of which frames have detections
                    # Roboflow API returns detections at api_fps (e.g., 10 FPS)
                    # Map API frame indices to actual video frame indices
                    # Use proper rounding to avoid accumulating errors
                    
                    # Instead of using frame_skip, map each API frame directly to video frames
                    # API frame i corresponds to video timestamp: i / api_fps
                    # Video frame for that timestamp: (i / api_fps) * original_fps
                    
                    # Temporal smoothing: Make detections persist across multiple frames
                    persistence_frames = max(1, int(original_fps / api_fps))  # Persist for frame skip duration
                    print(f'Detection persistence: {persistence_frames} frames (~{persistence_frames / original_fps:.2f}s)')
                    
                    detection_map = {}
                    for det_idx, frame_dets in enumerate(all_detections):
                        if frame_dets:  # Only map frames with actual detections
                            # Map API frame index to actual video frame index
                            # API frame det_idx represents time: det_idx / api_fps seconds
                            # Video frame at that time: (det_idx / api_fps) * original_fps
                            # Use round() to get nearest frame, not int() which truncates
                            base_frame_idx = round((det_idx / api_fps) * original_fps)
                            
                            # Apply detections to the base frame AND subsequent frames for persistence
                            for offset in range(persistence_frames):
                                actual_frame_idx = base_frame_idx + offset
                                if actual_frame_idx < total_frames:
                                    # If frame already has detections, merge them intelligently (replace overlapping boxes)
                                    if actual_frame_idx in detection_map:
                                        detection_map[actual_frame_idx] = merge_detections(
                                            detection_map[actual_frame_idx], frame_dets
                                        )
                                    else:
                                        detection_map[actual_frame_idx] = frame_dets.copy()
                    
                    print(f'Mapping {len(detection_map)} detection frames across {total_frames} total frames (with temporal smoothing)')
                    
                    # Create annotated frames directory
                    ann_frames_dir = tempfile.mkdtemp(prefix='rf_robo_ann_')
                    print(f'Created temp directory for annotated frames: {ann_frames_dir}')
                    
                    # Process all frames: annotate those with detections, copy others unchanged
                    annotated_count = 0
                    detection_frame_nums = []  # Track which frames got annotated for summary
                    
                    for i, frame_file in enumerate(files):
                        out_path = os.path.join(ann_frames_dir, f'ann_{i+1:06d}.jpg')
                        
                        if i in detection_map:
                            # This frame has detections - annotate it
                            try:
                                ann_bytes = _annotate_image_file(frame_file, detection_map[i])
                                if ann_bytes:
                                    with open(out_path, 'wb') as f:
                                        f.write(ann_bytes)
                                    annotated_count += 1
                                    detection_frame_nums.append(i)
                                    
                                    # Show sample detections for first few frames only
                                    if annotated_count <= 3:
                                        num_dets = len(detection_map[i])
                                        print(f'  Frame {i+1}: annotated with {num_dets} detection(s)')
                                else:
                                    # Annotation failed, use original
                                    shutil.copy(frame_file, out_path)
                            except Exception as e:
                                if i < 3:  # Log first few errors
                                    print(f'Failed to annotate frame {i+1}: {e}')
                                # Use original frame on error
                                shutil.copy(frame_file, out_path)
                        else:
                            # No detections - use original frame unchanged
                            shutil.copy(frame_file, out_path)
                        
                        # Progress update every 100 frames
                        if (i + 1) % 100 == 0:
                            print(f'Processed {i+1}/{total_frames} frames...')
                    
                    print(f'Annotated {annotated_count} frames with detections out of {total_frames} total frames')
                    
                    # Stitch into video using OpenCV (no FFmpeg dependency)
                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    print(f'Stitching full video with OpenCV at {original_fps:.2f} FPS...')
                    
                    # Use OpenCV stitching
                    stitch_success = stitch_video_cv2(ann_frames_dir, original_fps, ann_video_path, frame_pattern='ann_%06d.jpg')
                    
                    if not stitch_success:
                        # OpenCV failed - cannot proceed without FFmpeg
                        raise RuntimeError('OpenCV video stitching failed. Please check opencv-python-headless installation.')
                    
                    print(f'Successfully stitched annotated video with OpenCV: {ann_video_path}')
                    try:
                        from .cloudinary_utils import upload_video_streaming
                        from .config import MAX_CLOUDINARY_UPLOAD_SIZE
                        from .video_utils import transcode_video_to_preview
                        
                        # Check file size and compress if needed
                        video_size = os.path.getsize(ann_video_path)
                        upload_path = ann_video_path
                        
                        if video_size > MAX_CLOUDINARY_UPLOAD_SIZE:
                            print(f'Annotated video too large ({video_size / (1024*1024):.2f} MB), compressing...')
                            try:
                                upload_path = transcode_video_to_preview(ann_video_path)
                                compressed_size = os.path.getsize(upload_path)
                                print(f'Compressed to {compressed_size / (1024*1024):.2f} MB')
                            except Exception as compress_err:
                                print(f'Compression failed: {compress_err}, uploading original')
                                upload_path = ann_video_path
                        
                        uploaded = upload_video_streaming(upload_path, os.path.basename(video_path), folder="weed-detections/annotated", annotate=False)
                        annotated = uploaded.get('secure_url')
                        print(f'Annotated video uploaded to Cloudinary: {annotated}')
                        
                        # Cleanup compressed file if different
                        if upload_path != ann_video_path and os.path.exists(upload_path):
                            try:
                                os.remove(upload_path)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f'Failed to upload annotated video: {e}')
                    
                    # Cleanup
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    shutil.rmtree(ann_frames_dir, ignore_errors=True)
                    try:
                        if os.path.exists(ann_video_path):
                            os.remove(ann_video_path)
                    except Exception:
                        pass
                        
                except Exception as e:
                    print(f'Error creating annotated video from Roboflow results: {e}')
                    import traceback
                    traceback.print_exc()
        
        return all_detections, annotated
    except Exception as e:
        # If the video API fails, DO NOT fall back to expensive frame-by-frame inference
        # This fallback uses hosted image inference API which consumes too many credits
        print(f'Error in video inference: {e}')
        print('FALLBACK DISABLED: Frame-by-frame inference.')
        print('Possible solutions:')
        print('  1. Check if video is too large (compress before upload)')
        print('  2. Check if video format is supported by Roboflow')
        print('  3. Verify Roboflow API key and project settings')
        return [], None


def detect_file_type(file_path: str) -> str:
    """Detect if file is image or video based on extension."""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif']
    file_ext = os.path.splitext(file_path.lower())[1]
    if file_ext in video_extensions:
        return 'video'
    if file_ext in image_extensions:
        return 'image'
    return 'unknown'


def run_inference_auto(file_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[Any, Optional[str]]:
    """Automatically detect file type and run appropriate inference with optimization.
    
    Note: Expensive frame-by-frame fallback has been DISABLED to save Roboflow credits.

    Returns (detections_or_frames, annotated_url_or_none)
    """
    from .video_utils import compress_for_inference
    
    file_type = detect_file_type(file_path)
    if file_type == 'image':
        return run_inference(file_path, confidence=confidence, overlap=overlap)
    if file_type == 'video':
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f'Processing video: {file_size_mb:.1f} MB')
        
        # Compress large videos before Roboflow upload to avoid timeouts
        compressed_path = None
        inference_path = file_path
        try:
            if file_size_mb > 100:
                print(f'Video exceeds 100 MB, compressing for Roboflow upload...')
                compressed_path = compress_for_inference(file_path, max_size_mb=100)
                inference_path = compressed_path
                print(f'Using compressed video for inference: {os.path.getsize(compressed_path) / (1024 * 1024):.1f} MB')
            
            # Always start with configured default FPS for Roboflow batch-video
            result = run_video_inference(inference_path, fps=DEFAULT_VIDEO_FPS, confidence=confidence, overlap=overlap)
            return result
        finally:
            # Clean up compressed file if created
            if compressed_path and os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                    print(f'Cleaned up compressed file: {compressed_path}')
                except Exception as e:
                    print(f'Warning: Failed to delete compressed file {compressed_path}: {e}')
    
    print(f'Unsupported file type: {file_path}')
    return [], None

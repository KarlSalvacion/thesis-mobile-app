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
    from .config import VIDEO_ANNOTATION_MODE
except ImportError:
    VIDEO_ANNOTATION_MODE = 'fast'  # Default to fast mode
from .config import FFMPEG_BINARY
from .video_utils import get_video_fps, get_video_duration, get_video_frame_count

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
        print(f"Annotating image with {len(detections)} detections")
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
        print(f"Successfully created annotated image, size: {len(buf.getvalue())} bytes")
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


def _stitch_video_from_frames(frames_dir: str, fps: float, output_path: str) -> bool:
    """Create an MP4 from frames in frames_dir using ffmpeg pattern frame_*.jpg
    
    Uses -framerate for input to ensure exact frame timing matching original video.
    """
    try:
        # Count actual frames to verify
        frame_files = sorted([f for f in os.listdir(frames_dir) if f.startswith('ann_') and f.endswith('.jpg')])
        frame_count = len(frame_files)
        expected_duration = frame_count / fps
        print(f'Stitching {frame_count} frames at {fps} FPS (expected duration: {expected_duration:.2f}s)')
        
        # Verify frame sequence is continuous
        if frame_files:
            first_frame = frame_files[0]
            last_frame = frame_files[-1]
            print(f'Frame sequence: {first_frame} to {last_frame}')
        
        cmd_args = [
            FFMPEG_BINARY,
            '-y',
            '-framerate', str(fps),  # Input framerate - read frames at this rate
            '-start_number', '1',  # Start from ann_000001.jpg
            '-i', os.path.join(frames_dir, 'ann_%06d.jpg'),
            '-c:v', 'libx264',
            '-preset', 'medium',  # Balance between speed and quality
            '-crf', '18',  # High quality (lower is better, 18 is visually lossless)
            '-pix_fmt', 'yuv420p',
            '-video_track_timescale', str(int(fps * 1000)),  # Precise timing
            output_path,
        ]
        print(f'Stitching video with command: {" ".join(cmd_args)}')
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
        print('FFmpeg stitching completed successfully')
        
        # Verify output
        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            print(f'Output video created: {output_size / (1024*1024):.2f} MB')
        
        return True
    except subprocess.CalledProcessError as e:
        print('ffmpeg stitching failed:', e)
        if e.output:
            print('FFmpeg output:', e.output.decode())
        return False
    except Exception as e:
        print('ffmpeg stitching failed:', e)
        return False


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
        frame_skip = int(original_fps / detection_fps) if detection_fps > 0 else 1
        persistence_frames = max(1, frame_skip // 2)
        
        total_annotations = 0
        for frame_idx, frame_dets in enumerate(detections_by_frame):
            if not frame_dets:
                continue
            
            # Calculate time range for this detection (with persistence)
            start_frame = frame_idx * frame_skip
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
    allow_ffmpeg_fallback: bool = True,
    frame_interval: Optional[int] = None,
    max_frames: Optional[int] = None,
) -> Tuple[List[List[Dict[str, Any]]], Optional[str]]:
    """Run inference on a video file using Roboflow batch-video API.

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
        print(f'Raw Roboflow response type: {type(results)}')
        
        # Enhanced response parsing with detailed logging
        frames: List[Any] = []
        if isinstance(results, list):
            print('Response is a list, treating as direct frame predictions')
            frames = results
        elif isinstance(results, dict):
            print(f'Response is dict with keys: {list(results.keys())}')
            
            # Special handling for Roboflow's specific response format
            # Based on debug output: keys are ['frame_offset', 'time_offset', 'thesis-online-gathered-ds-y6uy4']
            if 'frame_offset' in results and 'thesis-online-gathered-ds-y6uy4' in results:
                print('Detected Roboflow video response format')
                frame_offsets = results['frame_offset']
                predictions_data = results['thesis-online-gathered-ds-y6uy4']
                
                print(f'Frame offsets: {len(frame_offsets)} items, type: {type(frame_offsets[0]) if frame_offsets else "empty"}')
                print(f'Predictions data: {len(predictions_data)} items, type: {type(predictions_data[0]) if predictions_data else "empty"}')
                
                # The predictions_data should contain the actual detection data
                if isinstance(predictions_data, list) and len(predictions_data) > 0:
                    frames = predictions_data
                    print(f'Using predictions data as frames: {len(frames)} items')
                else:
                    print('Predictions data is not a list or is empty')
            
            # Fallback to standard parsing
            elif 'predictions' in results:
                print('Found predictions key')
                if isinstance(results['predictions'], list):
                    frames = results['predictions']
                    print(f'predictions is list with {len(frames)} items')
                else:
                    print(f'predictions is not a list: {type(results["predictions"])}')
            elif 'frames' in results:
                print('Found frames key')
                if isinstance(results['frames'], list):
                    frames = results['frames']
                    print(f'frames is list with {len(frames)} items')
                else:
                    print(f'frames is not a list: {type(results["frames"])}')
            elif 'video' in results and isinstance(results['video'], dict):
                print('Found video key with dict value')
                video_data = results['video']
                print(f'video dict keys: {list(video_data.keys())}')
                if 'frames' in video_data and isinstance(video_data['frames'], list):
                    frames = video_data['frames']
                    print(f'video.frames is list with {len(frames)} items')
                elif 'predictions' in video_data and isinstance(video_data['predictions'], list):
                    frames = video_data['predictions']
                    print(f'video.predictions is list with {len(frames)} items')
            else:
                # Check if any key contains frame data
                for key, value in results.items():
                    if isinstance(value, list) and len(value) > 0:
                        # Check if this looks like frame data
                        first_item = value[0] if value else None
                        if isinstance(first_item, dict) and ('predictions' in first_item or 'bbox' in first_item or 'class' in first_item):
                            print(f'Found frame data in key "{key}" with {len(value)} items')
                            frames = value
                            break
                        elif isinstance(first_item, list):
                            print(f'Found nested list in key "{key}" with {len(value)} items')
                            frames = value
                            break
                        elif isinstance(first_item, dict):
                            # Check if this might be frame data even without obvious keys
                            print(f'Found dict list in key "{key}" with {len(value)} items, checking structure...')
                            # Look for any prediction-like structure in the first few items
                            for i, item in enumerate(value[:3]):
                                if isinstance(item, dict):
                                    print(f'  Item {i} keys: {list(item.keys())}')
                                    # If any item has prediction-like keys, treat as frames
                                    if any(k in item for k in ['predictions', 'detections', 'objects', 'class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                                        print(f'Found prediction-like data in key "{key}", treating as frames')
                                        frames = value
                                        break
                            if frames:
                                break

        print(f'Roboflow returned {len(frames)} frames after parsing')

        all_detections: List[List[Dict[str, Any]]] = []
        # Optional interval and max frames applied during parsing to reduce load
        for i, frame in enumerate(frames):
            if (i % interval) != 0:
                continue
            # Enhanced debugging for first few frames
            if i < 3:
                print(f'Frame {i} type: {type(frame)}')
                if isinstance(frame, dict):
                    print(f'Frame {i} keys: {list(frame.keys())}')
                    if 'predictions' in frame:
                        print(f'Frame {i} predictions type: {type(frame["predictions"])}')
                        if isinstance(frame['predictions'], list):
                            print(f'Frame {i} predictions length: {len(frame["predictions"])}')
                            if len(frame['predictions']) > 0:
                                print(f'Frame {i} first prediction: {frame["predictions"][0]}')
                elif isinstance(frame, list):
                    print(f'Frame {i} list length: {len(frame)}')
                    if len(frame) > 0:
                        print(f'Frame {i} first item: {frame[0]}')
            
            # Enhanced parsing logic
            raw_preds = []
            if isinstance(frame, dict):
                # Skip frames that are just metadata (no prediction data)
                if all(key in ['frame_offset', 'time_offset', 'timestamp', 'frame_number'] for key in frame.keys()):
                    if i < 3:
                        print(f'Frame {i} appears to be metadata only, skipping')
                    continue
                
                if 'predictions' in frame and isinstance(frame['predictions'], list):
                    raw_preds = frame['predictions']
                elif 'detections' in frame and isinstance(frame['detections'], list):
                    raw_preds = frame['detections']
                elif 'objects' in frame and isinstance(frame['objects'], list):
                    raw_preds = frame['objects']
                elif 'class' in frame or 'bbox' in frame or 'confidence' in frame:
                    # Single prediction object
                    raw_preds = [frame]
                else:
                    # Check if frame itself contains prediction data
                    if any(key in frame for key in ['class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                        raw_preds = [frame]
                    elif i < 3:
                        print(f'Frame {i} has no recognizable prediction data')
            elif isinstance(frame, list):
                raw_preds = frame
            else:
                print(f'Unknown frame type {type(frame)} for frame {i}')
            
            parsed = []
            for p in raw_preds:
                try:
                    normalized = _normalize_prediction(p)
                    # Only include detections above confidence threshold
                    if normalized['confidence'] >= conf:
                        parsed.append(normalized)
                except Exception as e:
                    print(f'Error normalizing prediction in frame {i}: {e}')
                    continue
            
            if len(all_detections) < max_allowed:
                all_detections.append(parsed)
            else:
                break
            
            # Log first few frames for debugging
            if i < 3:
                print(f'Frame {i}: {len(parsed)} detections after parsing')
                if len(parsed) > 0:
                    print(f'Frame {i} first detection: {parsed[0]}')

        annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})

        if len(all_detections) == 0:
            print('Video API returned 0 frames; trying alternative prediction types...')
            
            # Try without prediction_type
            try:
                print('Retrying without prediction_type...')
                job_id2, signed_url2, expire_time2 = model.predict_video(
                    video_path,
                    fps=api_fps,
                )
                results2 = model.poll_until_video_results(job_id2)
                print(f'Retry response type: {type(results2)}')
                
                frames2: List[Any] = []
                if isinstance(results2, list):
                    frames2 = results2
                elif isinstance(results2, dict):
                    print(f'Retry response keys: {list(results2.keys())}')
                    
                    # Use same parsing logic as main attempt
                    if 'frame_offset' in results2 and 'thesis-online-gathered-ds-y6uy4' in results2:
                        print('Retry: Detected Roboflow video response format')
                        predictions_data = results2['thesis-online-gathered-ds-y6uy4']
                        if isinstance(predictions_data, list) and len(predictions_data) > 0:
                            frames2 = predictions_data
                            print(f'Retry: Using predictions data as frames: {len(frames2)} items')
                    elif 'predictions' in results2 and isinstance(results2['predictions'], list):
                        frames2 = results2['predictions']
                    elif 'frames' in results2 and isinstance(results2['frames'], list):
                        frames2 = results2['frames']
                    elif 'video' in results2 and isinstance(results2['video'], dict):
                        video_data = results2['video']
                        if 'frames' in video_data and isinstance(video_data['frames'], list):
                            frames2 = video_data['frames']
                        elif 'predictions' in video_data and isinstance(video_data['predictions'], list):
                            frames2 = video_data['predictions']
                
                print(f'Retry returned {len(frames2)} frames')
                
                # Process retry results
                for i, frame in enumerate(frames2):
                    if isinstance(frame, dict) and isinstance(frame.get('predictions'), list):
                        raw_preds = frame.get('predictions')
                    elif isinstance(frame, list):
                        raw_preds = frame
                    elif isinstance(frame, dict) and ('class' in frame or 'bbox' in frame):
                        raw_preds = [frame]
                    else:
                        raw_preds = []
                    parsed = [_normalize_prediction(p) for p in raw_preds]
                    if len(all_detections) < max_allowed:
                        all_detections.append(parsed)
                    else:
                        break
                
                annotated = _extract_annotated_from_response(results2 if isinstance(results2, dict) else {})
            except Exception as e:
                print(f'Retry failed: {e}')
                annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})

        if len(all_detections) == 0:
            print('Video API returned 0 frames; triggering local frame sampling fallback...')
            raise RuntimeError('Zero frames returned by video API')
        
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
                            uploaded = upload_video_streaming(ann_video_path, os.path.basename(video_path), folder="weed-detections/annotated", annotate=False)
                            annotated = uploaded.get('secure_url')
                            print(f'Annotated video uploaded to Cloudinary: {annotated}')
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
                print('Using QUALITY annotation mode (frame extraction)')
                try:
                    # Extract ALL frames from original video at original FPS
                    tmpdir = tempfile.mkdtemp(prefix='rf_robo_frames_')
                    print(f'Created temp directory for frames: {tmpdir}')
                    
                    # Extract all frames at original FPS (not detection FPS)
                    out_pattern = os.path.join(tmpdir, 'frame_%06d.jpg')
                    # Force exact FPS extraction to handle VFR videos correctly
                    # Calculate expected frame count
                    expected_frames = int(original_duration * original_fps)
                    print(f'Expected frame count: {expected_frames} frames ({original_duration:.2f}s × {original_fps:.2f} FPS)')
                    
                    cmd_args = [
                        FFMPEG_BINARY,
                        '-y',
                        '-i', video_path,
                        '-vf', f'fps={original_fps}',  # Force constant frame rate extraction
                        '-vsync', 'cfr',  # Constant frame rate - ensure no dropped/duplicate frames
                        '-q:v', '2',  # High quality
                        out_pattern,
                    ]
                    print(f'Extracting all frames from video at original FPS ({original_fps:.2f})...')
                    subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
                    
                    # Get all extracted frames
                    files = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.lower().endswith('.jpg')])
                    total_frames = len(files)
                    print(f'Extracted {total_frames} frames from original video')
                    
                    # Create a mapping of which frames have detections
                    # Roboflow API returns detections at api_fps (e.g., 3 FPS)
                    # Calculate frame indices for detections
                    frame_skip = int(original_fps / api_fps) if api_fps > 0 else 1
                    
                    # Temporal smoothing: Make detections persist across multiple frames
                    # This prevents flickering and makes annotations more visible
                    # Persist detections for half the frame skip window (e.g., ~10 frames at 60 FPS)
                    persistence_frames = max(1, frame_skip // 2)
                    print(f'Detection persistence: {persistence_frames} frames (~{persistence_frames / original_fps:.2f}s)')
                    
                    detection_map = {}
                    for det_idx, frame_dets in enumerate(all_detections):
                        if frame_dets:  # Only map frames with actual detections
                            # Calculate which original frame this detection corresponds to
                            base_frame_idx = det_idx * frame_skip
                            
                            # Apply detections to the base frame AND subsequent frames for persistence
                            for offset in range(persistence_frames):
                                actual_frame_idx = base_frame_idx + offset
                                if actual_frame_idx < total_frames:
                                    # If frame already has detections, merge them (avoid duplicates)
                                    if actual_frame_idx in detection_map:
                                        # Simple merge: just extend the list (could add de-duplication logic)
                                        detection_map[actual_frame_idx].extend(frame_dets)
                                    else:
                                        detection_map[actual_frame_idx] = frame_dets.copy()
                    
                    print(f'Mapping {len(detection_map)} detection frames across {total_frames} total frames (with temporal smoothing)')
                    
                    # Create annotated frames directory
                    ann_frames_dir = tempfile.mkdtemp(prefix='rf_robo_ann_')
                    print(f'Created temp directory for annotated frames: {ann_frames_dir}')
                    
                    # Process all frames: annotate those with detections, copy others unchanged
                    annotated_count = 0
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
                                else:
                                    # Annotation failed, use original
                                    import shutil as sh
                                    sh.copy(frame_file, out_path)
                            except Exception as e:
                                if i < 3:  # Log first few errors
                                    print(f'Failed to annotate frame {i+1}: {e}')
                                # Use original frame on error
                                import shutil as sh
                                sh.copy(frame_file, out_path)
                        else:
                            # No detections - use original frame unchanged
                            import shutil as sh
                            sh.copy(frame_file, out_path)
                        
                        # Progress update every 100 frames
                        if (i + 1) % 100 == 0:
                            print(f'Processed {i+1}/{total_frames} frames...')
                    
                    print(f'Annotated {annotated_count} frames with detections out of {total_frames} total frames')
                    
                    # Stitch into video using original FPS
                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    print(f'Stitching full video at {original_fps:.2f} FPS...')
                    if _stitch_video_from_frames(ann_frames_dir, original_fps, ann_video_path):
                        print(f'Successfully stitched annotated video: {ann_video_path}')
                        try:
                            from .cloudinary_utils import upload_video_streaming
                            uploaded = upload_video_streaming(ann_video_path, os.path.basename(video_path), folder="weed-detections/annotated", annotate=False)
                            annotated = uploaded.get('secure_url')
                            print(f'Annotated video uploaded to Cloudinary: {annotated}')
                        except Exception as e:
                            print(f'Failed to upload annotated video: {e}')
                    else:
                        print('Failed to stitch annotated frames into video')
                    
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
        # If the video API fails (BAD REQUEST or similar), fall back to frame sampling using ffmpeg
        print(f'Error in video inference: {e}')
        if not allow_ffmpeg_fallback:
            # In fast mode we do not sample frames locally; return empty detections quickly
            return [], None
        try:
            print('Starting ffmpeg frame extraction fallback...')
            # Ensure ffmpeg is available; build a temporary dir for frames
            tmpdir = tempfile.mkdtemp(prefix='rf_frames_')
            print(f'Created temp directory: {tmpdir}')
            
            # Get original video FPS for full-length annotated video
            original_fps = get_video_fps(video_path) if USE_ORIGINAL_FPS else float(DEFAULT_VIDEO_FPS)
            original_duration = get_video_duration(video_path)
            print(f'Original video FPS: {original_fps:.2f}, Duration: {original_duration:.2f}s')
            
            # Extract ALL frames at original FPS for full-length video
            out_pattern = os.path.join(tmpdir, 'frame_%06d.jpg')
            ffmpeg = FFMPEG_BINARY
            # Force exact FPS extraction to handle VFR videos correctly
            expected_frames = int(original_duration * original_fps) if original_duration else 0
            print(f'Expected frame count: {expected_frames} frames')
            
            cmd_args = [
                ffmpeg,
                '-y',
                '-i', video_path,
                '-vf', f'fps={original_fps}',  # Force constant frame rate extraction
                '-vsync', 'cfr',  # Constant frame rate - ensure no dropped/duplicate frames
                '-q:v', '2',  # high-quality JPEGs
                out_pattern,
            ]
            try:
                print(f'Running ffmpeg command: {" ".join(cmd_args)}')
                result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
                print('ffmpeg frame extraction completed successfully')
            except subprocess.CalledProcessError as ff_err:
                print('ffmpeg frame extraction failed:', ff_err)
                print('ffmpeg error output:', ff_err.output.decode() if ff_err.output else 'No output')
                shutil.rmtree(tmpdir, ignore_errors=True)
                return [], None

            # Collect extracted frames in order
            files = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.lower().endswith('.jpg')])
            sampled = files  # Use all extracted frames
            
            # Initialize smart frame skipper
            skipper = SmartFrameSkipper(skip_window=SMART_SKIP_WINDOW, frame_interval=FRAME_INTERVAL)
            print(f'Smart frame skipping: enabled={ENABLE_SMART_SKIP}, window={SMART_SKIP_WINDOW}, interval={FRAME_INTERVAL}')
            
            print(f'Found {len(files)} extracted frames')
            
            all_detections = []
            # Temporal smoothing: Keep track of recent detections to persist across frames
            persistence_window = max(5, int(original_fps * 0.2))  # Persist for ~0.2 seconds
            print(f'Detection persistence: {persistence_window} frames (~{persistence_window / original_fps:.2f}s)')
            recent_detections = []  # Will store (frame_idx, detections) tuples
            
            ann_frames_dir = tempfile.mkdtemp(prefix='rf_ann_frames_') if _HAS_PIL else None
            if ann_frames_dir:
                print(f'Created annotated frames directory: {ann_frames_dir}')
            else:
                print('Warning: PIL not available, skipping annotated video creation')
            
            for i, frame_file in enumerate(sampled):
                # Check if we should process this frame
                if not skipper.should_process_frame(i):
                    # Skip inference but check if we have recent detections to apply
                    # Remove old detections outside persistence window
                    recent_detections = [(idx, dets) for idx, dets in recent_detections if i - idx < persistence_window]
                    
                    # Collect all recent detections for this frame
                    frame_dets = []
                    for _, dets in recent_detections:
                        frame_dets.extend(dets)
                    
                    all_detections.append(frame_dets)
                    
                    # Still need to save the frame for full-length video
                    if ann_frames_dir:
                        try:
                            out_path = os.path.join(ann_frames_dir, f'ann_{i+1:06d}.jpg')
                            if frame_dets:
                                # Apply persisted detections
                                ann_bytes = _annotate_image_file(frame_file, frame_dets)
                                if ann_bytes:
                                    with open(out_path, 'wb') as f:
                                        f.write(ann_bytes)
                                else:
                                    import shutil as sh
                                    sh.copy(frame_file, out_path)
                            else:
                                import shutil as sh
                                sh.copy(frame_file, out_path)
                        except Exception:
                            pass
                    continue
                
                if i < 5 or i % 50 == 0:  # Log first few and periodic updates
                    print(f'Processing frame {i+1}/{len(sampled)}: {os.path.basename(frame_file)}')
                
                # Use frame as-is for inference
                inference_path = frame_file
                
                # Apply frame compression if enabled
                if COMPRESS_FRAMES_BEFORE_INFERENCE:
                    compressed_path = _compress_frame_for_inference(inference_path, INFERENCE_IMAGE_SIZE)
                    if compressed_path != inference_path:
                        inference_path = compressed_path
                
                # Force direct per-frame predict to mirror preview
                dets, _ann = run_inference(inference_path, confidence=0.05, overlap=0.45)
                
                # Clean up old detections outside persistence window
                recent_detections = [(idx, d) for idx, d in recent_detections if i - idx < persistence_window]
                
                # Add current detections to recent list if any found
                if dets:
                    recent_detections.append((i, dets))
                
                # Merge all recent detections for this frame
                frame_dets = []
                for _, d in recent_detections:
                    frame_dets.extend(d)
                
                all_detections.append(frame_dets)
                
                # Update skipper if NEW detections found (not persisted ones)
                if len(dets) > 0:
                    skipper.on_detection_found()
                    if i < 5:  # Log first few frames with detections
                        print(f'  Frame {i+1} new detections: {len(dets)}, total with persistence: {len(frame_dets)} - entering smart skip window')
                
                if i < 3:  # Log first few frames
                    print(f'  Frame {i+1} detections: {len(frame_dets)} (new: {len(dets)})')
                    if len(frame_dets) > 0:
                        print(f'  First detection: {frame_dets[0]}')

                # Save frame: annotated if detections exist (including persisted), original if no detections
                if ann_frames_dir:
                    try:
                        out_path = os.path.join(ann_frames_dir, f'ann_{i+1:06d}.jpg')
                        if frame_dets:
                            # Annotate frame with all detections (including persisted)
                            ann_bytes = _annotate_image_file(frame_file, frame_dets)
                            if ann_bytes:
                                with open(out_path, 'wb') as f:
                                    f.write(ann_bytes)
                                if i < 3:
                                    print(f'  Saved annotated frame: {os.path.basename(out_path)}')
                            else:
                                # Annotation failed, copy original
                                import shutil as sh
                                sh.copy(frame_file, out_path)
                        else:
                            # No detections, copy original frame
                            import shutil as sh
                            sh.copy(frame_file, out_path)
                    except Exception as e:
                        if i < 3:
                            print(f'  Failed to save frame: {e}')
                        # On error, try to copy original
                        try:
                            import shutil as sh
                            sh.copy(frame_file, out_path)
                        except Exception:
                            pass
            
            # Print smart skip statistics
            stats = skipper.get_stats()
            print(f'Smart frame skipping stats: {stats["processed"]} processed, {stats["skipped"]} skipped ({stats["skip_rate"]})')

            # Count annotated frames before stitching
            if ann_frames_dir:
                ann_frame_files = sorted([f for f in os.listdir(ann_frames_dir) if f.lower().endswith('.jpg')])
                print(f'Total frames saved for annotated video: {len(ann_frame_files)}')
                print(f'Expected duration: {len(ann_frame_files) / original_fps:.2f} seconds at {original_fps:.2f} FPS')

            # Optionally stitch annotated frames to a temp video and return URL via Cloudinary
            annotated_video_url: Optional[str] = None
            if ann_frames_dir:
                try:
                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    # Use original video FPS for annotated output
                    print(f'Stitching annotated video at {original_fps:.2f} FPS')
                    if _stitch_video_from_frames(ann_frames_dir, original_fps, ann_video_path):
                        print(f'Successfully stitched annotated video: {ann_video_path}')
                        
                        # Verify output video duration (functions already imported at module level)
                        try:
                            output_duration = get_video_duration(ann_video_path)
                            output_frames = get_video_frame_count(ann_video_path)
                            input_duration = get_video_duration(video_path)
                            if output_duration and input_duration:
                                print(f'Original video: {input_duration:.2f}s, Annotated video: {output_duration:.2f}s')
                                if abs(output_duration - input_duration) > 0.5:
                                    print(f'WARNING: Duration mismatch! Difference: {abs(output_duration - input_duration):.2f}s')
                            if output_frames:
                                print(f'Annotated video frame count: {output_frames}')
                        except Exception as verify_err:
                            print(f'Could not verify output video: {verify_err}')
                        
                        try:
                            from .cloudinary_utils import upload_video_streaming
                            uploaded = upload_video_streaming(ann_video_path, os.path.basename(video_path), folder="weed-detections/annotated", annotate=False)
                            annotated_video_url = uploaded.get('secure_url')
                            print(f'Annotated video uploaded to Cloudinary: {annotated_video_url}')
                        except Exception as e:
                            print(f'Failed to upload annotated video to Cloudinary: {e}')
                            annotated_video_url = None
                    else:
                        print('Failed to stitch annotated frames into video')
                except Exception as e:
                    print(f'Error creating annotated video: {e}')
                    annotated_video_url = None

            # cleanup
            shutil.rmtree(tmpdir, ignore_errors=True)
            if ann_frames_dir:
                shutil.rmtree(ann_frames_dir, ignore_errors=True)
            if annotated_video_url:
                return all_detections, annotated_video_url
            print(f'Frame-sampling fallback produced {len(all_detections)} frames of detections')
            return all_detections, None
        except Exception as ex:
            print('Frame-sampling fallback also failed:', ex)
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


def run_inference_auto(file_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None, allow_ffmpeg_fallback: bool = True) -> Tuple[Any, Optional[str]]:
    """Automatically detect file type and run appropriate inference with optimization.

    Returns (detections_or_frames, annotated_url_or_none)
    """
    file_type = detect_file_type(file_path)
    if file_type == 'image':
        return run_inference(file_path, confidence=confidence, overlap=overlap)
    if file_type == 'video':
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f'Processing video: {file_size_mb:.1f} MB')
        # Always start with configured default FPS for Roboflow batch-video
        return run_video_inference(file_path, fps=DEFAULT_VIDEO_FPS, confidence=confidence, overlap=overlap, allow_ffmpeg_fallback=allow_ffmpeg_fallback)
    print(f'Unsupported file type: {file_path}')
    return [], None

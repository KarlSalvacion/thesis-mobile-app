import os
import time
import tempfile
import subprocess
import shlex
import shutil
from typing import Any, Dict, List, Optional, Tuple

from roboflow import Roboflow
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
    ENABLE_VIDEO_PREPROCESSING,
    PREPROCESSING_DENOISE,
    PREPROCESSING_SHARPEN,
    PREPROCESSING_CONTRAST,
    PREPROCESSING_BRIGHTNESS,
    PREPROCESSING_CONTRAST_FACTOR,
)

from .config import FFMPEG_BINARY


# Initialize Roboflow client
rf = Roboflow(api_key=ROBOFLOW_API_KEY)
try:
    ws = rf.workspace(ROBOFLOW_WORKSPACE) if ROBOFLOW_WORKSPACE else rf.workspace()
except Exception:
    ws = rf.workspace()
project = ws.project(ROBOFLOW_PROJECT)
model = project.version(ROBOFLOW_VERSION).model


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


def _preprocess_video_frame(input_path: str, output_path: str) -> bool:
    """Apply preprocessing to a video frame to improve detection quality.
    
    Similar to what Roboflow does in their video preprocessing pipeline.
    """
    if not ENABLE_VIDEO_PREPROCESSING:
        # If preprocessing is disabled, just copy the file
        shutil.copy2(input_path, output_path)
        return True
    
    try:
        # Build ffmpeg filter chain for preprocessing
        filters = []
        
        # 1. Denoising (similar to Roboflow's preprocessing)
        if PREPROCESSING_DENOISE:
            filters.append("hqdn3d=4:3:6:4.5")  # High quality denoising
        
        # 2. Contrast and brightness enhancement
        if PREPROCESSING_CONTRAST or PREPROCESSING_BRIGHTNESS != 1.0:
            contrast_str = f"eq=contrast={PREPROCESSING_CONTRAST_FACTOR}:brightness={PREPROCESSING_BRIGHTNESS}"
            filters.append(contrast_str)
        
        # 3. Sharpening (helps with object edges)
        if PREPROCESSING_SHARPEN:
            filters.append("unsharp=5:5:0.8:3:3:0.4")  # Subtle sharpening
        
        # Combine all filters
        filter_chain = ",".join(filters) if filters else "null"
        
        # Build ffmpeg command
        cmd = [
            FFMPEG_BINARY, "-y", "-i", input_path,
            "-vf", filter_chain,
            "-q:v", "2",  # High quality
            "-frames:v", "1",  # Single frame
            output_path
        ]
        
        print(f"  Preprocessing frame: {os.path.basename(input_path)}")
        print(f"  Filter chain: {filter_chain}")
        
        # Execute preprocessing
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return True
        else:
            print(f"  Preprocessing failed: {result.stderr}")
            # Fallback: copy original file
            shutil.copy2(input_path, output_path)
            return False
            
    except Exception as e:
        print(f"  Preprocessing error: {e}")
        # Fallback: copy original file
        shutil.copy2(input_path, output_path)
        return False


def _normalize_prediction(pred: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize prediction from various Roboflow response formats."""
    # Handle confidence in different formats
    raw_conf = pred.get('confidence', pred.get('score', pred.get('conf', 0.0)))
    conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
    
    # Handle class names in different formats
    class_name = pred.get('class', pred.get('label', pred.get('name', pred.get('class_name', 'unknown'))))
    
    # Handle bounding box coordinates in various formats
    x, y, w, h = 0, 0, 0, 0
    
    # Format 1: Direct x, y, width, height
    if all(key in pred for key in ['x', 'y', 'width', 'height']):
        x, y, w, h = pred['x'], pred['y'], pred['width'], pred['height']
    
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
        'confidence': round(conf, 3),
        'bbox': [round(x, 1), round(y, 1), round(w, 1), round(h, 1)],
    }


def run_inference(image_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run inference on a single image.

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
            print(f'  Image inference debug: confidence={conf}, overlap={ovlp}, image={os.path.basename(image_path)}')
        
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
        return detections, annotated
    except Exception as e:
        print(f'Error in image inference: {e}')
        return [], None


def run_video_inference(video_path: str, fps: int = DEFAULT_VIDEO_FPS, confidence: Optional[int] = None, overlap: Optional[int] = None, allow_ffmpeg_fallback: bool = True) -> Tuple[List[List[Dict[str, Any]]], Optional[str]]:
    """Run inference on a video file using Roboflow batch-video API.

    Returns (list_of_frame_detections, annotated_url_or_none)
    """
    print(f'Starting Roboflow batch-video inference with fps={fps}...')
    
    try:
        # Check if we should skip Roboflow video API entirely
        skip_roboflow_video = (
            os.getenv('SKIP_ROBOFLOW_VIDEO', 'false').lower() == 'true' or 
            FORCE_LOCAL_VIDEO_PROCESSING
        )
        if skip_roboflow_video:
            print('Skipping Roboflow video API, using local frame sampling...')
            raise RuntimeError('Skipping Roboflow video API')
        api_fps = max(1, int(round(fps if fps else DEFAULT_VIDEO_FPS)))
        
        # Try batch-video first
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
        for i, frame in enumerate(frames):
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
                    if normalized['confidence'] >= DEFAULT_CONFIDENCE:
                        parsed.append(normalized)
                except Exception as e:
                    print(f'Error normalizing prediction in frame {i}: {e}')
                    continue
            
            if len(all_detections) < MAX_VIDEO_FRAMES:
                all_detections.append(parsed)
            
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
                    if len(all_detections) < MAX_VIDEO_FRAMES:
                        all_detections.append(parsed)
                
                annotated = _extract_annotated_from_response(results2 if isinstance(results2, dict) else {})
            except Exception as e:
                print(f'Retry failed: {e}')
                annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})

        if len(all_detections) == 0:
            print('Video API returned 0 frames; triggering local frame sampling fallback...')
            raise RuntimeError('Zero frames returned by video API')
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
            # Calculate number of frames to extract (cap by MAX_VIDEO_FRAMES)
            max_frames = MAX_VIDEO_FRAMES
            # Use requested fps to extract approximately that many frames
            try:
                fps_to_use = float(fps)
            except Exception:
                fps_to_use = float(DEFAULT_VIDEO_FPS)
            print(f'Extracting frames with fps={fps_to_use}, max_frames={max_frames}')

            out_pattern = os.path.join(tmpdir, 'frame_%06d.jpg')
            ffmpeg = FFMPEG_BINARY
            # Build args list to be safe on Windows (avoid shlex.quote and shell=True)
            # Extract frames with good quality and consistent scale to aid detection
            # Use bicubic scaling with max width 1280 to reduce blur/compression artifacts
            vf_filter = f'fps={fps_to_use},scale=min(1280\\,iw):-2:flags=bicubic'
            cmd_args = [
                ffmpeg,
                '-y',
                '-i', video_path,
                '-vf', vf_filter,
                '-q:v', '2',  # high-quality JPEGs
                '-vframes', str(max_frames),
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
            sampled = files[:max_frames]
            print(f'Found {len(files)} extracted frames, processing {len(sampled)} frames')
            
            # Create preprocessing directory if needed
            preprocessed_dir = None
            if ENABLE_VIDEO_PREPROCESSING:
                preprocessed_dir = tempfile.mkdtemp(prefix='rf_preprocessed_')
                print(f'Created preprocessing directory: {preprocessed_dir}')
            
            all_detections = []
            for i, frame_file in enumerate(sampled):
                print(f'Processing frame {i+1}/{len(sampled)}: {os.path.basename(frame_file)}')
                
                # Apply preprocessing if enabled
                inference_path = frame_file
                if ENABLE_VIDEO_PREPROCESSING and preprocessed_dir:
                    preprocessed_path = os.path.join(preprocessed_dir, f'preprocessed_{os.path.basename(frame_file)}')
                    if _preprocess_video_frame(frame_file, preprocessed_path):
                        inference_path = preprocessed_path
                        print(f'  Using preprocessed frame for inference')
                    else:
                        print(f'  Using original frame for inference (preprocessing failed)')
                
                dets, _ann = run_inference(inference_path, confidence=confidence, overlap=overlap)
                all_detections.append(dets)
                if i < 3:  # Log first few frames
                    print(f'  Frame {i+1} detections: {len(dets)}')
                    if len(dets) > 0:
                        print(f'  First detection: {dets[0]}')

            # cleanup
            shutil.rmtree(tmpdir, ignore_errors=True)
            if preprocessed_dir:
                shutil.rmtree(preprocessed_dir, ignore_errors=True)
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

import os
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
    DEFAULT_CONFIDENCE,
    DEFAULT_OVERLAP,
    DEFAULT_VIDEO_FPS,
    MAX_VIDEO_FRAMES,
    ENABLE_SMART_SAMPLING,
    SAMPLE_INTERVAL,
)

from .config import FFMPEG_BINARY


# Initialize Roboflow client
rf = Roboflow(api_key=ROBOFLOW_API_KEY)
project = rf.workspace().project(ROBOFLOW_PROJECT)
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


def _normalize_prediction(pred: Dict[str, Any]) -> Dict[str, Any]:
    raw_conf = pred.get('confidence', 0.0)
    conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
    x = pred.get('x') if pred.get('x') is not None else (pred.get('bbox', {}) .get('x') if isinstance(pred.get('bbox'), dict) else 0)
    y = pred.get('y') if pred.get('y') is not None else (pred.get('bbox', {}) .get('y') if isinstance(pred.get('bbox'), dict) else 0)
    w = pred.get('width') if pred.get('width') is not None else (pred.get('bbox', {}) .get('width') if isinstance(pred.get('bbox'), dict) else 0)
    h = pred.get('height') if pred.get('height') is not None else (pred.get('bbox', {}) .get('height') if isinstance(pred.get('bbox'), dict) else 0)
    return {
        'class': pred.get('class', 'unknown'),
        'confidence': round(conf, 3),
        'bbox': [round(x, 1), round(y, 1), round(w, 1), round(h, 1)],
    }


def run_inference(image_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run inference on a single image.

    Returns (detections_list, annotated_url_or_none)
    """
    try:
        conf = DEFAULT_CONFIDENCE if confidence is None else int(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else int(overlap)
        resp = model.predict(image_path, confidence=conf, overlap=ovlp)
        # SDK may return an object with .json() or be directly dict-like
        try:
            result = resp.json() if hasattr(resp, 'json') else dict(resp)
        except Exception:
            result = resp if isinstance(resp, dict) else {}

        detections: List[Dict[str, Any]] = []
        if isinstance(result, dict) and 'predictions' in result:
            for pred in result.get('predictions', []):
                detections.append(_normalize_prediction(pred))

        annotated = _extract_annotated_from_response(result)
        return detections, annotated
    except Exception as e:
        print(f'Error in image inference: {e}')
        return [], None


def run_video_inference(video_path: str, fps: int = DEFAULT_VIDEO_FPS, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[List[List[Dict[str, Any]]], Optional[str]]:
    """Run optimized inference on a video file with smart sampling.

    Returns (list_of_frame_detections, annotated_url_or_none)
    """
    print(f'Starting optimized video inference with requested fps={fps}...')
    optimized_fps = fps

    try:
        # Roboflow video API expects integer fps >= 1; clamp for API call
        api_fps = max(1, int(round(optimized_fps if optimized_fps else DEFAULT_VIDEO_FPS)))
        conf = DEFAULT_CONFIDENCE if confidence is None else int(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else int(overlap)
        job_id, signed_url, expire_time = model.predict_video(
            video_path,
            fps=api_fps,
            confidence=conf,
            overlap=ovlp,
            prediction_type='batch-video',
        )

        # Block until results are ready
        results = model.poll_until_video_results(job_id)

        all_detections: List[List[Dict[str, Any]]] = []
        if isinstance(results, dict) and 'predictions' in results:
            max_frames = min(MAX_VIDEO_FRAMES, len(results['predictions']))
            predictions = results['predictions']
            if ENABLE_SMART_SAMPLING and len(predictions) > max_frames:
                step = max(1, len(predictions) // max_frames)
                predictions = predictions[::step][:max_frames]

            print(f'Processing {len(predictions)} frames (reduced from {len(results["predictions"])})')

            for frame_result in predictions:
                frame_preds = []
                if isinstance(frame_result, dict):
                    frame_preds = frame_result.get('predictions', [])
                elif isinstance(frame_result, list):
                    frame_preds = frame_result
                else:
                    frame_preds = []

                # Keep all predictions; client can filter by confidence
                parsed = []
                for pred in frame_preds:
                    normalized = _normalize_prediction(pred)
                    # filter by confidence threshold
                    threshold = (DEFAULT_CONFIDENCE if confidence is None else int(confidence)) / 100.0
                    if normalized['confidence'] >= threshold:
                        parsed.append(normalized)
                all_detections.append(parsed)

        annotated = None
        try:
            annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})
        except Exception:
            annotated = None

        print(f'Video inference completed. Processed {len(all_detections)} frames with {sum(len(f) for f in all_detections)} total detections')
        return all_detections, annotated
    except Exception as e:
        # If the video API fails (BAD REQUEST or similar), fall back to frame sampling using ffmpeg
        print(f'Error in video inference: {e}')
        try:
            # Ensure ffmpeg is available; build a temporary dir for frames
            tmpdir = tempfile.mkdtemp(prefix='rf_frames_')
            # Calculate number of frames to extract (cap by MAX_VIDEO_FRAMES)
            max_frames = MAX_VIDEO_FRAMES
            # Use optimized_fps to extract approximately that many frames
            try:
                fps_to_use = float(optimized_fps)
            except Exception:
                fps_to_use = float(DEFAULT_VIDEO_FPS)

            out_pattern = os.path.join(tmpdir, 'frame_%06d.jpg')
            ffmpeg = FFMPEG_BINARY
            # Build args list to be safe on Windows (avoid shlex.quote and shell=True)
            cmd_args = [
                ffmpeg,
                '-y',
                '-i', video_path,
                '-vf', f'fps={fps_to_use}',
                '-vframes', str(max_frames),
                out_pattern,
            ]
            try:
                subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as ff_err:
                print('ffmpeg frame extraction failed:', ff_err)
                shutil.rmtree(tmpdir, ignore_errors=True)
                return [], None

            # Collect extracted frames in order
            files = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.lower().endswith('.jpg')])
            sampled = files[:max_frames]
            all_detections = []
            for frame_file in sampled:
                dets, _ann = run_inference(frame_file)
                all_detections.append(dets)

            # cleanup
            shutil.rmtree(tmpdir, ignore_errors=True)
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


def run_inference_auto(file_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[Any, Optional[str]]:
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
        if file_size_mb > 100:
            print('Large video detected - using ultra-fast processing mode')
            return run_video_inference(file_path, fps=0.15, confidence=confidence, overlap=overlap)
        if file_size_mb > 50:
            print('Medium video detected - using fast processing mode')
            return run_video_inference(file_path, fps=0.25, confidence=confidence, overlap=overlap)
        return run_video_inference(file_path, confidence=confidence, overlap=overlap)
    print(f'Unsupported file type: {file_path}')
    return [], None

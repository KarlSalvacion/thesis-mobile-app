import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from backend.config.settings import (
    DEFAULT_CONFIDENCE,
    DEFAULT_OVERLAP,
    DEFAULT_VIDEO_FPS,
    ENABLE_PRECOMPRESSION,
    FORCE_LOCAL_VIDEO_PROCESSING,
    FRAME_INTERVAL,
    MAX_VIDEO_FRAMES,
    VIDEO_ANNOTATION_MODE,
    USE_ORIGINAL_FPS,
)
from backend.app.inference.annotation import HAS_PIL, _annotate_image_file, _create_annotated_video_fast
from backend.app.inference.helpers import (
    _extract_annotated_from_response,
    _normalize_prediction,
    _parse_roboflow_video_response,
    detect_file_type,
)
from backend.app.inference.image_runner import run_inference
from backend.app.inference.runtime import model
from backend.utils.video.video_probe import get_video_duration, get_video_fps, get_video_frame_count
from backend.utils.video.video_utils import extract_frames_cv2, stitch_video_cv2


def run_video_inference(
    video_path: str,
    fps: int = DEFAULT_VIDEO_FPS,
    confidence: Optional[int] = None,
    overlap: Optional[int] = None,
    frame_interval: Optional[int] = None,
    max_frames: Optional[int] = None,
) -> Tuple[List[List[Dict[str, Any]]], Optional[str]]:
    """Run inference on video using Roboflow batch-video API."""
    original_fps = get_video_fps(video_path) if USE_ORIGINAL_FPS else float(DEFAULT_VIDEO_FPS)
    original_duration = get_video_duration(video_path)
    original_frame_count = get_video_frame_count(video_path)

    print(f'Starting Roboflow video inference with fps={fps}...')
    print(f'Original video: FPS={original_fps:.2f}, Duration={original_duration:.2f}s, Frames={original_frame_count}')

    try:
        interval = max(1, int(frame_interval)) if frame_interval else FRAME_INTERVAL
        print(f'Processing every {interval} frame(s) for speed optimization')
        max_allowed = int(max_frames) if max_frames is not None else MAX_VIDEO_FRAMES

        skip_roboflow_video = os.getenv('SKIP_ROBOFLOW_VIDEO', 'false').lower() == 'true' or FORCE_LOCAL_VIDEO_PROCESSING
        if skip_roboflow_video:
            print('Skipping Roboflow video API, using local frame sampling...')
            raise RuntimeError('Skipping Roboflow video API')

        api_fps = max(1, int(round(fps if fps else DEFAULT_VIDEO_FPS)))
        conf = DEFAULT_CONFIDENCE if confidence is None else float(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else float(overlap)
        if conf > 1.0:
            conf = conf / 100.0
        if ovlp > 1.0:
            ovlp = ovlp / 100.0
        conf = max(0.0, min(1.0, conf))
        ovlp = max(0.0, min(1.0, ovlp))

        job_id, _signed_url, _expire_time = model.predict_video(
            video_path,
            fps=api_fps,
            prediction_type='batch-video',
        )

        results = model.poll_until_video_results(job_id)
        frames = _parse_roboflow_video_response(results)
        print(f'Roboflow returned {len(frames)} frames at {api_fps} FPS')

        all_detections: List[List[Dict[str, Any]]] = []
        for i, frame in enumerate(frames):
            if (i % interval) != 0:
                continue

            raw_preds = []
            if isinstance(frame, dict):
                if all(key in ['frame_offset', 'time_offset', 'timestamp', 'frame_number'] for key in frame.keys()):
                    continue
                if 'predictions' in frame and isinstance(frame['predictions'], list):
                    raw_preds = frame['predictions']
                elif 'detections' in frame and isinstance(frame['detections'], list):
                    raw_preds = frame['detections']
                elif 'objects' in frame and isinstance(frame['objects'], list):
                    raw_preds = frame['objects']
                elif any(key in frame for key in ['class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                    raw_preds = [frame]
            elif isinstance(frame, list):
                raw_preds = frame

            parsed = []
            for p in raw_preds:
                try:
                    normalized = _normalize_prediction(p)
                    if normalized['confidence'] >= conf:
                        parsed.append(normalized)
                except Exception as e:
                    if i < 3:
                        print(f'Error normalizing prediction in frame {i}: {e}')
                    continue

            if len(all_detections) < max_allowed:
                all_detections.append(parsed)
            else:
                break

            if i == 0 or (i + 1) % 100 == 0:
                total_dets = sum(len(dets) for dets in all_detections)
                print(f'Processed {i+1}/{len(frames)} frames, {total_dets} total detections')

        annotated = _extract_annotated_from_response(results if isinstance(results, dict) else {})

        if len(all_detections) == 0:
            print('Video API returned 0 frames; trying alternative prediction method...')
            try:
                job_id2, _signed_url2, _expire_time2 = model.predict_video(video_path, fps=api_fps)
                results2 = model.poll_until_video_results(job_id2)
                frames2 = _parse_roboflow_video_response(results2)
                print(f'Retry returned {len(frames2)} frames')

                for frame in frames2:
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

        if HAS_PIL and len(all_detections) > 0 and any(len(frame_dets) > 0 for frame_dets in all_detections):
            print('Creating annotated video from Roboflow API results...')
            use_fast_mode = VIDEO_ANNOTATION_MODE == 'fast'

            if use_fast_mode:
                print('Using FAST annotation mode (FFmpeg overlay)')
                try:
                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    if _create_annotated_video_fast(video_path, all_detections, ann_video_path, api_fps, original_fps):
                        print(f'Successfully created annotated video: {ann_video_path}')
                        try:
                            from utils.cloudinary_utils import upload_video_streaming
                            from config.settings import MAX_CLOUDINARY_UPLOAD_SIZE
                            from backend.utils.video.video_utils import transcode_video_to_preview

                            video_size = os.path.getsize(ann_video_path)
                            upload_path = ann_video_path

                            if video_size > MAX_CLOUDINARY_UPLOAD_SIZE:
                                print(f'Annotated video too large ({video_size / (1024*1024):.2f} MB), compressing with FFmpeg...')
                                try:
                                    upload_path = transcode_video_to_preview(ann_video_path)
                                    compressed_size = os.path.getsize(upload_path)
                                    print(f'FFmpeg compressed to {compressed_size / (1024*1024):.2f} MB')
                                except Exception as compress_err:
                                    print(f'FFmpeg compression failed: {compress_err}, uploading original')
                                    upload_path = ann_video_path

                            uploaded = upload_video_streaming(upload_path, os.path.basename(video_path), folder='weed-detections/annotated', annotate=False)
                            annotated = uploaded.get('secure_url')
                            print(f'Annotated video uploaded to Cloudinary: {annotated}')

                            if upload_path != ann_video_path and os.path.exists(upload_path):
                                try:
                                    os.remove(upload_path)
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f'Failed to upload annotated video: {e}')

                        try:
                            if os.path.exists(ann_video_path):
                                os.remove(ann_video_path)
                        except Exception:
                            pass
                    else:
                        print('Fast annotation failed, falling back to quality mode')
                        use_fast_mode = False
                except Exception as e:
                    print(f'Error in fast annotation: {e}')
                    import traceback

                    traceback.print_exc()
                    use_fast_mode = False

            if not use_fast_mode:
                print('Using QUALITY annotation mode (OpenCV frame extraction)')
                print('Optimized mode: only extracting frames at detection FPS')
                try:
                    frame_paths = extract_frames_cv2(video_path, target_fps=api_fps, max_frames=MAX_VIDEO_FRAMES)
                    if frame_paths is None:
                        raise RuntimeError('OpenCV not available for frame extraction. Please install opencv-python-headless.')

                    print(f'OpenCV extracted {len(frame_paths)} frames successfully')
                    files = frame_paths
                    tmpdir = os.path.dirname(frame_paths[0]) if frame_paths else None

                    total_frames = len(files)
                    ann_frames_dir = tempfile.mkdtemp(prefix='rf_robo_ann_')
                    annotated_count = 0

                    for i, frame_file in enumerate(files):
                        out_path = os.path.join(ann_frames_dir, f'ann_{i+1:06d}.jpg')

                        if i < len(all_detections) and all_detections[i]:
                            try:
                                ann_bytes = _annotate_image_file(frame_file, all_detections[i])
                                if ann_bytes:
                                    with open(out_path, 'wb') as f:
                                        f.write(ann_bytes)
                                    annotated_count += 1
                                else:
                                    shutil.copy(frame_file, out_path)
                            except Exception:
                                shutil.copy(frame_file, out_path)
                        else:
                            shutil.copy(frame_file, out_path)

                    ann_video_path = tempfile.mktemp(suffix='_annotated.mp4')
                    stitch_success = stitch_video_cv2(ann_frames_dir, api_fps, ann_video_path, frame_pattern='ann_%06d.jpg', target_size_mb=70)
                    if not stitch_success:
                        raise RuntimeError('OpenCV video stitching failed. Please check opencv-python-headless installation.')

                    video_size_mb = os.path.getsize(ann_video_path) / (1024 * 1024)
                    print(f'Successfully stitched annotated video: {video_size_mb:.2f} MB ({annotated_count} annotated frames)')

                    if video_size_mb <= 100:
                        from utils.cloudinary_utils import upload_video_streaming

                        try:
                            video_filename = os.path.basename(video_path) if video_path else 'video.mp4'
                            uploaded = upload_video_streaming(
                                ann_video_path,
                                video_filename,
                                folder='weed-detections/annotated',
                                annotate=False,
                            )
                            annotated = uploaded.get('secure_url')

                            shutil.rmtree(tmpdir, ignore_errors=True)
                            shutil.rmtree(ann_frames_dir, ignore_errors=True)
                            if os.path.exists(ann_video_path):
                                os.remove(ann_video_path)
                        except Exception as upload_error:
                            print(f'Cloudinary upload failed: {upload_error}')
                            annotated = ann_video_path
                            shutil.rmtree(tmpdir, ignore_errors=True)
                            shutil.rmtree(ann_frames_dir, ignore_errors=True)
                    else:
                        print(f'Video size {video_size_mb:.2f} MB exceeds 100MB limit')
                        annotated = ann_video_path
                        shutil.rmtree(tmpdir, ignore_errors=True)
                        shutil.rmtree(ann_frames_dir, ignore_errors=True)

                except Exception as e:
                    print(f'Error creating annotated video from Roboflow results: {e}')
                    import traceback

                    traceback.print_exc()

        return all_detections, annotated

    except Exception as e:
        print(f'Error in video inference: {e}')
        print('FALLBACK DISABLED: Frame-by-frame inference.')
        print('Possible solutions:')
        print('  1. Check if video is too large (compress before upload)')
        print('  2. Check if video format is supported by Roboflow')
        print('  3. Verify Roboflow API key and project settings')
        return [], None


def run_inference_auto(file_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[Any, Optional[str]]:
    """Detect file type and run image/video inference with optional pre-compression."""
    file_type = detect_file_type(file_path)
    if file_type == 'image':
        return run_inference(file_path, confidence=confidence, overlap=overlap)

    if file_type == 'video':
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f'Processing video: {file_size_mb:.1f} MB')

        compressed_path = None
        inference_path = file_path
        try:
            if file_size_mb > 100:
                print(f'Video exceeds 100 MB ({file_size_mb:.1f} MB), compressing for Roboflow upload...')
                if ENABLE_PRECOMPRESSION:
                    from backend.utils.video.video_utils import compress_for_inference

                    compressed_path = compress_for_inference(file_path, max_size_mb=100, force=False)
                    if compressed_path != file_path:
                        inference_path = compressed_path
                        print(f'Compressed with FFmpeg: {os.path.getsize(compressed_path) / (1024 * 1024):.1f} MB')
                    else:
                        print('Pre-compression disabled and api.video not available')
                else:
                    print('Pre-compression disabled and api.video not available')

            if DEFAULT_VIDEO_FPS is None:
                import math

                detected_fps = get_video_fps(inference_path)
                api_fps = int(math.floor(detected_fps))
                print(f'Auto-detected FPS: {detected_fps:.2f} -> Using {api_fps} for Roboflow API (rounded down)')
            else:
                api_fps = DEFAULT_VIDEO_FPS
                print(f'Using configured FPS: {api_fps}')

            return run_video_inference(inference_path, fps=api_fps, confidence=confidence, overlap=overlap)
        finally:
            if compressed_path and compressed_path != file_path and os.path.exists(compressed_path):
                try:
                    os.remove(compressed_path)
                    print(f'Cleaned up compressed file: {compressed_path}')
                except Exception as e:
                    print(f'Warning: Failed to delete compressed file {compressed_path}: {e}')

    print(f'Unsupported file type: {file_path}')
    return [], None

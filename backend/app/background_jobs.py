import datetime
import json
import os
import time
import traceback

from config.settings import DEFAULT_VIDEO_FPS, MAX_CLOUDINARY_UPLOAD_SIZE, MEMORY_CLEANUP_INTERVAL
from db.database import (
    get_job_status,
    insert_detection,
    update_job_result,
    update_job_status,
    update_srt_status,
    upsert_srt_track,
)
from inference.engine import _annotate_image_file, detect_file_type, run_inference_auto
from utils.cloudinary_utils import upload_image_bytes, upload_remote_url, upload_video_streaming
from utils.srt_parser import parse_srt_file, validate_srt_file
from utils.video_utils import transcode_video_to_preview


def cleanup_temp_files():
    """Clean up temporary files to prevent disk space issues."""
    import glob

    temp_patterns = [
        '/tmp/rf_robo_*',
        '/tmp/tmp*',
        '/tmp/*_annotated.mp4',
        '/tmp/temp_*.mp4',
    ]

    cleaned_count = 0
    for pattern in temp_patterns:
        for file_path in glob.glob(pattern):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    cleaned_count += 1
            except Exception as e:
                print(f'Warning: Could not remove {file_path}: {e}')

    if cleaned_count > 0:
        print(f'Cleaned up {cleaned_count} temporary files')


def process_media_background(
    job_id: str,
    media_path: str,
    media_filename: str,
    media_bytes: bytes,
    srt_content: bytes = None,
    srt_filename: str = None,
    is_video: bool = False,
    is_image: bool = False,
    skip_cloud: bool = False,
    confidence: int = None,
    overlap: int = None,
):
    """Process media file in background."""
    try:
        start_time = time.time()
        update_job_status(job_id, 'processing', 'Running inference...')

        print(f'[Job {job_id}] Starting inference...')
        detections, annotated_source = run_inference_auto(media_path, confidence=confidence, overlap=overlap)
        print(f'[Job {job_id}] Inference completed in {time.time() - start_time:.2f} seconds')

        update_job_status(job_id, 'processing', 'Uploading to cloud storage...')

        actual_file_type = detect_file_type(media_path)
        processing_time = time.time() - start_time
        input_size_bytes = len(media_bytes)

        try:
            result_size_bytes = len(json.dumps(detections).encode('utf-8')) if detections is not None else 0
        except Exception:
            result_size_bytes = None

        if isinstance(detections, list) and len(detections) > 0:
            if isinstance(detections[0], list):
                total_frames = len(detections)
                total_detections = sum(len(frame) for frame in detections)
                summary = f'Detected {total_detections} objects across {total_frames} frames'
            else:
                total_frames = 1
                total_detections = len(detections)
                summary = f'Detected {total_detections} objects'
        else:
            total_frames = 1 if actual_file_type == 'image' else 0
            total_detections = 0
            summary = 'No objects detected'

        timestamp = datetime.datetime.now().isoformat()
        has_srt_data = srt_content is not None

        cloud_result = None
        cloud_resource_type = None
        try:
            if skip_cloud:
                cloud_result = None
                cloud_resource_type = None
            elif is_image:
                cloud_result = upload_image_bytes(media_filename, media_bytes, folder='weed-detections/originals', annotate=True)
                cloud_resource_type = 'image'
            else:
                upload_path_for_cloud = media_path
                try:
                    size = os.path.getsize(media_path)
                    if size > MAX_CLOUDINARY_UPLOAD_SIZE:
                        print(f'[Job {job_id}] File too large ({size / (1024*1024):.2f} MB), compressing with FFmpeg...')
                        try:
                            upload_path_for_cloud = transcode_video_to_preview(media_path)
                            if os.path.getsize(upload_path_for_cloud) > MAX_CLOUDINARY_UPLOAD_SIZE:
                                raise Exception('Transcoded file still too large for Cloudinary')
                        except FileNotFoundError:
                            raise Exception('File size too large for Cloudinary. Install ffmpeg to proceed')
                except Exception:
                    try:
                        upload_path_for_cloud = transcode_video_to_preview(media_path)
                    except FileNotFoundError:
                        upload_path_for_cloud = media_path

                if not skip_cloud:
                    cloud_result = upload_video_streaming(upload_path_for_cloud, media_filename, folder='weed-detections/originals', annotate=True)
                    cloud_resource_type = 'video'
        except Exception as e:
            print(f'[Job {job_id}] Cloud upload failed: {e}')
            traceback.print_exc()

        if is_image and isinstance(detections, list) and len(detections) > 0:
            try:
                ann_bytes = _annotate_image_file(media_path, detections)
                if ann_bytes:
                    uploaded = upload_image_bytes(
                        f"{os.path.splitext(media_filename)[0]}-annotated.jpg",
                        ann_bytes,
                        folder='weed-detections/annotated',
                        annotate=False,
                    )
                    annotated_source = uploaded.get('secure_url')
            except Exception as e:
                print(f'[Job {job_id}] Error annotating image: {e}')

        annotated_url = None
        temp_video_path = None

        try:
            if annotated_source:
                if isinstance(annotated_source, str) and not annotated_source.startswith('http') and os.path.exists(annotated_source):
                    temp_video_path = annotated_source
                    print(f'[Job {job_id}] Temp video ready for client compression: {temp_video_path}')
                    annotated_url = None
                elif isinstance(annotated_source, str) and annotated_source.startswith('http'):
                    if 'res.cloudinary.com' in annotated_source:
                        annotated_url = annotated_source
                    else:
                        try:
                            remote_uploaded = upload_remote_url(
                                annotated_source,
                                media_filename,
                                folder='weed-detections/annotated',
                                resource_type=('video' if is_video else 'image'),
                                annotate=True,
                            )
                            annotated_url = remote_uploaded.get('annotated_url') or remote_uploaded.get('secure_url')
                        except Exception:
                            annotated_url = annotated_source
                elif isinstance(annotated_source, (bytes, bytearray)) and not is_video:
                    try:
                        base, _ext = os.path.splitext(media_filename)
                        uploaded = upload_image_bytes(
                            f'{base}-annotated.jpg',
                            annotated_source,
                            folder='weed-detections/annotated',
                            annotate=True,
                        )
                        annotated_url = uploaded.get('annotated_url') or uploaded.get('secure_url')
                    except Exception:
                        annotated_url = None

            if not annotated_url and cloud_result:
                if isinstance(cloud_result, dict) and cloud_result.get('eager'):
                    eager = cloud_result.get('eager')
                    if isinstance(eager, list) and len(eager) > 0 and eager[0].get('secure_url'):
                        annotated_url = eager[0].get('secure_url')
                if not annotated_url:
                    annotated_url = cloud_result.get('secure_url')
        except Exception:
            annotated_url = cloud_result.get('secure_url') if cloud_result else None

        update_job_status(job_id, 'processing', 'Saving to database...')

        job_data = get_job_status(job_id)
        display_filename = job_data.get('original_filename', media_filename) if job_data else media_filename

        detection_id = insert_detection(
            filename=display_filename,
            timestamp=timestamp,
            file_type=actual_file_type,
            summary=summary,
            total_frames=total_frames,
            total_detections=total_detections,
            processing_time=processing_time,
            input_size_bytes=input_size_bytes,
            result_size_bytes=result_size_bytes,
            has_srt_data=has_srt_data,
            cloud_public_id=(cloud_result.get('public_id') if cloud_result else None),
            cloud_resource_type=cloud_resource_type if cloud_result else None,
            cloud_secure_url=(cloud_result.get('secure_url') if cloud_result else None),
            cloud_annotated_url=annotated_url,
        )

        if detections and len(detections) > 0:
            batch_details = []
            detection_rate = None
            orig_video_fps = None
            if actual_file_type == 'video':
                try:
                    import cv2

                    cap = cv2.VideoCapture(media_path)
                    orig_video_fps = cap.get(cv2.CAP_PROP_FPS)
                    cap.release()
                    if orig_video_fps <= 0:
                        orig_video_fps = None
                except Exception:
                    orig_video_fps = None

                if orig_video_fps is None:
                    orig_video_fps = DEFAULT_VIDEO_FPS if DEFAULT_VIDEO_FPS else 30.0

                try:
                    from utils.video_probe import get_video_duration

                    duration_s = get_video_duration(media_path)
                    detection_frames_count = 0
                    if isinstance(detections, list) and len(detections) > 0 and isinstance(detections[0], list):
                        detection_frames_count = len(detections)
                    elif detections:
                        detection_frames_count = 1

                    if detection_frames_count > 0 and duration_s and duration_s > 0:
                        detection_rate = detection_frames_count / float(duration_s)
                    else:
                        detection_rate = orig_video_fps
                except Exception:
                    detection_rate = orig_video_fps

            for frame_idx, frame_detections in enumerate(detections if isinstance(detections[0], list) else [detections]):
                frame_timestamp_ms = 0
                if detection_rate and detection_rate > 0:
                    frame_timestamp_ms = int((frame_idx / detection_rate) * 1000)
                else:
                    if orig_video_fps and orig_video_fps > 0:
                        frame_timestamp_ms = int((frame_idx / orig_video_fps) * 1000)

                hours = frame_timestamp_ms // 3600000
                minutes = (frame_timestamp_ms % 3600000) // 60000
                seconds = (frame_timestamp_ms % 60000) // 1000
                milliseconds = frame_timestamp_ms % 1000
                frame_timestamp_str = f'{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}'

                for det in frame_detections:
                    batch_details.append(
                        {
                            'frame_number': frame_idx + 1,
                            'weed_class': det.get('class', 'unknown'),
                            'confidence': det.get('confidence', 0.0),
                            'bbox_x': det.get('bbox', [0, 0, 0, 0])[0],
                            'bbox_y': det.get('bbox', [0, 0, 0, 0])[1],
                            'bbox_width': det.get('bbox', [0, 0, 0, 0])[2],
                            'bbox_height': det.get('bbox', [0, 0, 0, 0])[3],
                            'detection_timestamp': frame_timestamp_str,
                        }
                    )

            if batch_details:
                from db.database import batch_insert_detection_details

                batch_insert_detection_details(detection_id, batch_details)

        srt_message = ''
        if srt_content:
            try:
                srt_text = srt_content.decode('utf-8')

                if not validate_srt_file(srt_text):
                    raise Exception('Invalid SRT file format')

                frames = parse_srt_file(srt_text)
                if not frames:
                    raise Exception('No valid frame data found in SRT file')

                coords = []
                min_lat = min_lon = float('inf')
                max_lat = max_lon = float('-inf')
                compact_frames = []

                for f in frames:
                    lat = f.get('latitude')
                    lon = f.get('longitude')
                    if lat is None or lon is None:
                        continue
                    coords.append([lon, lat])
                    if lat < min_lat:
                        min_lat = lat
                    if lat > max_lat:
                        max_lat = lat
                    if lon < min_lon:
                        min_lon = lon
                    if lon > max_lon:
                        max_lon = lon
                    compact_frames.append({'i': f.get('frame_number'), 't': f.get('timestamp'), 'lat': lat, 'lon': lon, 'alt': f.get('altitude')})

                if coords:
                    start_time_srt = frames[0].get('timestamp') if frames else None
                    end_time_srt = frames[-1].get('timestamp') if frames else None

                    bounds_geojson = json.dumps(
                        {
                            'type': 'Feature',
                            'properties': {},
                            'geometry': {
                                'type': 'Polygon',
                                'coordinates': [
                                    [
                                        [min_lon, min_lat],
                                        [max_lon, min_lat],
                                        [max_lon, max_lat],
                                        [min_lon, max_lat],
                                        [min_lon, min_lat],
                                    ]
                                ],
                            },
                        }
                    )

                    path_geojson = json.dumps(
                        {
                            'type': 'Feature',
                            'properties': {'detection_id': detection_id},
                            'geometry': {'type': 'LineString', 'coordinates': coords},
                        }
                    )

                    frames_json = json.dumps(compact_frames)

                    upsert_srt_track(detection_id, len(coords), start_time_srt, end_time_srt, bounds_geojson, path_geojson, frames_json)
                    srt_message = f' with {len(coords)} GPS points'
                else:
                    srt_message = ' (SRT file contained no GPS coordinates)'

            except Exception as e:
                srt_message = f' (SRT processing failed: {str(e)})'
                update_srt_status(detection_id, False)

        try:
            os.remove(media_path)
        except Exception:
            pass

        result_data = {
            'message': f'File uploaded and processed successfully{srt_message}',
            'detection_id': detection_id,
            'summary': summary,
            'processing_time': f'{processing_time:.2f}s',
            'has_srt_data': has_srt_data and srt_message and 'failed' not in srt_message,
            'cloud_public_id': cloud_result.get('public_id') if cloud_result else None,
            'cloud_resource_type': cloud_resource_type if cloud_result else None,
            'cloud_secure_url': cloud_result.get('secure_url') if cloud_result else None,
            'cloud_annotated_url': annotated_url,
            'needs_client_compression': temp_video_path is not None,
        }

        update_job_result(
            job_id=job_id,
            detection_id=detection_id,
            result_json=json.dumps(result_data),
            annotated_url=annotated_url,
            temp_video_path=temp_video_path,
            needs_compression=(temp_video_path is not None),
        )

        print(f'[Job {job_id}] Processing completed successfully')

        if temp_video_path:
            print(f'[Job {job_id}] Waiting for client to compress and upload annotated video')

    except Exception as e:
        print(f'[Job {job_id}] Processing failed: {e}')
        traceback.print_exc()
        update_job_status(job_id, 'failed', error_message=str(e))

        try:
            if os.path.exists(media_path):
                os.remove(media_path)
        except Exception:
            pass

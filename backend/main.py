import os
import datetime
import time
import uuid
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import json
from psycopg2.extras import RealDictCursor
from .inference import run_inference_auto, detect_file_type, _annotate_image_file
import tempfile
import traceback
from .cloudinary_utils import upload_image_bytes, upload_video_streaming, build_delivery_url, upload_remote_url
from .video_utils import transcode_video_to_preview
from io import BytesIO
try:
    from PIL import Image
except Exception:
    Image = None
from .database import (
    insert_detection, insert_detection_details,
    fetch_detection_session, fetch_all_detections, get_detection_statistics,
    upsert_srt_track, reset_compact_tables, update_srt_status, init_db,
    fetch_detections_by_class, upsert_heatmap, calculate_unique_weeds,
    # Job queue management
    create_processing_job, update_job_status, update_job_result,
    get_job_status, mark_compression_started, mark_compression_completed,
    get_pending_compression_jobs, cleanup_old_jobs, get_db_connection, close_connection_pool
)
from .srt_parser import parse_srt_file, validate_srt_file

# Helper function to convert dict rows to tuple arrays for frontend compatibility
def dict_to_detection_tuple(row: dict) -> list:
    """
    Convert a detection dict (from RealDictCursor) to a tuple array matching frontend expectations.
    Frontend expects a 21-element tuple in exact column order from detections table.
    
    Order matches: id, filename, timestamp, file_type, summary, total_frames, total_detections,
    processing_time, input_size_bytes, result_size_bytes, has_srt_data, cloud_public_id,
    cloud_resource_type, cloud_secure_url, cloud_annotated_url, weed_class_counts, has_gps_data,
    bounds_min_lat, bounds_max_lat, bounds_min_lng, bounds_max_lng
    """
    return [
        row['id'],                          # 0
        row['filename'],                    # 1
        row['timestamp'],                   # 2
        row['file_type'],                   # 3
        row.get('summary'),                 # 4
        row.get('total_frames', 0),         # 5
        row.get('total_detections', 0),     # 6
        row.get('processing_time', 0.0),    # 7
        row.get('input_size_bytes'),        # 8
        row.get('result_size_bytes'),       # 9
        row.get('has_srt_data', False),     # 10
        row.get('cloud_public_id'),         # 11
        row.get('cloud_resource_type'),     # 12
        row.get('cloud_secure_url'),        # 13
        row.get('cloud_annotated_url'),     # 14
        row.get('weed_class_counts'),       # 15
        row.get('has_gps_data', False),     # 16
        row.get('bounds_min_lat'),          # 17
        row.get('bounds_max_lat'),          # 18
        row.get('bounds_min_lng'),          # 19
        row.get('bounds_max_lng')           # 20
    ]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Local uploads no longer required; keep optional for dev if present
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
if os.path.isdir(UPLOAD_DIR):
    try:
        app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
    except Exception:
        pass

# Initialize DB
init_db()

# Job storage for background processing
processing_jobs: Dict[str, Dict[str, Any]] = {}

# Render.com Standard Plan: Job queue management
from .config import MAX_CONCURRENT_JOBS
active_jobs = 0
job_queue = []

def cleanup_temp_files():
    """Clean up temporary files to prevent disk space issues on Render.com"""
    import glob
    import os
    from .config import MEMORY_CLEANUP_INTERVAL
    
    temp_patterns = [
        '/tmp/rf_robo_*',
        '/tmp/tmp*',
        '/tmp/*_annotated.mp4',
        '/tmp/temp_*.mp4'
    ]
    
    cleaned_count = 0
    for pattern in temp_patterns:
        for file_path in glob.glob(pattern):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    cleaned_count += 1
            except Exception as e:
                print(f"Warning: Could not remove {file_path}: {e}")
    
    if cleaned_count > 0:
        print(f"🧹 Cleaned up {cleaned_count} temporary files")

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
    overlap: int = None
):
    """Process media file in background."""
    try:
        start_time = time.time()
        update_job_status(job_id, "processing", "Running inference...")
        
        # Run inference
        print(f"[Job {job_id}] Starting inference...")
        detections, annotated_source = run_inference_auto(media_path, confidence=confidence, overlap=overlap)
        print(f"[Job {job_id}] Inference completed in {time.time() - start_time:.2f} seconds")
        
        update_job_status(job_id, "processing", "Uploading to cloud storage...")
        
        # Get file type and process results
        actual_file_type = detect_file_type(media_path)
        processing_time = time.time() - start_time
        input_size_bytes = len(media_bytes)
        
        try:
            result_size_bytes = len(json.dumps(detections).encode('utf-8')) if detections is not None else 0
        except Exception:
            result_size_bytes = None

        # Calculate detection summary
        if isinstance(detections, list) and len(detections) > 0:
            if isinstance(detections[0], list):  # Video results
                total_frames = len(detections)
                total_detections = sum(len(frame) for frame in detections)
                summary = f"Detected {total_detections} objects across {total_frames} frames"
            else:  # Image results
                total_frames = 1
                total_detections = len(detections)
                summary = f"Detected {total_detections} objects"
        else:
            total_frames = 1 if actual_file_type == "image" else 0
            total_detections = 0
            summary = "No objects detected"
        
        timestamp = datetime.datetime.now().isoformat()
        has_srt_data = srt_content is not None

        # Upload original media to Cloudinary
        cloud_result = None
        cloud_resource_type = None
        try:
            if skip_cloud:
                cloud_result = None
                cloud_resource_type = None
            elif is_image:
                cloud_result = upload_image_bytes(media_filename, media_bytes, folder="weed-detections/originals", annotate=True)
                cloud_resource_type = "image"
            else:
                upload_path_for_cloud = media_path
                used_compressed = False
                try:
                    size = os.path.getsize(media_path)
                    from .config import MAX_CLOUDINARY_UPLOAD_SIZE
                    
                    if size > MAX_CLOUDINARY_UPLOAD_SIZE:
                        print(f"[Job {job_id}] File too large ({size / (1024*1024):.2f} MB), compressing with FFmpeg...")
                        try:
                            upload_path_for_cloud = transcode_video_to_preview(media_path)
                            used_compressed = True
                            if os.path.getsize(upload_path_for_cloud) > MAX_CLOUDINARY_UPLOAD_SIZE:
                                raise Exception(f"Transcoded file still too large for Cloudinary")
                        except FileNotFoundError:
                            raise Exception(f"File size too large for Cloudinary. Install ffmpeg to proceed")
                except Exception:
                    try:
                        upload_path_for_cloud = transcode_video_to_preview(media_path)
                        used_compressed = True
                    except FileNotFoundError:
                        upload_path_for_cloud = media_path

                if not skip_cloud:
                    cloud_result = upload_video_streaming(upload_path_for_cloud, media_filename, folder="weed-detections/originals", annotate=True)
                    cloud_resource_type = "video"
        except Exception as e:
            print(f"[Job {job_id}] Cloud upload failed: {e}")
            traceback.print_exc()

        # Annotate image if applicable
        if is_image and isinstance(detections, list) and len(detections) > 0:
            try:
                ann_bytes = _annotate_image_file(media_path, detections)
                if ann_bytes:
                    uploaded = upload_image_bytes(f"{os.path.splitext(media_filename)[0]}-annotated.jpg", ann_bytes, folder="weed-detections/annotated", annotate=False)
                    annotated_source = uploaded.get('secure_url')
            except Exception as e:
                print(f"[Job {job_id}] Error annotating image: {e}")

        # Determine annotated URL
        annotated_url = None
        temp_video_path = None  # For client-side compression
        
        try:
            if annotated_source:
                # Check if it's a local file path (for client-side compression)
                if isinstance(annotated_source, str) and not annotated_source.startswith('http') and os.path.exists(annotated_source):
                    # This is a temp video file path - store it for client download
                    temp_video_path = annotated_source
                    # Note: temp_video_path will be saved to DB later in update_job_result()
                    print(f"[Job {job_id}] Temp video ready for client compression: {temp_video_path}")
                    annotated_url = None  # Will be set after client uploads compressed version
                elif isinstance(annotated_source, str) and annotated_source.startswith('http'):
                    if 'res.cloudinary.com' in annotated_source:
                        annotated_url = annotated_source
                    else:
                        try:
                            remote_uploaded = upload_remote_url(annotated_source, media_filename, folder="weed-detections/annotated", resource_type=("video" if is_video else "image"), annotate=True)
                            annotated_url = remote_uploaded.get('annotated_url') or remote_uploaded.get('secure_url')
                        except Exception:
                            annotated_url = annotated_source
                elif isinstance(annotated_source, (bytes, bytearray)) and not is_video:
                    try:
                        base, _ext = os.path.splitext(media_filename)
                        uploaded = upload_image_bytes(f"{base}-annotated.jpg", annotated_source, folder="weed-detections/annotated", annotate=True)
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

        update_job_status(job_id, "processing", "Saving to database...")
        
        # Get original filename from job (for consistent naming between continuous and resumed uploads)
        job_data = get_job_status(job_id)
        display_filename = job_data.get("original_filename", media_filename) if job_data else media_filename
        
        # Insert detection record
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
            cloud_public_id=(cloud_result.get("public_id") if cloud_result else None),
            cloud_resource_type=cloud_resource_type if cloud_result else None,
            cloud_secure_url=(cloud_result.get("secure_url") if cloud_result else None),
            cloud_annotated_url=annotated_url,
        )

        # Store detection details
        if detections and len(detections) > 0:
            batch_details = []

            # Determine detection/frame rate for timestamp calculation.
            # NOTE: `detections` for video is returned at the detection FPS (api_fps),
            # which may be lower than the original video FPS. We must compute timestamps
            # using the detection frame rate (detections_per_second) so saved timestamps
            # map correctly to the video's timeline. Fall back to original FPS or
            # configured DEFAULT_VIDEO_FPS if we cannot compute detection rate.
            detection_rate = None
            orig_video_fps = None
            if actual_file_type == "video":
                try:
                    # Try to get original FPS from metadata
                    import cv2
                    cap = cv2.VideoCapture(media_path)
                    orig_video_fps = cap.get(cv2.CAP_PROP_FPS)
                    cap.release()
                    if orig_video_fps <= 0:
                        orig_video_fps = None
                except Exception:
                    orig_video_fps = None

                # Fallback to config FPS if original FPS not available
                from .config import DEFAULT_VIDEO_FPS
                if orig_video_fps is None:
                    orig_video_fps = DEFAULT_VIDEO_FPS if DEFAULT_VIDEO_FPS else 30.0

                # Prefer to compute detection_rate from returned detections and video duration
                try:
                    from .video_utils import get_video_duration
                    duration_s = get_video_duration(media_path)
                    # Count detection frames returned (for video results each item is a list)
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
                # Calculate frame timestamp in milliseconds from start of video
                frame_timestamp_ms = 0
                # Use detection_rate (frames per second used to generate detections) to compute timestamp
                if detection_rate and detection_rate > 0:
                    frame_timestamp_ms = int((frame_idx / detection_rate) * 1000)
                else:
                    # Fallback: use original video fps if available
                    if orig_video_fps and orig_video_fps > 0:
                        frame_timestamp_ms = int((frame_idx / orig_video_fps) * 1000)

                # Format as HH:MM:SS,mmm (SRT timestamp format)
                hours = frame_timestamp_ms // 3600000
                minutes = (frame_timestamp_ms % 3600000) // 60000
                seconds = (frame_timestamp_ms % 60000) // 1000
                milliseconds = frame_timestamp_ms % 1000
                frame_timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

                for det in frame_detections:
                    batch_details.append({
                        'frame_number': frame_idx + 1,
                        'weed_class': det.get('class', 'unknown'),
                        'confidence': det.get('confidence', 0.0),
                        'bbox_x': det.get('bbox', [0, 0, 0, 0])[0],
                        'bbox_y': det.get('bbox', [0, 0, 0, 0])[1],
                        'bbox_width': det.get('bbox', [0, 0, 0, 0])[2],
                        'bbox_height': det.get('bbox', [0, 0, 0, 0])[3],
                        'detection_timestamp': frame_timestamp_str  # Video timestamp, not upload timestamp
                    })
            
            if batch_details:
                from backend.database import batch_insert_detection_details
                batch_insert_detection_details(detection_id, batch_details)

        # Process SRT file if provided
        srt_message = ""
        if srt_content:
            try:
                srt_text = srt_content.decode('utf-8')
                
                if not validate_srt_file(srt_text):
                    raise Exception("Invalid SRT file format")
                
                frames = parse_srt_file(srt_text)
                if not frames:
                    raise Exception("No valid frame data found in SRT file")

                coords = []
                min_lat = min_lon = float("inf")
                max_lat = max_lon = float("-inf")
                compact_frames = []
                
                for f in frames:
                    lat = f.get('latitude')
                    lon = f.get('longitude')
                    if lat is None or lon is None:
                        continue
                    coords.append([lon, lat])
                    if lat < min_lat: min_lat = lat
                    if lat > max_lat: max_lat = lat
                    if lon < min_lon: min_lon = lon
                    if lon > max_lon: max_lon = lon
                    compact_frames.append({
                        'i': f.get('frame_number'),
                        't': f.get('timestamp'),
                        'lat': lat,
                        'lon': lon,
                        'alt': f.get('altitude')
                    })

                if coords:
                    start_time_srt = frames[0].get('timestamp') if frames else None
                    end_time_srt = frames[-1].get('timestamp') if frames else None

                    bounds_geojson = json.dumps({
                        'type': 'Feature',
                        'properties': {},
                        'geometry': {
                            'type': 'Polygon',
                            'coordinates': [[
                                [min_lon, min_lat],
                                [max_lon, min_lat],
                                [max_lon, max_lat],
                                [min_lon, max_lat],
                                [min_lon, min_lat]
                            ]]
                        }
                    })

                    path_geojson = json.dumps({
                        'type': 'Feature',
                        'properties': {'detection_id': detection_id},
                        'geometry': {'type': 'LineString', 'coordinates': coords}
                    })

                    frames_json = json.dumps(compact_frames)

                    upsert_srt_track(detection_id, len(coords), start_time_srt, end_time_srt, bounds_geojson, path_geojson, frames_json)
                    srt_message = f" with {len(coords)} GPS points"
                else:
                    srt_message = " (SRT file contained no GPS coordinates)"
                    
            except Exception as e:
                srt_message = f" (SRT processing failed: {str(e)})"
                update_srt_status(detection_id, False)

        # Cleanup temp files
        try:
            os.remove(media_path)
        except Exception:
            pass

        # Mark as completed - SAVE TO DATABASE
        result_data = {
            "message": f"File uploaded and processed successfully{srt_message}",
            "detection_id": detection_id,
            "summary": summary,
            "processing_time": f"{processing_time:.2f}s",
            "has_srt_data": has_srt_data and srt_message and "failed" not in srt_message,
            "cloud_public_id": cloud_result.get("public_id") if cloud_result else None,
            "cloud_resource_type": cloud_resource_type if cloud_result else None,
            "cloud_secure_url": cloud_result.get("secure_url") if cloud_result else None,
            "cloud_annotated_url": annotated_url,
            "needs_client_compression": temp_video_path is not None,  # Flag for mobile app
        }
        
        # Update database with result
        update_job_result(
            job_id=job_id,
            detection_id=detection_id,
            result_json=json.dumps(result_data),
            annotated_url=annotated_url,
            temp_video_path=temp_video_path,
            needs_compression=(temp_video_path is not None)
        )
        
        print(f"[Job {job_id}] Processing completed successfully")
        
        if temp_video_path:
            print(f"[Job {job_id}] ⚠️  Waiting for client to compress and upload annotated video")
        
    except Exception as e:
        print(f"[Job {job_id}] Processing failed: {e}")
        traceback.print_exc()
        
        # Save error to database
        update_job_status(job_id, "failed", error_message=str(e))
        
        # Cleanup temp files
        try:
            if os.path.exists(media_path):
                os.remove(media_path)
        except Exception:
            pass

@app.post("/upload-combined/")
async def upload_combined_files(
    background_tasks: BackgroundTasks,
    media_file: UploadFile = File(..., description="Video or image file"),
    srt_file: UploadFile = File(None, description="Optional SRT file for video"),
    skip_cloud: bool = Query(False, description="Skip Cloudinary upload for speed"),
    confidence: int = Query(None, description="Confidence threshold (0-100)"),
    overlap: int = Query(None, description="Overlap threshold (0-100)")
):
    """Upload media file and process in background. Returns job_id immediately for status polling."""
    
    # Validate file types - use lowercase for validation only
    media_filename_lower = media_file.filename.lower()
    if not (media_filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.mp4', '.mov', '.avi', '.mkv'))):
        raise HTTPException(status_code=400, detail="Media file must be an image or video")
    
    is_video = media_filename_lower.endswith(('.mp4', '.mov', '.avi', '.mkv'))
    is_image = media_filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif'))
    
    # Validation rules
    if srt_file and is_image:
        raise HTTPException(status_code=400, detail="SRT files can only be uploaded with video files, not images")
    
    if srt_file and not srt_file.filename.lower().endswith('.srt'):
        raise HTTPException(status_code=400, detail="SRT file must have .srt extension")
    
    # Read media bytes
    media_bytes = await media_file.read()
    if not media_bytes:
        raise HTTPException(status_code=400, detail="Empty media file")
    
    # Read SRT if provided
    srt_content = None
    srt_filename_str = None
    if srt_file:
        srt_content = await srt_file.read()
        srt_filename_str = srt_file.filename
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save media to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(media_file.filename)[1])
    tmp.write(media_bytes)
    tmp.flush()
    tmp.close()
    media_path = tmp.name
    
    # Create job in database for persistence
    create_processing_job(
        job_id=job_id,
        original_filename=media_file.filename,
        is_video=is_video,
        is_image=is_image,
        has_srt=(srt_file is not None)
    )
    
    # Start background processing
    background_tasks.add_task(
        process_media_background,
        job_id=job_id,
        media_path=media_path,
        media_filename=media_file.filename,
        media_bytes=media_bytes,
        srt_content=srt_content,
        srt_filename=srt_filename_str,
        is_video=is_video,
        is_image=is_image,
        skip_cloud=skip_cloud,
        confidence=confidence,
        overlap=overlap
    )
    
    # Return immediately with job ID
    return JSONResponse({
        "job_id": job_id,
        "status": "processing",
        "message": "File uploaded successfully. Processing in background. Use /job-status/{job_id} to check progress."
    })

@app.get("/job-status/{job_id}")
async def get_job_status_endpoint(job_id: str):
    """Check the status of a background processing job."""
    job_data = get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Parse result_json if available
    result = None
    if job_data["result_json"]:
        try:
            result = json.loads(job_data["result_json"])
        except:
            result = None
    
    return JSONResponse({
        "job_id": job_data["job_id"],
        "status": job_data["status"],
        "progress": job_data["progress"],
        "result": result,
        "error": job_data["error_message"],
        "temp_video_path": job_data["temp_video_path"],
        "needs_client_compression": job_data["needs_client_compression"]
    })

@app.get("/download-temp-video/{job_id}")
async def download_temp_video(job_id: str):
    """Download temporary annotated video for client-side compression."""
    from fastapi.responses import FileResponse
    
    job_data = get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    temp_video_path = job_data.get("temp_video_path")
    
    if not temp_video_path or not os.path.exists(temp_video_path):
        raise HTTPException(status_code=404, detail="Temp video not found")
    
    # Mark that compression has started
    mark_compression_started(job_id)
    
    return FileResponse(
        temp_video_path,
        media_type="video/mp4",
        filename=f"annotated_{job_id}.mp4"
    )

@app.post("/upload-compressed-video/{job_id}")
async def upload_compressed_video(
    job_id: str,
    compressed_video: UploadFile = File(..., description="Client-compressed video")
):
    """Receive compressed video from client and upload to Cloudinary."""
    job_data = get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        # Read compressed video
        video_bytes = await compressed_video.read()
        video_size_mb = len(video_bytes) / (1024 * 1024)
        print(f"[Job {job_id}] Received compressed video: {video_size_mb:.2f} MB")
        
        # Save to temp file
        temp_compressed = tempfile.mktemp(suffix='_compressed.mp4')
        with open(temp_compressed, 'wb') as f:
            f.write(video_bytes)
        
        # Upload to Cloudinary
        from .cloudinary_utils import upload_video_streaming
        
        # Parse result to get detection_id and filename
        detection_id = job_data.get("detection_id")
        original_filename = job_data.get("original_filename", "video.mp4")
        
        uploaded = upload_video_streaming(
            temp_compressed,
            original_filename,
            folder="weed-detections/annotated",
            annotate=False
        )
        
        annotated_url = uploaded.get('secure_url')
        print(f"[Job {job_id}] Compressed video uploaded to Cloudinary: {annotated_url}")
        
        # Update database with annotated URL
        if detection_id:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "UPDATE detections SET cloud_annotated_url = %s WHERE id = %s",
                        (annotated_url, detection_id)
                    )
                    conn.commit()
                    print(f"[Job {job_id}] Database updated with annotated URL")
                except Exception as e:
                    print(f"[Job {job_id}] Failed to update annotated URL: {e}")
        
        # Mark compression as completed in job queue
        mark_compression_completed(job_id, annotated_url)
        
        # Cleanup temp files
        try:
            os.remove(temp_compressed)
            temp_video_path = job_data.get("temp_video_path")
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
        except Exception:
            pass
        
        return JSONResponse({
            "success": True,
            "message": "Compressed video uploaded successfully",
            "annotated_url": annotated_url
        })
        
    except Exception as e:
        print(f"[Job {job_id}] Error uploading compressed video: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ========== JOB RECOVERY ENDPOINTS ==========

@app.get("/jobs/pending-compression")
async def get_pending_compression_jobs_endpoint():
    """Get all jobs waiting for client-side compression."""
    try:
        jobs = get_pending_compression_jobs()
        return JSONResponse({
            "success": True,
            "jobs": jobs,
            "count": len(jobs)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/{job_id}/resume-compression")
async def resume_compression(job_id: str):
    """Resume compression workflow for a job after connectivity loss."""
    job_data = get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if not job_data["needs_client_compression"]:
        return JSONResponse({
            "success": False,
            "message": "Job does not need compression"
        })
    
    if not job_data["temp_video_path"] or not os.path.exists(job_data["temp_video_path"]):
        return JSONResponse({
            "success": False,
            "message": "Temp video no longer available"
        })
    
    return JSONResponse({
        "success": True,
        "message": "Job ready for compression resumption",
        "job_id": job_id,
        "temp_video_available": True,
        "detection_id": job_data["detection_id"]
    })

@app.delete("/jobs/{job_id}")
async def cancel_job_delete(job_id: str):
    """Cancel a job and clean up resources (DELETE method)."""
    return await cancel_job_logic(job_id)

@app.post("/cancel-job/{job_id}")
async def cancel_job_post(job_id: str):
    """Cancel a job and clean up resources (POST method for frontend)."""
    return await cancel_job_logic(job_id)

async def cancel_job_logic(job_id: str):
    """Shared logic for cancelling a job."""
    job_data = get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        print(f"[Job {job_id}] 🛑 Cancellation requested by user")
        
        # Clean up temp files
        if job_data.get("temp_video_path") and os.path.exists(job_data["temp_video_path"]):
            os.remove(job_data["temp_video_path"])
            print(f"[Job {job_id}] Removed temp video file")
        
        # Mark as failed/cancelled in database
        update_job_status(job_id, "failed", error_message="Cancelled by user")
        print(f"[Job {job_id}] Marked as cancelled in database")
        
        return JSONResponse({
            "success": True,
            "message": "Job cancelled successfully"
        })
    except Exception as e:
        print(f"[Job {job_id}] ❌ Error cancelling job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/jobs/cleanup")
async def cleanup_old_jobs_endpoint(days: int = Query(7, description="Clean up jobs older than X days")):
    """Clean up old completed/failed jobs."""
    try:
        deleted_count = cleanup_old_jobs(days)
        return JSONResponse({
            "success": True,
            "message": f"Cleaned up {deleted_count} old jobs",
            "deleted_count": deleted_count
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload/")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), 
    skip_cloud: bool = Query(False, description="Skip Cloudinary upload for speed"), 
    confidence: int = Query(None, description="Confidence threshold (0-100)"), 
    overlap: int = Query(None, description="Overlap threshold (0-100)")
):
    """Upload and process a video or image file for weed detection. Returns job_id immediately for status polling."""
    
    # Read file
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    file_size_mb = len(file_bytes) / (1024 * 1024)
    print(f"Processing file: {file.filename} ({file_size_mb:.1f} MB)")
    
    # Render.com Standard Plan: Enforce file size limits
    from .config import MAX_UPLOAD_SIZE_MB
    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large: {file_size_mb:.1f}MB. Maximum allowed: {MAX_UPLOAD_SIZE_MB}MB for Render.com Standard Plan"
        )
    
    # Basic validation for images to avoid downstream crashes
    if file.filename.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif")):
        if Image is None:
            print("Warning: Pillow not installed; skipping image validation")
        else:
            try:
                img = Image.open(BytesIO(file_bytes))
                img.verify()  # verifies integrity
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid or corrupted image file")
    
    # Determine file type
    is_video = file.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv'))
    is_image = file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'))
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
    tmp.write(file_bytes)
    tmp.flush()
    tmp.close()
    file_path = tmp.name
    
    # Create job in database for persistence
    create_processing_job(
        job_id=job_id,
        original_filename=file.filename,
        is_video=is_video,
        is_image=is_image,
        has_srt=False
    )
    
    # Start background processing (reuse the same function)
    background_tasks.add_task(
        process_media_background,
        job_id=job_id,
        media_path=file_path,
        media_filename=file.filename,
        media_bytes=file_bytes,
        srt_content=None,  # No SRT for single file upload
        srt_filename=None,
        is_video=is_video,
        is_image=is_image,
        skip_cloud=skip_cloud,
        confidence=confidence,
        overlap=overlap
    )
    
    # Return immediately with job ID
    return JSONResponse({
        "job_id": job_id,
        "status": "processing",
        "message": "File uploaded successfully. Processing in background. Use /job-status/{job_id} to check progress."
    })

@app.post("/upload-srt/")
async def upload_srt_file(
    detection_id: int = Query(..., description="Detection session ID to associate SRT data with"),
    srt_file: UploadFile = File(..., description="SRT subtitle file")
):
    """Upload SRT file to associate with a detection session."""
    
    # Validate file extension
    if not srt_file.filename.lower().endswith('.srt'):
        raise HTTPException(status_code=400, detail="File must be an SRT file")
    
    # Read SRT content
    srt_content = await srt_file.read()
    srt_text = srt_content.decode('utf-8')
    
    # Validate SRT format
    if not validate_srt_file(srt_text):
        raise HTTPException(status_code=400, detail="Invalid SRT file format")
    
    # Parse SRT file
    frames = parse_srt_file(srt_text)
    if not frames:
        raise HTTPException(status_code=400, detail="No valid frame data found in SRT file")

    # Build compact track and bounds
    coords = []
    min_lat = min_lon = float("inf")
    max_lat = max_lon = float("-inf")
    compact_frames = []
    for f in frames:
        lat = f.get('latitude')
        lon = f.get('longitude')
        if lat is None or lon is None:
            continue
        coords.append([lon, lat])
        if lat < min_lat: min_lat = lat
        if lat > max_lat: max_lat = lat
        if lon < min_lon: min_lon = lon
        if lon > max_lon: max_lon = lon
        compact_frames.append({
            'i': f.get('frame_number'),
            't': f.get('timestamp'),
            'lat': lat,
            'lon': lon,
            'alt': f.get('altitude')
        })

    if not coords:
        raise HTTPException(status_code=400, detail="SRT has no GPS coordinates")

    start_time = frames[0].get('timestamp') if frames else None
    end_time = frames[-1].get('timestamp') if frames else None

    bounds_geojson = json.dumps({
        'type': 'Feature',
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[
                [min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]
            ]]
        },
        'properties': { 'detection_id': detection_id }
    })

    path_geojson = json.dumps({
        'type': 'Feature',
        'geometry': { 'type': 'LineString', 'coordinates': coords },
        'properties': { 'detection_id': detection_id, 'points': len(coords) }
    })

    frames_json = json.dumps(compact_frames)

    # Store compact SRT track in DB (replace if exists)
    upsert_srt_track(
        detection_id=detection_id,
        point_count=len(coords),
        start_time=start_time,
        end_time=end_time,
        bounds_geojson=bounds_geojson,
        path_geojson=path_geojson,
        frames_json=frames_json
    )

    return JSONResponse(content={
        "message": "SRT file uploaded successfully (compact track stored)",
        "detection_id": detection_id,
        "frames_processed": len(frames),
        "points_stored": len(coords),
        "bounds": { 'min_lat': min_lat, 'min_lon': min_lon, 'max_lat': max_lat, 'max_lon': max_lon }
    })

@app.get("/health")
async def health_check():
    """Health check endpoint with memory usage for Render.com monitoring"""
    import psutil
    import os
    
    try:
        # Get memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_available_mb = memory.available / (1024 * 1024)
        
        # Get disk usage
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_free_mb = disk.free / (1024 * 1024)
        
        # Count active jobs
        active_count = sum(1 for job in processing_jobs.values() if job.get('status') == 'processing')
        
        return {
            "status": "healthy",
            "memory": {
                "percent": memory_percent,
                "available_mb": round(memory_available_mb, 1),
                "total_mb": round(memory.total / (1024 * 1024), 1)
            },
            "disk": {
                "percent": disk_percent,
                "free_mb": round(disk_free_mb, 1)
            },
            "jobs": {
                "active": active_count,
                "queued": len(job_queue),
                "total": len(processing_jobs)
            },
            "render_plan": "standard_2gb_1cpu"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "render_plan": "standard_2gb_1cpu"
        }

@app.get("/detections/")
async def get_detections():
    """Get all detection sessions."""
    detections = fetch_all_detections()
    # Convert dict rows to tuple arrays for frontend compatibility
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {"detections": detection_tuples}

@app.get("/detections/with-srt/")
async def get_detections_with_srt():
    """Get only detection sessions that have associated SRT data for mapping."""
    from psycopg2.extras import RealDictCursor
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM detections WHERE has_srt_data = TRUE ORDER BY timestamp DESC")
        detections = [dict(row) for row in cursor.fetchall()]
    # Convert dict rows to tuple arrays for frontend compatibility
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {"detections": detection_tuples}

@app.get("/detection/{detection_id}")
async def get_detection_details(detection_id: int):
    """Get complete details of a specific detection session."""
    session_data = fetch_detection_session(detection_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    # Convert detection dict to tuple array for frontend compatibility
    detection_tuple = dict_to_detection_tuple(session_data['detection'])
    
    # Convert detection_details dicts to tuple arrays (frontend expects tuples)
    # Detection details tuple format: [id, detection_id, frame_number, weed_class, confidence, 
    #   bbox_x, bbox_y, bbox_width, bbox_height, normalized_bbox_x, normalized_bbox_y, 
    #   normalized_bbox_width, normalized_bbox_height, detection_timestamp, latitude, longitude, altitude]
    detection_details_tuples = []
    for detail in session_data['detection_details']:
        detection_details_tuples.append([
            detail['id'],
            detail['detection_id'],
            detail['frame_number'],
            detail['weed_class'],
            detail['confidence'],
            detail['bbox_x'],
            detail['bbox_y'],
            detail['bbox_width'],
            detail['bbox_height'],
            detail.get('normalized_bbox_x'),
            detail.get('normalized_bbox_y'),
            detail.get('normalized_bbox_width'),
            detail.get('normalized_bbox_height'),
            detail['detection_timestamp'],
            detail.get('latitude'),
            detail.get('longitude'),
            detail.get('altitude')
        ])
    
    # Convert srt_track dict to tuple if exists
    srt_track_tuple = None
    if session_data['srt_track']:
        st = session_data['srt_track']
        srt_track_tuple = [
            st['detection_id'],
            st['point_count'],
            st.get('start_time'),
            st.get('end_time'),
            st.get('bounds_geojson'),
            st['path_geojson'],
            st['frames_json']
        ]
    
    return {
        "detection": detection_tuple,
        "srt_track": srt_track_tuple,
        "detection_details": detection_details_tuples,
        "frame_metadata": []  # Deprecated, kept for compatibility
    }

@app.get("/detection/{detection_id}/unique-weeds")
async def get_unique_weeds(
    detection_id: int,
    # Lower the default IoU threshold to make matching across frames more permissive
    # (reduces over-counting by treating lower-overlap detections as the same weed).
    iou_threshold: float = Query(0.4, description="IoU threshold for matching (0.0-1.0)"),
    # Allow a slightly larger frame gap to permit tracking across brief missed detections
    frame_gap: int = Query(3, description="Maximum frame gap for tracking")
):
    """Calculate unique weed count by tracking across frames.
    
    This solves the problem of counting the same weed multiple times across frames.
    Returns unique weed count instead of total detection count.
    """
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    print(f"🔍 [UNIQUE WEEDS] Calculating for detection {detection_id} with iou_threshold={iou_threshold}, frame_gap={frame_gap}")
    unique_weeds = calculate_unique_weeds(detection_id, iou_threshold, frame_gap)
    print(f"✅ [UNIQUE WEEDS] Result: {unique_weeds['unique_count']} unique from {unique_weeds['total_detections']} total ({unique_weeds['reduction_percentage']}% reduction)")
    
    return {
        "detection_id": detection_id,
        "unique_weed_count": unique_weeds['unique_count'],
        "total_detections": unique_weeds['total_detections'],
        "reduction_percentage": unique_weeds['reduction_percentage'],
        "weed_species": unique_weeds['by_class'],
        "tracking_params": {
            "iou_threshold": iou_threshold,
            "frame_gap": frame_gap
        },
        "message": f"Found {unique_weeds['unique_count']} unique weeds from {unique_weeds['total_detections']} total detections ({unique_weeds['reduction_percentage']}% reduction)"
    }

@app.delete("/detection/{detection_id}")
async def delete_detection_session(detection_id: int):
    """Delete a detection session and all associated data.
    
    This endpoint deletes:
    - Detection record from detections table
    - All detection_details (cascade)
    - SRT tracks data
    - Heatmap data
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Check if detection exists
            cursor.execute("SELECT id FROM detections WHERE id = %s", (detection_id,))
            detection = cursor.fetchone()
            
            if not detection:
                raise HTTPException(status_code=404, detail="Detection session not found")
            
            # Delete the detection (CASCADE will handle related records)
            cursor.execute("DELETE FROM detections WHERE id = %s", (detection_id,))
            
            # Also explicitly delete from related tables in case CASCADE doesn't work
            cursor.execute("DELETE FROM detection_details WHERE detection_id = %s", (detection_id,))
            cursor.execute("DELETE FROM srt_tracks WHERE detection_id = %s", (detection_id,))
            cursor.execute("DELETE FROM heatmaps WHERE detection_id = %s", (detection_id,))
            
            conn.commit()
            
            return {
                "message": f"Detection session {detection_id} and all associated data deleted successfully",
                "deleted_id": detection_id
            }
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete detection session: {str(e)}")

@app.get("/statistics/")
async def get_statistics():
    """Get overall detection statistics."""
    stats = get_detection_statistics()
    return stats

@app.get("/detections/class/{weed_class}")
async def get_detections_by_class(weed_class: str):
    """Get all detections of a specific weed class."""
    detections = fetch_detections_by_class(weed_class)
    # Convert dict rows to tuple arrays for frontend compatibility
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {"weed_class": weed_class, "detections": detection_tuples}

@app.post("/admin/reset-compact-tables")
async def admin_reset_compact_tables(confirm: bool = Query(False, description="Set true to confirm reset")):
    """Admin: Drop and recreate compact SRT/heatmap tables."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    reset_compact_tables()
    return {"message": "Compact tables reset: srt_tracks, heatmaps"}

@app.post("/admin/reset-db")
async def admin_reset_db(confirm: bool = Query(False, description="Set true to confirm full DB reset (drop all tables)")):
    """Admin: Drop all tables and recreate them."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # Drop all tables in correct order (due to foreign keys)
            tables = ['processing_jobs', 'detection_details', 'heatmaps', 'srt_tracks', 'detections']
            for table in tables:
                cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            conn.commit()
        # Recreate tables
        init_db()
        return {"message": "Database tables dropped and recreated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {e}")

@app.post("/admin/drop-tables")
async def admin_drop_tables(tables: str = Query("", description="Comma-separated table names to drop"), confirm: bool = Query(False)):
    """Admin: Drop specific tables by name (use cautiously)."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    if not tables:
        raise HTTPException(status_code=400, detail="Provide table names via tables query param")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            dropped = []
            for name in [t.strip() for t in tables.split(',') if t.strip()]:
                cursor.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                dropped.append(name)
            conn.commit()
            return {"message": "Dropped tables", "dropped": dropped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/detection/{detection_id}/gmap-polyline")
async def get_gmap_polyline(detection_id: int):
    """Return Google Maps-ready polyline points and bounds for a detection's SRT track."""
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT path_geojson, bounds_geojson FROM srt_tracks WHERE detection_id = %s", (detection_id,))
        row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="SRT track not found")
    path_geojson = json.loads(row['path_geojson'])
    bounds_geojson = json.loads(row['bounds_geojson']) if row['bounds_geojson'] else None
    coords = path_geojson.get('geometry', {}).get('coordinates', [])
    points = [{ 'lat': lat, 'lng': lng } for lng, lat in coords]
    bounds = None
    if bounds_geojson and bounds_geojson.get('geometry', {}).get('coordinates'):
        ring = bounds_geojson['geometry']['coordinates'][0]
        lats = [pt[1] for pt in ring]
        lngs = [pt[0] for pt in ring]
        bounds = { 'min_lat': min(lats), 'min_lng': min(lngs), 'max_lat': max(lats), 'max_lng': max(lngs) }
    return { 'detection_id': detection_id, 'points': points, 'bounds': bounds }

@app.post("/detection/{detection_id}/generate-heatmap")
async def generate_heatmap(detection_id: int, grid_size_m: float = Query(1.0), persist: bool = Query(True)):
    """Generate heatmap from detection_details mapped to SRT frames; optionally persist aggregated grid."""
    # Load srt frames
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT frames_json, bounds_geojson FROM srt_tracks WHERE detection_id = %s", (detection_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="SRT track not found")
        frames_json = row['frames_json']
        bounds_geojson = row['bounds_geojson']
        frames = { int(f.get('i')): (f.get('lat'), f.get('lon')) for f in json.loads(frames_json) if f.get('lat') is not None and f.get('lon') is not None }

        # Load detection details
        cursor.execute("SELECT frame_number, weed_class, confidence FROM detection_details WHERE detection_id = %s", (detection_id,))
        details = cursor.fetchall()

    # Map detections to lat/lng points
    points = []
    for detail in details:
        frame_number = detail['frame_number']
        weed_class = detail['weed_class']
        confidence = detail['confidence']
        pos = frames.get(int(frame_number))
        if not pos:
            continue
        lat, lon = pos
        points.append({ 'lat': lat, 'lng': lon, 'weight': float(confidence) })

    if not points:
        return { 'detection_id': detection_id, 'points': [], 'grid': None, 'persisted': False }

    # Aggregate into grid cells
    # Approximate meters per degree at mid-latitude
    import math
    mean_lat = sum(p['lat'] for p in points) / len(points)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(math.radians(mean_lat))
    cell_deg_lat = grid_size_m / meters_per_deg_lat
    cell_deg_lng = grid_size_m / meters_per_deg_lng if meters_per_deg_lng > 0 else grid_size_m / 1.0

    grid = {}
    # Determine origin (minimum lat/lng) so grid indices are relative to the field bounds
    min_lat = min(p['lat'] for p in points)
    min_lng = min(p['lng'] for p in points)

    for p in points:
        # Use coordinates relative to the origin when computing integer grid indices
        key_lat = int(math.floor((p['lat'] - min_lat) / cell_deg_lat))
        key_lng = int(math.floor((p['lng'] - min_lng) / cell_deg_lng))
        key = f"{key_lat}:{key_lng}"
        cell = grid.get(key)
        if not cell:
            grid[key] = { 'lat_idx': key_lat, 'lng_idx': key_lng, 'count': 0, 'sum_weight': 0.0 }
            cell = grid[key]
        cell['count'] += 1
        cell['sum_weight'] += p['weight']

    # Convert grid to list with representative cell center
    cells = []
    # Convert grid to list with representative cell center (offset by origin)
    for cell in grid.values():
        center_lat = min_lat + (cell['lat_idx'] + 0.5) * cell_deg_lat
        center_lng = min_lng + (cell['lng_idx'] + 0.5) * cell_deg_lng
        cells.append({
            'lat': center_lat,
            'lng': center_lng,
            'count': cell['count'],
            'avg_weight': cell['sum_weight'] / cell['count'] if cell['count'] else 0.0
        })

    persisted = False
    if persist:
        try:
            upsert_heatmap(
                detection_id=detection_id,
                grid_size_m=grid_size_m,
                bounds_geojson=bounds_geojson,
                cells_json=json.dumps(cells)
            )
            persisted = True
        except Exception:
            persisted = False

    return { 'detection_id': detection_id, 'points': points, 'grid': { 'grid_size_m': grid_size_m, 'cells': cells }, 'persisted': persisted }

@app.get("/detection/{detection_id}/unique-weeds-heatmap")
async def get_unique_weeds_heatmap(
    detection_id: int,
    iou_threshold: float = Query(0.6, description="IoU threshold for matching (0.0-1.0)"),
    frame_gap: int = Query(2, description="Maximum frame gap for tracking"),
    grid_size_m: float = Query(0.5, description="Grid cell size in meters"),
    debug: bool = Query(False, description="When true, return matched detections and grid details for debugging")
):
    """Generate heatmap based on unique weed count per GPS location.
    
    This endpoint:
    1. Gets all detections with their timestamps (not frame numbers)
    2. Matches detection timestamps to SRT timestamps to get GPS coordinates
    3. Calculates unique weeds using the tracking algorithm
    4. Groups unique weeds by GPS grid cells
    5. Returns heatmap points with weight based on unique weed count
    
    IMPORTANT: Matches by timestamp, not frame number, because:
    - Original video: 30 FPS, 1900 frames
    - Processed video: 10 FPS, 633 frames
    - But timestamps align: frame 0 = 00:00:00,000 in both
    """
    import math
    
    # Helper function to parse SRT timestamp to milliseconds
    def srt_timestamp_to_ms(timestamp_str):
        """Convert SRT timestamp 'HH:MM:SS,mmm' to milliseconds."""
        try:
            if not timestamp_str or not isinstance(timestamp_str, str):
                return None
            parts = timestamp_str.replace(',', ':').split(':')
            if len(parts) != 4:
                return None
            hours, minutes, seconds, ms = map(int, parts)
            return hours * 3600000 + minutes * 60000 + seconds * 1000 + ms
        except Exception:
            return None
    
    # Load SRT frames for GPS data
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT frames_json FROM srt_tracks WHERE detection_id = %s", (detection_id,))
        row = cursor.fetchone()
        if not row:
            # No SRT data available - return basic unique weeds count without GPS mapping
            cursor.execute("""
                SELECT id, frame_number, weed_class, confidence,
                       bbox_x, bbox_y, bbox_width, bbox_height,
                       detection_timestamp
                FROM detection_details
                WHERE detection_id = %s
                ORDER BY frame_number, id
            """, (detection_id,))
            
            detections = cursor.fetchall()
            
            if not detections:
                return {
                    'detection_id': detection_id,
                    'unique_weed_count': 0,
                    'total_detections': 0,
                    'gps_matched_detections': 0,
                    'reduction_percentage': 0,
                    'points': [],
                    'grid_size_m': grid_size_m,
                    'tracking_params': {
                        'iou_threshold': iou_threshold,
                        'frame_gap': frame_gap,
                        'timestamp_tolerance_ms': 0
                    },
                    'message': 'No SRT data available - cannot generate GPS-based heatmap',
                    'no_gps_data': True
                }
            
            # Calculate unique weeds without GPS mapping
            from .database import calculate_unique_weeds
            unique_weeds = calculate_unique_weeds(detection_id, iou_threshold, frame_gap)
            
            return {
                'detection_id': detection_id,
                'unique_weed_count': unique_weeds['unique_count'],
                'total_detections': unique_weeds['total_detections'],
                'gps_matched_detections': 0,
                'reduction_percentage': unique_weeds['reduction_percentage'],
                'points': [],  # No GPS points available
                'grid_size_m': grid_size_m,
                'tracking_params': {
                    'iou_threshold': iou_threshold,
                    'frame_gap': frame_gap,
                    'timestamp_tolerance_ms': 0
                },
                'message': f'Found {unique_weeds["unique_count"]} unique weeds from {unique_weeds["total_detections"]} total detections (no GPS data available)',
                'no_gps_data': True
            }
        
        frames_json = row['frames_json']
        srt_frames = json.loads(frames_json)
        
        # Create timestamp -> (lat, lon) mapping
        # SRT frames have 't' (timestamp in HH:MM:SS,mmm format)
        timestamp_to_gps = {}
        for frame_data in srt_frames:
            timestamp_str = frame_data.get('t')  # SRT timestamp
            lat = frame_data.get('lat')
            lon = frame_data.get('lon')
            if timestamp_str and lat is not None and lon is not None:
                timestamp_ms = srt_timestamp_to_ms(timestamp_str)
                if timestamp_ms is not None:
                    timestamp_to_gps[timestamp_ms] = (lat, lon)
        
        print(f"[Heatmap] Loaded {len(timestamp_to_gps)} SRT GPS points")
        
        # Get all detection details with timestamps
        cursor.execute("""
            SELECT id, frame_number, weed_class, confidence,
                   bbox_x, bbox_y, bbox_width, bbox_height,
                   detection_timestamp
            FROM detection_details
            WHERE detection_id = %s
            ORDER BY frame_number, id
        """, (detection_id,))
        
        detections = cursor.fetchall()
    
    if not detections:
        return {
            'detection_id': detection_id,
            'unique_weed_count': 0,
            'points': [],
            'message': 'No detections found'
        }
    
    print(f"[Heatmap] Processing {len(detections)} detections")
    
    # Match detections to GPS by timestamp (with tolerance for slight mismatches)
    TIMESTAMP_TOLERANCE_MS = 200  # Increased to 200ms to handle frame rate differences between original (30fps) and processed (10fps) videos
    
    detections_with_gps = []
    matched_count = 0
    
    for det in detections:
        det_id = det['id']
        frame_num = det['frame_number']
        weed_class = det['weed_class']
        confidence = det['confidence']
        bbox_x = det['bbox_x']
        bbox_y = det['bbox_y']
        bbox_width = det['bbox_width']
        bbox_height = det['bbox_height']
        timestamp_str = det['detection_timestamp']
        
        # Parse detection timestamp
        det_timestamp_ms = srt_timestamp_to_ms(timestamp_str)
        if det_timestamp_ms is None:
            continue
        
        # Find closest SRT timestamp within tolerance
        best_match = None
        min_diff = float('inf')
        
        # First try exact match or very close match
        for srt_ms, (lat, lon) in timestamp_to_gps.items():
            diff = abs(srt_ms - det_timestamp_ms)
            if diff <= TIMESTAMP_TOLERANCE_MS and diff < min_diff:
                min_diff = diff
                best_match = (lat, lon)
        
        # If no match found within tolerance, try a more lenient approach
        # This handles cases where frame rates differ significantly
        if best_match is None:
            # Sort SRT timestamps and find the closest one
            sorted_srt_times = sorted(timestamp_to_gps.keys())
            for srt_ms in sorted_srt_times:
                diff = abs(srt_ms - det_timestamp_ms)
                if diff < min_diff:
                    min_diff = diff
                    best_match = timestamp_to_gps[srt_ms]
            
            # Only use this match if it's within a reasonable range (1 second)
            if min_diff > 1000:  # 1 second
                best_match = None
        
        if best_match:
            matched_count += 1
            detections_with_gps.append({
                'id': det_id,
                'frame_num': frame_num,
                'class': weed_class,
                'confidence': confidence,
                'bbox': [bbox_x, bbox_y, bbox_width, bbox_height],
                'gps': best_match,
                'timestamp_ms': det_timestamp_ms
            })
    
    print(f"[Heatmap] Matched {matched_count}/{len(detections)} detections to GPS coordinates")
    
    # Calculate match percentage
    match_percentage = (matched_count / len(detections) * 100) if len(detections) > 0 else 0
    print(f"[Heatmap] Match rate: {match_percentage:.1f}%")
    
    if match_percentage < 60:
        print(f"[Heatmap] ⚠️ WARNING: Low match rate (<60%). Consider increasing TIMESTAMP_TOLERANCE_MS or checking FPS calculation.")
    
    if not detections_with_gps:
        return {
            'detection_id': detection_id,
            'unique_weed_count': 0,
            'points': [],
            'message': f'No GPS matches found. Matched {matched_count}/{len(detections)} detections.'
        }
    
    # Calculate unique weeds with tracking
    def calculate_iou(box1, box2):
        """Calculate Intersection over Union between two bounding boxes."""
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2
        
        x_left = max(x1, x2)
        y_top = max(y1, y2)
        x_right = min(x1 + w1, x2 + w2)
        y_bottom = min(y1 + h1, y2 + h2)
        
        if x_right < x_left or y_bottom < y_top:
            return 0.0
        
        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        box1_area = w1 * h1
        box2_area = w2 * h2
        union_area = box1_area + box2_area - intersection_area
        
        return intersection_area / union_area if union_area > 0 else 0.0
    
    # GPS distance validation helper
    def calculate_gps_distance(lat1, lon1, lat2, lon2):
        """Calculate distance in meters between two GPS coordinates using Haversine formula."""
        if None in [lat1, lon1, lat2, lon2]:
            return None
        
        from math import radians, cos, sin, asin, sqrt
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        r = 6371000  # Radius of earth in meters
        return c * r
    
    # Improved tracking algorithm for 10 FPS drone video
    # At 10 FPS, typical agricultural drone (3-5 m/s) covers 0.3-0.5m per frame
    # Same weed visible for 1-3 seconds = 10-30 frames at 10 FPS
    # Use IoU + GPS + temporal tracking to avoid over-counting
    
    # Sort detections by frame number for temporal tracking
    detections_with_gps_sorted = sorted(detections_with_gps, key=lambda x: x['frame_num'])
    
    tracks = []
    TEMPORAL_FRAME_GAP = max(frame_gap, 20)  # At 10 FPS, 20 frames = 2.0 seconds (longer tracking window)
    GPS_CLUSTER_THRESHOLD_M = 1.0  # Weeds within 1.0m are likely the same plant (slightly relaxed for better merging)
    MIN_MATCH_SCORE = 0.4  # Reduced from 0.5 - allow weaker matches to merge more tracks
    
    for det in detections_with_gps_sorted:
        det_id = det['id']
        frame_num = det['frame_num']
        weed_class = det['class']
        confidence = det['confidence']
        box = det['bbox']
        gps_lat, gps_lon = det['gps']
        
        matched_track = None
        best_score = 0.0
        
        # Try to match with existing tracks (same class)
        for track in tracks:
            if track['weed_class'] != weed_class:
                continue
            
            # Check temporal gap (must be within frame window)
            frame_diff = frame_num - track['last_frame']
            if frame_diff > TEMPORAL_FRAME_GAP or frame_diff < 0:
                continue
            
            # Calculate IoU with track's last bounding box
            iou = calculate_iou(box, track['last_bbox'])
            
            # Calculate GPS distance to track's last position
            gps_dist = calculate_gps_distance(gps_lat, gps_lon, track['last_gps'][0], track['last_gps'][1])
            
            # Matching criteria: Require BOTH good IoU AND close GPS OR very high IoU alone
            score = 0.0
            if iou >= iou_threshold:
                # Strong spatial match in image space
                if gps_dist is not None and gps_dist <= GPS_CLUSTER_THRESHOLD_M:
                    # Both IoU and GPS agree - strong match
                    score = iou * 2.5
                elif iou >= 0.8:
                    # Very high IoU even without GPS confirmation
                    score = iou * 1.5
                else:
                    # Decent IoU but GPS is far or unknown - weaker match
                    score = iou * 0.8
            elif gps_dist is not None and gps_dist <= GPS_CLUSTER_THRESHOLD_M:
                # Close GPS but low IoU - could be same weed from different angle
                score = 0.5 / (1.0 + gps_dist)
            
            if score > best_score:
                best_score = score
                matched_track = track
        
        if matched_track is not None and best_score >= MIN_MATCH_SCORE:
            # Update existing track
            matched_track['detections'].append(det)
            matched_track['detection_ids'].append(det_id)
            matched_track['frames'].append(frame_num)
            matched_track['gps_coords'].append((gps_lat, gps_lon))
            matched_track['count'] += 1
            matched_track['last_frame'] = frame_num
            matched_track['last_bbox'] = box
            matched_track['last_gps'] = (gps_lat, gps_lon)
            matched_track['avg_confidence'] = (matched_track['avg_confidence'] * (matched_track['count'] - 1) + confidence) / matched_track['count']
        else:
            # Create new track
            tracks.append({
                'weed_class': weed_class,
                'detections': [det],
                'detection_ids': [det_id],
                'frames': [frame_num],
                'gps_coords': [(gps_lat, gps_lon)],
                'avg_confidence': confidence,
                'count': 1,
                'first_frame': frame_num,
                'last_frame': frame_num,
                'last_bbox': box,
                'last_gps': (gps_lat, gps_lon)
            })
    
    print(f"[Heatmap] Tracked {len(tracks)} unique weeds from {len(detections_with_gps)} GPS-matched detections using temporal+spatial tracking")
    print(f"[Heatmap] Tracking params: IoU≥{iou_threshold}, frame_gap≤{TEMPORAL_FRAME_GAP}, GPS≤{GPS_CLUSTER_THRESHOLD_M}m, min_score≥{MIN_MATCH_SCORE}")
    
    # Now we have unique weeds (tracks), assign each to GPS grid cells
    if not tracks or not any(t['gps_coords'] for t in tracks):
        return {
            'detection_id': detection_id,
            'unique_weed_count': len(tracks),
            'points': [],
            'message': 'No GPS data available for heatmap'
        }
    
    # Get all GPS points to calculate mean latitude
    all_gps = []
    for track in tracks:
        if track['gps_coords']:
            all_gps.extend(track['gps_coords'])
    
    if not all_gps:
        return {
            'detection_id': detection_id,
            'unique_weed_count': len(tracks),
            'points': [],
            'message': 'No GPS coordinates found'
        }
    
    mean_lat = sum(lat for lat, lon in all_gps) / len(all_gps)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(math.radians(mean_lat))
    cell_deg_lat = grid_size_m / meters_per_deg_lat
    cell_deg_lng = grid_size_m / meters_per_deg_lng if meters_per_deg_lng > 0 else grid_size_m / 1.0
    
    # Find min/max bounds for grid origin
    min_lat = min(lat for lat, lon in all_gps)
    min_lng = min(lon for lat, lon in all_gps)
    max_lat = max(lat for lat, lon in all_gps)
    max_lng = max(lon for lat, lon in all_gps)
    
    print(f"[Heatmap] GPS Bounds: lat ({min_lat:.6f} to {max_lat:.6f}), lng ({min_lng:.6f} to {max_lng:.6f})")
    print(f"[Heatmap] GPS Range: lat span={max_lat-min_lat:.8f}° ({(max_lat-min_lat)*111320:.1f}m), lng span={max_lng-min_lng:.8f}° ({(max_lng-min_lng)*111320*math.cos(math.radians(mean_lat)):.1f}m)")
    print(f"[Heatmap] Grid origin: ({min_lat:.6f}, {min_lng:.6f}), cell size: {grid_size_m}m")
    print(f"[Heatmap] Cell degrees: lat={cell_deg_lat:.8f}, lng={cell_deg_lng:.8f}")
    
    # Assign each unique weed to a grid cell based on its average GPS location
    grid = {}
    for track in tracks:
        if not track['gps_coords']:
            continue
        
        # Calculate average GPS position for this unique weed
        avg_lat = sum(lat for lat, lon in track['gps_coords']) / len(track['gps_coords'])
        avg_lon = sum(lon for lat, lon in track['gps_coords']) / len(track['gps_coords'])
        
        # Assign to grid cell (relative to min bounds)
        key_lat = int(math.floor((avg_lat - min_lat) / cell_deg_lat))
        key_lng = int(math.floor((avg_lon - min_lng) / cell_deg_lng))
        key = f"{key_lat}:{key_lng}"
        if key not in grid:
            # Track both unique counts and raw GPS sums so we can compute
            # a representative cell center as the average of actual points
            grid[key] = {
                'lat_idx': key_lat,
                'lng_idx': key_lng,
                'unique_count': 0,
                'by_class': {},
                'sum_lat': 0.0,
                'sum_lng': 0.0,
                'count_points': 0
            }

        grid[key]['unique_count'] += 1
        grid[key]['sum_lat'] += avg_lat
        grid[key]['sum_lng'] += avg_lon
        grid[key]['count_points'] += 1

        # Track by class
        weed_class = track['weed_class']
        if weed_class not in grid[key]['by_class']:
            grid[key]['by_class'][weed_class] = 0
        grid[key]['by_class'][weed_class] += 1
    
    # Convert grid to heatmap points. Use the average GPS of tracks in each cell
    # as the representative point so heat markers land on actual detections.
    points = []
    for cell in grid.values():
        if cell.get('count_points') and cell['count_points'] > 0:
            center_lat = cell['sum_lat'] / cell['count_points']
            center_lng = cell['sum_lng'] / cell['count_points']
        else:
            # Fallback to grid center if no raw points (shouldn't happen)
            center_lat = min_lat + (cell['lat_idx'] + 0.5) * cell_deg_lat
            center_lng = min_lng + (cell['lng_idx'] + 0.5) * cell_deg_lng

        points.append({
            'lat': center_lat,
            'lng': center_lng,
            'weight': cell['unique_count'],  # Weight based on number of unique weeds
            'unique_count': cell['unique_count'],
            'by_class': cell['by_class']
        })
    
    print(f"[Heatmap] Generated {len(points)} heatmap points from {len(grid)} grid cells")
    if len(points) > 0:
        print(f"[Heatmap] Sample heatmap point: lat={points[0]['lat']:.6f}, lng={points[0]['lng']:.6f}, weight={points[0]['weight']}")
    if len(detections_with_gps) > 0:
        sample_det = detections_with_gps[0]
        gps_lat, gps_lng = sample_det['gps']
        print(f"[Heatmap] Sample detection GPS: lat={gps_lat:.6f}, lng={gps_lng:.6f}, frame={sample_det['frame_num']}")
    
    return {
        'detection_id': detection_id,
        'unique_weed_count': len(tracks),
        'total_detections': len(detections),
        'gps_matched_detections': len(detections_with_gps),
        'reduction_percentage': round((1 - len(tracks) / len(detections)) * 100, 1) if len(detections) > 0 else 0,
        'points': points,
        'grid_size_m': grid_size_m,
        'tracking_params': {
            'iou_threshold': iou_threshold,
            'frame_gap': frame_gap,
            'timestamp_tolerance_ms': TIMESTAMP_TOLERANCE_MS
        },
        'message': f'Found {len(tracks)} unique weeds from {len(detections_with_gps)} GPS-matched detections (matched {matched_count}/{len(detections)} total detections by timestamp)'
    , 'debug': ({'matched_detections': detections_with_gps, 'grid': grid} if debug else None)
    }

@app.get("/detection/{detection_id}/export")
async def export_report(
    detection_id: int,
    format: str = Query("json", description="Export format: json, csv, or pdf")
):
    """Export detection report in JSON, CSV, or PDF format."""
    from fastapi.responses import StreamingResponse
    import io
    import csv
    from datetime import datetime as dt
    
    # Fetch all detection data
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    detection = session['detection']
    detection_details = session['detection_details']
    srt_track = session.get('srt_track')
    
    # Extract detection fields from dict
    det_id = detection['id']
    filename = detection['filename']
    timestamp = detection['timestamp']
    file_type = detection['file_type']
    summary = detection.get('summary')
    total_frames = detection.get('total_frames', 0)
    total_detections = detection.get('total_detections', 0)
    processing_time = detection.get('processing_time', 0.0)
    input_size_bytes = detection.get('input_size_bytes')
    result_size_bytes = detection.get('result_size_bytes')
    has_srt_data = detection.get('has_srt_data', False)
    cloud_public_id = detection.get('cloud_public_id')
    cloud_resource_type = detection.get('cloud_resource_type')
    cloud_secure_url = detection.get('cloud_secure_url')
    cloud_annotated_url = detection.get('cloud_annotated_url')
    
    # Calculate statistics
    weed_classes = {}
    total_confidence = 0
    for detail in detection_details:
        weed_class = detail['weed_class']
        confidence = detail['confidence']
        if weed_class not in weed_classes:
            weed_classes[weed_class] = {'count': 0, 'total_confidence': 0}
        weed_classes[weed_class]['count'] += 1
        weed_classes[weed_class]['total_confidence'] += confidence
        total_confidence += confidence
    
    # Calculate averages
    avg_confidence = (total_confidence / len(detection_details)) if detection_details else 0
    for weed_class in weed_classes:
        weed_classes[weed_class]['avg_confidence'] = weed_classes[weed_class]['total_confidence'] / weed_classes[weed_class]['count']
    
    if format.lower() == "json":
        # JSON Export
        report = {
            'report_generated': dt.now().isoformat(),
            'detection_session': {
                'id': det_id,
                'filename': filename,
                'timestamp': timestamp,
                'file_type': file_type,
                'summary': summary,
                'total_frames': total_frames,
                'total_detections': total_detections,
                'processing_time': processing_time,
                'has_gps_data': bool(has_srt_data),
                'cloud_url': cloud_secure_url,
                'annotated_url': cloud_annotated_url
            },
            'statistics': {
                'total_weeds_detected': len(detection_details),
                'average_confidence': round(avg_confidence, 2),
                'weed_classes': {
                    weed_class: {
                        'count': data['count'],
                        'percentage': round((data['count'] / len(detection_details)) * 100, 2),
                        'avg_confidence': round(data['avg_confidence'], 2)
                    }
                    for weed_class, data in weed_classes.items()
                }
            },
            'detections': [
                {
                    'id': d['id'],
                    'frame_number': d['frame_number'],
                    'weed_class': d['weed_class'],
                    'confidence': round(d['confidence'], 2),
                    'bbox': {
                        'x': d['bbox_x'], 
                        'y': d['bbox_y'], 
                        'width': d['bbox_width'], 
                        'height': d['bbox_height']
                    },
                    'timestamp': d.get('detection_timestamp')
                }
                for d in detection_details
            ]
        }
        
        if srt_track:
            frames_json = json.loads(srt_track['frames_json'])
            report['gps_data'] = {
                'point_count': srt_track['point_count'],
                'start_time': srt_track.get('start_time'),
                'end_time': srt_track.get('end_time'),
                'frames': frames_json
            }
        
        return JSONResponse(content=report)
    
    elif format.lower() == "csv":
        # CSV Export
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header rows
        writer.writerow(['Weed Detection Report'])
        writer.writerow(['Generated', dt.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(['Session ID', det_id])
        writer.writerow(['Filename', filename])
        writer.writerow(['Timestamp', timestamp])
        writer.writerow(['Total Detections', len(detection_details)])
        writer.writerow(['Average Confidence', f"{avg_confidence:.2f}%"])
        writer.writerow([])
        
        # Weed class summary
        writer.writerow(['Weed Class Summary'])
        writer.writerow(['Class', 'Count', 'Percentage', 'Avg Confidence'])
        for weed_class, data in weed_classes.items():
            writer.writerow([
                weed_class,
                data['count'],
                f"{(data['count'] / len(detection_details)) * 100:.2f}%",
                f"{data['avg_confidence']:.2f}%"
            ])
        writer.writerow([])
        
        # Detailed detections
        writer.writerow(['Detailed Detections'])
        writer.writerow(['ID', 'Frame', 'Weed Class', 'Confidence', 'BBox X', 'BBox Y', 'Width', 'Height'])
        for d in detection_details:
            writer.writerow([
                d['id'], 
                d['frame_number'], 
                d['weed_class'], 
                f"{d['confidence']:.2f}", 
                d['bbox_x'], 
                d['bbox_y'], 
                d['bbox_width'], 
                d['bbox_height']
            ])
        
        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=detection_report_{det_id}.csv"}
        )
    
    elif format.lower() == "pdf":
        # PDF Export (requires reportlab - optional, fallback to JSON if not available)
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []
            
            # Title
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=30,
                alignment=TA_CENTER
            )
            story.append(Paragraph("Weed Detection Report", title_style))
            story.append(Spacer(1, 0.2*inch))
            
            # Session info
            session_data = [
                ['Session ID:', str(det_id)],
                ['Filename:', filename],
                ['Date:', timestamp],
                ['File Type:', file_type],
                ['Total Frames:', str(total_frames)],
                ['Total Detections:', str(len(detection_details))],
                ['Processing Time:', f"{processing_time:.2f}s"],
                ['Average Confidence:', f"{avg_confidence:.2f}%"],
                ['GPS Data:', 'Yes' if has_srt_data else 'No']
            ]
            
            session_table = Table(session_data, colWidths=[2*inch, 4*inch])
            session_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
            ]))
            story.append(session_table)
            story.append(Spacer(1, 0.3*inch))
            
            # Heatmap image if SRT data available
            if has_srt_data:
                print(f"🗺️  Session has SRT data, generating heatmap for PDF...")
                try:
                    # Get heatmap data
                    print(f"📊 Fetching heatmap data for detection {detection_id}...")
                    heatmap_response = await get_unique_weeds_heatmap(detection_id, 0.6, 2, 0.3, False)
                    points = heatmap_response.get('points', [])
                    print(f"📊 Got {len(points)} heatmap points")
                    
                    if points:
                        # Generate heatmap image using folium (Leaflet) like Mapscreen
                        import folium
                        from folium.plugins import HeatMap
                        import tempfile
                        import os
                        from io import BytesIO
                        
                        # Create folium map with same settings as Mapscreen
                        # Calculate center
                        avg_lat = sum(p['lat'] for p in points) / len(points)
                        avg_lng = sum(p['lng'] for p in points) / len(points)
                        
                        # Create map with Google Satellite tiles (same as Mapscreen)
                        m = folium.Map(
                            location=[avg_lat, avg_lng],
                            zoom_start=17,
                            max_zoom=20
                        )
                        
                        # Add Google Satellite tiles like Mapscreen
                        folium.TileLayer(
                            tiles='https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                            attr='Map data ©2025 Google',
                            name='Google Satellite',
                            max_zoom=20,
                            subdomains=['mt0', 'mt1', 'mt2', 'mt3']
                        ).add_to(m)
                        
                        # Add polyline if we have SRT data (flight path)
                        try:
                            print(f"📍 Fetching polyline for detection {detection_id}...")
                            polyline_response = await get_gmap_polyline(detection_id)
                            polyline_points = polyline_response.get('points', [])
                            print(f"📍 Got {len(polyline_points)} polyline points")
                            if polyline_points:
                                folium.PolyLine(
                                    locations=[[p['lat'], p['lng']] for p in polyline_points],
                                    color='#2563eb',
                                    weight=3,
                                    opacity=0.8
                                ).add_to(m)
                                print(f"✅ Added polyline to map")
                                
                                # Add start marker (green)
                                start_point = polyline_points[0]
                                folium.Marker(
                                    location=[start_point['lat'], start_point['lng']],
                                    icon=folium.DivIcon(
                                        html='<div style="background-color: #22c55e; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
                                        icon_size=(14, 14),
                                        icon_anchor=(7, 7)
                                    ),
                                    popup='Flight Start'
                                ).add_to(m)
                                print(f"✅ Added start marker")
                                
                                # Add end marker (red)
                                end_point = polyline_points[-1]
                                folium.Marker(
                                    location=[end_point['lat'], end_point['lng']],
                                    icon=folium.DivIcon(
                                        html='<div style="background-color: #ef4444; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
                                        icon_size=(14, 14),
                                        icon_anchor=(7, 7)
                                    ),
                                    popup='Flight End'
                                ).add_to(m)
                                print(f"✅ Added end marker")
                        except Exception as e:
                            print(f"❌ Error adding polyline: {e}")
                            import traceback
                            traceback.print_exc()
                        
                        # Add heatmap layer with exact same settings as Mapscreen
                        heat_data = [[p['lat'], p['lng'], p['weight']] for p in points]
                        HeatMap(
                            heat_data,
                            radius=6,            # Reduced radius for smaller, tighter heat points
                            blur=6,              # Slightly less blur to keep points distinct
                            max_zoom=18,
                            max=4,               # Lower max to make low-density areas more visible
                            gradient={           # Custom gradient: green (low) -> yellow -> red (high)
                                0.0: 'green',
                                0.3: 'lime',
                                0.5: 'yellow',
                                0.7: 'orange',
                                1.0: 'red'
                            }
                        ).add_to(m)
                        
                        # Fit bounds
                        if len(points) > 1:
                            m.fit_bounds([
                                [min(p['lat'] for p in points), min(p['lng'] for p in points)],
                                [max(p['lat'] for p in points), max(p['lng'] for p in points)]
                            ])
                        
                        # Save to temporary HTML file
                        html_file = None
                        try:
                            with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
                                html_file = f.name
                                m.save(html_file)
                            
                            # Try selenium screenshot first
                            try:
                                from selenium import webdriver
                                from selenium.webdriver.chrome.options import Options
                                from selenium.webdriver.chrome.service import Service
                                import time
                                
                                chrome_options = Options()
                                chrome_options.add_argument('--headless')
                                chrome_options.add_argument('--no-sandbox')
                                chrome_options.add_argument('--disable-dev-shm-usage')
                                chrome_options.add_argument('--disable-gpu')
                                chrome_options.add_argument('--window-size=800,600')
                                
                                # Try webdriver-manager first, fall back to system Chrome
                                try:
                                    from webdriver_manager.chrome import ChromeDriverManager
                                    service = Service(ChromeDriverManager().install())
                                except Exception as wdm_error:
                                    print(f"⚠️  webdriver-manager failed: {wdm_error}, trying system Chrome...")
                                    # Try to use system Chrome driver
                                    service = Service()
                                
                                driver = webdriver.Chrome(service=service, options=chrome_options)
                                driver.get(f'file://{html_file}')
                                time.sleep(5)  # Wait for tiles to load
                                screenshot = driver.get_screenshot_as_png()
                                driver.quit()
                                
                                img_buffer = BytesIO(screenshot)
                                print(f"✅ Screenshot captured with selenium")
                                
                            except Exception as selenium_error:
                                print(f"❌ Error taking screenshot with selenium: {selenium_error}")
                                print("⚠️  Falling back to matplotlib for heatmap...")
                                
                                # Fallback to matplotlib
                                import matplotlib.pyplot as plt
                                fig, ax = plt.subplots(figsize=(6, 4))
                                lats = [p['lat'] for p in points]
                                lngs = [p['lng'] for p in points]
                                weights = [p['weight'] for p in points]
                                scatter = ax.scatter(lngs, lats, c=weights, cmap='RdYlGn_r', s=50, alpha=0.7, edgecolors='black')
                                ax.set_xlabel('Longitude')
                                ax.set_ylabel('Latitude')
                                ax.set_title('Weed Detection Heatmap')
                                ax.grid(True, alpha=0.3)
                                cbar = plt.colorbar(scatter, ax=ax)
                                cbar.set_label('Unique Weed Count')
                                img_buffer = BytesIO()
                                fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
                                img_buffer.seek(0)
                                plt.close(fig)
                                print(f"✅ Heatmap generated with matplotlib")
                            
                            # Add to PDF
                            story.append(Paragraph("GPS Heatmap", styles['Heading2']))
                            story.append(Spacer(1, 0.1*inch))
                            heatmap_img = Image(img_buffer, width=6*inch, height=4*inch)
                            story.append(heatmap_img)
                            story.append(Spacer(1, 0.2*inch))
                            
                            # Add legend
                            story.append(Paragraph("Map Legend", styles['Heading3']))
                            story.append(Spacer(1, 0.1*inch))
                            
                            # Create legend table with color indicators
                            legend_data = [
                                ['Low Density', '≤2 weeds', 'Medium Density', '3-5 weeds', 'High Density', '>5 weeds'],
                                ['Flight Path', 'Blue line', 'Start Point', 'Green marker', 'End Point', 'Red marker']
                            ]
                            
                            legend_table = Table(legend_data, colWidths=[1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch, 1.2*inch])
                            legend_table.setStyle(TableStyle([
                                # Header row styling
                                ('BACKGROUND', (0, 0), (5, 0), colors.HexColor('#f3f4f6')),
                                ('TEXTCOLOR', (0, 0), (5, 0), colors.black),
                                ('ALIGN', (0, 0), (5, 0), 'CENTER'),
                                ('FONTNAME', (0, 0), (5, 0), 'Helvetica-Bold'),
                                ('FONTSIZE', (0, 0), (5, 0), 10),
                                ('BOTTOMPADDING', (0, 0), (5, 0), 8),
                                
                                # Data row styling
                                ('BACKGROUND', (0, 1), (5, 1), colors.HexColor('#ffffff')),
                                ('TEXTCOLOR', (0, 1), (5, 1), colors.black),
                                ('ALIGN', (0, 1), (5, 1), 'CENTER'),
                                ('FONTSIZE', (0, 1), (5, 1), 9),
                                ('GRID', (0, 0), (5, 1), 0.5, colors.grey),
                                
                                # Color indicators for density levels
                                ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#22c55e')),  # Low - green
                                ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#eab308')),  # Medium - yellow
                                ('BACKGROUND', (4, 0), (4, 0), colors.HexColor('#ef4444')),  # High - red
                                
                                # Color indicators for markers
                                ('BACKGROUND', (0, 1), (0, 1), colors.HexColor('#2563eb')),  # Path - blue
                                ('BACKGROUND', (2, 1), (2, 1), colors.HexColor('#22c55e')),  # Start - green
                                ('BACKGROUND', (4, 1), (4, 1), colors.HexColor('#ef4444')),  # End - red
                            ]))
                            story.append(legend_table)
                            story.append(Spacer(1, 0.3*inch))
                            print(f"✅ Heatmap added to PDF")
                            
                        finally:
                            # Clean up temp file
                            if html_file and os.path.exists(html_file):
                                os.unlink(html_file)
                                print(f"🧹 Cleaned up temp HTML file")
                                
                except Exception as e:
                    print(f"❌ Error generating heatmap image: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue without heatmap - don't fail the entire PDF export
            
            # Weed class summary
            story.append(Paragraph("Weed Species Summary", styles['Heading2']))
            story.append(Spacer(1, 0.1*inch))
            
            class_data = [['Weed Class', 'Count', 'Percentage', 'Avg Confidence']]
            for weed_class, data in weed_classes.items():
                class_data.append([
                    weed_class,
                    str(data['count']),
                    f"{(data['count'] / len(detection_details)) * 100:.1f}%",
                    f"{data['avg_confidence']:.1f}%"
                ])
            
            class_table = Table(class_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
            class_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            story.append(class_table)
            story.append(Spacer(1, 0.3*inch))
            
            # Detection details (first 50 for brevity)
            story.append(Paragraph(f"Detection Details (showing first 50 of {len(detection_details)})", styles['Heading2']))
            story.append(Spacer(1, 0.1*inch))
            
            detail_data = [['Frame', 'Weed Class', 'Confidence', 'BBox (x, y, w, h)']]
            for d in detection_details[:50]:
                detail_data.append([
                    str(d['frame_number']),
                    d['weed_class'],
                    f"{d['confidence']:.1f}%",
                    f"({d['bbox_x']:.0f}, {d['bbox_y']:.0f}, {d['bbox_width']:.0f}, {d['bbox_height']:.0f})"
                ])
            
            detail_table = Table(detail_data, colWidths=[1*inch, 2*inch, 1.5*inch, 2*inch])
            detail_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2ecc71')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            story.append(detail_table)
            
            # Build PDF
            doc.build(story)
            buffer.seek(0)
            
            return StreamingResponse(
                buffer,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=detection_report_{det_id}.pdf"}
            )
        except ImportError:
            # Fallback to JSON if reportlab not installed
            raise HTTPException(
                status_code=501,
                detail="PDF export requires 'reportlab' package. Install with: pip install reportlab"
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Use 'json', 'csv', or 'pdf'")

@app.post("/detection/{detection_id}/share")
async def create_share_package(detection_id: int):
    """Create a shareable package with detection report and media URLs."""
    import base64
    
    # Fetch detection data
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    detection = session['detection']
    detection_details = session['detection_details']
    
    # Extract detection fields from dict
    det_id = detection['id']
    filename = detection['filename']
    timestamp = detection['timestamp']
    file_type = detection['file_type']
    summary = detection.get('summary')
    total_frames = detection.get('total_frames', 0)
    total_detections = detection.get('total_detections', 0)
    processing_time = detection.get('processing_time', 0.0)
    input_size_bytes = detection.get('input_size_bytes')
    result_size_bytes = detection.get('result_size_bytes')
    has_srt_data = detection.get('has_srt_data', False)
    cloud_public_id = detection.get('cloud_public_id')
    cloud_secure_url = detection.get('cloud_secure_url')
    cloud_annotated_url = detection.get('cloud_annotated_url')
    
    # Calculate simple stats
    weed_classes = {}
    for detail in detection_details:
        weed_class = detail['weed_class']
        weed_classes[weed_class] = weed_classes.get(weed_class, 0) + 1
    
    # Create shareable package
    share_package = {
        'detection_id': det_id,
        'filename': filename,
        'timestamp': timestamp,
        'summary': summary,
        'total_detections': len(detection_details),
        'weed_species': weed_classes,
        'has_gps_data': bool(has_srt_data),
        'media_urls': {
            'original': cloud_secure_url,
            'annotated': cloud_annotated_url
        },
        'share_message': f"🌿 Weed Detection Results\n\nFile: {filename}\nDetected: {len(detection_details)} weeds\nSpecies: {', '.join(weed_classes.keys())}\n\nView details at: {cloud_annotated_url or cloud_secure_url or 'N/A'}"
    }
    
    # Generate a simple share token (base64 encoded detection_id)
    share_token = base64.urlsafe_b64encode(str(det_id).encode()).decode()
    share_package['share_token'] = share_token
    # Note: In production, this should point to a web frontend or public share page
    share_package['share_url'] = f"https://your-domain.com/shared/{share_token}"
    
    return JSONResponse(content=share_package)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

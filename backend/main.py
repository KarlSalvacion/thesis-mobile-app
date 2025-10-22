import os
import datetime
import time
import sqlite3
import uuid
from typing import Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import json
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
    upsert_srt_track, reset_compact_tables, update_srt_status, DB_NAME, init_db,
    fetch_detections_by_class, upsert_heatmap, calculate_unique_weeds
)
from .srt_parser import parse_srt_file, validate_srt_file

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
        processing_jobs[job_id]["status"] = "processing"
        processing_jobs[job_id]["progress"] = "Running inference..."
        
        # Run inference
        print(f"[Job {job_id}] Starting inference...")
        detections, annotated_source = run_inference_auto(media_path, confidence=confidence, overlap=overlap)
        print(f"[Job {job_id}] Inference completed in {time.time() - start_time:.2f} seconds")
        
        processing_jobs[job_id]["progress"] = "Uploading to cloud storage..."
        
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
                    processing_jobs[job_id]["temp_video_path"] = temp_video_path
                    processing_jobs[job_id]["original_filename"] = media_filename
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

        processing_jobs[job_id]["progress"] = "Saving to database..."
        
        # Insert detection record
        detection_id = insert_detection(
            filename=media_filename,
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
            for frame_idx, frame_detections in enumerate(detections if isinstance(detections[0], list) else [detections]):
                for det in frame_detections:
                    batch_details.append({
                        'frame_number': frame_idx + 1,
                        'weed_class': det.get('class', 'unknown'),
                        'confidence': det.get('confidence', 0.0),
                        'bbox_x': det.get('bbox', [0, 0, 0, 0])[0],
                        'bbox_y': det.get('bbox', [0, 0, 0, 0])[1],
                        'bbox_width': det.get('bbox', [0, 0, 0, 0])[2],
                        'bbox_height': det.get('bbox', [0, 0, 0, 0])[3],
                        'detection_timestamp': timestamp
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

        # Mark as completed
        processing_jobs[job_id]["status"] = "completed"
        processing_jobs[job_id]["result"] = {
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
        print(f"[Job {job_id}] Processing completed successfully")
        
        if temp_video_path:
            print(f"[Job {job_id}] ⚠️  Waiting for client to compress and upload annotated video")
        
    except Exception as e:
        print(f"[Job {job_id}] Processing failed: {e}")
        traceback.print_exc()
        processing_jobs[job_id]["status"] = "failed"
        processing_jobs[job_id]["error"] = str(e)
        
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
    
    # Validate file types
    media_filename = media_file.filename.lower()
    if not (media_filename.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.mp4', '.mov', '.avi', '.mkv'))):
        raise HTTPException(status_code=400, detail="Media file must be an image or video")
    
    is_video = media_filename.endswith(('.mp4', '.mov', '.avi', '.mkv'))
    is_image = media_filename.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif'))
    
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
    
    # Initialize job status
    processing_jobs[job_id] = {
        "status": "queued",
        "progress": "Uploaded, starting processing...",
        "result": None,
        "error": None
    }
    
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
async def get_job_status(job_id: str):
    """Check the status of a background processing job."""
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_data = processing_jobs[job_id]
    
    return JSONResponse({
        "job_id": job_id,
        "status": job_data["status"],
        "progress": job_data.get("progress"),
        "result": job_data.get("result"),
        "error": job_data.get("error"),
        "temp_video_path": job_data.get("temp_video_path")  # For client-side compression
    })

@app.get("/download-temp-video/{job_id}")
async def download_temp_video(job_id: str):
    """Download temporary annotated video for client-side compression."""
    from fastapi.responses import FileResponse
    
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_data = processing_jobs[job_id]
    temp_video_path = job_data.get("temp_video_path")
    
    if not temp_video_path or not os.path.exists(temp_video_path):
        raise HTTPException(status_code=404, detail="Temp video not found")
    
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
    if job_id not in processing_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_data = processing_jobs[job_id]
    
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
        detection_id = job_data.get("result", {}).get("detection_id")
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
            import sqlite3
            from .database import DB_NAME
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE detections SET cloud_annotated_url = ? WHERE id = ?",
                    (annotated_url, detection_id)
                )
                conn.commit()
                print(f"[Job {job_id}] Database updated with annotated URL")
            except Exception as e:
                print(f"[Job {job_id}] Failed to update annotated URL: {e}")
            finally:
                conn.close()
        
        # Update job result
        if "result" in job_data:
            job_data["result"]["cloud_annotated_url"] = annotated_url
        
        # Cleanup temp files
        try:
            os.remove(temp_compressed)
            temp_video_path = job_data.get("temp_video_path")
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                job_data["temp_video_path"] = None
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
    
    # Initialize job status
    processing_jobs[job_id] = {
        "status": "queued",
        "progress": "Uploaded, starting processing...",
        "result": None,
        "error": None
    }
    
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

@app.get("/detections/")
async def get_detections():
    """Get all detection sessions."""
    detections = fetch_all_detections()
    # Optionally map in a delivery URL for convenience
    enriched = []
    for row in detections:
        # row: (id, filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data, cloud_public_id, cloud_resource_type, cloud_secure_url)
        if len(row) >= 14 and row[13]:
            enriched.append(row)
        else:
            enriched.append(row)
    return {"detections": enriched}

@app.get("/detections/with-srt/")
async def get_detections_with_srt():
    """Get only detection sessions that have associated SRT data for mapping."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM detections WHERE has_srt_data = TRUE ORDER BY timestamp DESC")
        detections = cursor.fetchall()
    return {"detections": detections}

@app.get("/detection/{detection_id}")
async def get_detection_details(detection_id: int):
    """Get complete details of a specific detection session."""
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    return session

@app.get("/detection/{detection_id}/unique-weeds")
async def get_unique_weeds(
    detection_id: int,
    iou_threshold: float = Query(0.3, description="IoU threshold for matching (0.0-1.0)"),
    frame_gap: int = Query(10, description="Maximum frame gap for tracking")
):
    """Calculate unique weed count by tracking across frames.
    
    This solves the problem of counting the same weed multiple times across frames.
    Returns unique weed count instead of total detection count.
    """
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    unique_weeds = calculate_unique_weeds(detection_id, iou_threshold, frame_gap)
    
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

@app.get("/statistics/")
async def get_statistics():
    """Get overall detection statistics."""
    stats = get_detection_statistics()
    return stats

@app.get("/detections/class/{weed_class}")
async def get_detections_by_class(weed_class: str):
    """Get all detections of a specific weed class."""
    detections = fetch_detections_by_class(weed_class)
    return {"weed_class": weed_class, "detections": detections}

@app.post("/admin/reset-compact-tables")
async def admin_reset_compact_tables(confirm: bool = Query(False, description="Set true to confirm reset")):
    """Admin: Drop and recreate compact SRT/heatmap tables."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    reset_compact_tables()
    return {"message": "Compact tables reset: srt_tracks, heatmaps"}

@app.post("/admin/reset-db")
async def admin_reset_db(confirm: bool = Query(False, description="Set true to confirm full DB reset (delete file)")):
    """Admin: Delete the SQLite DB file and recreate all tables."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    try:
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        # Also try removing one level up (in case old DB was at project root)
        old_db_name = "weed_detection.db"  # Just the filename
        parent_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, old_db_name)
        parent_db = os.path.abspath(parent_db)
        if os.path.exists(parent_db):
            os.remove(parent_db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete DB file: {e}")
    # Recreate tables
    init_db()
    return {"message": "Database file reset and tables recreated"}

@app.post("/admin/drop-tables")
async def admin_drop_tables(tables: str = Query("", description="Comma-separated table names to drop"), confirm: bool = Query(False)):
    """Admin: Drop specific tables by name (use cautiously)."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required: set confirm=true")
    if not tables:
        raise HTTPException(status_code=400, detail="Provide table names via tables query param")
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        dropped = []
        for name in [t.strip() for t in tables.split(',') if t.strip()]:
            cursor.execute(f"DROP TABLE IF EXISTS {name}")
            dropped.append(name)
        conn.commit()
        return {"message": "Dropped tables", "dropped": dropped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

@app.get("/detection/{detection_id}/gmap-polyline")
async def get_gmap_polyline(detection_id: int):
    """Return Google Maps-ready polyline points and bounds for a detection's SRT track."""
    import sqlite3
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT path_geojson, bounds_geojson FROM srt_tracks WHERE detection_id = ?", (detection_id,))
        row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="SRT track not found")
    path_geojson = json.loads(row[0])
    bounds_geojson = json.loads(row[1]) if row[1] else None
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
async def generate_heatmap(detection_id: int, grid_size_m: float = Query(10.0), persist: bool = Query(True)):
    """Generate heatmap from detection_details mapped to SRT frames; optionally persist aggregated grid."""
    import sqlite3
    # Load srt frames
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT frames_json, bounds_geojson FROM srt_tracks WHERE detection_id = ?", (detection_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="SRT track not found")
        frames_json = row[0]
        bounds_geojson = row[1]
        frames = { int(f.get('i')): (f.get('lat'), f.get('lon')) for f in json.loads(frames_json) if f.get('lat') is not None and f.get('lon') is not None }

        # Load detection details
        cursor.execute("SELECT frame_number, weed_class, confidence FROM detection_details WHERE detection_id = ?", (detection_id,))
        details = cursor.fetchall()

    # Map detections to lat/lng points
    points = []
    for frame_number, weed_class, confidence in details:
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
    for p in points:
        key_lat = int(math.floor(p['lat'] / cell_deg_lat))
        key_lng = int(math.floor(p['lng'] / cell_deg_lng))
        key = f"{key_lat}:{key_lng}"
        cell = grid.get(key)
        if not cell:
            grid[key] = { 'lat_idx': key_lat, 'lng_idx': key_lng, 'count': 0, 'sum_weight': 0.0 }
            cell = grid[key]
        cell['count'] += 1
        cell['sum_weight'] += p['weight']

    # Convert grid to list with representative cell center
    cells = []
    for cell in grid.values():
        center_lat = (cell['lat_idx'] + 0.5) * cell_deg_lat
        center_lng = (cell['lng_idx'] + 0.5) * cell_deg_lng
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
    
    # Parse detection tuple
    det_id, filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data = detection[0:11]
    cloud_public_id = detection[11] if len(detection) > 11 else None
    cloud_resource_type = detection[12] if len(detection) > 12 else None
    cloud_secure_url = detection[13] if len(detection) > 13 else None
    cloud_annotated_url = detection[14] if len(detection) > 14 else None
    
    # Calculate statistics
    weed_classes = {}
    total_confidence = 0
    for detail in detection_details:
        weed_class = detail[3]
        confidence = detail[4]
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
                    'id': d[0],
                    'frame_number': d[2],
                    'weed_class': d[3],
                    'confidence': round(d[4], 2),
                    'bbox': {
                        'x': d[5], 'y': d[6], 'width': d[7], 'height': d[8]
                    },
                    'timestamp': d[14] if len(d) > 14 else None
                }
                for d in detection_details
            ]
        }
        
        if srt_track:
            frames_json = json.loads(srt_track[6]) if len(srt_track) > 6 else []
            report['gps_data'] = {
                'point_count': srt_track[1] if len(srt_track) > 1 else 0,
                'start_time': srt_track[2] if len(srt_track) > 2 else None,
                'end_time': srt_track[3] if len(srt_track) > 3 else None,
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
            writer.writerow([d[0], d[2], d[3], f"{d[4]:.2f}", d[5], d[6], d[7], d[8]])
        
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
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
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
                    str(d[2]),
                    d[3],
                    f"{d[4]:.1f}%",
                    f"({d[5]:.0f}, {d[6]:.0f}, {d[7]:.0f}, {d[8]:.0f})"
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
    
    # Parse detection tuple
    det_id, filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data = detection[0:11]
    cloud_public_id = detection[11] if len(detection) > 11 else None
    cloud_secure_url = detection[13] if len(detection) > 13 else None
    cloud_annotated_url = detection[14] if len(detection) > 14 else None
    
    # Calculate simple stats
    weed_classes = {}
    for detail in detection_details:
        weed_class = detail[3]
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

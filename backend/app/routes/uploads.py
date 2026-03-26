import json
import os
import tempfile
import uuid
from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from app.background_jobs import process_media_background
from db.database import create_processing_job, upsert_srt_track
from utils.srt_parser import parse_srt_file, validate_srt_file

try:
    from PIL import Image
except Exception:
    Image = None

router = APIRouter()


@router.post('/upload-combined/')
async def upload_combined_files(
    background_tasks: BackgroundTasks,
    media_file: UploadFile = File(..., description='Video or image file'),
    srt_file: UploadFile = File(None, description='Optional SRT file for video'),
    skip_cloud: bool = Query(False, description='Skip Cloudinary upload for speed'),
    confidence: int = Query(None, description='Confidence threshold (0-100)'),
    overlap: int = Query(None, description='Overlap threshold (0-100)'),
):
    media_filename_lower = media_file.filename.lower()
    if not media_filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.mp4', '.mov', '.avi', '.mkv')):
        raise HTTPException(status_code=400, detail='Media file must be an image or video')

    is_video = media_filename_lower.endswith(('.mp4', '.mov', '.avi', '.mkv'))
    is_image = media_filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif'))

    if srt_file and is_image:
        raise HTTPException(status_code=400, detail='SRT files can only be uploaded with video files, not images')

    if srt_file and not srt_file.filename.lower().endswith('.srt'):
        raise HTTPException(status_code=400, detail='SRT file must have .srt extension')

    media_bytes = await media_file.read()
    if not media_bytes:
        raise HTTPException(status_code=400, detail='Empty media file')

    srt_content = None
    srt_filename_str = None
    if srt_file:
        srt_content = await srt_file.read()
        srt_filename_str = srt_file.filename

    job_id = str(uuid.uuid4())

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(media_file.filename)[1])
    tmp.write(media_bytes)
    tmp.flush()
    tmp.close()
    media_path = tmp.name

    create_processing_job(
        job_id=job_id,
        original_filename=media_file.filename,
        is_video=is_video,
        is_image=is_image,
        has_srt=(srt_file is not None),
    )

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
        overlap=overlap,
    )

    return JSONResponse(
        {
            'job_id': job_id,
            'status': 'processing',
            'message': 'File uploaded successfully. Processing in background. Use /job-status/{job_id} to check progress.',
        }
    )


@router.post('/upload/')
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    skip_cloud: bool = Query(False, description='Skip Cloudinary upload for speed'),
    confidence: int = Query(None, description='Confidence threshold (0-100)'),
    overlap: int = Query(None, description='Overlap threshold (0-100)'),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail='Empty file uploaded')

    file_size_mb = len(file_bytes) / (1024 * 1024)
    print(f'Processing file: {file.filename} ({file_size_mb:.1f} MB)')

    from config.settings import MAX_UPLOAD_SIZE_MB

    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f'File too large: {file_size_mb:.1f}MB. Maximum allowed: {MAX_UPLOAD_SIZE_MB}MB for Render.com Standard Plan',
        )

    if file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif')):
        if Image is None:
            print('Warning: Pillow not installed; skipping image validation')
        else:
            try:
                img = Image.open(BytesIO(file_bytes))
                img.verify()
            except Exception:
                raise HTTPException(status_code=400, detail='Invalid or corrupted image file')

    is_video = file.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv'))
    is_image = file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'))

    job_id = str(uuid.uuid4())

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
    tmp.write(file_bytes)
    tmp.flush()
    tmp.close()
    file_path = tmp.name

    create_processing_job(
        job_id=job_id,
        original_filename=file.filename,
        is_video=is_video,
        is_image=is_image,
        has_srt=False,
    )

    background_tasks.add_task(
        process_media_background,
        job_id=job_id,
        media_path=file_path,
        media_filename=file.filename,
        media_bytes=file_bytes,
        srt_content=None,
        srt_filename=None,
        is_video=is_video,
        is_image=is_image,
        skip_cloud=skip_cloud,
        confidence=confidence,
        overlap=overlap,
    )

    return JSONResponse(
        {
            'job_id': job_id,
            'status': 'processing',
            'message': 'File uploaded successfully. Processing in background. Use /job-status/{job_id} to check progress.',
        }
    )


@router.post('/upload-srt/')
async def upload_srt_file(
    detection_id: int = Query(..., description='Detection session ID to associate SRT data with'),
    srt_file: UploadFile = File(..., description='SRT subtitle file'),
):
    if not srt_file.filename.lower().endswith('.srt'):
        raise HTTPException(status_code=400, detail='File must be an SRT file')

    srt_content = await srt_file.read()
    srt_text = srt_content.decode('utf-8')

    if not validate_srt_file(srt_text):
        raise HTTPException(status_code=400, detail='Invalid SRT file format')

    frames = parse_srt_file(srt_text)
    if not frames:
        raise HTTPException(status_code=400, detail='No valid frame data found in SRT file')

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

    if not coords:
        raise HTTPException(status_code=400, detail='SRT has no GPS coordinates')

    start_time = frames[0].get('timestamp') if frames else None
    end_time = frames[-1].get('timestamp') if frames else None

    bounds_geojson = json.dumps(
        {
            'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [[[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]]},
            'properties': {'detection_id': detection_id},
        }
    )

    path_geojson = json.dumps(
        {
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords},
            'properties': {'detection_id': detection_id, 'points': len(coords)},
        }
    )

    frames_json = json.dumps(compact_frames)

    upsert_srt_track(
        detection_id=detection_id,
        point_count=len(coords),
        start_time=start_time,
        end_time=end_time,
        bounds_geojson=bounds_geojson,
        path_geojson=path_geojson,
        frames_json=frames_json,
    )

    return JSONResponse(
        content={
            'message': 'SRT file uploaded successfully (compact track stored)',
            'detection_id': detection_id,
            'frames_processed': len(frames),
            'points_stored': len(coords),
            'bounds': {'min_lat': min_lat, 'min_lon': min_lon, 'max_lat': max_lat, 'max_lon': max_lon},
        }
    )

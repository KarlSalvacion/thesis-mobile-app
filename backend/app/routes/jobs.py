import json
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.db.database import (
    cleanup_old_jobs,
    get_job_status,
    get_pending_compression_jobs,
    get_db_connection,
    mark_compression_completed,
    mark_compression_started,
    update_job_status,
)
from backend.utils.cloudinary_utils import upload_video_streaming

router = APIRouter()


@router.get('/job-status/{job_id}')
async def get_job_status_endpoint(job_id: str):
    job_data = get_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail='Job not found')

    result = None
    if job_data['result_json']:
        try:
            result = json.loads(job_data['result_json'])
        except Exception:
            result = None

    return JSONResponse(
        {
            'job_id': job_data['job_id'],
            'status': job_data['status'],
            'progress': job_data['progress'],
            'result': result,
            'error': job_data['error_message'],
            'temp_video_path': job_data['temp_video_path'],
            'needs_client_compression': job_data['needs_client_compression'],
        }
    )


@router.get('/download-temp-video/{job_id}')
async def download_temp_video(job_id: str):
    job_data = get_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail='Job not found')

    temp_video_path = job_data.get('temp_video_path')
    if not temp_video_path or not os.path.exists(temp_video_path):
        raise HTTPException(status_code=404, detail='Temp video not found')

    mark_compression_started(job_id)

    return FileResponse(temp_video_path, media_type='video/mp4', filename=f'annotated_{job_id}.mp4')


@router.post('/upload-compressed-video/{job_id}')
async def upload_compressed_video(job_id: str, compressed_video: UploadFile = File(..., description='Client-compressed video')):
    job_data = get_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail='Job not found')

    try:
        video_bytes = await compressed_video.read()
        video_size_mb = len(video_bytes) / (1024 * 1024)
        print(f'[Job {job_id}] Received compressed video: {video_size_mb:.2f} MB')

        temp_compressed = tempfile.mktemp(suffix='_compressed.mp4')
        with open(temp_compressed, 'wb') as f:
            f.write(video_bytes)

        detection_id = job_data.get('detection_id')
        original_filename = job_data.get('original_filename', 'video.mp4')

        uploaded = upload_video_streaming(temp_compressed, original_filename, folder='weed-detections/annotated', annotate=False)
        annotated_url = uploaded.get('secure_url')
        print(f'[Job {job_id}] Compressed video uploaded to Cloudinary: {annotated_url}')

        if detection_id:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute('UPDATE detections SET cloud_annotated_url = %s WHERE id = %s', (annotated_url, detection_id))
                    conn.commit()
                    print(f'[Job {job_id}] Database updated with annotated URL')
                except Exception as e:
                    print(f'[Job {job_id}] Failed to update annotated URL: {e}')

        mark_compression_completed(job_id, annotated_url)

        try:
            os.remove(temp_compressed)
            temp_video_path = job_data.get('temp_video_path')
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
        except Exception:
            pass

        return JSONResponse({'success': True, 'message': 'Compressed video uploaded successfully', 'annotated_url': annotated_url})

    except Exception as e:
        print(f'[Job {job_id}] Error uploading compressed video: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/jobs/pending-compression')
async def get_pending_compression_jobs_endpoint():
    try:
        jobs = get_pending_compression_jobs()
        return JSONResponse({'success': True, 'jobs': jobs, 'count': len(jobs)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/jobs/{job_id}/resume-compression')
async def resume_compression(job_id: str):
    job_data = get_job_status(job_id)

    if not job_data:
        raise HTTPException(status_code=404, detail='Job not found')

    if not job_data['needs_client_compression']:
        return JSONResponse({'success': False, 'message': 'Job does not need compression'})

    if not job_data['temp_video_path'] or not os.path.exists(job_data['temp_video_path']):
        return JSONResponse({'success': False, 'message': 'Temp video no longer available'})

    return JSONResponse(
        {
            'success': True,
            'message': 'Job ready for compression resumption',
            'job_id': job_id,
            'temp_video_available': True,
            'detection_id': job_data['detection_id'],
        }
    )


async def _cancel_job_logic(job_id: str):
    job_data = get_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail='Job not found')

    try:
        print(f'[Job {job_id}] Cancellation requested by user')
        if job_data.get('temp_video_path') and os.path.exists(job_data['temp_video_path']):
            os.remove(job_data['temp_video_path'])
            print(f'[Job {job_id}] Removed temp video file')

        update_job_status(job_id, 'failed', error_message='Cancelled by user')
        print(f'[Job {job_id}] Marked as cancelled in database')

        return JSONResponse({'success': True, 'message': 'Job cancelled successfully'})
    except Exception as e:
        print(f'[Job {job_id}] Error cancelling job: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.delete('/jobs/{job_id}')
async def cancel_job_delete(job_id: str):
    return await _cancel_job_logic(job_id)


@router.post('/cancel-job/{job_id}')
async def cancel_job_post(job_id: str):
    return await _cancel_job_logic(job_id)


@router.post('/jobs/cleanup')
async def cleanup_old_jobs_endpoint(days: int = Query(7, description='Clean up jobs older than X days')):
    try:
        deleted_count = cleanup_old_jobs(days)
        return JSONResponse({'success': True, 'message': f'Cleaned up {deleted_count} old jobs', 'deleted_count': deleted_count})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

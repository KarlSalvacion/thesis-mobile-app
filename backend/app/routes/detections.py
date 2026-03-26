import base64
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor

from app.serializers import dict_to_detection_tuple, detection_details_to_tuples, srt_track_to_tuple
from db.database import (
    calculate_unique_weeds,
    fetch_all_detections,
    fetch_detection_session,
    fetch_detections_by_class,
    get_db_connection,
    get_detection_statistics,
)

router = APIRouter()


@router.get('/detections/')
async def get_detections():
    detections = fetch_all_detections()
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {'detections': detection_tuples}


@router.get('/detections/with-srt/')
async def get_detections_with_srt():
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT * FROM detections WHERE has_srt_data = TRUE ORDER BY timestamp DESC')
        detections = [dict(row) for row in cursor.fetchall()]
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {'detections': detection_tuples}


@router.get('/detection/{detection_id}')
async def get_detection_details(detection_id: int):
    session_data = fetch_detection_session(detection_id)
    if not session_data:
        raise HTTPException(status_code=404, detail='Detection session not found')

    detection_tuple = dict_to_detection_tuple(session_data['detection'])
    detection_details_tuples = detection_details_to_tuples(session_data['detection_details'])
    srt_track_tuple = srt_track_to_tuple(session_data['srt_track'])

    return {
        'detection': detection_tuple,
        'srt_track': srt_track_tuple,
        'detection_details': detection_details_tuples,
        'frame_metadata': [],
    }


@router.get('/detection/{detection_id}/unique-weeds')
async def get_unique_weeds(
    detection_id: int,
    iou_threshold: float = Query(0.58, description='IoU threshold for matching (0.0-1.0)'),
    frame_gap: int = Query(13, description='Maximum frame gap for tracking'),
):
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail='Detection session not found')

    print(f'[UNIQUE WEEDS] Calculating for detection {detection_id} with iou_threshold={iou_threshold}, frame_gap={frame_gap}')
    unique_weeds = calculate_unique_weeds(detection_id, iou_threshold, frame_gap)

    return {
        'detection_id': detection_id,
        'unique_weed_count': unique_weeds['unique_count'],
        'total_detections': unique_weeds['total_detections'],
        'reduction_percentage': unique_weeds['reduction_percentage'],
        'weed_species': unique_weeds['by_class'],
        'tracking_params': {'iou_threshold': iou_threshold, 'frame_gap': frame_gap},
        'message': (
            f"Found {unique_weeds['unique_count']} unique weeds from {unique_weeds['total_detections']} "
            f"total detections ({unique_weeds['reduction_percentage']}% reduction)"
        ),
    }


@router.delete('/detection/{detection_id}')
async def delete_detection_session(detection_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute('SELECT id FROM detections WHERE id = %s', (detection_id,))
            detection = cursor.fetchone()

            if not detection:
                raise HTTPException(status_code=404, detail='Detection session not found')

            cursor.execute('DELETE FROM detections WHERE id = %s', (detection_id,))
            cursor.execute('DELETE FROM detection_details WHERE detection_id = %s', (detection_id,))
            cursor.execute('DELETE FROM srt_tracks WHERE detection_id = %s', (detection_id,))
            cursor.execute('DELETE FROM heatmaps WHERE detection_id = %s', (detection_id,))
            conn.commit()

            return {
                'message': f'Detection session {detection_id} and all associated data deleted successfully',
                'deleted_id': detection_id,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'Failed to delete detection session: {str(e)}')


@router.get('/statistics/')
async def get_statistics():
    return get_detection_statistics()


@router.get('/detections/class/{weed_class}')
async def get_detections_by_class(weed_class: str):
    detections = fetch_detections_by_class(weed_class)
    detection_tuples = [dict_to_detection_tuple(d) for d in detections]
    return {'weed_class': weed_class, 'detections': detection_tuples}


@router.post('/detection/{detection_id}/share')
async def create_share_package(detection_id: int):
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail='Detection session not found')

    detection = session['detection']
    detection_details = session['detection_details']

    det_id = detection['id']
    filename = detection['filename']
    timestamp = detection['timestamp']
    summary = detection.get('summary')
    has_srt_data = detection.get('has_srt_data', False)
    cloud_secure_url = detection.get('cloud_secure_url')
    cloud_annotated_url = detection.get('cloud_annotated_url')

    weed_classes = {}
    for detail in detection_details:
        weed_class = detail['weed_class']
        weed_classes[weed_class] = weed_classes.get(weed_class, 0) + 1

    share_package = {
        'detection_id': det_id,
        'filename': filename,
        'timestamp': timestamp,
        'summary': summary,
        'total_detections': len(detection_details),
        'weed_species': weed_classes,
        'has_gps_data': bool(has_srt_data),
        'media_urls': {'original': cloud_secure_url, 'annotated': cloud_annotated_url},
        'share_message': (
            f"Weed Detection Results\n\nFile: {filename}\nDetected: {len(detection_details)} weeds\n"
            f"Species: {', '.join(weed_classes.keys())}\n\n"
            f"View details at: {cloud_annotated_url or cloud_secure_url or 'N/A'}"
        ),
    }

    share_token = base64.urlsafe_b64encode(str(det_id).encode()).decode()
    share_package['share_token'] = share_token
    share_package['share_url'] = f'https://your-domain.com/shared/{share_token}'

    return JSONResponse(content=share_package)

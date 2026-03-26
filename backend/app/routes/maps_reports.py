import io
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg2.extras import RealDictCursor

from db.database import (
    calculate_unique_weeds,
    fetch_detection_session,
    get_db_connection,
    upsert_heatmap,
)

router = APIRouter()


@router.get('/detection/{detection_id}/gmap-polyline')
async def get_gmap_polyline(detection_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT path_geojson, bounds_geojson FROM srt_tracks WHERE detection_id = %s', (detection_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='SRT track not found')

    path_geojson = json.loads(row['path_geojson'])
    bounds_geojson = json.loads(row['bounds_geojson']) if row['bounds_geojson'] else None
    coords = path_geojson.get('geometry', {}).get('coordinates', [])
    points = [{'lat': lat, 'lng': lng} for lng, lat in coords]

    bounds = None
    if bounds_geojson and bounds_geojson.get('geometry', {}).get('coordinates'):
        ring = bounds_geojson['geometry']['coordinates'][0]
        lats = [pt[1] for pt in ring]
        lngs = [pt[0] for pt in ring]
        bounds = {'min_lat': min(lats), 'min_lng': min(lngs), 'max_lat': max(lats), 'max_lng': max(lngs)}

    return {'detection_id': detection_id, 'points': points, 'bounds': bounds}


@router.post('/detection/{detection_id}/generate-heatmap')
async def generate_heatmap(detection_id: int, grid_size_m: float = Query(1.0), persist: bool = Query(True)):
    import math

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT frames_json, bounds_geojson FROM srt_tracks WHERE detection_id = %s', (detection_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='SRT track not found')

        frames_json = row['frames_json']
        bounds_geojson = row['bounds_geojson']
        frames = {
            int(f.get('i')): (f.get('lat'), f.get('lon'))
            for f in json.loads(frames_json)
            if f.get('lat') is not None and f.get('lon') is not None
        }

        cursor.execute('SELECT frame_number, weed_class, confidence FROM detection_details WHERE detection_id = %s', (detection_id,))
        details = cursor.fetchall()

    points = []
    for detail in details:
        frame_number = detail['frame_number']
        pos = frames.get(int(frame_number))
        if not pos:
            continue
        lat, lon = pos
        points.append({'lat': lat, 'lng': lon, 'weight': float(detail['confidence'])})

    if not points:
        return {'detection_id': detection_id, 'points': [], 'grid': None, 'persisted': False}

    mean_lat = sum(p['lat'] for p in points) / len(points)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(math.radians(mean_lat))
    cell_deg_lat = grid_size_m / meters_per_deg_lat
    cell_deg_lng = grid_size_m / meters_per_deg_lng if meters_per_deg_lng > 0 else grid_size_m

    grid = {}
    min_lat = min(p['lat'] for p in points)
    min_lng = min(p['lng'] for p in points)

    for p in points:
        key_lat = int(math.floor((p['lat'] - min_lat) / cell_deg_lat))
        key_lng = int(math.floor((p['lng'] - min_lng) / cell_deg_lng))
        key = f'{key_lat}:{key_lng}'
        cell = grid.get(key)
        if not cell:
            grid[key] = {'lat_idx': key_lat, 'lng_idx': key_lng, 'count': 0, 'sum_weight': 0.0}
            cell = grid[key]
        cell['count'] += 1
        cell['sum_weight'] += p['weight']

    cells = []
    for cell in grid.values():
        center_lat = min_lat + (cell['lat_idx'] + 0.5) * cell_deg_lat
        center_lng = min_lng + (cell['lng_idx'] + 0.5) * cell_deg_lng
        cells.append(
            {
                'lat': center_lat,
                'lng': center_lng,
                'count': cell['count'],
                'avg_weight': cell['sum_weight'] / cell['count'] if cell['count'] else 0.0,
            }
        )

    persisted = False
    if persist:
        try:
            upsert_heatmap(
                detection_id=detection_id,
                grid_size_m=grid_size_m,
                bounds_geojson=bounds_geojson,
                cells_json=json.dumps(cells),
            )
            persisted = True
        except Exception:
            persisted = False

    return {'detection_id': detection_id, 'points': points, 'grid': {'grid_size_m': grid_size_m, 'cells': cells}, 'persisted': persisted}


@router.get('/detection/{detection_id}/unique-weeds-heatmap')
async def get_unique_weeds_heatmap(
    detection_id: int,
    iou_threshold: float = Query(0.58, description='IoU threshold for matching (0.0-1.0)'),
    frame_gap: int = Query(13, description='Maximum frame gap for tracking'),
    grid_size_m: float = Query(2.0, description='Grid cell size in meters'),
    debug: bool = Query(False, description='When true, return matched detections and grid details for debugging'),
):
    import math

    def srt_timestamp_to_ms(timestamp_str):
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

    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT frames_json FROM srt_tracks WHERE detection_id = %s', (detection_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                '''
                SELECT id, frame_number, weed_class, confidence,
                       bbox_x, bbox_y, bbox_width, bbox_height,
                       detection_timestamp
                FROM detection_details
                WHERE detection_id = %s
                ORDER BY frame_number, id
                ''',
                (detection_id,),
            )
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
                        'timestamp_tolerance_ms': 0,
                    },
                    'message': 'No SRT data available - cannot generate GPS-based heatmap',
                    'no_gps_data': True,
                }

            unique_weeds = calculate_unique_weeds(detection_id, iou_threshold, frame_gap)
            return {
                'detection_id': detection_id,
                'unique_weed_count': unique_weeds['unique_count'],
                'total_detections': unique_weeds['total_detections'],
                'gps_matched_detections': 0,
                'reduction_percentage': unique_weeds['reduction_percentage'],
                'points': [],
                'grid_size_m': grid_size_m,
                'tracking_params': {
                    'iou_threshold': iou_threshold,
                    'frame_gap': frame_gap,
                    'timestamp_tolerance_ms': 0,
                },
                'message': (
                    f"Found {unique_weeds['unique_count']} unique weeds from {unique_weeds['total_detections']} "
                    'total detections (no GPS data available)'
                ),
                'no_gps_data': True,
            }

        srt_frames = json.loads(row['frames_json'])
        timestamp_to_gps = {}
        for frame_data in srt_frames:
            timestamp_str = frame_data.get('t')
            lat = frame_data.get('lat')
            lon = frame_data.get('lon')
            if timestamp_str and lat is not None and lon is not None:
                timestamp_ms = srt_timestamp_to_ms(timestamp_str)
                if timestamp_ms is not None:
                    timestamp_to_gps[timestamp_ms] = (lat, lon)

        cursor.execute(
            '''
            SELECT id, frame_number, weed_class, confidence,
                   bbox_x, bbox_y, bbox_width, bbox_height,
                   detection_timestamp
            FROM detection_details
            WHERE detection_id = %s
            ORDER BY frame_number, id
            ''',
            (detection_id,),
        )
        detections = cursor.fetchall()

    if not detections:
        return {'detection_id': detection_id, 'unique_weed_count': 0, 'points': [], 'message': 'No detections found'}

    TIMESTAMP_TOLERANCE_MS = 200
    detections_with_gps = []
    matched_count = 0

    for det in detections:
        det_timestamp_ms = srt_timestamp_to_ms(det['detection_timestamp'])
        if det_timestamp_ms is None:
            continue

        best_match = None
        min_diff = float('inf')

        for srt_ms, (lat, lon) in timestamp_to_gps.items():
            diff = abs(srt_ms - det_timestamp_ms)
            if diff <= TIMESTAMP_TOLERANCE_MS and diff < min_diff:
                min_diff = diff
                best_match = (lat, lon)

        if best_match is None:
            sorted_srt_times = sorted(timestamp_to_gps.keys())
            for srt_ms in sorted_srt_times:
                diff = abs(srt_ms - det_timestamp_ms)
                if diff < min_diff:
                    min_diff = diff
                    best_match = timestamp_to_gps[srt_ms]
            if min_diff > 1000:
                best_match = None

        if best_match:
            matched_count += 1
            detections_with_gps.append(
                {
                    'id': det['id'],
                    'frame_num': det['frame_number'],
                    'class': det['weed_class'],
                    'confidence': det['confidence'],
                    'bbox': [det['bbox_x'], det['bbox_y'], det['bbox_width'], det['bbox_height']],
                    'gps': best_match,
                    'timestamp_ms': det_timestamp_ms,
                }
            )

    if not detections_with_gps:
        return {
            'detection_id': detection_id,
            'unique_weed_count': 0,
            'points': [],
            'message': f'No GPS matches found. Matched {matched_count}/{len(detections)} detections.',
        }

    def calculate_iou(box1, box2):
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

    def calculate_gps_distance(lat1, lon1, lat2, lon2):
        if None in [lat1, lon1, lat2, lon2]:
            return None
        from math import asin, cos, radians, sin, sqrt

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        return c * 6371000

    detections_with_gps_sorted = sorted(detections_with_gps, key=lambda x: x['frame_num'])

    tracks = []
    TEMPORAL_FRAME_GAP = frame_gap
    GPS_CLUSTER_THRESHOLD_M = 0.42
    MIN_MATCH_SCORE = 0.47

    for det in detections_with_gps_sorted:
        frame_num = det['frame_num']
        weed_class = det['class']
        confidence = det['confidence']
        box = det['bbox']
        gps_lat, gps_lon = det['gps']

        matched_track = None
        best_score = 0.0

        for track in tracks:
            if track['weed_class'] != weed_class:
                continue
            frame_diff = frame_num - track['last_frame']
            if frame_diff > TEMPORAL_FRAME_GAP or frame_diff < 0:
                continue

            iou = calculate_iou(box, track['last_bbox'])
            gps_dist = calculate_gps_distance(gps_lat, gps_lon, track['last_gps'][0], track['last_gps'][1])

            score = 0.0
            if iou >= iou_threshold:
                if gps_dist is not None and gps_dist <= GPS_CLUSTER_THRESHOLD_M:
                    score = iou * 1.7
                elif gps_dist is not None and gps_dist <= GPS_CLUSTER_THRESHOLD_M * 2.1:
                    score = iou * 1.25
                elif gps_dist is not None and gps_dist > GPS_CLUSTER_THRESHOLD_M * 2.6:
                    score = iou * 0.3
                else:
                    if iou >= 0.75:
                        score = iou * 1.5
                    elif iou >= 0.65:
                        score = iou * 1.3
                    else:
                        score = iou * 1.15
            elif gps_dist is not None and gps_dist <= GPS_CLUSTER_THRESHOLD_M * 0.55:
                score = 0.42

            if score > best_score:
                best_score = score
                matched_track = track

        if matched_track is not None and best_score >= MIN_MATCH_SCORE:
            matched_track['detections'].append(det)
            matched_track['detection_ids'].append(det['id'])
            matched_track['frames'].append(frame_num)
            matched_track['gps_coords'].append((gps_lat, gps_lon))
            matched_track['count'] += 1
            matched_track['last_frame'] = frame_num
            matched_track['last_bbox'] = box
            matched_track['last_gps'] = (gps_lat, gps_lon)
            matched_track['avg_confidence'] = (
                matched_track['avg_confidence'] * (matched_track['count'] - 1) + confidence
            ) / matched_track['count']
        else:
            tracks.append(
                {
                    'weed_class': weed_class,
                    'detections': [det],
                    'detection_ids': [det['id']],
                    'frames': [frame_num],
                    'gps_coords': [(gps_lat, gps_lon)],
                    'avg_confidence': confidence,
                    'count': 1,
                    'first_frame': frame_num,
                    'last_frame': frame_num,
                    'last_bbox': box,
                    'last_gps': (gps_lat, gps_lon),
                }
            )

    if not tracks or not any(t['gps_coords'] for t in tracks):
        return {
            'detection_id': detection_id,
            'unique_weed_count': len(tracks),
            'points': [],
            'message': 'No GPS data available for heatmap',
        }

    all_gps = []
    for track in tracks:
        if track['gps_coords']:
            all_gps.extend(track['gps_coords'])

    if not all_gps:
        return {
            'detection_id': detection_id,
            'unique_weed_count': len(tracks),
            'points': [],
            'message': 'No GPS coordinates found',
        }

    mean_lat = sum(lat for lat, lon in all_gps) / len(all_gps)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(math.radians(mean_lat))
    cell_deg_lat = grid_size_m / meters_per_deg_lat
    cell_deg_lng = grid_size_m / meters_per_deg_lng if meters_per_deg_lng > 0 else grid_size_m

    min_lat = min(lat for lat, lon in all_gps)
    min_lng = min(lon for lat, lon in all_gps)

    grid = {}
    for track in tracks:
        if not track['gps_coords']:
            continue

        avg_lat = sum(lat for lat, lon in track['gps_coords']) / len(track['gps_coords'])
        avg_lon = sum(lon for lat, lon in track['gps_coords']) / len(track['gps_coords'])

        key_lat = int(math.floor((avg_lat - min_lat) / cell_deg_lat))
        key_lng = int(math.floor((avg_lon - min_lng) / cell_deg_lng))
        key = f'{key_lat}:{key_lng}'

        if key not in grid:
            grid[key] = {
                'lat_idx': key_lat,
                'lng_idx': key_lng,
                'unique_count': 0,
                'by_class': {},
                'sum_lat': 0.0,
                'sum_lng': 0.0,
                'count_points': 0,
            }

        grid[key]['unique_count'] += 1
        grid[key]['sum_lat'] += avg_lat
        grid[key]['sum_lng'] += avg_lon
        grid[key]['count_points'] += 1

        weed_class = track['weed_class']
        if weed_class not in grid[key]['by_class']:
            grid[key]['by_class'][weed_class] = 0
        grid[key]['by_class'][weed_class] += 1

    points = []
    for cell in grid.values():
        if cell.get('count_points') and cell['count_points'] > 0:
            center_lat = cell['sum_lat'] / cell['count_points']
            center_lng = cell['sum_lng'] / cell['count_points']
        else:
            center_lat = min_lat + (cell['lat_idx'] + 0.5) * cell_deg_lat
            center_lng = min_lng + (cell['lng_idx'] + 0.5) * cell_deg_lng

        points.append(
            {
                'lat': center_lat,
                'lng': center_lng,
                'weight': cell['unique_count'],
                'unique_count': cell['unique_count'],
                'by_class': cell['by_class'],
            }
        )

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
            'timestamp_tolerance_ms': TIMESTAMP_TOLERANCE_MS,
        },
        'message': (
            f'Found {len(tracks)} unique weeds from {len(detections_with_gps)} GPS-matched detections '
            f'(matched {matched_count}/{len(detections)} total detections by timestamp)'
        ),
        'debug': ({'matched_detections': detections_with_gps, 'grid': grid} if debug else None),
    }


@router.get('/detection/{detection_id}/export')
async def export_report(detection_id: int, format: str = Query('json', description='Export format: json, csv, or pdf')):
    import csv
    import datetime as dt

    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail='Detection session not found')

    detection = session['detection']
    detection_details = session['detection_details']
    srt_track = session.get('srt_track')

    det_id = detection['id']
    filename = detection['filename']
    timestamp = detection['timestamp']
    file_type = detection['file_type']
    summary = detection.get('summary')
    total_frames = detection.get('total_frames', 0)
    processing_time = detection.get('processing_time', 0.0)
    has_srt_data = detection.get('has_srt_data', False)
    cloud_secure_url = detection.get('cloud_secure_url')
    cloud_annotated_url = detection.get('cloud_annotated_url')

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

    avg_confidence = (total_confidence / len(detection_details)) if detection_details else 0
    for weed_class in weed_classes:
        weed_classes[weed_class]['avg_confidence'] = (
            weed_classes[weed_class]['total_confidence'] / weed_classes[weed_class]['count']
        )

    if format.lower() == 'json':
        report = {
            'report_generated': dt.datetime.now().isoformat(),
            'detection_session': {
                'id': det_id,
                'filename': filename,
                'timestamp': timestamp,
                'file_type': file_type,
                'summary': summary,
                'total_frames': total_frames,
                'total_detections': detection.get('total_detections', 0),
                'processing_time': processing_time,
                'has_gps_data': bool(has_srt_data),
                'cloud_url': cloud_secure_url,
                'annotated_url': cloud_annotated_url,
            },
            'statistics': {
                'total_weeds_detected': len(detection_details),
                'average_confidence': round(avg_confidence, 2),
                'weed_classes': {
                    weed_class: {
                        'count': data['count'],
                        'percentage': round((data['count'] / len(detection_details)) * 100, 2),
                        'avg_confidence': round(data['avg_confidence'], 2),
                    }
                    for weed_class, data in weed_classes.items()
                },
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
                        'height': d['bbox_height'],
                    },
                    'timestamp': d.get('detection_timestamp'),
                }
                for d in detection_details
            ],
        }

        if srt_track:
            frames_json = json.loads(srt_track['frames_json'])
            report['gps_data'] = {
                'point_count': srt_track['point_count'],
                'start_time': srt_track.get('start_time'),
                'end_time': srt_track.get('end_time'),
                'frames': frames_json,
            }

        return JSONResponse(content=report)

    if format.lower() == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Weed Detection Report'])
        writer.writerow(['Generated', dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(['Session ID', det_id])
        writer.writerow(['Filename', filename])
        writer.writerow(['Timestamp', timestamp])
        writer.writerow(['Total Detections', len(detection_details)])
        writer.writerow(['Average Confidence', f'{avg_confidence * 100:.2f}%'])
        writer.writerow([])
        writer.writerow(['Weed Class Summary'])
        writer.writerow(['Class', 'Count', 'Percentage', 'Avg Confidence'])
        for weed_class, data in weed_classes.items():
            writer.writerow(
                [
                    weed_class,
                    data['count'],
                    f"{(data['count'] / len(detection_details)) * 100:.2f}%",
                    f"{data['avg_confidence'] * 100:.2f}%",
                ]
            )
        writer.writerow([])
        writer.writerow(['Detailed Detections'])
        writer.writerow(['ID', 'Frame', 'Weed Class', 'Confidence', 'BBox X', 'BBox Y', 'Width', 'Height'])
        for d in detection_details:
            writer.writerow(
                [
                    d['id'],
                    d['frame_number'],
                    d['weed_class'],
                    f"{d['confidence']:.2f}",
                    d['bbox_x'],
                    d['bbox_y'],
                    d['bbox_width'],
                    d['bbox_height'],
                ]
            )

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename=detection_report_{det_id}.csv'},
        )

    if format.lower() == 'pdf':
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=30,
                alignment=TA_CENTER,
            )
            story.append(Paragraph('Weed Detection Report', title_style))
            story.append(Spacer(1, 0.2 * inch))

            session_data = [
                ['Session ID:', str(det_id)],
                ['Filename:', filename],
                ['Date:', timestamp],
                ['File Type:', file_type],
                ['Total Frames:', str(total_frames)],
                ['Total Detections:', str(len(detection_details))],
                ['Processing Time:', f'{processing_time:.2f}s'],
                ['Average Confidence:', f'{avg_confidence * 100:.2f}%'],
                ['GPS Data:', 'Yes' if has_srt_data else 'No'],
            ]

            session_table = Table(session_data, colWidths=[2 * inch, 4 * inch])
            session_table.setStyle(
                TableStyle(
                    [
                        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                    ]
                )
            )
            story.append(session_table)
            story.append(Spacer(1, 0.3 * inch))

            if has_srt_data:
                try:
                    heatmap_response = await get_unique_weeds_heatmap(detection_id, 0.6, 2, 0.3, False)
                    points = heatmap_response.get('points', [])

                    if points:
                        import os
                        import platform
                        import tempfile
                        import time
                        from io import BytesIO

                        import folium
                        from folium.plugins import HeatMap

                        avg_lat = sum(p['lat'] for p in points) / len(points)
                        avg_lng = sum(p['lng'] for p in points) / len(points)

                        m = folium.Map(location=[avg_lat, avg_lng], zoom_start=17, max_zoom=20)
                        folium.TileLayer(
                            tiles='https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                            attr='Map data Google',
                            name='Google Satellite',
                            max_zoom=20,
                            subdomains=['mt0', 'mt1', 'mt2', 'mt3'],
                        ).add_to(m)

                        try:
                            polyline_response = await get_gmap_polyline(detection_id)
                            polyline_points = polyline_response.get('points', [])
                            if polyline_points:
                                folium.PolyLine(
                                    locations=[[p['lat'], p['lng']] for p in polyline_points],
                                    color='#2563eb',
                                    weight=3,
                                    opacity=0.8,
                                ).add_to(m)

                                start_point = polyline_points[0]
                                folium.Marker(
                                    location=[start_point['lat'], start_point['lng']],
                                    icon=folium.DivIcon(
                                        html='<div style="background-color: #22c55e; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white;"></div>',
                                        icon_size=(14, 14),
                                        icon_anchor=(7, 7),
                                    ),
                                    popup='Flight Start',
                                ).add_to(m)

                                end_point = polyline_points[-1]
                                folium.Marker(
                                    location=[end_point['lat'], end_point['lng']],
                                    icon=folium.DivIcon(
                                        html='<div style="background-color: #ef4444; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white;"></div>',
                                        icon_size=(14, 14),
                                        icon_anchor=(7, 7),
                                    ),
                                    popup='Flight End',
                                ).add_to(m)
                        except Exception:
                            pass

                        heat_data = [[p['lat'], p['lng'], p['weight']] for p in points]
                        HeatMap(
                            heat_data,
                            radius=6,
                            blur=6,
                            max_zoom=18,
                            max=4,
                            gradient={0.0: 'green', 0.3: 'lime', 0.5: 'yellow', 0.7: 'orange', 1.0: 'red'},
                        ).add_to(m)

                        if len(points) > 1:
                            m.fit_bounds(
                                [
                                    [min(p['lat'] for p in points), min(p['lng'] for p in points)],
                                    [max(p['lat'] for p in points), max(p['lng'] for p in points)],
                                ]
                            )

                        html_file = None
                        try:
                            with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
                                html_file = f.name
                                m.save(html_file)

                            try:
                                from selenium import webdriver
                                from selenium.webdriver.chrome.options import Options
                                from selenium.webdriver.chrome.service import Service

                                chrome_options = Options()
                                chrome_options.add_argument('--headless=new')
                                chrome_options.add_argument('--no-sandbox')
                                chrome_options.add_argument('--disable-dev-shm-usage')
                                chrome_options.add_argument('--disable-gpu')
                                chrome_options.add_argument('--window-size=1200,800')
                                chrome_options.add_argument('--hide-scrollbars')

                                service = None
                                driver = None
                                try:
                                    from webdriver_manager.chrome import ChromeDriverManager

                                    service = Service(ChromeDriverManager().install())
                                    driver = webdriver.Chrome(service=service, options=chrome_options)
                                except Exception:
                                    driver = webdriver.Chrome(options=chrome_options)

                                driver.set_page_load_timeout(15)
                                file_url = (
                                    f"file:///{html_file.replace(os.sep, '/')}"
                                    if platform.system() == 'Windows'
                                    else f'file://{html_file}'
                                )
                                driver.get(file_url)
                                time.sleep(3)
                                screenshot = driver.get_screenshot_as_png()
                                driver.quit()
                                img_buffer = BytesIO(screenshot)
                            except Exception:
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

                            story.append(Paragraph('GPS Heatmap', styles['Heading2']))
                            story.append(Spacer(1, 0.1 * inch))
                            heatmap_img = Image(img_buffer, width=6 * inch, height=4 * inch)
                            story.append(heatmap_img)
                            story.append(Spacer(1, 0.2 * inch))
                        finally:
                            if html_file and os.path.exists(html_file):
                                os.unlink(html_file)
                except Exception:
                    pass

            story.append(Paragraph('Weed Species Summary', styles['Heading2']))
            story.append(Spacer(1, 0.1 * inch))

            class_data = [['Weed Class', 'Count', 'Percentage', 'Avg Confidence']]
            for weed_class, data in weed_classes.items():
                class_data.append(
                    [
                        weed_class,
                        str(data['count']),
                        f"{(data['count'] / len(detection_details)) * 100:.1f}%",
                        f"{data['avg_confidence'] * 100:.1f}%",
                    ]
                )

            class_table = Table(class_data, colWidths=[2 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
            class_table.setStyle(
                TableStyle(
                    [
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 11),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ]
                )
            )
            story.append(class_table)
            story.append(Spacer(1, 0.3 * inch))

            story.append(Paragraph(f'Detection Details (showing first 50 of {len(detection_details)})', styles['Heading2']))
            story.append(Spacer(1, 0.1 * inch))

            detail_data = [['Frame', 'Weed Class', 'Confidence', 'BBox (x, y, w, h)']]
            for d in detection_details[:50]:
                detail_data.append(
                    [
                        str(d['frame_number']),
                        d['weed_class'],
                        f"{d['confidence'] * 100:.1f}%",
                        f"({d['bbox_x']:.0f}, {d['bbox_y']:.0f}, {d['bbox_width']:.0f}, {d['bbox_height']:.0f})",
                    ]
                )

            detail_table = Table(detail_data, colWidths=[1 * inch, 2 * inch, 1.5 * inch, 2 * inch])
            detail_table.setStyle(
                TableStyle(
                    [
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2ecc71')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                    ]
                )
            )
            story.append(detail_table)

            doc.build(story)
            buffer.seek(0)

            return StreamingResponse(
                buffer,
                media_type='application/pdf',
                headers={'Content-Disposition': f'attachment; filename=detection_report_{det_id}.pdf'},
            )
        except ImportError:
            raise HTTPException(
                status_code=501,
                detail="PDF export requires 'reportlab' package. Install with: pip install reportlab",
            )

    raise HTTPException(status_code=400, detail="Invalid format. Use 'json', 'csv', or 'pdf'")

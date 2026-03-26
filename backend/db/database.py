import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor, execute_batch
import json
import os
from datetime import datetime
from contextlib import contextmanager
from ..config.settings import DATABASE_URL, DB_POOL_MIN_CONN, DB_POOL_MAX_CONN

# PostgreSQL connection pool
connection_pool = None

def init_connection_pool():
    '''Initialize PostgreSQL connection pool.'''
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2.pool.SimpleConnectionPool(
                DB_POOL_MIN_CONN,
                DB_POOL_MAX_CONN,
                DATABASE_URL
            )
            print(f"PostgreSQL connection pool created ({DB_POOL_MIN_CONN}-{DB_POOL_MAX_CONN} connections)")
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            raise

@contextmanager
def get_db_connection():
    '''Context manager for database connections from pool.'''
    if connection_pool is None:
        init_connection_pool()
    
    conn = connection_pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        connection_pool.putconn(conn)

def close_connection_pool():
    '''Close all connections in the pool.'''
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        connection_pool = None
        print("PostgreSQL connection pool closed")

def init_db():
    '''Initialize the database and create tables if they don't exist.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detections (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                file_type TEXT NOT NULL,
                summary TEXT,
                total_frames INTEGER DEFAULT 0,
                total_detections INTEGER DEFAULT 0,
                processing_time REAL DEFAULT 0.0,
                input_size_bytes INTEGER,
                result_size_bytes INTEGER,
                has_srt_data BOOLEAN DEFAULT FALSE,
                cloud_public_id TEXT,
                cloud_resource_type TEXT,
                cloud_secure_url TEXT,
                cloud_annotated_url TEXT,
                weed_class_counts TEXT,
                has_gps_data BOOLEAN DEFAULT FALSE,
                bounds_min_lat REAL,
                bounds_max_lat REAL,
                bounds_min_lng REAL,
                bounds_max_lng REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS srt_tracks (
                detection_id INTEGER PRIMARY KEY,
                point_count INTEGER NOT NULL,
                start_time TEXT,
                end_time TEXT,
                bounds_geojson TEXT,
                path_geojson TEXT NOT NULL,
                frames_json TEXT NOT NULL,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS heatmaps (
                detection_id INTEGER PRIMARY KEY,
                grid_size_m REAL NOT NULL,
                bounds_geojson TEXT,
                cells_json TEXT NOT NULL,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS detection_details (
                id SERIAL PRIMARY KEY,
                detection_id INTEGER NOT NULL,
                frame_number INTEGER NOT NULL,
                weed_class TEXT NOT NULL,
                confidence REAL NOT NULL,
                bbox_x REAL NOT NULL,
                bbox_y REAL NOT NULL,
                bbox_width REAL NOT NULL,
                bbox_height REAL NOT NULL,
                normalized_bbox_x REAL,
                normalized_bbox_y REAL,
                normalized_bbox_width REAL,
                normalized_bbox_height REAL,
                detection_timestamp TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id SERIAL PRIMARY KEY,
                job_id TEXT UNIQUE NOT NULL,
                detection_id INTEGER,
                status TEXT NOT NULL,
                progress TEXT,
                error_message TEXT,
                original_filename TEXT,
                is_video BOOLEAN DEFAULT FALSE,
                is_image BOOLEAN DEFAULT FALSE,
                has_srt BOOLEAN DEFAULT FALSE,
                result_json TEXT,
                temp_video_path TEXT,
                needs_client_compression BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_has_srt ON detections(has_srt_data)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_file_type ON detections(file_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_session ON detection_details(detection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_class ON detection_details(weed_class)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_gps ON detection_details(detection_id, latitude, longitude)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_frame ON detection_details(detection_id, frame_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_detection ON processing_jobs(detection_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status)")
        
        conn.commit()
        print("PostgreSQL database initialized successfully")

def reset_compact_tables():
    '''Drop and recreate compact SRT/heatmap tables to reset data.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS srt_tracks CASCADE")
        cursor.execute("DROP TABLE IF EXISTS heatmaps CASCADE")
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS srt_tracks (
                detection_id INTEGER PRIMARY KEY,
                point_count INTEGER NOT NULL,
                start_time TEXT,
                end_time TEXT,
                bounds_geojson TEXT,
                path_geojson TEXT NOT NULL,
                frames_json TEXT NOT NULL,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS heatmaps (
                detection_id INTEGER PRIMARY KEY,
                grid_size_m REAL NOT NULL,
                bounds_geojson TEXT,
                cells_json TEXT NOT NULL,
                FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()

def drop_all_tables():
    '''Drop all tables in the database.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS processing_jobs CASCADE")
        cursor.execute("DROP TABLE IF EXISTS detection_details CASCADE")
        cursor.execute("DROP TABLE IF EXISTS heatmaps CASCADE")
        cursor.execute("DROP TABLE IF EXISTS srt_tracks CASCADE")
        cursor.execute("DROP TABLE IF EXISTS detections CASCADE")
        conn.commit()
        print("All tables dropped successfully")

def insert_detection(filename, file_type, summary="", processing_time=0.0, 
                    input_size_bytes=0, result_size_bytes=0,
                    cloud_public_id=None, cloud_resource_type=None, 
                    cloud_secure_url=None, cloud_annotated_url=None,
                    timestamp=None, total_frames=0, total_detections=0, has_srt_data=False):
    '''Insert a new detection record and return its ID.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO detections (
                filename, timestamp, file_type, summary, processing_time,
                input_size_bytes, result_size_bytes,
                cloud_public_id, cloud_resource_type, cloud_secure_url, cloud_annotated_url,
                total_frames, total_detections, has_srt_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (filename, timestamp, file_type, summary, processing_time,
              input_size_bytes, result_size_bytes,
              cloud_public_id, cloud_resource_type, cloud_secure_url, cloud_annotated_url,
              total_frames, total_detections, has_srt_data))
        
        detection_id = cursor.fetchone()[0]
        conn.commit()
        return detection_id

def update_detection(detection_id, **kwargs):
    '''Update detection record with given fields.'''
    if not kwargs:
        return
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        set_clause = ", ".join([f"{key} = %s" for key in kwargs.keys()])
        values = list(kwargs.values()) + [detection_id]
        
        query = f"UPDATE detections SET {set_clause} WHERE id = %s"
        cursor.execute(query, values)
        conn.commit()

def get_detection(detection_id):
    '''Retrieve a single detection by ID.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM detections WHERE id = %s", (detection_id,))
        return dict(cursor.fetchone()) if cursor.rowcount > 0 else None

def get_all_detections():
    '''Retrieve all detections ordered by timestamp (newest first).'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM detections ORDER BY timestamp DESC")
        return [dict(row) for row in cursor.fetchall()]

def delete_detection(detection_id):
    '''Delete a detection and its related data (cascades automatically).'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM detections WHERE id = %s", (detection_id,))
        conn.commit()

def insert_detection_details_batch(detection_id, detections_list):
    '''Bulk insert detection details for a session.'''
    if not detections_list:
        return
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        values = []
        for d in detections_list:
            # Handle both old format (nested bbox/gps) and new format (flattened)
            if 'bbox' in d and isinstance(d['bbox'], dict):
                # Old format with nested dict
                bbox_x = d['bbox']['x']
                bbox_y = d['bbox']['y']
                bbox_width = d['bbox']['width']
                bbox_height = d['bbox']['height']
                weed_class = d['class']
            else:
                # New format with flattened fields
                bbox_x = d.get('bbox_x', 0)
                bbox_y = d.get('bbox_y', 0)
                bbox_width = d.get('bbox_width', 0)
                bbox_height = d.get('bbox_height', 0)
                weed_class = d.get('weed_class', 'unknown')
            
            values.append((
                detection_id,
                d.get('frame_number', 0),
                weed_class,
                d.get('confidence', 0.0),
                bbox_x,
                bbox_y,
                bbox_width,
                bbox_height,
                d.get('normalized_bbox', {}).get('x') if isinstance(d.get('normalized_bbox'), dict) else None,
                d.get('normalized_bbox', {}).get('y') if isinstance(d.get('normalized_bbox'), dict) else None,
                d.get('normalized_bbox', {}).get('width') if isinstance(d.get('normalized_bbox'), dict) else None,
                d.get('normalized_bbox', {}).get('height') if isinstance(d.get('normalized_bbox'), dict) else None,
                d.get('detection_timestamp') or d.get('timestamp'),
                d.get('gps', {}).get('latitude') if isinstance(d.get('gps'), dict) else d.get('latitude'),
                d.get('gps', {}).get('longitude') if isinstance(d.get('gps'), dict) else d.get('longitude'),
                d.get('gps', {}).get('altitude') if isinstance(d.get('gps'), dict) else d.get('altitude')
            ))
        
        execute_batch(cursor, '''
            INSERT INTO detection_details (
                detection_id, frame_number, weed_class, confidence,
                bbox_x, bbox_y, bbox_width, bbox_height,
                normalized_bbox_x, normalized_bbox_y, normalized_bbox_width, normalized_bbox_height,
                detection_timestamp, latitude, longitude, altitude
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', values)
        
        conn.commit()

# Alias for backward compatibility
batch_insert_detection_details = insert_detection_details_batch

def get_detection_details(detection_id):
    '''Retrieve all detection details for a session.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM detection_details 
            WHERE detection_id = %s 
            ORDER BY frame_number, id
        ''', (detection_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_detection_details_with_gps(detection_id):
    '''Retrieve detection details that have GPS coordinates.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM detection_details 
            WHERE detection_id = %s 
            AND latitude IS NOT NULL 
            AND longitude IS NOT NULL
            ORDER BY frame_number
        ''', (detection_id,))
        return [dict(row) for row in cursor.fetchall()]

def count_detections_by_class(detection_id):
    '''Count detections grouped by weed class.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT weed_class, COUNT(*) as count 
            FROM detection_details 
            WHERE detection_id = %s 
            GROUP BY weed_class
        ''', (detection_id,))
        return {row[0]: row[1] for row in cursor.fetchall()}

def insert_srt_track(detection_id, point_count, start_time, end_time, 
                    bounds_geojson, path_geojson, frames_json):
    '''Insert aggregated SRT track data for a session.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO srt_tracks (
                detection_id, point_count, start_time, end_time,
                bounds_geojson, path_geojson, frames_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (detection_id) DO UPDATE SET
                point_count = EXCLUDED.point_count,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                bounds_geojson = EXCLUDED.bounds_geojson,
                path_geojson = EXCLUDED.path_geojson,
                frames_json = EXCLUDED.frames_json
        ''', (detection_id, point_count, start_time, end_time,
              bounds_geojson, path_geojson, frames_json))
        conn.commit()

def get_srt_track(detection_id):
    '''Retrieve SRT track data for a session.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM srt_tracks WHERE detection_id = %s
        ''', (detection_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def insert_heatmap(detection_id, grid_size_m, bounds_geojson, cells_json):
    '''Insert aggregated heatmap data for a session.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO heatmaps (
                detection_id, grid_size_m, bounds_geojson, cells_json
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (detection_id) DO UPDATE SET
                grid_size_m = EXCLUDED.grid_size_m,
                bounds_geojson = EXCLUDED.bounds_geojson,
                cells_json = EXCLUDED.cells_json
        ''', (detection_id, grid_size_m, bounds_geojson, cells_json))
        conn.commit()

def get_heatmap(detection_id):
    '''Retrieve heatmap data for a session.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM heatmaps WHERE detection_id = %s
        ''', (detection_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def get_jobs_by_detection(detection_id):
    '''Get all jobs for a detection.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM processing_jobs 
            WHERE detection_id = %s 
            ORDER BY created_at DESC
        ''', (detection_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_pending_jobs():
    '''Get all pending processing jobs.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM processing_jobs 
            WHERE status = 'pending' 
            ORDER BY created_at ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]

def get_unique_weed_classes():
    '''Get all unique weed classes from detection_details.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT weed_class 
            FROM detection_details 
            ORDER BY weed_class
        ''')
        return [row[0] for row in cursor.fetchall()]

# Alias functions for backward compatibility with main.py
def insert_detection_details(detection_id, detection_data):
    '''Insert a single detection detail (backward compatibility wrapper).'''
    return insert_detection_details_batch(detection_id, [detection_data])

def fetch_detection_session(detection_id):
    '''Fetch complete detection session with all details, srt_track, and detection_details.
    Returns same format as SQLite version for frontend compatibility.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get main detection info
        cursor.execute("SELECT * FROM detections WHERE id = %s", (detection_id,))
        detection = cursor.fetchone()
        
        if not detection:
            return None
        
        # Get compact SRT track (if available)
        cursor.execute("""
            SELECT detection_id, point_count, start_time, end_time, 
                   bounds_geojson, path_geojson, frames_json 
            FROM srt_tracks WHERE detection_id = %s
        """, (detection_id,))
        srt_track = cursor.fetchone()
        
        # Get detection details
        cursor.execute("""
            SELECT * FROM detection_details 
            WHERE detection_id = %s 
            ORDER BY frame_number, id
        """, (detection_id,))
        detection_details = cursor.fetchall()
        
        return {
            'detection': dict(detection),
            'srt_track': dict(srt_track) if srt_track else None,
            'detection_details': [dict(row) for row in detection_details],
            'frame_metadata': []  # Deprecated: kept for backward compatibility
        }

def fetch_all_detections():
    '''Fetch all detections (alias for get_all_detections).'''
    return get_all_detections()

def get_detection_statistics():
    '''Get overall detection statistics.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT 
                COUNT(*) as total_sessions,
                SUM(total_detections) as total_detections,
                SUM(total_frames) as total_frames_processed,
                COUNT(DISTINCT CASE WHEN has_srt_data THEN id END) as sessions_with_gps
            FROM detections
        ''')
        return dict(cursor.fetchone())

def upsert_srt_track(detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json):
    '''Upsert SRT track (alias for insert_srt_track).'''
    return insert_srt_track(detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json)

def update_srt_status(detection_id, has_srt_data):
    '''Update SRT status for a detection.'''
    update_detection(detection_id, has_srt_data=has_srt_data)

def fetch_detections_by_class(weed_class):
    '''Fetch all detections that contain a specific weed class.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT DISTINCT d.* 
            FROM detections d
            INNER JOIN detection_details dd ON d.id = dd.detection_id
            WHERE dd.weed_class = %s
            ORDER BY d.timestamp DESC
        ''', (weed_class,))
        return [dict(row) for row in cursor.fetchall()]

def upsert_heatmap(detection_id, grid_size_m, bounds_geojson, cells_json):
    '''Upsert heatmap (alias for insert_heatmap).'''
    return insert_heatmap(detection_id, grid_size_m, bounds_geojson, cells_json)

def calculate_unique_weeds(detection_id, iou_threshold=0.58, frame_gap=13):
    """Calculate unique weed count by tracking weeds across frames using a simple online tracker.

    This function iterates detections in temporal order and attempts to match each detection
    to existing tracks using IoU and GPS proximity. If no match is found within the allowed
    frame_gap, a new track is started.

    CALIBRATED DEFAULTS FOR 10 FPS VIDEO:
    - iou_threshold: 0.58 - 58% overlap required (carefully tuned)
    - frame_gap: 13 frames - at 10 FPS, 13 frames = 1.3 seconds
      Precise window calibrated for 40-60 unique weeds from 284 detections

    Args:
        detection_id: The detection session ID
        iou_threshold: IoU threshold for considering same weed (0.0-1.0)
        frame_gap: Maximum frame gap to consider for tracking (frames)
                   At 10 FPS: 10 frames = 1 second, 20 frames = 2 seconds

    Returns:
        dict with unique_count, total_detections, tracks, and breakdown by class
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, frame_number, weed_class, confidence,
                   bbox_x, bbox_y, bbox_width, bbox_height,
                   latitude, longitude
            FROM detection_details
            WHERE detection_id = %s
            ORDER BY frame_number, id
        """, (detection_id,))
        
        rows = cursor.fetchall()
    
    if not rows:
        return {'unique_count': 0, 'total_detections': 0, 'tracks': [], 'by_class': {}, 'reduction_percentage': 0}

    # Helper: IoU
    def calculate_iou(box1, box2):
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2
        x_left = max(x1, x2)
        y_top = max(y1, y2)
        x_right = min(x1 + w1, x2 + w2)
        y_bottom = min(y1 + h1, y2 + h2)
        if x_right <= x_left or y_bottom <= y_top:
            return 0.0
        inter = (x_right - x_left) * (y_bottom - y_top)
        union = w1 * h1 + w2 * h2 - inter
        return inter / union if union > 0 else 0.0

    # Helper: GPS haversine distance (meters)
    def calculate_gps_distance(lat1, lon1, lat2, lon2):
        if None in (lat1, lon1, lat2, lon2):
            return None
        from math import radians, sin, cos, asin, sqrt
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return 6371000 * c

    # Build detection list
    detections = []
    for r in rows:
        detections.append({
            'id': r['id'],
            'frame': r['frame_number'],
            'class': r['weed_class'],
            'confidence': r['confidence'],
            'bbox': (r['bbox_x'], r['bbox_y'], r['bbox_width'], r['bbox_height']),
            'lat': r['latitude'],
            'lon': r['longitude']
        })

    # Online tracker: tracks is a list of dicts with last seen bbox/frame and history
    tracks = []
    GPS_MATCH_THRESHOLD_M = 0.42  # Calibrated 0.42m - precise middle ground
    MIN_MATCH_SCORE = 0.47  # Calibrated threshold - carefully balanced
    
    has_gps = any(det['lat'] is not None for det in detections)
    print(f"🔍 [UNIQUE WEEDS] Processing {len(detections)} detections, GPS available: {has_gps}")
    print(f"🔍 [UNIQUE WEEDS] Using iou_threshold={iou_threshold}, frame_gap={frame_gap}")
    
    # For non-GPS videos, adjust parameters moderately
    if not has_gps:
        # Lower IoU threshold - accept weaker bbox matches
        iou_threshold = max(0.3, iou_threshold - 0.2)  # Reduce by 0.2 (0.5 -> 0.3)
        # Increase frame gap moderately
        frame_gap = int(frame_gap * 1.8)  # 1.8x the frame gap (15 -> 27 frames)
        MIN_MATCH_SCORE = 0.3  # Lower minimum score threshold
        print(f"🔧 [UNIQUE WEEDS] Adjusted for non-GPS: iou_threshold={iou_threshold}, frame_gap={frame_gap}, min_score={MIN_MATCH_SCORE}")

    for det in detections:
        matched_track = None
        best_score = 0.0

        # Try to match to existing tracks of same class
        for tr in tracks:
            if tr['class'] != det['class']:
                continue

            # Enforce temporal gap
            if det['frame'] - tr['last_frame'] > frame_gap:
                continue

            # Compute IoU between current detection and track's last bbox
            iou = calculate_iou(det['bbox'], tr['last_bbox'])
            
            # For non-GPS videos, also compute pixel distance between bbox centers
            pixel_dist = None
            if not has_gps:
                # Calculate center-to-center distance in pixels
                det_center_x = det['bbox'][0] + det['bbox'][2] / 2
                det_center_y = det['bbox'][1] + det['bbox'][3] / 2
                tr_center_x = tr['last_bbox'][0] + tr['last_bbox'][2] / 2
                tr_center_y = tr['last_bbox'][1] + tr['last_bbox'][3] / 2
                pixel_dist = ((det_center_x - tr_center_x)**2 + (det_center_y - tr_center_y)**2)**0.5

            # Compute GPS distance if available
            gps_dist = None
            if det['lat'] is not None and tr.get('last_lat') is not None:
                gps_dist = calculate_gps_distance(det['lat'], det['lon'], tr['last_lat'], tr['last_lon'])

            # Matching criteria: Precisely calibrated for ~40-60 unique weeds
            score = 0.0
            if iou >= iou_threshold:
                # IoU meets threshold
                if gps_dist is not None and gps_dist <= GPS_MATCH_THRESHOLD_M:
                    # Both IoU and GPS agree - strong match
                    score = iou * 1.7
                elif gps_dist is not None and gps_dist <= GPS_MATCH_THRESHOLD_M * 2.1:
                    # GPS within 2.1x threshold - moderate match
                    score = iou * 1.25
                elif gps_dist is not None and gps_dist > GPS_MATCH_THRESHOLD_M * 2.6:
                    # GPS too far - light penalty
                    score = iou * 0.3
                else:
                    # Moderate GPS distance or no GPS
                    if iou >= 0.75:
                        score = iou * 1.5
                    elif iou >= 0.65:
                        score = iou * 1.3
                    else:
                        score = iou * 1.15
            elif gps_dist is not None and gps_dist <= GPS_MATCH_THRESHOLD_M * 0.55:
                # Very close GPS but IoU below threshold
                score = 0.42
            elif pixel_dist is not None and iou >= iou_threshold * 0.7:
                # No GPS, IoU close to threshold - use pixel proximity
                avg_bbox_size = (det['bbox'][2] + det['bbox'][3]) / 2
                if pixel_dist < avg_bbox_size * 2.3:
                    score = 0.52 / (1.0 + pixel_dist / avg_bbox_size)
                else:
                    score = 0.0

            # Prefer tracks with higher score and above minimum threshold
            if score > best_score and score >= MIN_MATCH_SCORE:
                best_score = score
                matched_track = tr

        if matched_track is not None:
            # Append detection to matched track, update last seen info
            matched_track['detections'].append(det)
            matched_track['detection_ids'].append(det['id'])
            matched_track['last_frame'] = det['frame']
            matched_track['last_bbox'] = det['bbox']
            if det['lat'] is not None:
                matched_track['last_lat'] = det['lat']
                matched_track['last_lon'] = det['lon']
            matched_track['count'] += 1
            matched_track['avg_confidence'] = (matched_track['avg_confidence'] * (matched_track['count'] - 1) + det['confidence']) / matched_track['count']
        else:
            # Start a new track
            new_tr = {
                'class': det['class'],
                'detections': [det],
                'detection_ids': [det['id']],
                'first_frame': det['frame'],
                'last_frame': det['frame'],
                'last_bbox': det['bbox'],
                'last_lat': det['lat'],
                'last_lon': det['lon'],
                'count': 1,
                'avg_confidence': det['confidence']
            }
            tracks.append(new_tr)

    # Summarize
    unique_count = len(tracks)
    by_class = {}
    for tr in tracks:
        by_class[tr['class']] = by_class.get(tr['class'], 0) + 1

    reduction = round((1 - unique_count / len(detections)) * 100, 1) if len(detections) > 0 else 0

    return {
        'unique_count': unique_count,
        'total_detections': len(detections),
        'tracks': tracks,
        'by_class': by_class,
        'reduction_percentage': reduction
    }

# Job queue management functions (matching SQLite interface)
def create_processing_job(job_id, original_filename, is_video=False, is_image=False, has_srt=False):
    '''Create a new processing job in the database.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO processing_jobs 
            (job_id, status, progress, original_filename, is_video, is_image, has_srt)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (job_id, 'queued', 'Uploaded, starting processing...', original_filename, is_video, is_image, has_srt))
        conn.commit()

def update_job_status(job_id, status, progress=None, error_message=None):
    '''Update job status and progress.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        updates = ['status = %s', 'updated_at = CURRENT_TIMESTAMP']
        values = [status]
        
        if progress is not None:
            updates.append('progress = %s')
            values.append(progress)
        
        if error_message is not None:
            updates.append('error_message = %s')
            values.append(error_message)
        
        if status in ['completed', 'failed']:
            updates.append('completed_at = CURRENT_TIMESTAMP')
        
        values.append(job_id)
        
        query = f"UPDATE processing_jobs SET {', '.join(updates)} WHERE job_id = %s"
        cursor.execute(query, values)
        conn.commit()

def update_job_result(job_id, detection_id, result_json, annotated_url=None, temp_video_path=None, needs_compression=False):
    '''Update job with result data.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE processing_jobs 
            SET detection_id = %s,
                status = %s,
                progress = %s,
                result_json = %s,
                temp_video_path = %s,
                needs_client_compression = %s,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE job_id = %s
        ''', (detection_id, 'completed', 'Processing complete', result_json, temp_video_path, needs_compression, job_id))
        
        # Update detection with annotated URL
        if annotated_url:
            update_detection(detection_id, cloud_annotated_url=annotated_url)
        
        conn.commit()

def get_job_status(job_id):
    '''Get job status by job_id.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM processing_jobs WHERE job_id = %s", (job_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def mark_compression_started(job_id):
    '''Mark compression as started.'''
    return update_job_status(job_id, status='compressing', progress='Compressing video...')

def mark_compression_completed(job_id, annotated_url):
    '''Mark compression as completed.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE processing_jobs 
            SET status = %s, 
                progress = %s,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE job_id = %s
        ''', ('completed', 'Compression complete', job_id))
        conn.commit()

def get_pending_compression_jobs():
    '''Get jobs that need compression.'''
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('''
            SELECT * FROM processing_jobs 
            WHERE status IN ('pending', 'processing', 'queued') 
            ORDER BY created_at ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]

def cleanup_old_jobs(days=7):
    '''Delete old completed jobs.'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM processing_jobs 
            WHERE status IN ('completed', 'failed') 
            AND created_at < (CURRENT_TIMESTAMP - INTERVAL '%s days')
        ''', (days,))
        deleted = cursor.rowcount
        conn.commit()
        return deleted

# Initialize connection pool on module import
init_connection_pool()

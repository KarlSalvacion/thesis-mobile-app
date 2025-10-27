import sqlite3
import json
import os
from datetime import datetime

# Store database in backend folder
DB_NAME = os.path.join(os.path.dirname(__file__), "weed_detection.db")

def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Main detections table (sessions) - OPTIMIZED with summary fields
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            -- OPTIMIZED: Cached summary fields for fast mobile app queries
            weed_class_counts TEXT,
            has_gps_data BOOLEAN DEFAULT FALSE,
            bounds_min_lat REAL,
            bounds_max_lat REAL,
            bounds_min_lng REAL,
            bounds_max_lng REAL
        )
    """)
    
    # REMOVED: frame_metadata table (redundant with srt_tracks)
    # Data stored once in srt_tracks.frames_json instead of twice
    
    # Compact SRT track storage (aggregated per session)
    cursor.execute("""
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
    """)

    # Optional aggregated heatmap storage per session (grid-based)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS heatmaps (
            detection_id INTEGER PRIMARY KEY,
            grid_size_m REAL NOT NULL,
            bounds_geojson TEXT,
            cells_json TEXT NOT NULL,
            FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
        )
    """)
    
    # Individual detection details table - OPTIMIZED with GPS data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detection_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            -- OPTIMIZED: GPS coordinates stored directly for fast heatmap generation
            latitude REAL,
            longitude REAL,
            altitude REAL,
            FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
        )
    """)
    
    # OPTIMIZED: Better indexes for mobile app queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_has_srt ON detections(has_srt_data)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_file_type ON detections(file_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_session ON detection_details(detection_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_class ON detection_details(weed_class)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_gps ON detection_details(detection_id, latitude, longitude)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_frame ON detection_details(detection_id, frame_number)")
    
    conn.commit()

    # Backfill columns for older DBs (SQLite lacks IF NOT EXISTS for columns)
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(detections)").fetchall()]
    
    columns_to_add = [
        ("input_size_bytes", "INTEGER"),
        ("result_size_bytes", "INTEGER"),
        ("has_srt_data", "BOOLEAN DEFAULT FALSE"),
        ("cloud_public_id", "TEXT"),
        ("cloud_resource_type", "TEXT"),
        ("cloud_secure_url", "TEXT"),
        ("cloud_annotated_url", "TEXT"),
        # New optimized columns
        ("weed_class_counts", "TEXT"),
        ("has_gps_data", "BOOLEAN DEFAULT FALSE"),
        ("bounds_min_lat", "REAL"),
        ("bounds_max_lat", "REAL"),
        ("bounds_min_lng", "REAL"),
        ("bounds_max_lng", "REAL"),
    ]
    
    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE detections ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception as e:
                pass  # Column might already exist
    
    # Backfill GPS columns in detection_details
    existing_detail_columns = [row[1] for row in cursor.execute("PRAGMA table_info(detection_details)").fetchall()]
    detail_columns_to_add = [
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("altitude", "REAL"),
    ]
    
    for col_name, col_type in detail_columns_to_add:
        if col_name not in existing_detail_columns:
            try:
                cursor.execute(f"ALTER TABLE detection_details ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                pass
    
    conn.close()

def reset_compact_tables():
    """Drop and recreate compact SRT/heatmap tables to reset data."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Drop if exist
    cursor.execute("DROP TABLE IF EXISTS srt_tracks")
    cursor.execute("DROP TABLE IF EXISTS heatmaps")
    conn.commit()
    # Recreate
    cursor.execute("""
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
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS heatmaps (
            detection_id INTEGER PRIMARY KEY,
            grid_size_m REAL NOT NULL,
            bounds_geojson TEXT,
            cells_json TEXT NOT NULL,
            FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def insert_detection(
    filename,
    timestamp,
    file_type,
    summary,
    total_frames=0,
    total_detections=0,
    processing_time=0.0,
    input_size_bytes=None,
    result_size_bytes=None,
    has_srt_data=False,
    cloud_public_id=None,
    cloud_resource_type=None,
    cloud_secure_url=None,
    cloud_annotated_url=None,
):
    """Insert a new detection session record."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO detections (filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data, cloud_public_id, cloud_resource_type, cloud_secure_url, cloud_annotated_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            filename,
            timestamp,
            file_type,
            summary,
            total_frames,
            total_detections,
            processing_time,
            input_size_bytes,
            result_size_bytes,
            has_srt_data,
            cloud_public_id,
            cloud_resource_type,
            cloud_secure_url,
            cloud_annotated_url,
        ),
    )
    detection_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return detection_id

def insert_detection_details(detection_id, detection_data):
    """Insert individual weed detection details."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO detection_details (
            detection_id, frame_number, weed_class, confidence, 
            bbox_x, bbox_y, bbox_width, bbox_height,
            normalized_bbox_x, normalized_bbox_y, normalized_bbox_width, normalized_bbox_height,
            detection_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        detection_id, detection_data['frame_number'], detection_data['weed_class'],
        detection_data['confidence'], detection_data['bbox_x'], detection_data['bbox_y'],
        detection_data['bbox_width'], detection_data['bbox_height'],
        detection_data.get('normalized_bbox_x'), detection_data.get('normalized_bbox_y'),
        detection_data.get('normalized_bbox_width'), detection_data.get('normalized_bbox_height'),
        detection_data['detection_timestamp']
    ))
    
    conn.commit()
    conn.close()

def batch_insert_detection_details(detection_id: int, detections_list: list, srt_frames: dict = None):
    """Batch insert multiple detection details at once (10x faster than individual inserts).
    
    Args:
        detection_id: The parent detection session ID
        detections_list: List of detection data dictionaries
        srt_frames: Optional dict mapping frame_number -> (lat, lon, alt) for GPS data
    
    Returns:
        Number of rows inserted
    """
    if not detections_list:
        return 0
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Prepare batch data as tuples (with GPS data if available)
    batch_data = []
    for det in detections_list:
        frame_num = det['frame_number']
        lat, lon, alt = None, None, None
        
        # Look up GPS data from SRT if available
        if srt_frames and frame_num in srt_frames:
            lat, lon, alt = srt_frames[frame_num]
        
        batch_data.append((
            detection_id,
            frame_num,
            det['weed_class'],
            det['confidence'],
            det['bbox_x'],
            det['bbox_y'],
            det['bbox_width'],
            det['bbox_height'],
            det.get('normalized_bbox_x'),
            det.get('normalized_bbox_y'),
            det.get('normalized_bbox_width'),
            det.get('normalized_bbox_height'),
            det['detection_timestamp'],
            lat,
            lon,
            alt
        ))
    
    # Use executemany for batch insert (much faster than individual inserts)
    cursor.executemany("""
        INSERT INTO detection_details (
            detection_id, frame_number, weed_class, confidence, 
            bbox_x, bbox_y, bbox_width, bbox_height,
            normalized_bbox_x, normalized_bbox_y, normalized_bbox_width, normalized_bbox_height,
            detection_timestamp, latitude, longitude, altitude
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch_data)
    
    rows_inserted = cursor.rowcount
    conn.commit()
    conn.close()
    
    return rows_inserted


def calculate_unique_weeds(detection_id: int, iou_threshold: float = 0.3, frame_gap: int = 10) -> dict:
    """Calculate unique weed count by tracking weeds across frames using a simple online tracker.

    This function iterates detections in temporal order and attempts to match each detection
    to existing tracks using IoU and GPS proximity. If no match is found within the allowed
    frame_gap, a new track is started.

    Args:
        detection_id: The detection session ID
        iou_threshold: IoU threshold for considering same weed (0.0-1.0)
        frame_gap: Maximum frame gap to consider for tracking (frames)

    Returns:
        dict with unique_count, total_detections, tracks, and breakdown by class
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, frame_number, weed_class, confidence,
               bbox_x, bbox_y, bbox_width, bbox_height,
               latitude, longitude
        FROM detection_details
        WHERE detection_id = ?
        ORDER BY frame_number, id
    """, (detection_id,))

    rows = cursor.fetchall()
    conn.close()

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
        det_id, frame_num, weed_class, confidence, bx, by, bw, bh, lat, lon = r
        detections.append({
            'id': det_id,
            'frame': frame_num,
            'class': weed_class,
            'confidence': confidence,
            'bbox': (bx, by, bw, bh),
            'lat': lat,
            'lon': lon
        })

    # Online tracker: tracks is a list of dicts with last seen bbox/frame and history
    tracks = []
    GPS_MATCH_THRESHOLD_M = 2.0  # meters

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

            # Compute GPS distance if available
            gps_dist = None
            if det['lat'] is not None and tr.get('last_lat') is not None:
                gps_dist = calculate_gps_distance(det['lat'], det['lon'], tr['last_lat'], tr['last_lon'])

            # Matching criteria: IoU OR GPS proximity
            score = 0.0
            if iou >= iou_threshold:
                score = iou
            elif gps_dist is not None and gps_dist <= GPS_MATCH_THRESHOLD_M:
                # Favor small GPS distances (convert to a score between 0.0-1.0)
                score = 1.0 / (1.0 + gps_dist)

            # Prefer tracks with higher score
            if score > best_score:
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


def update_session_summary(detection_id: int):
    """Update cached summary fields in detections table for fast mobile queries.
    
    Call this after inserting detection_details to cache:
    - weed_class_counts (JSON)
    - has_gps_data
    - bounds (min/max lat/lng)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get class counts
    cursor.execute("""
        SELECT weed_class, COUNT(*) 
        FROM detection_details 
        WHERE detection_id = ? 
        GROUP BY weed_class
    """, (detection_id,))
    class_counts = {row[0]: row[1] for row in cursor.fetchall()}
    class_counts_json = json.dumps(class_counts)
    
    # Check if any detections have GPS data
    cursor.execute("""
        SELECT COUNT(*) 
        FROM detection_details 
        WHERE detection_id = ? AND latitude IS NOT NULL
    """, (detection_id,))
    has_gps = cursor.fetchone()[0] > 0
    
    # Get GPS bounds if available
    bounds = {}
    if has_gps:
        cursor.execute("""
            SELECT 
                MIN(latitude), MAX(latitude),
                MIN(longitude), MAX(longitude)
            FROM detection_details 
            WHERE detection_id = ? AND latitude IS NOT NULL
        """, (detection_id,))
        result = cursor.fetchone()
        if result and result[0] is not None:
            bounds = {
                'min_lat': result[0],
                'max_lat': result[1],
                'min_lng': result[2],
                'max_lng': result[3]
            }
    
    # Update detections table
    cursor.execute("""
        UPDATE detections SET
            weed_class_counts = ?,
            has_gps_data = ?,
            bounds_min_lat = ?,
            bounds_max_lat = ?,
            bounds_min_lng = ?,
            bounds_max_lng = ?
        WHERE id = ?
    """, (
        class_counts_json,
        has_gps,
        bounds.get('min_lat'),
        bounds.get('max_lat'),
        bounds.get('min_lng'),
        bounds.get('max_lng'),
        detection_id
    ))
    
    conn.commit()
    conn.close()


def get_sessions_for_mobile():
    """Get all detection sessions optimized for mobile app list view.
    
    Returns session data with cached summaries (no joins needed).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            id, filename, timestamp, file_type, 
            total_frames, total_detections, 
            cloud_secure_url, cloud_annotated_url,
            weed_class_counts, has_gps_data, has_srt_data
        FROM detections 
        ORDER BY timestamp DESC
    """)
    
    sessions = []
    for row in cursor.fetchall():
        session = {
            'id': row[0],
            'filename': row[1],
            'timestamp': row[2],
            'file_type': row[3],
            'total_frames': row[4],
            'total_detections': row[5],
            'cloud_secure_url': row[6],
            'cloud_annotated_url': row[7],
            'weed_class_counts': json.loads(row[8]) if row[8] else {},
            'has_gps_data': bool(row[9]),
            'has_srt_data': bool(row[10])
        }
        sessions.append(session)
    
    conn.close()
    return sessions


def get_detections_for_heatmap(detection_id: int):
    """Get all detections with GPS data for heatmap generation (single query).
    
    Much faster than joining tables - GPS data stored directly in detection_details.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            frame_number, weed_class, confidence,
            latitude, longitude, altitude,
            bbox_x, bbox_y, bbox_width, bbox_height
        FROM detection_details
        WHERE detection_id = ? AND latitude IS NOT NULL
        ORDER BY frame_number
    """, (detection_id,))
    
    detections = []
    for row in cursor.fetchall():
        detections.append({
            'frame_number': row[0],
            'weed_class': row[1],
            'confidence': row[2],
            'latitude': row[3],
            'longitude': row[4],
            'altitude': row[5],
            'bbox': [row[6], row[7], row[8], row[9]]
        })
    
    conn.close()
    return detections


def fetch_detection_session(detection_id):
    """Fetch complete detection session with all details."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Get main detection info
    cursor.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
    detection = cursor.fetchone()
    
    if not detection:
        conn.close()
        return None
    
    # Get compact SRT track (if available)
    cursor.execute("SELECT detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json FROM srt_tracks WHERE detection_id = ?", (detection_id,))
    srt_track = cursor.fetchone()
    
    # Get detection details
    cursor.execute("SELECT * FROM detection_details WHERE detection_id = ? ORDER BY frame_number, id", (detection_id,))
    detection_details = cursor.fetchall()
    
    conn.close()
    
    return {
        'detection': detection,
        'srt_track': srt_track,
        'detection_details': detection_details,
        'frame_metadata': []  # Deprecated: frame_metadata table removed, kept for backward compatibility
    }

def upsert_srt_track(detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json):
    """Insert or replace compact SRT track for a detection session."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO srt_tracks (detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(detection_id) DO UPDATE SET
            point_count=excluded.point_count,
            start_time=excluded.start_time,
            end_time=excluded.end_time,
            bounds_geojson=excluded.bounds_geojson,
            path_geojson=excluded.path_geojson,
            frames_json=excluded.frames_json
        """,
        (detection_id, point_count, start_time, end_time, bounds_geojson, path_geojson, frames_json)
    )
    
    # Update the detection record to mark it as having SRT data
    cursor.execute(
        "UPDATE detections SET has_srt_data = TRUE WHERE id = ?",
        (detection_id,)
    )
    
    conn.commit()
    conn.close()

def update_srt_status(detection_id, has_srt_data):
    """Update the SRT data status for a detection session."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE detections SET has_srt_data = ? WHERE id = ?",
        (has_srt_data, detection_id)
    )
    conn.commit()
    conn.close()

def upsert_heatmap(detection_id, grid_size_m, bounds_geojson, cells_json):
    """Insert or replace aggregated heatmap data for a detection session."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO heatmaps (detection_id, grid_size_m, bounds_geojson, cells_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(detection_id) DO UPDATE SET
            grid_size_m=excluded.grid_size_m,
            bounds_geojson=excluded.bounds_geojson,
            cells_json=excluded.cells_json
        """,
        (detection_id, grid_size_m, bounds_geojson, cells_json)
    )
    conn.commit()
    conn.close()

def fetch_all_detections():
    """Return all detection session records, sorted by ID descending (newest first)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detections ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def fetch_detections_by_class(weed_class):
    """Fetch all detections of a specific weed class."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dd.*, d.filename, d.timestamp 
        FROM detection_details dd 
        JOIN detections d ON dd.detection_id = d.id 
        WHERE dd.weed_class = ? 
        ORDER BY d.timestamp DESC
    """, (weed_class,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_detection_statistics():
    """Get overall statistics about detections."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Total sessions
    cursor.execute("SELECT COUNT(*) FROM detections")
    total_sessions = cursor.fetchone()[0]
    
    # Total detections
    cursor.execute("SELECT COUNT(*) FROM detection_details")
    total_detections = cursor.fetchall()[0][0]
    
    # Weed class distribution
    cursor.execute("SELECT weed_class, COUNT(*) FROM detection_details GROUP BY weed_class")
    class_distribution = cursor.fetchall()
    
    # File type distribution
    cursor.execute("SELECT file_type, COUNT(*) FROM detections GROUP BY file_type")
    file_type_distribution = cursor.fetchall()
    
    conn.close()
    
    return {
        'total_sessions': total_sessions,
        'total_detections': total_detections,
        'class_distribution': class_distribution,
        'file_type_distribution': file_type_distribution
    }

if __name__ == "__main__":
    init_db()
    print("✅ Enhanced database initialized with new tables!")
    print("📊 Tables created:")
    print("   - detections (sessions)")
    print("   - srt_tracks (compact SRT/GPS data)")
    print("   - detection_details (individual detections)")
    print("   - heatmaps (optional grid-based aggregation)")

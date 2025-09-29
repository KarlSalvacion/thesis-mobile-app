import sqlite3
import json
from datetime import datetime

DB_NAME = "weed_detection.db"

def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Main detections table (sessions)
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
            has_srt_data BOOLEAN DEFAULT FALSE
        )
    """)
    
    # Frame metadata table (from SRT files)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS frame_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detection_id INTEGER NOT NULL,
            frame_number INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            relative_altitude REAL,
            iso INTEGER,
            shutter_speed TEXT,
            f_number REAL,
            exposure_value REAL,
            focal_length REAL,
            color_temperature INTEGER,
            camera_model TEXT DEFAULT 'DJI',
            FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
        )
    """)
    
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
    
    # Individual detection details table
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
            FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
        )
    """)
    
    # Create indexes for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_id ON frame_metadata(detection_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_frame_number ON frame_metadata(frame_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detection_details_id ON detection_details(detection_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_weed_class ON detection_details(weed_class)")
    
    conn.commit()

    # Backfill columns for older DBs (SQLite lacks IF NOT EXISTS for columns)
    try:
        cursor.execute("ALTER TABLE detections ADD COLUMN input_size_bytes INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE detections ADD COLUMN result_size_bytes INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE detections ADD COLUMN has_srt_data BOOLEAN DEFAULT FALSE")
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

def insert_detection(filename, timestamp, file_type, summary, total_frames=0, total_detections=0, processing_time=0.0, input_size_bytes=None, result_size_bytes=None, has_srt_data=False):
    """Insert a new detection session record."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO detections (filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data)
    )
    detection_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return detection_id

def insert_frame_metadata(detection_id, frame_data):
    """Insert frame metadata from SRT file."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO frame_metadata (
            detection_id, frame_number, timestamp, latitude, longitude, altitude, 
            relative_altitude, iso, shutter_speed, f_number, exposure_value, 
            focal_length, color_temperature
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        detection_id, frame_data['frame_number'], frame_data['timestamp'],
        frame_data.get('latitude'), frame_data.get('longitude'), frame_data.get('altitude'),
        frame_data.get('relative_altitude'), frame_data.get('iso'), frame_data.get('shutter_speed'),
        frame_data.get('f_number'), frame_data.get('exposure_value'), frame_data.get('focal_length'),
        frame_data.get('color_temperature')
    ))
    
    conn.commit()
    conn.close()

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
        'detection_details': detection_details
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
    """Return all detection session records."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detections ORDER BY timestamp DESC")
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
    print("   - frame_metadata (SRT data)")
    print("   - detection_details (individual detections)")

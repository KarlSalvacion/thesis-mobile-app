import os
import datetime
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import json
from inference import run_inference_auto, detect_file_type
from database import (
    insert_detection, insert_frame_metadata, insert_detection_details,
    fetch_detection_session, fetch_all_detections, get_detection_statistics,
    upsert_srt_track, reset_compact_tables
)
from srt_parser import parse_srt_file, validate_srt_file
from database import DB_NAME

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Serve uploaded media statically for frontend previews
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Initialize DB
from database import init_db
init_db()

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    """Upload and process a video or image file for weed detection."""
    start_time = time.time()
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    file_bytes = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Auto-detect file type and run appropriate inference
    detections = run_inference_auto(file_path)
    
    # Get the actual file type based on file extension
    actual_file_type = detect_file_type(file_path)
    
    # Calculate processing time and sizes
    processing_time = time.time() - start_time
    input_size_bytes = len(file_bytes) if file_bytes else None
    try:
        result_size_bytes = len(json.dumps(detections).encode('utf-8')) if detections is not None else 0
    except Exception:
        result_size_bytes = None

    # Handle both image and video results
    if isinstance(detections, list) and len(detections) > 0:
        if isinstance(detections[0], list):  # Video results (list of frames)
            total_frames = len(detections)
            total_detections = sum(len(frame) for frame in detections)
            summary = f"Detected {total_detections} objects across {total_frames} frames"
        else:  # Image results (single list)
            total_frames = 1
            total_detections = len(detections)
            summary = f"Detected {total_detections} objects"
    else:
        total_frames = 1 if actual_file_type == "image" else 0
        total_detections = 0
        summary = "No objects detected"
    
    timestamp = datetime.datetime.now().isoformat()

    # Insert main detection record
    detection_id = insert_detection(
        filename=file.filename,
        timestamp=timestamp,
        file_type=actual_file_type,
        summary=summary,
        total_frames=total_frames,
        total_detections=total_detections,
        processing_time=processing_time,
        input_size_bytes=input_size_bytes,
        result_size_bytes=result_size_bytes
    )

    # Store individual detection details if any
    if detections and len(detections) > 0:
        if isinstance(detections[0], list):  # Video
            for frame_idx, frame_detections in enumerate(detections):
                for detection in frame_detections:
                    detection_data = {
                        'frame_number': frame_idx + 1,
                        'weed_class': detection['class'],
                        'confidence': detection['confidence'],
                        'bbox_x': detection['bbox'][0],
                        'bbox_y': detection['bbox'][1],
                        'bbox_width': detection['bbox'][2],
                        'bbox_height': detection['bbox'][3],
                        'detection_timestamp': timestamp
                    }
                    insert_detection_details(detection_id, detection_data)
        else:  # Image
            for detection in detections:
                detection_data = {
                    'frame_number': 1,
                    'weed_class': detection['class'],
                    'confidence': detection['confidence'],
                    'bbox_x': detection['bbox'][0],
                    'bbox_y': detection['bbox'][1],
                    'bbox_width': detection['bbox'][2],
                    'bbox_height': detection['bbox'][3],
                    'detection_timestamp': timestamp
                }
                insert_detection_details(detection_id, detection_data)

    return JSONResponse(content={
        "detection_id": detection_id,
        "filename": file.filename,
        "file_type": actual_file_type,
        "summary": summary,
        "total_frames": total_frames,
        "total_detections": total_detections,
        "processing_time": round(processing_time, 2),
        "input_size_bytes": input_size_bytes,
        "result_size_bytes": result_size_bytes
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
    return {"detections": detections}

@app.get("/detection/{detection_id}")
async def get_detection_details(detection_id: int):
    """Get complete details of a specific detection session."""
    session = fetch_detection_session(detection_id)
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    return session

@app.get("/statistics/")
async def get_statistics():
    """Get overall detection statistics."""
    stats = get_detection_statistics()
    return stats

@app.get("/detections/class/{weed_class}")
async def get_detections_by_class(weed_class: str):
    """Get all detections of a specific weed class."""
    from database import fetch_detections_by_class
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
        # Also try removing one level up (in case DB was at project root)
        parent_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, DB_NAME)
        parent_db = os.path.abspath(parent_db)
        if os.path.exists(parent_db):
            os.remove(parent_db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete DB file: {e}")
    # Recreate tables
    from database import init_db as recreate
    recreate()
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT path_geojson, bounds_geojson FROM srt_tracks WHERE detection_id = ?", (detection_id,))
    row = cursor.fetchone()
    conn.close()
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT frames_json, bounds_geojson FROM srt_tracks WHERE detection_id = ?", (detection_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="SRT track not found")
    frames_json = row[0]
    bounds_geojson = row[1]
    frames = { int(f.get('i')): (f.get('lat'), f.get('lon')) for f in json.loads(frames_json) if f.get('lat') is not None and f.get('lon') is not None }

    # Load detection details
    cursor.execute("SELECT frame_number, weed_class, confidence FROM detection_details WHERE detection_id = ?", (detection_id,))
    details = cursor.fetchall()
    conn.close()

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
            from database import upsert_heatmap
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

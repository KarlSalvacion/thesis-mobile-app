import os
import datetime
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
from inference import run_inference_auto, detect_file_type
from database import (
    insert_detection, insert_frame_metadata, insert_detection_details,
    fetch_detection_session, fetch_all_detections, get_detection_statistics
)
from srt_parser import parse_srt_file, validate_srt_file

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
    
    # Store frame metadata
    for frame_data in frames:
        insert_frame_metadata(detection_id, frame_data)
    
    return JSONResponse(content={
        "message": "SRT file uploaded successfully",
        "detection_id": detection_id,
        "frames_processed": len(frames),
        "first_frame": frames[0] if frames else None,
        "last_frame": frames[-1] if frames else None
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

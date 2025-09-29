import os
from roboflow import Roboflow
from config import (
    ROBOFLOW_API_KEY, 
    ROBOFLOW_PROJECT, 
    ROBOFLOW_VERSION,
    DEFAULT_CONFIDENCE,
    DEFAULT_OVERLAP,
    DEFAULT_VIDEO_FPS,
    MAX_VIDEO_FRAMES,
    ENABLE_SMART_SAMPLING,
    SAMPLE_INTERVAL
)

# Initialize Roboflow client
rf = Roboflow(api_key=ROBOFLOW_API_KEY)
project = rf.workspace().project(ROBOFLOW_PROJECT)
model = project.version(ROBOFLOW_VERSION).model

def run_inference(image_path: str):
    """Run inference on a single image."""
    try:
        result = model.predict(image_path, confidence=DEFAULT_CONFIDENCE, overlap=DEFAULT_OVERLAP).json()
        
        detections = []
        if "predictions" in result:
            for pred in result["predictions"]:
                detections.append({
                    "class": pred.get("class", "unknown"),
                    "confidence": pred.get("confidence", 0.0),
                    "bbox": [
                        pred.get("x", 0), 
                        pred.get("y", 0), 
                        pred.get("width", 0), 
                        pred.get("height", 0)
                    ]
                })
        
        return detections
    except Exception as e:
        print(f"Error in image inference: {e}")
        return []

def run_video_inference(video_path: str, fps: int = DEFAULT_VIDEO_FPS):
    """Run optimized inference on a video file with smart sampling."""
    try:
        print(f"Starting optimized video inference with {fps} FPS sampling...")
        
        # Use much lower FPS for faster processing
        optimized_fps = min(fps, 0.5)  # Maximum 0.5 FPS (1 frame every 2 seconds)
        
        # Start video prediction with optimized settings
        job_id, signed_url, expire_time = model.predict_video(
            video_path,
            fps=optimized_fps,
            prediction_type="batch-video",
        )
        
        print(f"Video job started with ID: {job_id}")
        
        # Wait for results
        results = model.poll_until_video_results(job_id)
        
        # Process video results with aggressive optimization
        all_detections = []
        if "predictions" in results:
            # Limit to maximum frames for faster processing
            max_frames = min(MAX_VIDEO_FRAMES, len(results["predictions"]))
            
            # Smart sampling: take every nth frame if we have too many
            predictions = results["predictions"]
            if ENABLE_SMART_SAMPLING and len(predictions) > max_frames:
                # Sample frames intelligently
                step = max(1, len(predictions) // max_frames)
                predictions = predictions[::step][:max_frames]
            
            print(f"Processing {len(predictions)} frames (reduced from {len(results['predictions'])})")
            
            for i, frame_result in enumerate(predictions):
                frame_detections = []
                # Limit detections per frame to reduce data size
                max_detections_per_frame = 10
                frame_preds = frame_result[:max_detections_per_frame] if isinstance(frame_result, list) else []
                
                for pred in frame_preds:
                    # Only include high confidence detections to reduce noise
                    confidence = pred.get("confidence", 0.0)
                    if confidence >= (DEFAULT_CONFIDENCE / 100.0):  # Convert percentage to decimal
                        frame_detections.append({
                            "class": pred.get("class", "unknown"),
                            "confidence": round(confidence, 3),  # Round to reduce data size
                            "bbox": [
                                round(pred.get("x", 0), 1), 
                                round(pred.get("y", 0), 1), 
                                round(pred.get("width", 0), 1), 
                                round(pred.get("height", 0), 1)
                            ]
                        })
                all_detections.append(frame_detections)
        
        print(f"Video inference completed. Processed {len(all_detections)} frames with {sum(len(frame) for frame in all_detections)} total detections")
        return all_detections
        
    except Exception as e:
        print(f"Error in video inference: {e}")
        return []

def detect_file_type(file_path: str):
    """Detect if file is image or video based on extension."""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif']
    
    file_ext = os.path.splitext(file_path.lower())[1]
    
    if file_ext in video_extensions:
        return "video"
    elif file_ext in image_extensions:
        return "image"
    else:
        return "unknown"

def run_inference_auto(file_path: str):
    """Automatically detect file type and run appropriate inference with optimization."""
    file_type = detect_file_type(file_path)
    
    if file_type == "image":
        return run_inference(file_path)
    elif file_type == "video":
        # Check file size for additional optimization
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)
        
        print(f"Processing video: {file_size_mb:.1f} MB")
        
        # For very large videos (>100MB), use ultra-fast processing
        if file_size_mb > 100:
            print("Large video detected - using ultra-fast processing mode")
            return run_video_inference(file_path, fps=0.25)  # 1 frame every 4 seconds
        elif file_size_mb > 50:
            print("Medium video detected - using fast processing mode") 
            return run_video_inference(file_path, fps=0.33)  # 1 frame every 3 seconds
        else:
            return run_video_inference(file_path)
    else:
        print(f"Unsupported file type: {file_path}")
        return []

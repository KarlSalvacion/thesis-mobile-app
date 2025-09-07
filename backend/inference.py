import os
from roboflow import Roboflow

# Initialize Roboflow client (prefer env var in production)
_rf_key = os.getenv("ROBOFLOW_API_KEY", "RpeaIrOXAbnFIfwEbbdB")
rf = Roboflow(api_key=_rf_key)
project = rf.workspace().project("thesis-online-gathered-ds-y6uy4")
model = project.version("1").model

def run_inference(image_path: str):
    """Run inference on a single image."""
    try:
        result = model.predict(image_path, confidence=40, overlap=30).json()
        
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

def run_video_inference(video_path: str, fps: int = 2):
    """Run inference on a video file."""
    try:
        # Start video prediction
        job_id, signed_url, expire_time = model.predict_video(
            video_path,
            fps=fps,
            prediction_type="batch-video",
        )
        
        # Wait for results
        results = model.poll_until_video_results(job_id)
        
        # Process video results
        all_detections = []
        if "predictions" in results:
            # Cap processed frames to reduce memory/size
            max_frames = 300
            for frame_result in results["predictions"][:max_frames]:
                frame_detections = []
                for pred in frame_result:
                    frame_detections.append({
                        "class": pred.get("class", "unknown"),
                        "confidence": pred.get("confidence", 0.0),
                        "bbox": [
                            pred.get("x", 0), 
                            pred.get("y", 0), 
                            pred.get("width", 0), 
                            pred.get("height", 0)
                        ]
                    })
                all_detections.append(frame_detections)
        
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
    """Automatically detect file type and run appropriate inference."""
    file_type = detect_file_type(file_path)
    
    if file_type == "image":
        return run_inference(file_path)
    elif file_type == "video":
        return run_video_inference(file_path)
    else:
        print(f"Unsupported file type: {file_path}")
        return []

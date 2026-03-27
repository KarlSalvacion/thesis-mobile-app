import os
from typing import Any, Dict, List, Optional


def calculate_iou(box1, box2):
    """Calculate IoU between two detections with bbox=[x, y, w, h]."""
    x1, y1, w1, h1 = box1['bbox']
    x2, y2, w2, h2 = box2['bbox']

    x1_min, y1_min, x1_max, y1_max = x1, y1, x1 + w1, y1 + h1
    x2_min, y2_min, x2_max, y2_max = x2, y2, x2 + w2, y2 + h2

    inter_x_min = max(x1_min, x2_min)
    inter_y_min = max(y1_min, y2_min)
    inter_x_max = min(x1_max, x2_max)
    inter_y_max = min(y1_max, y2_max)

    if inter_x_max <= inter_x_min or inter_y_max <= inter_y_min:
        return 0.0

    inter_area = (inter_x_max - inter_x_min) * (inter_y_max - inter_y_min)
    box1_area = w1 * h1
    box2_area = w2 * h2
    union_area = box1_area + box2_area - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def merge_detections(existing_dets, new_dets):
    """Merge new detections into existing ones, replacing overlaps by confidence recency."""
    iou_threshold = 0.3
    merged = []
    used_new = set()

    for exist_det in existing_dets:
        replaced = False
        for i, new_det in enumerate(new_dets):
            if i in used_new:
                continue
            if exist_det['class'] == new_det['class']:
                iou = calculate_iou(exist_det, new_det)
                if iou > iou_threshold:
                    merged.append(new_det)
                    used_new.add(i)
                    replaced = True
                    break

        if not replaced:
            merged.append(exist_det)

    for i, new_det in enumerate(new_dets):
        if i not in used_new:
            merged.append(new_det)

    return merged


def _parse_roboflow_video_response(results: Any) -> List[Any]:
    """Parse Roboflow video API response and extract frames list."""
    frames: List[Any] = []

    if isinstance(results, list):
        return results
    if not isinstance(results, dict):
        return frames

    if 'frame_offset' in results and 'thesis-online-gathered-ds-y6uy4' in results:
        predictions_data = results['thesis-online-gathered-ds-y6uy4']
        if isinstance(predictions_data, list):
            return predictions_data

    if 'predictions' in results and isinstance(results['predictions'], list):
        return results['predictions']

    if 'frames' in results and isinstance(results['frames'], list):
        return results['frames']

    if 'video' in results and isinstance(results['video'], dict):
        video_data = results['video']
        if 'frames' in video_data and isinstance(video_data['frames'], list):
            return video_data['frames']
        if 'predictions' in video_data and isinstance(video_data['predictions'], list):
            return video_data['predictions']

    for _, value in results.items():
        if isinstance(value, list) and len(value) > 0:
            first_item = value[0]
            if isinstance(first_item, dict):
                if any(k in first_item for k in ['predictions', 'detections', 'objects', 'class', 'bbox', 'confidence', 'x', 'y', 'width', 'height']):
                    return value

    return frames


def _extract_annotated_from_response(obj: Any) -> Optional[str]:
    """Try common keys in Roboflow responses to locate an annotated URL."""
    if not isinstance(obj, dict):
        return None

    candidates = (
        'annotated',
        'annotated_image',
        'annotated_url',
        'image',
        'image_url',
        'video_url',
        'annotated_video',
        'video_signed_url',
        'signed_url',
    )
    for k in candidates:
        v = obj.get(k)
        if isinstance(v, str) and v.startswith('http'):
            return v

    for k in ('result', 'data', 'outputs'):
        nested = obj.get(k)
        if isinstance(nested, dict):
            v = _extract_annotated_from_response(nested)
            if v:
                return v
    return None


def _normalize_prediction(pred: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize prediction from various Roboflow response formats."""
    raw_conf = pred.get('confidence', pred.get('score', pred.get('conf', 0.0)))
    conf = raw_conf / 100.0 if raw_conf > 1.0 else raw_conf
    class_name = pred.get('class', pred.get('label', pred.get('name', pred.get('class_name', 'unknown'))))

    x, y, w, h = 0, 0, 0, 0

    if all(key in pred for key in ['x', 'y', 'width', 'height']):
        cx, cy = float(pred['x']), float(pred['y'])
        w, h = float(pred['width']), float(pred['height'])
        x = cx - w / 2.0
        y = cy - h / 2.0
    elif 'bbox' in pred and isinstance(pred['bbox'], dict):
        bbox = pred['bbox']
        x = bbox.get('x', 0)
        y = bbox.get('y', 0)
        w = bbox.get('width', 0)
        h = bbox.get('height', 0)
    elif 'bbox' in pred and isinstance(pred['bbox'], list) and len(pred['bbox']) >= 4:
        bbox = pred['bbox']
        x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
    elif 'coordinates' in pred and isinstance(pred['coordinates'], list) and len(pred['coordinates']) >= 4:
        coords = pred['coordinates']
        x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
        x, y = x1, y1
        w, h = x2 - x1, y2 - y1
    elif all(key in pred for key in ['center_x', 'center_y', 'width', 'height']):
        x = pred['center_x'] - pred['width'] / 2
        y = pred['center_y'] - pred['height'] / 2
        w, h = pred['width'], pred['height']
    else:
        coord_keys = ['x', 'y', 'width', 'height', 'w', 'h', 'x1', 'y1', 'x2', 'y2']
        found_coords = {k: pred.get(k, 0) for k in coord_keys if k in pred}
        if 'x' in found_coords and 'y' in found_coords:
            x, y = found_coords['x'], found_coords['y']
            w = found_coords.get('width', found_coords.get('w', 0))
            h = found_coords.get('height', found_coords.get('h', 0))

    return {
        'class': str(class_name),
        'confidence': round(float(conf), 3),
        'bbox': [round(float(x), 1), round(float(y), 1), round(float(w), 1), round(float(h), 1)],
    }


def _get_class_color(class_name: str, format: str = 'bgr'):
    """Get deterministic class color in bgr/rgb/hex format."""
    class_name_lower = str(class_name).lower()

    if 'caperonia' in class_name_lower or 'Caperonia Palustris' in class_name_lower:
        if format == 'bgr':
            return (255, 0, 0)
        if format == 'rgb':
            return (0, 0, 255)
        return 'blue'

    if 'crus-galli' in class_name_lower or 'Echinochloa crus-galli' in class_name_lower:
        if format == 'bgr':
            return (0, 255, 0)
        if format == 'rgb':
            return (0, 255, 0)
        return 'green'

    if 'colona' in class_name_lower or 'Echinochloa colona' in class_name_lower:
        if format == 'bgr':
            return (0, 255, 255)
        if format == 'rgb':
            return (255, 255, 0)
        return 'yellow'

    if format == 'bgr':
        return (0, 0, 255)
    if format == 'rgb':
        return (255, 0, 0)
    return 'red'


def detect_file_type(file_path: str) -> str:
    """Detect if file is image or video based on extension."""
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif']
    file_ext = os.path.splitext(file_path.lower())[1]
    if file_ext in video_extensions:
        return 'video'
    if file_ext in image_extensions:
        return 'image'
    return 'unknown'

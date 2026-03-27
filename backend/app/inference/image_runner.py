from typing import Any, Dict, List, Optional, Tuple

from backend.config.settings import DEFAULT_CONFIDENCE, DEFAULT_OVERLAP, USE_LOCAL_INFERENCE
from backend.app.inference.annotation import HAS_PIL, _annotate_image_file
from backend.app.inference.helpers import _extract_annotated_from_response, _normalize_prediction
from backend.app.inference.runtime import local_model, model


def run_inference(image_path: str, confidence: Optional[int] = None, overlap: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Run inference on a single image using local inference or cloud API."""
    try:
        conf = DEFAULT_CONFIDENCE if confidence is None else float(confidence)
        ovlp = DEFAULT_OVERLAP if overlap is None else float(overlap)
        if conf > 1.0:
            conf = conf / 100.0
        if ovlp > 1.0:
            ovlp = ovlp / 100.0
        conf = max(0.0, min(1.0, conf))
        ovlp = max(0.0, min(1.0, ovlp))

        if not hasattr(run_inference, '_debug_count'):
            run_inference._debug_count = 0
        run_inference._debug_count += 1

        if run_inference._debug_count <= 3:
            inference_type = 'local' if (local_model is not None and USE_LOCAL_INFERENCE) else 'cloud'
            print(f'  Image inference ({inference_type}): confidence={conf}, overlap={ovlp}, image={image_path}')

        if local_model is not None and USE_LOCAL_INFERENCE:
            resp = local_model.infer(image_path, confidence=conf, iou_threshold=1.0 - ovlp)
            result = resp[0] if isinstance(resp, list) and len(resp) > 0 else resp
        else:
            resp = model.predict(image_path, confidence=conf, overlap=ovlp)
            try:
                result = resp.json() if hasattr(resp, 'json') else dict(resp)
            except Exception:
                result = resp if isinstance(resp, dict) else {}

        if run_inference._debug_count <= 3:
            print(f"  Raw result keys: {list(result.keys()) if isinstance(result, dict) else 'not dict'}")
            if isinstance(result, dict) and 'predictions' in result:
                print(f"  Raw predictions count: {len(result.get('predictions', []))}")

        detections: List[Dict[str, Any]] = []
        if isinstance(result, dict) and 'predictions' in result:
            for pred in result.get('predictions', []):
                normalized = _normalize_prediction(pred)
                if run_inference._debug_count <= 3:
                    print(f'  Raw prediction: {pred}')
                    print(f'  Normalized prediction: {normalized}')
                detections.append(normalized)

        annotated = _extract_annotated_from_response(result)
        if detections and HAS_PIL:
            try:
                ann_bytes = _annotate_image_file(image_path, detections)
                if ann_bytes:
                    return detections, ann_bytes
            except Exception:
                pass

        return detections, annotated
    except Exception as e:
        print(f'Error in image inference: {e}')
        return [], None

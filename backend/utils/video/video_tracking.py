try:
    import cv2 as _cv2
    import numpy as _np

    _HAS_OPENCV = True
except ImportError:
    _HAS_OPENCV = False
    _cv2 = None
    _np = None


class MotionDetectionSkipper:
    def __init__(self, motion_threshold: float = 2.0, min_changed_pixels: int = 1000):
        self.motion_threshold = motion_threshold
        self.min_changed_pixels = min_changed_pixels
        self.prev_frame = None
        self.total_frames = 0
        self.skipped_frames = 0
        self.motion_frames = 0

        if not _HAS_OPENCV:
            print('Warning: OpenCV not available, motion detection disabled')

    def has_motion(self, frame_path: str) -> bool:
        if not _HAS_OPENCV or _cv2 is None:
            return True

        self.total_frames += 1

        try:
            current_frame = _cv2.imread(frame_path, _cv2.IMREAD_GRAYSCALE)
            if current_frame is None:
                print(f'Warning: Failed to read frame {frame_path}')
                return True

            if self.prev_frame is None:
                self.prev_frame = current_frame
                self.motion_frames += 1
                return True

            if current_frame.shape != self.prev_frame.shape:
                current_frame = _cv2.resize(current_frame, (self.prev_frame.shape[1], self.prev_frame.shape[0]))

            diff = _cv2.absdiff(self.prev_frame, current_frame)
            _, thresh = _cv2.threshold(diff, self.motion_threshold, 255, _cv2.THRESH_BINARY)
            changed_pixels = _np.sum(thresh > 0)

            self.prev_frame = current_frame

            has_motion = changed_pixels >= self.min_changed_pixels

            if has_motion:
                self.motion_frames += 1
            else:
                self.skipped_frames += 1

            return has_motion

        except Exception as e:
            print(f'Error in motion detection: {e}')
            return True

    def reset(self):
        self.prev_frame = None
        self.total_frames = 0
        self.skipped_frames = 0
        self.motion_frames = 0

    def get_stats(self) -> dict:
        skip_rate = (self.skipped_frames / self.total_frames * 100) if self.total_frames > 0 else 0
        return {
            'total_frames': self.total_frames,
            'motion_frames': self.motion_frames,
            'skipped_frames': self.skipped_frames,
            'skip_rate': f'{skip_rate:.1f}%',
        }


class ObjectTracker:
    def __init__(self, tracker_type: str = 'CSRT', confidence_decay: float = 0.95):
        self.tracker_type = tracker_type
        self.confidence_decay = confidence_decay
        self.active_tracks = []
        self.next_track_id = 0
        self.has_opencv = _HAS_OPENCV

        if not _HAS_OPENCV:
            print('Warning: OpenCV not available, object tracking disabled')

    def _create_tracker(self):
        if not self.has_opencv or _cv2 is None:
            return None

        try:
            if self.tracker_type == 'KCF':
                try:
                    return _cv2.legacy.TrackerKCF_create()
                except AttributeError:
                    return _cv2.TrackerKCF_create()
            elif self.tracker_type == 'CSRT':
                try:
                    return _cv2.legacy.TrackerCSRT_create()
                except AttributeError:
                    return _cv2.TrackerCSRT_create()
            elif self.tracker_type == 'MOSSE':
                try:
                    return _cv2.legacy.TrackerMOSSE_create()
                except AttributeError:
                    return _cv2.TrackerMOSSE_create()
            else:
                print(f'Unknown tracker type: {self.tracker_type}, using KCF')
                try:
                    return _cv2.legacy.TrackerKCF_create()
                except AttributeError:
                    return _cv2.TrackerKCF_create()
        except Exception as e:
            print(f'Failed to create tracker: {e}')
            return None

    def update(self, frame_path: str, new_detections: list[dict]) -> list[dict]:
        if not self.has_opencv or _cv2 is None:
            return new_detections

        try:
            frame = _cv2.imread(frame_path)
            if frame is None:
                print(f'Warning: Failed to read frame for tracking: {frame_path}')
                return new_detections

            updated_tracks = []
            for tracker, bbox, cls, conf, age in self.active_tracks:
                success, new_bbox = tracker.update(frame)

                if success:
                    x, y, w, h = new_bbox
                    updated_bbox = [float(x), float(y), float(w), float(h)]
                    new_conf = conf * self.confidence_decay

                    if new_conf > 0.2 and age < 30:
                        updated_tracks.append((tracker, updated_bbox, cls, new_conf, age + 1))

            matched_detections = []
            unmatched_detections = []
            matched_tracks = set()

            for det in new_detections:
                det_bbox = det['bbox']
                det_class = det['class']
                det_conf = det['confidence']

                best_iou = 0.3
                best_track_idx = -1

                for idx, (tracker, track_bbox, track_class, track_conf, age) in enumerate(updated_tracks):
                    if track_class != det_class or idx in matched_tracks:
                        continue

                    iou = self._calculate_iou(det_bbox, track_bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_track_idx = idx

                if best_track_idx >= 0:
                    matched_tracks.add(best_track_idx)
                    tracker, track_bbox, track_class, track_conf, age = updated_tracks[best_track_idx]

                    alpha = 0.7
                    smoothed_bbox = [alpha * det_bbox[i] + (1 - alpha) * track_bbox[i] for i in range(4)]

                    new_tracker = self._create_tracker()
                    if new_tracker is not None:
                        bbox_tuple = (
                            int(smoothed_bbox[0]),
                            int(smoothed_bbox[1]),
                            int(smoothed_bbox[2]),
                            int(smoothed_bbox[3]),
                        )
                        new_tracker.init(frame, bbox_tuple)
                        updated_tracks[best_track_idx] = (new_tracker, smoothed_bbox, track_class, det_conf, 0)

                    matched_detections.append({'class': track_class, 'confidence': det_conf, 'bbox': smoothed_bbox})
                else:
                    unmatched_detections.append(det)

            for det in unmatched_detections:
                tracker = self._create_tracker()
                if tracker is not None:
                    bbox = det['bbox']
                    bbox_tuple = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                    tracker.init(frame, bbox_tuple)
                    updated_tracks.append((tracker, bbox, det['class'], det['confidence'], 0))
                    matched_detections.append(det)

            for idx, (tracker, track_bbox, track_class, track_conf, age) in enumerate(updated_tracks):
                if idx not in matched_tracks and track_conf > 0.3:
                    matched_detections.append({'class': track_class, 'confidence': track_conf, 'bbox': track_bbox})

            self.active_tracks = updated_tracks
            return matched_detections

        except Exception as e:
            print(f'Error in object tracking: {e}')
            return new_detections

    def _calculate_iou(self, bbox1, bbox2) -> float:
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2

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

    def reset(self):
        self.active_tracks = []
        self.next_track_id = 0


class TemporalConsistencyFilter:
    def __init__(self, min_appearances: int = 3, max_gap: int = 5):
        self.min_appearances = min_appearances
        self.max_gap = max_gap
        self.detection_history = {}
        self.current_frame_idx = 0

    def filter(self, detections: list[dict]) -> list[dict]:
        self.current_frame_idx += 1

        expired_keys = []
        for key, (count, last_frame, bbox, cls, conf) in self.detection_history.items():
            if self.current_frame_idx - last_frame > self.max_gap:
                expired_keys.append(key)

        for key in expired_keys:
            del self.detection_history[key]

        filtered_detections = []

        for det in detections:
            bbox = det['bbox']
            cls = det['class']
            conf = det['confidence']

            grid_x = int(bbox[0] / 20)
            grid_y = int(bbox[1] / 20)
            grid_w = int(bbox[2] / 20)
            grid_h = int(bbox[3] / 20)
            key = f'{cls}_{grid_x}_{grid_y}_{grid_w}_{grid_h}'

            if key in self.detection_history:
                count, last_frame, old_bbox, old_cls, old_conf = self.detection_history[key]
                new_count = count + 1
                self.detection_history[key] = (new_count, self.current_frame_idx, bbox, cls, max(conf, old_conf))
                if new_count >= self.min_appearances:
                    filtered_detections.append(det)
            else:
                self.detection_history[key] = (1, self.current_frame_idx, bbox, cls, conf)
                if conf > 0.8:
                    filtered_detections.append(det)

        return filtered_detections

    def reset(self):
        self.detection_history = {}
        self.current_frame_idx = 0


class BackgroundSubtractor:
    def __init__(self, learning_rate: float = 0.01, var_threshold: int = 16):
        self.learning_rate = learning_rate
        self.var_threshold = var_threshold
        self.bg_subtractor = None
        self.has_opencv = _HAS_OPENCV

        if self.has_opencv and _cv2 is not None:
            try:
                self.bg_subtractor = _cv2.createBackgroundSubtractorMOG2(
                    detectShadows=True,
                    varThreshold=var_threshold,
                )
                print(f'Background subtractor initialized (MOG2, threshold={var_threshold})')
            except Exception as e:
                print(f'Failed to initialize background subtractor: {e}')
                self.bg_subtractor = None
        else:
            print('Warning: OpenCV not available, background subtraction disabled')

    def is_moving(self, frame_path: str, bbox: list[float]) -> bool:
        if not self.has_opencv or self.bg_subtractor is None or _cv2 is None:
            return True

        try:
            frame = _cv2.imread(frame_path)
            if frame is None:
                return True

            fg_mask = self.bg_subtractor.apply(frame, learningRate=self.learning_rate)
            x, y, w, h = [int(v) for v in bbox]

            h_frame, w_frame = fg_mask.shape[:2]
            x = max(0, min(x, w_frame - 1))
            y = max(0, min(y, h_frame - 1))
            w = max(1, min(w, w_frame - x))
            h = max(1, min(h, h_frame - y))

            roi_mask = fg_mask[y : y + h, x : x + w]
            if roi_mask.size == 0:
                return True

            foreground_pixels = _np.sum(roi_mask > 0)
            total_pixels = roi_mask.size
            foreground_ratio = foreground_pixels / total_pixels

            return foreground_ratio > 0.10

        except Exception as e:
            print(f'Error in background subtraction: {e}')
            return True

    def reset(self):
        if self.bg_subtractor is not None:
            try:
                self.bg_subtractor = _cv2.createBackgroundSubtractorMOG2(
                    detectShadows=True,
                    varThreshold=self.var_threshold,
                )
            except Exception:
                pass

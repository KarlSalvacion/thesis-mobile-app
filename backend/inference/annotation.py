import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from config.settings import (
    COMPRESS_FRAMES_BEFORE_INFERENCE,
    DETECTION_PERSISTENCE_FRAMES,
    DETECTION_PERSISTENCE_MULTIPLIER,
    ENABLE_SMART_SKIP,
    FFMPEG_BINARY,
    FRAME_INTERVAL,
)
from inference.helpers import _get_class_color

try:
    import cv2 as _cv2

    HAS_CV2 = True
    print('OpenCV successfully imported for image annotation')
except Exception:
    HAS_CV2 = False

try:
    from PIL import Image as _PILImage
    from PIL import ImageDraw as _PILDraw
    from PIL import ImageFont as _PILFont

    HAS_PIL = True
    print('PIL/Pillow successfully imported for image annotation')
except Exception as e:
    HAS_PIL = False
    print(f'Warning: PIL/Pillow not available for image annotation: {e}')


def _annotate_image_file(input_path: str, detections: List[Dict[str, Any]]) -> Optional[bytes]:
    """Draw boxes and labels on an image and return JPEG bytes."""
    if not detections:
        print('Warning: No detections to annotate')
        return None

    if HAS_CV2:
        try:
            img = _cv2.imread(input_path)
            if img is None:
                raise ValueError(f'Failed to load image: {input_path}')

            for det in detections:
                x, y, w, h = det.get('bbox', [0, 0, 0, 0])
                cls = str(det.get('class', ''))
                conf = det.get('confidence', 0.0)
                x, y, w, h = int(x), int(y), int(w), int(h)
                color = _get_class_color(cls, format='bgr')

                _cv2.rectangle(img, (x, y), (x + w, y + h), color, 3)
                label = f'{cls} {conf:.2f}'
                font = _cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                thickness = 2
                (text_w, text_h), _ = _cv2.getTextSize(label, font, font_scale, thickness)
                _cv2.rectangle(img, (x, y - text_h - 8), (x + text_w + 6, y), color, -1)
                _cv2.putText(img, label, (x + 3, y - 4), font, font_scale, (255, 255, 255), thickness)

            success, buffer = _cv2.imencode('.jpg', img, [_cv2.IMWRITE_JPEG_QUALITY, 85])
            if success:
                return buffer.tobytes()
            raise ValueError('Failed to encode image to JPEG')
        except Exception as e:
            print(f'OpenCV annotation failed, falling back to PIL: {e}')

    if not HAS_PIL:
        print('Warning: Neither OpenCV nor PIL/Pillow available, cannot annotate image')
        return None

    try:
        img = _PILImage.open(input_path).convert('RGB')
        draw = _PILDraw.Draw(img)
        try:
            font = _PILFont.load_default()
        except Exception:
            font = None

        for det in detections:
            x, y, w, h = det.get('bbox', [0, 0, 0, 0])
            cls = str(det.get('class', ''))
            conf = det.get('confidence', 0.0)
            box = [x, y, x + w, y + h]
            color = _get_class_color(cls, format='rgb')

            draw.rectangle(box, outline=color, width=3)
            label = f'{cls} {conf:.2f}'
            if font:
                try:
                    bbox = font.getbbox(label)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except AttributeError:
                    tw, th = draw.textsize(label, font=font)
            else:
                tw, th = (len(label) * 6, 10)

            bx0, by0 = x, y - th - 4
            bx1, by1 = x + tw + 6, y
            draw.rectangle([bx0, by0, bx1, by1], fill=color)
            draw.text((x + 3, y - th - 2), label, fill=(255, 255, 255), font=font)

        import io

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return buf.getvalue()
    except Exception as e:
        print(f'Error in _annotate_image_file: {e}')
        import traceback

        traceback.print_exc()
        return None


def _compress_frame_for_inference(frame_path: str, target_size: int = 640) -> Optional[str]:
    """Compress and resize frame for faster inference."""
    if not HAS_PIL or not COMPRESS_FRAMES_BEFORE_INFERENCE:
        return frame_path

    try:
        img = _PILImage.open(frame_path)
        img.thumbnail((target_size, target_size), _PILImage.Resampling.LANCZOS)
        compressed_path = frame_path.replace('.jpg', '_compressed.jpg')
        img.save(compressed_path, format='JPEG', quality=85, optimize=True)
        print(f'Compressed frame from {os.path.getsize(frame_path)} to {os.path.getsize(compressed_path)} bytes')
        return compressed_path
    except Exception as e:
        print(f'Warning: Frame compression failed: {e}')
        return frame_path


class SmartFrameSkipper:
    """Manages smart frame skipping logic to avoid missing stationary objects."""

    def __init__(self, skip_window: int = 5, frame_interval: int = 1):
        self.skip_window = skip_window
        self.frame_interval = frame_interval
        self.frames_since_detection = skip_window + 1
        self.total_processed = 0
        self.total_skipped = 0

    def on_detection_found(self):
        self.frames_since_detection = 0

    def should_process_frame(self, frame_idx: int) -> bool:
        if not ENABLE_SMART_SKIP:
            should_process = (frame_idx % FRAME_INTERVAL) == 0
        else:
            if self.frames_since_detection < self.skip_window:
                should_process = True
                self.frames_since_detection += 1
            else:
                should_process = (frame_idx % self.frame_interval) == 0
                if not should_process:
                    self.frames_since_detection += 1

        if should_process:
            self.total_processed += 1
        else:
            self.total_skipped += 1
        return should_process

    def get_stats(self) -> dict:
        total = self.total_processed + self.total_skipped
        return {
            'total_frames': total,
            'processed': self.total_processed,
            'skipped': self.total_skipped,
            'skip_rate': f"{(self.total_skipped / total * 100) if total > 0 else 0:.1f}%",
        }


def _create_annotated_video_fast(
    video_path: str,
    detections_by_frame: List[List[Dict[str, Any]]],
    output_path: str,
    detection_fps: float,
    original_fps: float,
) -> bool:
    """Create annotated video using FFmpeg drawbox/drawtext filters."""
    try:
        print('Creating annotated video using fast FFmpeg overlay method...')
        print(f'Detection FPS: {detection_fps}, Original FPS: {original_fps}')

        filter_parts = []
        if DETECTION_PERSISTENCE_FRAMES is None:
            persistence_frames = max(1, round((original_fps / detection_fps) * DETECTION_PERSISTENCE_MULTIPLIER))
        else:
            persistence_frames = DETECTION_PERSISTENCE_FRAMES
        print(
            f'Detection persistence: {persistence_frames} frames '
            f'(~{persistence_frames / original_fps:.2f}s, multiplier: {DETECTION_PERSISTENCE_MULTIPLIER}x)'
        )

        total_annotations = 0
        for frame_idx, frame_dets in enumerate(detections_by_frame):
            if not frame_dets:
                continue

            start_frame = round((frame_idx / detection_fps) * original_fps)
            end_frame = start_frame + persistence_frames
            start_time = start_frame / original_fps
            end_time = end_frame / original_fps

            for det in frame_dets:
                bbox = det.get('bbox', [0, 0, 0, 0])
                x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
                cls = det.get('class', 'unknown')
                conf = det.get('confidence', 0.0)

                color = _get_class_color(cls, format='hex')
                cls_safe = cls.replace(' ', '_').replace("'", '').replace('"', '').replace(':', '')

                filter_parts.append(
                    f"drawbox=x={int(x)}:y={int(y)}:w={int(w)}:h={int(h)}:color={color}@0.8:t=3:enable='between(t,{start_time:.3f},{end_time:.3f})'"
                )

                label = f'{cls_safe}_{conf:.2f}'.replace('.', 'p')
                text_y = max(10, int(y) - 5)
                filter_parts.append(
                    f"drawtext=text={label}:x={int(x)+2}:y={text_y}:fontsize=16:fontcolor=white:box=1:boxcolor={color}@0.8:enable='between(t,{start_time:.3f},{end_time:.3f})'"
                )
                total_annotations += 1

        if not filter_parts:
            print('No detections to annotate')
            return False

        print(f'Creating {total_annotations} annotations across {len([d for d in detections_by_frame if d])} frames')
        vf_filter = ','.join(filter_parts)

        estimated_cmd_length = 200 + len(vf_filter)
        if estimated_cmd_length > 8000:
            print(f'Command too long ({estimated_cmd_length} chars) for Windows FFmpeg')
            print('Falling back to quality mode (OpenCV) for reliability')
            return False

        cmd_args = [
            FFMPEG_BINARY,
            '-y',
            '-i',
            video_path,
            '-vf',
            vf_filter,
            '-c:v',
            'libx264',
            '-preset',
            'fast',
            '-crf',
            '23',
            '-c:a',
            'copy',
            output_path,
        ]

        print(f'Command length: {estimated_cmd_length} chars (within Windows limit)')
        print('Running FFmpeg annotation...')
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT, timeout=300)
        print('FFmpeg annotation completed successfully')

        if os.path.exists(output_path):
            output_size = os.path.getsize(output_path)
            print(f'Annotated video created: {output_size / (1024*1024):.2f} MB')

        return True

    except subprocess.TimeoutExpired:
        print('FFmpeg annotation timed out after 5 minutes')
        return False
    except subprocess.CalledProcessError as e:
        print(f'FFmpeg annotation failed: {e}')
        if e.output:
            error_output = e.output.decode() if isinstance(e.output, bytes) else str(e.output)
            print(f'FFmpeg error (last 1000 chars): {error_output[-1000:]}')
        return False
    except Exception as e:
        print(f'Error in fast video annotation: {e}')
        import traceback

        traceback.print_exc()
        return False

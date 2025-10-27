"""Video utilities.

This project does not require ffmpeg. The transcode function is intentionally a
no-op: uploads will send the original file to Cloudinary. Keeping this helper
prevents import errors for code that referenced it while avoiding external
ffmpeg dependencies.
"""

import os
from typing import Optional, List
import tempfile
import subprocess
import shlex
from .config import FFMPEG_BINARY, ANNOTATED_VIDEO_HEIGHT, ANNOTATED_VIDEO_BITRATE, MAX_CLOUDINARY_UPLOAD_SIZE


def transcode_video_to_preview(input_path: str, target_height: Optional[int] = None, target_bitrate: Optional[str] = None) -> str:
    """No-op transcoder.

    Returns the original input path unchanged. Caller is responsible for
    deleting the file if needed.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    # If file is already within Cloudinary size limits, no need to transcode
    try:
        size = os.path.getsize(input_path)
        if size <= MAX_CLOUDINARY_UPLOAD_SIZE:
            return input_path
    except Exception:
        # If we can't stat the file for some reason, attempt to transcode anyway
        pass

    th = target_height or ANNOTATED_VIDEO_HEIGHT
    tb = target_bitrate or ANNOTATED_VIDEO_BITRATE

    # Create a temporary output file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()
    out_path = tmp.name

    # Build ffmpeg command to downscale and lower bitrate (use list, no shell)
    cmd_args = [
        FFMPEG_BINARY,
        '-y',
        '-i', input_path,
        '-vf', f'scale=-2:{int(th)}',
        '-b:v', str(tb),
        '-preset', 'veryfast',
        '-c:a', 'copy',
        out_path,
    ]

    try:
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        # Clean up output if ffmpeg failed
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        # Re-raise a descriptive error so callers can fallback
        raise FileNotFoundError("ffmpeg not available or failed to transcode video; ensure ffmpeg is installed and on PATH")

    # Ensure output file is smaller than cloudinary limit; if not, leave it to caller to decide
    return out_path


def compress_for_inference(input_path: str, max_size_mb: int = 100, force: bool = False) -> str:
    """Compress video for Roboflow inference while maintaining detection quality.
    
    Strategy:
    - Reduce resolution to 1080p max (detection quality unaffected)
    - Use H.264 codec with optimized settings
    - Maintain aspect ratio
    - Target file size ~100MB for fast API upload
    - Keep original FPS for accurate frame mapping
    
    Args:
        input_path: Path to original video
        max_size_mb: Target maximum file size in MB
        force: Force re-encoding even if size is OK (for codec compatibility)
        
    Returns:
        Path to compressed video file (temp file - caller should delete)
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")
    
    # Check if compression/re-encoding is needed
    size_mb = os.path.getsize(input_path) / (1024 * 1024)
    
    if not force and size_mb <= max_size_mb:
        # Size is OK, but check if codec is compatible
        if not needs_reencoding(input_path):
            print(f"Video is {size_mb:.1f} MB with compatible codec, no processing needed")
            return input_path
        else:
            print(f"Video codec incompatible, re-encoding to H.264...")
    else:
        print(f"Compressing video for inference (current: {size_mb:.1f} MB, target: {max_size_mb} MB)...")
    
    # Create temporary output file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()
    out_path = tmp.name
    
    # Get current video size to determine compression strategy
    current_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    
    # Use 1080p for Render.com Standard Plan (reduced from 1440p)
    target_height = 1080  # 1920x1080 resolution (Render.com optimized)
    
    if current_size_mb > 200:  # More aggressive threshold for Render.com
        # More aggressive CRF for very large files
        crf = 32  # Higher CRF for smaller files (was 30)
        bitrate_limit = '3M'  # Lower bitrate cap for Render.com (was 5M)
        print(f"Compressing large video (1080p, CRF 32) for {current_size_mb:.1f} MB video")
    else:
        # Standard compression for moderate files
        crf = 30  # Higher CRF for Render.com (was 28)
        bitrate_limit = None
        print(f"Using standard compression (1080p, CRF 30) for {current_size_mb:.1f} MB video")
    
    # Compression settings optimized for detection quality
    cmd_args = [
        FFMPEG_BINARY,
        '-y',  # Overwrite output
        '-i', input_path,
        '-vf', f'scale=-2:\'min({target_height},ih)\'',  # Scale to 1440p max
        '-c:v', 'libx264',  # H.264 codec
        '-crf', str(crf),  # Variable quality
        '-preset', 'veryfast',  # Very fast encoding for speed (was 'faster')
        '-pix_fmt', 'yuv420p',  # Compatibility
        '-c:a', 'aac',  # Audio codec
        '-b:a', '64k',  # Lower audio bitrate (not needed for detection)
    ]
    
    # Add bitrate limit for very large files
    if bitrate_limit:
        cmd_args.extend(['-maxrate', bitrate_limit, '-bufsize', '4M'])
    
    cmd_args.extend(['-movflags', '+faststart', out_path])
    
    try:
        print(f"Running ffmpeg compression: {' '.join(cmd_args[:3])}...")
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)
        
        # Check output file size
        if os.path.exists(out_path):
            compressed_size_mb = os.path.getsize(out_path) / (1024 * 1024)
            original_size_mb = os.path.getsize(input_path) / (1024 * 1024)
            reduction = ((original_size_mb - compressed_size_mb) / original_size_mb) * 100
            print(f"✅ Compression complete: {original_size_mb:.1f} MB → {compressed_size_mb:.1f} MB ({reduction:.1f}% reduction)")
            
            # If still too large and we haven't tried aggressive yet, retry with 1080p
            if compressed_size_mb > max_size_mb and target_height > 1080:
                print(f"⚠️  Output still {compressed_size_mb:.1f} MB (target: {max_size_mb} MB), retrying with 1080p...")
                os.remove(out_path)
                
                # Retry with more aggressive settings (1080p)
                tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                tmp2.close()
                out_path2 = tmp2.name
                
                cmd_args_aggressive = [
                    FFMPEG_BINARY, '-y', '-i', input_path,
                    '-vf', 'scale=-2:\'min(1080,ih)\'',  # 1080p fallback
                    '-c:v', 'libx264', '-crf', '32',
                    '-preset', 'faster', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-maxrate', '3M', '-bufsize', '4M',
                    '-movflags', '+faststart', out_path2
                ]
                
                subprocess.check_output(cmd_args_aggressive, stderr=subprocess.STDOUT)
                compressed_size_mb = os.path.getsize(out_path2) / (1024 * 1024)
                print(f"✅ Aggressive compression: {original_size_mb:.1f} MB → {compressed_size_mb:.1f} MB ({((original_size_mb - compressed_size_mb) / original_size_mb) * 100:.1f}% reduction)")
                return out_path2
            
            return out_path
        else:
            raise FileNotFoundError("FFmpeg did not create output file")
            
    except subprocess.CalledProcessError as e:
        # Clean up output if ffmpeg failed
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        
        error_output = e.output.decode('utf-8') if e.output else str(e)
        print(f"❌ FFmpeg compression failed: {error_output}")
        raise FileNotFoundError(f"ffmpeg compression failed: {error_output}")
    except Exception as e:
        # Clean up on any error
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        raise


def get_video_codec(video_path: str) -> str:
    """Get the video codec name (e.g., 'h264', 'hevc', 'vp9').
    
    Uses ffprobe to detect codec. Returns 'unknown' if unable to detect.
    """
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        codec = result.lower()
        print(f'Detected video codec: {codec}')
        return codec
    except Exception as e:
        print(f'Could not detect video codec: {e}')
        return 'unknown'


def needs_reencoding(video_path: str) -> bool:
    """Check if video needs re-encoding for Roboflow compatibility.
    
    DJI drones and some cameras use H.265/HEVC which Roboflow may not accept.
    This function detects incompatible codecs.
    
    Returns True if video should be re-encoded to H.264.
    """
    codec = get_video_codec(video_path)
    
    # Incompatible codecs that need re-encoding
    incompatible_codecs = ['hevc', 'h265', 'vp9', 'av1', 'mpeg2video']
    
    if codec in incompatible_codecs:
        print(f'⚠️  Video codec {codec} is incompatible with Roboflow, re-encoding required')
        return True
    
    print(f'✅ Video codec {codec} is compatible with Roboflow')
    return False


def get_video_fps(video_path: str) -> float:
    """Get the FPS (frames per second) of a video file.
    
    Tries OpenCV first (faster), falls back to ffprobe if unavailable.
    Returns the video FPS, or 30.0 if unable to detect.
    """
    # Try OpenCV first (no external dependencies)
    if _HAS_OPENCV and _cv2 is not None:
        try:
            cap = _cv2.VideoCapture(video_path)
            if cap.isOpened():
                fps = cap.get(_cv2.CAP_PROP_FPS)
                cap.release()
                
                # Sanity check: FPS should be between 1 and 120
                if 1 <= fps <= 120:
                    print(f'Detected original video FPS (OpenCV): {fps:.2f}')
                    return fps
        except Exception as e:
            print(f'OpenCV FPS detection failed: {e}, trying ffprobe...')
    
    # Fall back to ffprobe
    try:
        # Use ffprobe to get video metadata
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        
        # Parse the frame rate (usually in format "30/1" or "30000/1001")
        if '/' in result:
            num, den = result.split('/')
            fps = float(num) / float(den)
        else:
            fps = float(result)
        
        # Sanity check: FPS should be between 1 and 120
        if 1 <= fps <= 120:
            print(f'Detected original video FPS (ffprobe): {fps:.2f}')
            return fps
        else:
            print(f'Unusual FPS detected ({fps}), using fallback: 30.0')
            return 30.0
            
    except Exception as e:
        print(f'Could not detect video FPS: {e}, using fallback: 30.0')
        return 30.0


def get_video_duration(video_path: str) -> Optional[float]:
    """Get the duration of a video file in seconds using ffprobe.
    
    Returns the video duration in seconds, or None if unable to detect.
    """
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        duration = float(result)
        print(f'Detected video duration: {duration:.2f} seconds')
        return duration
    except Exception as e:
        print(f'Could not detect video duration: {e}')
        return None


def get_video_frame_count(video_path: str) -> Optional[int]:
    """Get the total number of frames in a video using ffprobe.
    
    Returns the frame count, or None if unable to detect.
    """
    try:
        cmd_args = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-count_frames',
            '-show_entries', 'stream=nb_read_frames',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = subprocess.check_output(cmd_args, stderr=subprocess.STDOUT).decode('utf-8').strip()
        frame_count = int(result)
        print(f'Detected video frame count: {frame_count} frames')
        return frame_count
    except Exception as e:
        # Fallback: calculate from duration and FPS
        print(f'Could not count frames directly: {e}, calculating from duration and FPS')
        try:
            duration = get_video_duration(video_path)
            fps = get_video_fps(video_path)
            if duration and fps:
                frame_count = int(duration * fps)
                print(f'Calculated frame count: {frame_count} frames')
                return frame_count
        except Exception:
            pass
        return None


# ============================================================================
# OpenCV-based video processing (faster alternatives with automatic fallback)
# ============================================================================

# Check if OpenCV is available
try:
    import cv2 as _cv2
    import numpy as _np
    _HAS_OPENCV = True
    print("OpenCV (cv2) successfully imported for video processing")
except ImportError:
    _HAS_OPENCV = False
    _cv2 = None
    _np = None
    print("OpenCV not available, will use FFmpeg fallback for video processing")


def extract_frames_cv2(video_path: str, target_fps: Optional[float] = None, max_frames: int = 10000) -> Optional[List[str]]:
    """Extract video frames using OpenCV (2-3x faster than FFmpeg).
    
    Returns list of frame file paths in temp directory, or None if OpenCV unavailable.
    Falls back to None to signal caller should use FFmpeg method.
    
    Args:
        video_path: Path to input video file
        target_fps: Target FPS for frame extraction (None = use original FPS)
        max_frames: Maximum number of frames to extract
        
    Returns:
        List of frame file paths, or None if OpenCV not available
    """
    if not _HAS_OPENCV or _cv2 is None:
        print("OpenCV not available, caller should use FFmpeg fallback")
        return None
    
    try:
        cap = _cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Failed to open video with OpenCV: {video_path}")
            return None
        
        # Get video properties
        video_fps = cap.get(_cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT))
        
        print(f"OpenCV video info: {video_fps:.2f} FPS, {total_frames} total frames")
        
        # Calculate which frames to extract (match Roboflow's frame selection)
        # Use time-based calculation to avoid drift
        if target_fps is None or target_fps >= video_fps:
            # Extract all frames
            frame_indices = list(range(min(total_frames, max_frames)))
            effective_fps = video_fps
        else:
            # Extract frames at target FPS using time-based calculation
            # Match Roboflow's method: frame at time t = t * target_fps
            video_duration = total_frames / video_fps
            num_frames = int(video_duration * target_fps)
            num_frames = min(num_frames, max_frames)
            
            # Calculate exact frame indices (same as Roboflow)
            frame_indices = []
            for i in range(num_frames):
                timestamp = i / target_fps  # Time in seconds
                frame_idx = round(timestamp * video_fps)  # Corresponding video frame
                if frame_idx < total_frames:
                    frame_indices.append(frame_idx)
            
            effective_fps = target_fps
        
        print(f"Extracting frames at {effective_fps:.2f} FPS ({len(frame_indices)} frames total)")
        
        # Create temp directory for frames
        tmpdir = tempfile.mkdtemp(prefix='cv2_frames_')
        frame_paths = []
        
        frame_idx = 0
        extracted_count = 0
        frame_indices_set = set(frame_indices)  # For O(1) lookup
        
        while cap.isOpened() and extracted_count < len(frame_indices):
            ret, frame = cap.read()
            if not ret:
                break
            
            # Extract only the specific frames we need
            if frame_idx in frame_indices_set:
                frame_path = os.path.join(tmpdir, f'frame_{extracted_count + 1:06d}.jpg')
                _cv2.imwrite(frame_path, frame, [_cv2.IMWRITE_JPEG_QUALITY, 95])
                frame_paths.append(frame_path)
                extracted_count += 1
            
            frame_idx += 1
        
        cap.release()
        print(f"OpenCV extracted {extracted_count} frames to {tmpdir}")
        
        return frame_paths
        
    except Exception as e:
        print(f"Error in OpenCV frame extraction: {e}")
        import traceback
        traceback.print_exc()
        return None


def stitch_video_cv2(frames_dir: str, fps: float, output_path: str, frame_pattern: str = 'ann_%06d.jpg') -> bool:
    """Stitch frames into video using OpenCV VideoWriter (2-3x faster than FFmpeg).
    
    Args:
        frames_dir: Directory containing frame images
        fps: Output video framerate
        output_path: Path for output video file
        frame_pattern: Frame filename pattern (e.g., 'ann_%06d.jpg')
        
    Returns:
        True if successful, False otherwise
    """
    if not _HAS_OPENCV or _cv2 is None:
        print("OpenCV not available for video stitching")
        return False
    
    try:
        # Find all frames matching pattern
        import re
        pattern_regex = frame_pattern.replace('%06d', r'(\d{6})')
        
        frame_files = []
        for filename in os.listdir(frames_dir):
            if re.match(pattern_regex.replace('.jpg', r'\.jpg$'), filename):
                frame_files.append(filename)
        
        frame_files = sorted(frame_files)
        frame_count = len(frame_files)
        
        if frame_count == 0:
            print(f"No frames found matching pattern {frame_pattern} in {frames_dir}")
            return False
        
        print(f"OpenCV stitching {frame_count} frames at {fps:.2f} FPS")
        
        # Read first frame to get dimensions
        first_frame_path = os.path.join(frames_dir, frame_files[0])
        first_frame = _cv2.imread(first_frame_path)
        if first_frame is None:
            print(f"Failed to read first frame: {first_frame_path}")
            return False
        
        height, width = first_frame.shape[:2]
        print(f"Video dimensions: {width}x{height}")
        
        # Keep 1080p resolution for quality (annotations need to be readable!)
        # Client-side compression will handle file size optimization
        # Ensure even dimensions (required for H.264 encoding later)
        if width % 2 != 0:
            width = width - 1
        if height % 2 != 0:
            height = height - 1
        
        print(f"Stitching at full resolution: {width}x{height} (maintaining quality for annotations)")
        
        # OpenCV VideoWriter - use mp4v for fast encoding
        # Client will compress to H.264 with high quality settings
        fourcc = _cv2.VideoWriter_fourcc(*'mp4v')
        out = _cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        if not out.isOpened():
            print("Failed to open VideoWriter with mp4v codec")
            return False
        
        # Write all frames
        for i, filename in enumerate(frame_files):
            frame_path = os.path.join(frames_dir, filename)
            frame = _cv2.imread(frame_path)
            
            if frame is None:
                print(f"Warning: Failed to read frame {filename}, skipping")
                continue
            
            # Always resize to target dimensions (for resolution reduction + consistency)
            frame = _cv2.resize(frame, (width, height))
            
            out.write(frame)
            
            # Progress update every 100 frames
            if (i + 1) % 100 == 0:
                print(f"Stitched {i + 1}/{frame_count} frames...")
        
        out.release()
        print(f"OpenCV video stitching completed: {output_path}")
        
        # Verify output file exists and get size
        if os.path.exists(output_path):
            uncompressed_size = os.path.getsize(output_path)
            size_mb = uncompressed_size / (1024 * 1024)
            print(f"Stitched video size: {size_mb:.2f} MB (720p, mp4v codec)")
            print(f"✅ Skipping backend compression - client will compress with react-native-compressor")
            
            return True
        else:
            print("Output video file not created")
            return False
        
    except Exception as e:
        print(f"Error in OpenCV video stitching: {e}")
        import traceback
        traceback.print_exc()
        return False


class MotionDetectionSkipper:
    """Smart frame skipping using OpenCV motion detection (cv2.absdiff).
    
    Skips frames with minimal motion to avoid redundant inference calls.
    More sophisticated than simple frame interval - detects actual scene changes.
    """
    
    def __init__(self, motion_threshold: float = 2.0, min_changed_pixels: int = 1000):
        """Initialize motion detector.
        
        Args:
            motion_threshold: Pixel difference threshold (0-255) to consider as motion
            min_changed_pixels: Minimum number of changed pixels to consider frame as having motion
        """
        self.motion_threshold = motion_threshold
        self.min_changed_pixels = min_changed_pixels
        self.prev_frame = None
        self.total_frames = 0
        self.skipped_frames = 0
        self.motion_frames = 0
        
        if not _HAS_OPENCV:
            print("Warning: OpenCV not available, motion detection disabled")
    
    def has_motion(self, frame_path: str) -> bool:
        """Check if frame has significant motion compared to previous frame.
        
        Args:
            frame_path: Path to current frame image
            
        Returns:
            True if motion detected (or first frame), False if static
        """
        if not _HAS_OPENCV or _cv2 is None:
            # Always process if OpenCV not available
            return True
        
        self.total_frames += 1
        
        try:
            # Read current frame
            current_frame = _cv2.imread(frame_path, _cv2.IMREAD_GRAYSCALE)
            if current_frame is None:
                print(f"Warning: Failed to read frame {frame_path}")
                return True  # Process on error
            
            # First frame - always process
            if self.prev_frame is None:
                self.prev_frame = current_frame
                self.motion_frames += 1
                return True
            
            # Resize frames to same size if needed (handle variable resolution)
            if current_frame.shape != self.prev_frame.shape:
                current_frame = _cv2.resize(current_frame, 
                                           (self.prev_frame.shape[1], self.prev_frame.shape[0]))
            
            # Calculate absolute difference
            diff = _cv2.absdiff(self.prev_frame, current_frame)
            
            # Threshold difference to get binary mask of changed pixels
            _, thresh = _cv2.threshold(diff, self.motion_threshold, 255, _cv2.THRESH_BINARY)
            
            # Count number of changed pixels
            changed_pixels = _np.sum(thresh > 0)
            
            # Update previous frame
            self.prev_frame = current_frame
            
            # Check if motion exceeds threshold
            has_motion = changed_pixels >= self.min_changed_pixels
            
            if has_motion:
                self.motion_frames += 1
            else:
                self.skipped_frames += 1
            
            return has_motion
            
        except Exception as e:
            print(f"Error in motion detection: {e}")
            return True  # Process on error
    
    def reset(self):
        """Reset motion detector state."""
        self.prev_frame = None
        self.total_frames = 0
        self.skipped_frames = 0
        self.motion_frames = 0
    
    def get_stats(self) -> dict:
        """Get motion detection statistics."""
        skip_rate = (self.skipped_frames / self.total_frames * 100) if self.total_frames > 0 else 0
        return {
            'total_frames': self.total_frames,
            'motion_frames': self.motion_frames,
            'skipped_frames': self.skipped_frames,
            'skip_rate': f"{skip_rate:.1f}%"
        }


class ObjectTracker:
    """Track detected objects across video frames using OpenCV trackers.
    
    Helps maintain consistent IDs for objects and smooth their bounding boxes,
    reducing jitter and false positives from frame-to-frame detection inconsistencies.
    """
    
    def __init__(self, tracker_type: str = 'CSRT', confidence_decay: float = 0.95):
        """Initialize object tracker.
        
        Args:
            tracker_type: Type of OpenCV tracker ('KCF', 'CSRT', 'MOSSE')
                - KCF: Fast, good for real-time (recommended)
                - CSRT: More accurate but slower
                - MOSSE: Fastest but less accurate
            confidence_decay: Confidence decay rate per frame (0.9-0.99)
        """
        self.tracker_type = tracker_type
        self.confidence_decay = confidence_decay
        self.active_tracks = []  # List of (tracker, bbox, class, confidence, age) tuples
        self.next_track_id = 0
        self.has_opencv = _HAS_OPENCV
        
        if not _HAS_OPENCV:
            print("Warning: OpenCV not available, object tracking disabled")
    
    def _create_tracker(self):
        """Create a new tracker instance."""
        if not self.has_opencv or _cv2 is None:
            return None
        
        try:
            if self.tracker_type == 'KCF':
                # Legacy tracker (deprecated but widely compatible)
                try:
                    return _cv2.legacy.TrackerKCF_create()
                except AttributeError:
                    # Older OpenCV versions
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
                print(f"Unknown tracker type: {self.tracker_type}, using KCF")
                try:
                    return _cv2.legacy.TrackerKCF_create()
                except AttributeError:
                    return _cv2.TrackerKCF_create()
        except Exception as e:
            print(f"Failed to create tracker: {e}")
            return None
    
    def update(self, frame_path: str, new_detections: List[dict]) -> List[dict]:
        """Update trackers with new frame and detections.
        
        Args:
            frame_path: Path to current frame image
            new_detections: List of new detections from inference
                Each detection: {'class': str, 'confidence': float, 'bbox': [x, y, w, h]}
        
        Returns:
            Smoothed/tracked detections with consistent tracking
        """
        if not self.has_opencv or _cv2 is None:
            # Return detections as-is if tracking unavailable
            return new_detections
        
        try:
            # Read current frame
            frame = _cv2.imread(frame_path)
            if frame is None:
                print(f"Warning: Failed to read frame for tracking: {frame_path}")
                return new_detections
            
            # Update existing trackers
            updated_tracks = []
            for tracker, bbox, cls, conf, age in self.active_tracks:
                success, new_bbox = tracker.update(frame)
                
                if success:
                    # Convert bbox format from (x, y, w, h) tuple to list
                    x, y, w, h = new_bbox
                    updated_bbox = [float(x), float(y), float(w), float(h)]
                    
                    # Decay confidence over time
                    new_conf = conf * self.confidence_decay
                    
                    # Keep track if confidence still reasonable
                    if new_conf > 0.2 and age < 30:  # Max 30 frames without detection
                        updated_tracks.append((tracker, updated_bbox, cls, new_conf, age + 1))
            
            # Match new detections to existing tracks (IoU-based matching)
            matched_detections = []
            unmatched_detections = []
            matched_tracks = set()
            
            for det in new_detections:
                det_bbox = det['bbox']
                det_class = det['class']
                det_conf = det['confidence']
                
                # Find best matching track (same class, highest IoU)
                best_iou = 0.3  # Minimum IoU threshold for matching
                best_track_idx = -1
                
                for idx, (tracker, track_bbox, track_class, track_conf, age) in enumerate(updated_tracks):
                    if track_class != det_class or idx in matched_tracks:
                        continue
                    
                    # Calculate IoU
                    iou = self._calculate_iou(det_bbox, track_bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_track_idx = idx
                
                if best_track_idx >= 0:
                    # Match found - update track with new detection
                    matched_tracks.add(best_track_idx)
                    tracker, track_bbox, track_class, track_conf, age = updated_tracks[best_track_idx]
                    
                    # Blend tracked bbox with detected bbox (smoothing)
                    alpha = 0.7  # Weight for new detection (0.7 = 70% new, 30% tracked)
                    smoothed_bbox = [
                        alpha * det_bbox[i] + (1 - alpha) * track_bbox[i]
                        for i in range(4)
                    ]
                    
                    # Re-initialize tracker with new detection
                    new_tracker = self._create_tracker()
                    if new_tracker is not None:
                        bbox_tuple = (int(smoothed_bbox[0]), int(smoothed_bbox[1]), 
                                     int(smoothed_bbox[2]), int(smoothed_bbox[3]))
                        new_tracker.init(frame, bbox_tuple)
                        updated_tracks[best_track_idx] = (new_tracker, smoothed_bbox, track_class, det_conf, 0)
                    
                    matched_detections.append({
                        'class': track_class,
                        'confidence': det_conf,  # Use new confidence
                        'bbox': smoothed_bbox
                    })
                else:
                    # No match - new object appeared
                    unmatched_detections.append(det)
            
            # Add unmatched detections as new tracks
            for det in unmatched_detections:
                tracker = self._create_tracker()
                if tracker is not None:
                    bbox = det['bbox']
                    bbox_tuple = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
                    tracker.init(frame, bbox_tuple)
                    updated_tracks.append((tracker, bbox, det['class'], det['confidence'], 0))
                    matched_detections.append(det)
            
            # Keep tracks that weren't matched but still tracked successfully
            for idx, (tracker, track_bbox, track_class, track_conf, age) in enumerate(updated_tracks):
                if idx not in matched_tracks and track_conf > 0.3:
                    # Include tracked object even without new detection
                    matched_detections.append({
                        'class': track_class,
                        'confidence': track_conf,
                        'bbox': track_bbox
                    })
            
            self.active_tracks = updated_tracks
            return matched_detections
            
        except Exception as e:
            print(f"Error in object tracking: {e}")
            import traceback
            traceback.print_exc()
            return new_detections
    
    def _calculate_iou(self, bbox1: List[float], bbox2: List[float]) -> float:
        """Calculate IoU between two bboxes [x, y, w, h]."""
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
        """Reset all tracks."""
        self.active_tracks = []
        self.next_track_id = 0


class TemporalConsistencyFilter:
    """Filter detections based on temporal consistency across frames.
    
    Reduces false positives by requiring objects to appear in multiple
    consecutive frames before being considered valid.
    """
    
    def __init__(self, min_appearances: int = 3, max_gap: int = 5):
        """Initialize temporal filter.
        
        Args:
            min_appearances: Minimum frames an object must appear in to be valid
            max_gap: Maximum frame gap allowed between appearances
        """
        self.min_appearances = min_appearances
        self.max_gap = max_gap
        self.detection_history = {}  # bbox_key -> (count, last_frame_idx, bbox, class, conf)
        self.current_frame_idx = 0
    
    def filter(self, detections: List[dict]) -> List[dict]:
        """Filter detections based on temporal consistency.
        
        Args:
            detections: List of detections for current frame
        
        Returns:
            Filtered list of consistent detections
        """
        # Update frame index
        self.current_frame_idx += 1
        
        # Remove old entries that haven't appeared recently
        expired_keys = []
        for key, (count, last_frame, bbox, cls, conf) in self.detection_history.items():
            if self.current_frame_idx - last_frame > self.max_gap:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.detection_history[key]
        
        # Process current detections
        current_keys = set()
        filtered_detections = []
        
        for det in detections:
            bbox = det['bbox']
            cls = det['class']
            conf = det['confidence']
            
            # Create a spatial key (grid-based to handle slight movement)
            # Divide frame into 20x20 pixel grid cells
            grid_x = int(bbox[0] / 20)
            grid_y = int(bbox[1] / 20)
            grid_w = int(bbox[2] / 20)
            grid_h = int(bbox[3] / 20)
            key = f"{cls}_{grid_x}_{grid_y}_{grid_w}_{grid_h}"
            current_keys.add(key)
            
            # Check if this detection has history
            if key in self.detection_history:
                count, last_frame, old_bbox, old_cls, old_conf = self.detection_history[key]
                new_count = count + 1
                
                # Update history
                self.detection_history[key] = (new_count, self.current_frame_idx, bbox, cls, max(conf, old_conf))
                
                # Include detection if it meets minimum appearances
                if new_count >= self.min_appearances:
                    filtered_detections.append(det)
            else:
                # New detection - add to history but don't include yet
                self.detection_history[key] = (1, self.current_frame_idx, bbox, cls, conf)
                
                # For high-confidence detections, reduce requirement
                if conf > 0.8:
                    filtered_detections.append(det)
        
        return filtered_detections
    
    def reset(self):
        """Reset filter state."""
        self.detection_history = {}
        self.current_frame_idx = 0


class BackgroundSubtractor:
    """Use background subtraction to identify moving objects (potential weeds swaying).
    
    Helps distinguish static objects from moving ones, useful for filtering
    out false positives from static background elements.
    """
    
    def __init__(self, learning_rate: float = 0.01, var_threshold: int = 16):
        """Initialize background subtractor.
        
        Args:
            learning_rate: How quickly to adapt to new background (0.001-0.1)
            var_threshold: Threshold for foreground detection (lower = more sensitive)
        """
        self.learning_rate = learning_rate
        self.var_threshold = var_threshold
        self.bg_subtractor = None
        self.has_opencv = _HAS_OPENCV
        
        if self.has_opencv and _cv2 is not None:
            try:
                self.bg_subtractor = _cv2.createBackgroundSubtractorMOG2(
                    detectShadows=True,
                    varThreshold=var_threshold
                )
                print(f"Background subtractor initialized (MOG2, threshold={var_threshold})")
            except Exception as e:
                print(f"Failed to initialize background subtractor: {e}")
                self.bg_subtractor = None
        else:
            print("Warning: OpenCV not available, background subtraction disabled")
    
    def is_moving(self, frame_path: str, bbox: List[float]) -> bool:
        """Check if object in bounding box is moving.
        
        Args:
            frame_path: Path to current frame
            bbox: Bounding box [x, y, w, h]
        
        Returns:
            True if object appears to be moving, False if static
        """
        if not self.has_opencv or self.bg_subtractor is None or _cv2 is None:
            # If unavailable, assume all objects are moving
            return True
        
        try:
            # Read frame
            frame = _cv2.imread(frame_path)
            if frame is None:
                return True
            
            # Apply background subtraction
            fg_mask = self.bg_subtractor.apply(frame, learningRate=self.learning_rate)
            
            # Extract region of interest (ROI) from mask
            x, y, w, h = [int(v) for v in bbox]
            
            # Ensure bbox is within frame bounds
            h_frame, w_frame = fg_mask.shape[:2]
            x = max(0, min(x, w_frame - 1))
            y = max(0, min(y, h_frame - 1))
            w = max(1, min(w, w_frame - x))
            h = max(1, min(h, h_frame - y))
            
            roi_mask = fg_mask[y:y+h, x:x+w]
            
            # Calculate percentage of foreground pixels in ROI
            if roi_mask.size == 0:
                return True
            
            foreground_pixels = _np.sum(roi_mask > 0)
            total_pixels = roi_mask.size
            foreground_ratio = foreground_pixels / total_pixels
            
            # Consider moving if >10% of pixels are foreground
            return foreground_ratio > 0.10
            
        except Exception as e:
            print(f"Error in background subtraction: {e}")
            return True
    
    def reset(self):
        """Reset background model."""
        if self.bg_subtractor is not None:
            # Re-create the subtractor to clear history
            try:
                self.bg_subtractor = _cv2.createBackgroundSubtractorMOG2(
                    detectShadows=True,
                    varThreshold=self.var_threshold
                )
            except Exception:
                pass

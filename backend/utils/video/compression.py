import os
import subprocess
import tempfile

from backend.config.settings import FFMPEG_BINARY
from backend.utils.video.video_probe import needs_reencoding


def compress_for_inference(input_path: str, max_size_mb: int = 100, force: bool = False) -> str:
    """Compress video for inference while preserving detection quality."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f'Input video not found: {input_path}')

    size_mb = os.path.getsize(input_path) / (1024 * 1024)

    if not force and size_mb <= max_size_mb:
        if not needs_reencoding(input_path):
            print(f'Video is {size_mb:.1f} MB with compatible codec, no processing needed')
            return input_path
        print('Video codec incompatible, re-encoding to H.264...')
    else:
        print(f'Compressing video for inference (current: {size_mb:.1f} MB, target: {max_size_mb} MB)...')

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    tmp.close()
    out_path = tmp.name

    current_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    target_height = 1080

    if current_size_mb > 200:
        crf = 32
        bitrate_limit = '3M'
        print(f'Compressing large video (1080p, CRF 32) for {current_size_mb:.1f} MB video')
    else:
        crf = 30
        bitrate_limit = None
        print(f'Using standard compression (1080p, CRF 30) for {current_size_mb:.1f} MB video')

    cmd_args = [
        FFMPEG_BINARY,
        '-y',
        '-i',
        input_path,
        '-vf',
        f"scale=-2:'min({target_height},ih)'",
        '-c:v',
        'libx264',
        '-crf',
        str(crf),
        '-preset',
        'veryfast',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        '64k',
    ]

    if bitrate_limit:
        cmd_args.extend(['-maxrate', bitrate_limit, '-bufsize', '4M'])

    cmd_args.extend(['-movflags', '+faststart', out_path])

    try:
        print(f"Running ffmpeg compression: {' '.join(cmd_args[:3])}...")
        subprocess.check_output(cmd_args, stderr=subprocess.STDOUT)

        if os.path.exists(out_path):
            compressed_size_mb = os.path.getsize(out_path) / (1024 * 1024)
            original_size_mb = os.path.getsize(input_path) / (1024 * 1024)
            reduction = ((original_size_mb - compressed_size_mb) / original_size_mb) * 100
            print(f'Compression complete: {original_size_mb:.1f} MB -> {compressed_size_mb:.1f} MB ({reduction:.1f}% reduction)')

            if compressed_size_mb > max_size_mb and target_height > 1080:
                print(f'Output still {compressed_size_mb:.1f} MB (target: {max_size_mb} MB), retrying with 1080p...')
                os.remove(out_path)
                tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
                tmp2.close()
                out_path2 = tmp2.name

                cmd_args_aggressive = [
                    FFMPEG_BINARY,
                    '-y',
                    '-i',
                    input_path,
                    '-vf',
                    "scale=-2:'min(1080,ih)'",
                    '-c:v',
                    'libx264',
                    '-crf',
                    '32',
                    '-preset',
                    'faster',
                    '-pix_fmt',
                    'yuv420p',
                    '-c:a',
                    'aac',
                    '-b:a',
                    '64k',
                    '-maxrate',
                    '3M',
                    '-bufsize',
                    '4M',
                    '-movflags',
                    '+faststart',
                    out_path2,
                ]

                subprocess.check_output(cmd_args_aggressive, stderr=subprocess.STDOUT)
                compressed_size_mb = os.path.getsize(out_path2) / (1024 * 1024)
                print(
                    f"Aggressive compression: {original_size_mb:.1f} MB -> {compressed_size_mb:.1f} MB "
                    f"({((original_size_mb - compressed_size_mb) / original_size_mb) * 100:.1f}% reduction)"
                )
                return out_path2

            return out_path

        raise FileNotFoundError('FFmpeg did not create output file')

    except subprocess.CalledProcessError as e:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        error_output = e.output.decode('utf-8') if e.output else str(e)
        print(f'FFmpeg compression failed: {error_output}')
        raise FileNotFoundError(f'ffmpeg compression failed: {error_output}')
    except Exception:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        raise

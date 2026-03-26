import os
from typing import Optional, Dict, Any
import cloudinary
import cloudinary.uploader
from ..config.settings import (
    CLOUDINARY_URL,
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    ANNOTATED_IMAGE_MAX_WIDTH,
    ANNOTATED_IMAGE_JPEG_QUALITY,
    ANNOTATED_VIDEO_HEIGHT,
    ANNOTATED_VIDEO_BITRATE,
)


def _ensure_configured() -> None:
    # Prefer discrete credentials if provided
    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True,
        )
        return
    # Fall back to URL string
    if CLOUDINARY_URL:
        # Some SDK versions may not accept cloudinary_url kw; parse manually if needed
        try:
            cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
            return
        except TypeError:
            # Manual parse: cloudinary://<api_key>:<api_secret>@<cloud_name>
            try:
                import re
                m = re.match(r"^cloudinary://([^:]+):([^@]+)@([^/]+)$", CLOUDINARY_URL)
                if m:
                    api_key, api_secret, cloud_name = m.groups()
                    cloudinary.config(
                        cloud_name=cloud_name,
                        api_key=api_key,
                        api_secret=api_secret,
                        secure=True,
                    )
                    return
            except Exception:
                pass
    raise RuntimeError("Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET or CLOUDINARY_URL.")


def upload_image_bytes(name: str, data: bytes, folder: str = "uploads", annotate: bool = False) -> Dict[str, Any]:
    _ensure_configured()
    options: Dict[str, Any] = {
        "folder": folder,
        "public_id": os.path.splitext(name)[0],
        "resource_type": "image",
        "overwrite": True,
    }
    if annotate:
        # Delivery transformation for compressed annotated preview
        options.update({
            "transformation": [
                {"width": ANNOTATED_IMAGE_MAX_WIDTH, "crop": "limit"},
                {"quality": ANNOTATED_IMAGE_JPEG_QUALITY, "fetch_format": "jpg"},
            ]
        })
    result = cloudinary.uploader.upload(data, **options)
    # Determine annotated URL (if transformations/eager present) for convenience
    annotated_url = None
    try:
        if result.get('eager') and isinstance(result.get('eager'), list) and result['eager'][0].get('secure_url'):
            annotated_url = result['eager'][0]['secure_url']
    except Exception:
        annotated_url = None
    if not annotated_url:
        annotated_url = result.get('secure_url')
    result['annotated_url'] = annotated_url
    return result


def upload_video_streaming(temp_path: str, name: str, folder: str = "uploads", annotate: bool = False) -> Dict[str, Any]:
    _ensure_configured()
    options: Dict[str, Any] = {
        "folder": folder,
        "public_id": os.path.splitext(name)[0],
        "resource_type": "video",
        "overwrite": True,
    }
    if annotate:
        # Delivery transformation for compressed annotated preview
        options.update({
            "eager": [{
                "height": ANNOTATED_VIDEO_HEIGHT,
                "crop": "limit",
                "bit_rate": ANNOTATED_VIDEO_BITRATE,
                "format": "mp4",
                "video_codec": "auto",
            }],
            "eager_async": True,
        })
    # Increase chunk size for faster uploads on good networks (Cloudinary supports up to ~100MB chunks)
    result = cloudinary.uploader.upload_large(temp_path, chunk_size=50_000_000, **options)
    # upload_large may include 'eager' with transformation secure_url(s)
    annotated_url = None
    try:
        if result.get('eager') and isinstance(result.get('eager'), list) and result['eager'][0].get('secure_url'):
            annotated_url = result['eager'][0]['secure_url']
    except Exception:
        annotated_url = None
    if not annotated_url:
        annotated_url = result.get('secure_url')
    result['annotated_url'] = annotated_url
    return result


def build_delivery_url(public_id: str, resource_type: str = "image", annotated: bool = True) -> str:
    _ensure_configured()
    from cloudinary.utils import cloudinary_url
    if resource_type == "image":
        url, _ = cloudinary_url(public_id, resource_type="image", secure=True, transformation=[
            {"width": ANNOTATED_IMAGE_MAX_WIDTH, "crop": "limit"},
            {"quality": ANNOTATED_IMAGE_JPEG_QUALITY, "fetch_format": "jpg"},
        ])
        return url
    else:
        url, _ = cloudinary_url(public_id, resource_type="video", secure=True, transformation=[
            {"height": ANNOTATED_VIDEO_HEIGHT, "crop": "limit"},
            {"bit_rate": ANNOTATED_VIDEO_BITRATE},
            {"video_codec": "auto", "format": "mp4"},
        ])
        return url


def upload_remote_url(remote_url: str, name: str, folder: str = "uploads", resource_type: str = "image", annotate: bool = False) -> Dict[str, Any]:
    """Tell Cloudinary to fetch a remote URL and store it in the account.

    This is useful when an external service (e.g., Roboflow) provides a hosted annotated
    asset URL. Cloudinary will fetch and store it under the provided public_id.
    """
    _ensure_configured()
    options: Dict[str, Any] = {
        "folder": folder,
        "public_id": os.path.splitext(name)[0],
        "resource_type": resource_type,
        "overwrite": True,
    }
    if annotate:
        # If requested, include the same delivery transformations used for annotated previews
        if resource_type == "image":
            options.update({
                "transformation": [
                    {"width": ANNOTATED_IMAGE_MAX_WIDTH, "crop": "limit"},
                    {"quality": ANNOTATED_IMAGE_JPEG_QUALITY, "fetch_format": "jpg"},
                ]
            })
        else:
            options.update({
                "eager": [{
                    "height": ANNOTATED_VIDEO_HEIGHT,
                    "crop": "limit",
                    "bit_rate": ANNOTATED_VIDEO_BITRATE,
                    "format": "mp4",
                    "video_codec": "auto",
                }],
                "eager_async": True,
            })

    # Cloudinary uploader can accept a remote URL as the first argument
    result = cloudinary.uploader.upload(remote_url, **options)

    # Normalize annotated_url like other helpers
    annotated_url = None
    try:
        if result.get('eager') and isinstance(result.get('eager'), list) and result['eager'][0].get('secure_url'):
            annotated_url = result['eager'][0]['secure_url']
    except Exception:
        annotated_url = None
    if not annotated_url:
        annotated_url = result.get('secure_url')
    result['annotated_url'] = annotated_url
    return result



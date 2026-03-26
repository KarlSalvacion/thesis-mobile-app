def dict_to_detection_tuple(row: dict) -> list:
    """Convert detection dict to frontend tuple format (21 fields)."""
    return [
        row['id'],
        row['filename'],
        row['timestamp'],
        row['file_type'],
        row.get('summary'),
        row.get('total_frames', 0),
        row.get('total_detections', 0),
        row.get('processing_time', 0.0),
        row.get('input_size_bytes'),
        row.get('result_size_bytes'),
        row.get('has_srt_data', False),
        row.get('cloud_public_id'),
        row.get('cloud_resource_type'),
        row.get('cloud_secure_url'),
        row.get('cloud_annotated_url'),
        row.get('weed_class_counts'),
        row.get('has_gps_data', False),
        row.get('bounds_min_lat'),
        row.get('bounds_max_lat'),
        row.get('bounds_min_lng'),
        row.get('bounds_max_lng'),
    ]


def detection_details_to_tuples(detection_details: list[dict]) -> list[list]:
    """Convert detection_details dict rows to frontend tuple format."""
    tuples = []
    for detail in detection_details:
        tuples.append(
            [
                detail['id'],
                detail['detection_id'],
                detail['frame_number'],
                detail['weed_class'],
                detail['confidence'],
                detail['bbox_x'],
                detail['bbox_y'],
                detail['bbox_width'],
                detail['bbox_height'],
                detail.get('normalized_bbox_x'),
                detail.get('normalized_bbox_y'),
                detail.get('normalized_bbox_width'),
                detail.get('normalized_bbox_height'),
                detail['detection_timestamp'],
                detail.get('latitude'),
                detail.get('longitude'),
                detail.get('altitude'),
            ]
        )
    return tuples


def srt_track_to_tuple(srt_track: dict | None) -> list | None:
    """Convert srt_track dict to frontend tuple format."""
    if not srt_track:
        return None

    return [
        srt_track['detection_id'],
        srt_track['point_count'],
        srt_track.get('start_time'),
        srt_track.get('end_time'),
        srt_track.get('bounds_geojson'),
        srt_track['path_geojson'],
        srt_track['frames_json'],
    ]

from math import radians, sin, cos, asin, sqrt


def _calculate_iou(box1, box2):
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    x_left = max(x1, x2)
    y_top = max(y1, y2)
    x_right = min(x1 + w1, x2 + w2)
    y_bottom = min(y1 + h1, y2 + h2)
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    union = w1 * h1 + w2 * h2 - inter
    return inter / union if union > 0 else 0.0


def _calculate_gps_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return 6371000 * c


def calculate_unique_weeds_impl(get_db_connection, real_dict_cursor, detection_id, iou_threshold=0.58, frame_gap=13):
    """Calculate unique weed count by tracking weeds across frames.

    Kept behavior-identical with the previous in-module implementation.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=real_dict_cursor)
        cursor.execute(
            """
            SELECT id, frame_number, weed_class, confidence,
                   bbox_x, bbox_y, bbox_width, bbox_height,
                   latitude, longitude
            FROM detection_details
            WHERE detection_id = %s
            ORDER BY frame_number, id
        """,
            (detection_id,),
        )

        rows = cursor.fetchall()

    if not rows:
        return {
            "unique_count": 0,
            "total_detections": 0,
            "tracks": [],
            "by_class": {},
            "reduction_percentage": 0,
        }

    detections = []
    for r in rows:
        detections.append(
            {
                "id": r["id"],
                "frame": r["frame_number"],
                "class": r["weed_class"],
                "confidence": r["confidence"],
                "bbox": (r["bbox_x"], r["bbox_y"], r["bbox_width"], r["bbox_height"]),
                "lat": r["latitude"],
                "lon": r["longitude"],
            }
        )

    tracks = []
    gps_match_threshold_m = 0.42
    min_match_score = 0.47

    has_gps = any(det["lat"] is not None for det in detections)
    print(f"[UNIQUE WEEDS] Processing {len(detections)} detections, GPS available: {has_gps}")
    print(f"[UNIQUE WEEDS] Using iou_threshold={iou_threshold}, frame_gap={frame_gap}")

    if not has_gps:
        iou_threshold = max(0.3, iou_threshold - 0.2)
        frame_gap = int(frame_gap * 1.8)
        min_match_score = 0.3
        print(
            f"[UNIQUE WEEDS] Adjusted for non-GPS: "
            f"iou_threshold={iou_threshold}, frame_gap={frame_gap}, min_score={min_match_score}"
        )

    for det in detections:
        matched_track = None
        best_score = 0.0

        for tr in tracks:
            if tr["class"] != det["class"]:
                continue
            if det["frame"] - tr["last_frame"] > frame_gap:
                continue

            iou = _calculate_iou(det["bbox"], tr["last_bbox"])

            pixel_dist = None
            if not has_gps:
                det_center_x = det["bbox"][0] + det["bbox"][2] / 2
                det_center_y = det["bbox"][1] + det["bbox"][3] / 2
                tr_center_x = tr["last_bbox"][0] + tr["last_bbox"][2] / 2
                tr_center_y = tr["last_bbox"][1] + tr["last_bbox"][3] / 2
                pixel_dist = ((det_center_x - tr_center_x) ** 2 + (det_center_y - tr_center_y) ** 2) ** 0.5

            gps_dist = None
            if det["lat"] is not None and tr.get("last_lat") is not None:
                gps_dist = _calculate_gps_distance(det["lat"], det["lon"], tr["last_lat"], tr["last_lon"])

            score = 0.0
            if iou >= iou_threshold:
                if gps_dist is not None and gps_dist <= gps_match_threshold_m:
                    score = iou * 1.7
                elif gps_dist is not None and gps_dist <= gps_match_threshold_m * 2.1:
                    score = iou * 1.25
                elif gps_dist is not None and gps_dist > gps_match_threshold_m * 2.6:
                    score = iou * 0.3
                else:
                    if iou >= 0.75:
                        score = iou * 1.5
                    elif iou >= 0.65:
                        score = iou * 1.3
                    else:
                        score = iou * 1.15
            elif gps_dist is not None and gps_dist <= gps_match_threshold_m * 0.55:
                score = 0.42
            elif pixel_dist is not None and iou >= iou_threshold * 0.7:
                avg_bbox_size = (det["bbox"][2] + det["bbox"][3]) / 2
                if pixel_dist < avg_bbox_size * 2.3:
                    score = 0.52 / (1.0 + pixel_dist / avg_bbox_size)
                else:
                    score = 0.0

            if score > best_score and score >= min_match_score:
                best_score = score
                matched_track = tr

        if matched_track is not None:
            matched_track["detections"].append(det)
            matched_track["detection_ids"].append(det["id"])
            matched_track["last_frame"] = det["frame"]
            matched_track["last_bbox"] = det["bbox"]
            if det["lat"] is not None:
                matched_track["last_lat"] = det["lat"]
                matched_track["last_lon"] = det["lon"]
            matched_track["count"] += 1
            matched_track["avg_confidence"] = (
                matched_track["avg_confidence"] * (matched_track["count"] - 1) + det["confidence"]
            ) / matched_track["count"]
        else:
            tracks.append(
                {
                    "class": det["class"],
                    "detections": [det],
                    "detection_ids": [det["id"]],
                    "first_frame": det["frame"],
                    "last_frame": det["frame"],
                    "last_bbox": det["bbox"],
                    "last_lat": det["lat"],
                    "last_lon": det["lon"],
                    "count": 1,
                    "avg_confidence": det["confidence"],
                }
            )

    unique_count = len(tracks)
    by_class = {}
    for tr in tracks:
        by_class[tr["class"]] = by_class.get(tr["class"], 0) + 1

    reduction = round((1 - unique_count / len(detections)) * 100, 1) if detections else 0

    return {
        "unique_count": unique_count,
        "total_detections": len(detections),
        "tracks": tracks,
        "by_class": by_class,
        "reduction_percentage": reduction,
    }

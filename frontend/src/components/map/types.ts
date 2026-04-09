export type DetectionRow = [
  id: number,
  filename: string,
  timestamp: string,
  file_type: string,
  summary: string | null,
  total_frames: number,
  total_detections: number,
  processing_time: number,
  input_size_bytes: number | null,
  result_size_bytes: number | null,
  has_srt_data: boolean | null
]

export type GMapPoint = { lat: number; lng: number }

export type PolylineBounds = {
  min_lat: number
  min_lng: number
  max_lat: number
  max_lng: number
}

export type PolylineResponse = {
  detection_id: number
  points: GMapPoint[]
  bounds?: PolylineBounds | null
}

export type DetectionDetailRow = [
  id: number,
  detection_id: number,
  frame_number: number,
  weed_class: string,
  confidence: number,
  bbox_x: number,
  bbox_y: number,
  bbox_width: number,
  bbox_height: number,
  normalized_bbox_x: number | null,
  normalized_bbox_y: number | null,
  normalized_bbox_width: number | null,
  normalized_bbox_height: number | null,
  detection_timestamp: string
]

export type HeatPoint = { lat: number; lng: number; weight: number }

export type DensityStats = {
  low: number
  medium: number
  high: number
  gpsPoints: number
}

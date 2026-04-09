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

export type FrameMetadataRow = [
  id: number,
  detection_id: number,
  frame_number: number,
  timestamp: string,
  latitude: number | null,
  longitude: number | null,
  altitude: number | null,
  relative_altitude: number | null,
  iso: number | null,
  shutter_speed: string | null,
  f_number: number | null,
  exposure_value: number | null,
  focal_length: number | null,
  color_temperature: number | null,
]

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

export type UniqueWeedPayload = {
  unique_weed_count: number
  total_detections: number
  no_gps_data?: boolean
  [key: string]: any
}

export type SummarySpecies = {
  name: string
  count: number
  confidence: number
  color: string
}

export type DetectionSummary = {
  totalWeeds: number
  confidence: number
  timestamp: string
  species: SummarySpecies[]
}

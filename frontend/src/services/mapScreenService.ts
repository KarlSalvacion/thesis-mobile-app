import { API_BASE } from '../config'
import { DetectionDetailRow, DetectionRow, DensityStats, GMapPoint, HeatPoint, PolylineResponse } from '../components/map/types'

export type MapDataPayload = {
  details: DetectionDetailRow[]
  polyline: GMapPoint[]
  heatPoints: HeatPoint[]
  bounds: PolylineResponse['bounds']
  uniqueWeedCount: number
  totalDetections: number
}

export function createEmptyMapData(): MapDataPayload {
  return {
    details: [],
    polyline: [],
    heatPoints: [],
    bounds: null,
    uniqueWeedCount: 0,
    totalDetections: 0,
  }
}

export async function fetchMapDataForDetection(detection: DetectionRow): Promise<MapDataPayload> {
  const detId = detection[0]

  const res2 = await fetch(`${API_BASE}/detection/${detId}`)
  if (!res2.ok) throw new Error('Failed to fetch detection session')
  const j2 = await res2.json()

  const detectionTuple = j2?.detection ?? []
  ;(detection as any).cloud_secure_url = detectionTuple[13]
  ;(detection as any).cloud_annotated_url = detectionTuple[14]

  const payload: MapDataPayload = {
    details: (j2?.detection_details ?? []) as DetectionDetailRow[],
    polyline: [],
    heatPoints: [],
    bounds: null,
    uniqueWeedCount: 0,
    totalDetections: 0,
  }

  if (!detection[10]) {
    return payload
  }

  const res3 = await fetch(`${API_BASE}/detection/${detId}/gmap-polyline`)
  if (!res3.ok) {
    return payload
  }

  const j3: PolylineResponse = await res3.json()
  payload.polyline = j3?.points ?? []
  payload.bounds = j3?.bounds ?? null

  const res4 = await fetch(
    `${API_BASE}/detection/${detId}/unique-weeds-heatmap?grid_size_m=2.0&iou_threshold=0.58&frame_gap=13`
  )

  if (!res4.ok) {
    return payload
  }

  const j4 = await res4.json()
  payload.heatPoints = (j4?.points ?? []).map((point: any) => ({
    lat: point.lat,
    lng: point.lng,
    weight: point.unique_count || point.weight || 1,
  }))
  payload.uniqueWeedCount = j4?.unique_weed_count ?? 0
  payload.totalDetections = j4?.total_detections ?? 0

  return payload
}

export function computeDensityStats(heatPoints: HeatPoint[], polyline: GMapPoint[]): DensityStats {
  if (heatPoints.length === 0) {
    return { low: 0, medium: 0, high: 0, gpsPoints: polyline.length }
  }

  let low = 0
  let medium = 0
  let high = 0

  heatPoints.forEach((point) => {
    const weedCount = point.weight
    if (weedCount <= 2) {
      low += weedCount
    } else if (weedCount === 3) {
      medium += weedCount
    } else {
      high += weedCount
    }
  })

  return { low, medium, high, gpsPoints: polyline.length }
}

export function formatDateTime(ts?: string | null) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    const dateStr = d.toLocaleDateString()
    const timeStr = d.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    })
    return `${dateStr} ${timeStr}`
  } catch {
    return String(ts)
  }
}

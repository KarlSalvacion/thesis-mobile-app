import { API_BASE } from '../config'
import {
  DetectionDetailRow,
  DetectionRow,
  DetectionSummary,
  FrameMetadataRow,
  UniqueWeedPayload,
} from '../components/detresults/types'

export function pickColorForClass(className: string): string {
  const map: Record<string, string> = {
    amaranthus: 'bg-red-500',
    echinochloa: 'bg-orange-500',
    default: 'bg-yellow-500',
  }
  const key = className.toLowerCase()
  if (key.includes('amaran')) return map.amaranthus
  if (key.includes('echino')) return map.echinochloa
  return map.default
}

export function formatAmPm(ts?: string | null) {
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

export function buildDetectionSummary(
  selectedDetection: DetectionRow | null,
  details: DetectionDetailRow[]
): DetectionSummary | null {
  if (!selectedDetection) return null

  const totalDetections = details.length
  const avgConfidence =
    totalDetections > 0
      ? Math.round((details.reduce((s, d) => s + (d[4] ?? 0), 0) / totalDetections) * 1000) / 10
      : 0

  const byClass: Record<string, { count: number; avg: number }> = {}
  details.forEach((d) => {
    const name = d[3]
    const conf = d[4] ?? 0
    if (!byClass[name]) byClass[name] = { count: 0, avg: 0 }
    const prev = byClass[name]
    prev.count += 1
    prev.avg += conf
  })

  const species = Object.entries(byClass)
    .map(([name, v]) => ({
      name,
      count: v.count,
      confidence: v.count ? Math.round((v.avg / v.count) * 1000) / 10 : 0,
      color: pickColorForClass(name),
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6)

  return {
    totalWeeds: totalDetections,
    confidence: avgConfidence,
    timestamp: selectedDetection[2],
    species,
  }
}

async function fetchUniqueWeedsForVideo(detection: DetectionRow): Promise<UniqueWeedPayload | null> {
  const detId = detection[0]

  if (detection[10]) {
    const withGps = await fetch(
      `${API_BASE}/detection/${detId}/unique-weeds-heatmap?grid_size_m=2.0&iou_threshold=0.58&frame_gap=13`
    )
    if (withGps.ok) return (await withGps.json()) as UniqueWeedPayload
  }

  const noGps = await fetch(`${API_BASE}/detection/${detId}/unique-weeds?iou_threshold=0.58&frame_gap=13`)
  if (!noGps.ok) return null
  return (await noGps.json()) as UniqueWeedPayload
}

export async function fetchDetectionResultsData(detection: DetectionRow): Promise<{
  frames: FrameMetadataRow[]
  details: DetectionDetailRow[]
  uniqueWeedCount: number | null
  uniqueWeedData: UniqueWeedPayload | null
}> {
  const detId = detection[0]
  const res = await fetch(`${API_BASE}/detection/${detId}`)
  if (!res.ok) throw new Error(`Failed to load session ${detId}`)

  const j = await res.json()
  const detectionTuple = j?.detection ?? []
  ;(detection as any).cloud_public_id = detectionTuple[11]
  ;(detection as any).cloud_resource_type = detectionTuple[12]
  ;(detection as any).cloud_secure_url = detectionTuple[13]
  ;(detection as any).cloud_annotated_url = detectionTuple[14]

  const frames = (j?.frame_metadata ?? []) as FrameMetadataRow[]
  const details = (j?.detection_details ?? []) as DetectionDetailRow[]

  if (detection[3] !== 'video') {
    return { frames, details, uniqueWeedCount: null, uniqueWeedData: null }
  }

  const uniqueData = await fetchUniqueWeedsForVideo(detection)
  return {
    frames,
    details,
    uniqueWeedCount: uniqueData?.unique_weed_count ?? null,
    uniqueWeedData: uniqueData,
  }
}

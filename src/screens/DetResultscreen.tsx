import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { View, Text, ScrollView, ActivityIndicator, RefreshControl, Image } from 'react-native'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'
import { API_BASE } from '../config'

type DetectionRow = [
  id: number,
  filename: string,
  timestamp: string,
  file_type: string,
  summary: string | null,
  total_frames: number,
  total_detections: number,
  processing_time: number,
  input_size_bytes: number | null,
  result_size_bytes: number | null
]

type FrameMetadataRow = [
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

type DetectionDetailRow = [
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

function pickColorForClass(className: string): string {
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

const DetectionResults = () => {
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string>('')
  const [latestDetection, setLatestDetection] = useState<DetectionRow | null>(null)
  const [details, setDetails] = useState<DetectionDetailRow[]>([])
  const [frames, setFrames] = useState<FrameMetadataRow[]>([])

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    let cancelled = false
    try {
      if (!opts?.silent) setLoading(true)
      setError('')
      const res = await fetch(`${API_BASE}/detections/`)
      const json = await res.json()
      const rows: DetectionRow[] = json?.detections ?? []
      const latest = rows?.[0] ?? null
      if (!latest) {
        setLatestDetection(null)
        setDetails([])
        setFrames([])
        setError('No detection sessions found.')
        return
      }
      const detId = latest[0]
      const res2 = await fetch(`${API_BASE}/detection/${detId}`)
      const j2 = await res2.json()
      setLatestDetection(latest)
      setFrames((j2?.frame_metadata ?? []) as FrameMetadataRow[])
      setDetails((j2?.detection_details ?? []) as DetectionDetailRow[])
    } catch (e: any) {
      setError(e?.message || 'Failed to load results')
    } finally {
      if (!opts?.silent) setLoading(false)
    }
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let active = true
    async function boot() {
      try {
        await load()
      } catch {
      } finally {
        active = false
      }
    }
    boot()
    return () => {
      active = false
    }
  }, [load])

  const summary = useMemo(() => {
    if (!latestDetection) return null
    const totalDetections = details.length
    const avgConfidence =
      totalDetections > 0
        ? Math.round((details.reduce((s, d) => s + (d[4] ?? 0), 0) / totalDetections) * 1000) / 10
        : 0
    const ts = latestDetection[2]
    const byClass: Record<string, { count: number; avg: number }> = {}
    details.forEach(d => {
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
    return { totalWeeds: totalDetections, confidence: avgConfidence, timestamp: ts, species }
  }, [latestDetection, details])

  function formatAmPm(ts?: string | null) {
    if (!ts) return ''
    try {
      const d = new Date(ts)
      const dateStr = d.toLocaleDateString()
      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })
      return `${dateStr} ${timeStr}`
    } catch {
      return String(ts)
    }
  }

  return (
    <ScrollView className="flex-1 bg-bgColor1" showsVerticalScrollIndicator={false}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => load()} />}>
      <View className="flex-1 justify-start items-center pt-12 pb-8 px-4">
        {/* Video Placeholder */}
        <View className="w-full items-center mb-6">
          <View className="bg-gray-800 rounded-2xl shadow-lg w-full max-w-md h-64 items-center justify-center overflow-hidden">
            {latestDetection && latestDetection[3] === 'image' ? (
              <Image
                source={{ uri: `${API_BASE}/uploads/${latestDetection[1]}` }}
                resizeMode="cover"
                style={{ width: '100%', height: '100%' }}
                onError={() => {}}
              />
            ) : (
              <>
                <Ionicons name="play-circle" size={64} color="white" />
                <Text className="text-white text-lg font-medium mt-3">
                  {latestDetection?.[3] === 'video' ? 'Detection Video' : 'Media preview unavailable'}
                </Text>
                <Text className="text-gray-300 text-xs mt-1 px-3 text-center">
                  {latestDetection?.[3] === 'video'
                    ? 'Video playback requires serving uploads/ over HTTP in the backend.'
                    : 'Configure backend static hosting to preview media.'}
                </Text>
              </>
            )}
          </View>
        </View>

        {/* Header */}
        {loading && (
          <View className="w-full max-w-md mb-6">
            <View className="bg-white rounded-2xl shadow-lg p-6 items-center">
              <ActivityIndicator />
              <Text className="text-gray-600 mt-2">Loading results…</Text>
            </View>
          </View>
        )}
        {!!error && (
          <View className="w-full max-w-md mb-6">
            <View className="bg-white rounded-2xl shadow-lg p-6">
              <Text className="text-red-600 text-center">{error}</Text>
            </View>
          </View>
        )}

        {/* Summary Stats */}
        <View className="w-full max-w-md mb-6">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Detection Summary
            </Text>
            
            <View className="flex-row justify-between items-center mb-4">
              <View className="items-center flex-1">
                <View className="bg-green-100 rounded-full w-16 h-16 items-center justify-center mb-2">
                  <Text className="text-2xl font-bold text-green-600">
                    {summary?.totalWeeds ?? 0}
                  </Text>
                </View>
                <Text className="text-sm text-gray-600 text-center">Total Weeds</Text>
              </View>
              
              <View className="items-center flex-1">
                <View className="bg-blue-100 rounded-full w-16 h-16 items-center justify-center mb-2">
                  <Text className="text-lg font-bold text-blue-600">
                    {summary?.confidence ?? 0}%
                  </Text>
                </View>
                <Text className="text-sm text-gray-600 text-center">Confidence</Text>
              </View>
            </View>

            <View className="bg-gray-50 rounded-lg p-3">
              <Text className="text-xs text-gray-600 text-center">
                {latestDetection ? `File: ${latestDetection[1]} (${latestDetection[3]})` : ''}
              </Text>
              <Text className="text-xs text-gray-500 text-center mt-1">
                {summary?.timestamp ? `Detected on ${formatAmPm(summary.timestamp)}` : 'No recent session'}
              </Text>
            </View>
          </View>
        </View>

        {/* Species Breakdown */}
        <View className="w-full max-w-md mb-6">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Weed Species Detected
            </Text>
            
            {(summary?.species ?? []).map((species, index) => (
              <View key={index} className="mb-4 last:mb-0">
                <View className="flex-row items-center justify-between mb-2">
                  <View className="flex-row items-center">
                    <View className={`w-4 h-4 rounded-full ${species.color} mr-3`} />
                    <Text className="text-base font-medium text-gray-800">
                      {species.name}
                    </Text>
                  </View>
                  <Text className="text-lg font-bold text-gray-700">
                    {species.count}
                  </Text>
                </View>
                
                <View className="flex-row items-center justify-between">
                  <View className="flex-1 bg-gray-200 rounded-full h-2 mr-3">
                    <View 
                      className={`h-2 rounded-full ${species.color}`}
                      style={{ width: `${Math.min(100, Math.max(0, species.confidence))}%` }}
                    />
                  </View>
                  <Text className="text-sm text-gray-600 min-w-[50px] text-right">
                    {species.confidence}%
                  </Text>
                </View>
              </View>
            ))}
            {(!summary || (summary.species?.length ?? 0) === 0) && (
              <Text className="text-center text-gray-500">No detections available.</Text>
            )}
          </View>
        </View>

        {/* Action Buttons */}
        <View className="w-full max-w-md">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Actions
            </Text>
            
            <View className="space-y-3">
              <View className="bg-green-50 border border-green-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="map-marker-alt" size={20} color="rgb(37, 165, 120)" />
                  <Text className="text-green-700 font-medium ml-3 flex-1">
                    View on Map
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(37, 165, 120)" />
                </View>
              </View>
              
              <View className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="download" size={20} color="rgb(59, 130, 246)" />
                  <Text className="text-blue-700 font-medium ml-3 flex-1">
                    Export Report
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(59, 130, 246)" />
                </View>
              </View>
              
              <View className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="share" size={20} color="rgb(245, 101, 101)" />
                  <Text className="text-orange-700 font-medium ml-3 flex-1">
                    Share Results
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(245, 101, 101)" />
                </View>
              </View>
            </View>
          </View>
        </View>
      </View>
    </ScrollView>
  )
}

export default DetectionResults
import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { View, Text, ActivityIndicator, Pressable, ScrollView, RefreshControl } from 'react-native'
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

const Mapscreen = () => {
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string>('')
  const [latestDetection, setLatestDetection] = useState<DetectionRow | null>(null)
  const [frames, setFrames] = useState<FrameMetadataRow[]>([])
  const [details, setDetails] = useState<DetectionDetailRow[]>([])

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    try {
      if (!opts?.silent) setLoading(true)
      setError('')
      const res = await fetch(`${API_BASE}/detections/`)
      const json = await res.json()
      const rows: DetectionRow[] = json?.detections ?? []
      const latest = rows?.[0] ?? null
      if (!latest) {
        setError('No detection sessions found.')
        setLatestDetection(null)
        setFrames([])
        setDetails([])
        return
      }
      const detId = latest[0]
      const res2 = await fetch(`${API_BASE}/detection/${detId}`)
      const j2 = await res2.json()
      setLatestDetection(latest)
      setFrames((j2?.frame_metadata ?? []) as FrameMetadataRow[])
      setDetails((j2?.detection_details ?? []) as DetectionDetailRow[])
    } catch (e: any) {
      setError(e?.message || 'Failed to load map data')
    } finally {
      if (!opts?.silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const density = useMemo(() => {
    // Group detections by frame number, then map to available GPS positions
    const byFrame: Record<number, number> = {}
    details.forEach(d => {
      const f = d[2]
      byFrame[f] = (byFrame[f] || 0) + 1
    })
    // classify
    let low = 0, medium = 0, high = 0
    Object.values(byFrame).forEach(count => {
      if (count <= 2) low += 1
      else if (count <= 5) medium += 1
      else high += 1
    })
    // flight path points count
    const gpsPoints = frames.filter(f => f[4] != null && f[5] != null).length
    return { low, medium, high, gpsPoints }
  }, [details, frames])

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
    <ScrollView className=" h-full w-full bg-bgColor1" contentContainerStyle={{ alignItems: 'center', justifyContent: 'center', paddingVertical: 16 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => load()} />}>
      <View className='h-[310px] w-[380px] bg-greenColor item-center justify-center rounded-lg'>
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : error ? (
          <Text className='text-center text-white px-4'>{error}</Text>
        ) : (
          <Text className='text-center text-white px-4'>
            {latestDetection ? `Frames with GPS: ${density.gpsPoints}` : 'No session'}
          </Text>
        )}
      </View>
      <Pressable onPress={() => load()} className='mt-2 px-4 py-2 bg-gray-700 rounded-md'>
        <Text className='text-white font-medium'>Refresh</Text>
      </Pressable>

      <View className='h-[50px] w-[380px] bg-transparent mt-2 p-0 flex-row items-center justify-between' >
        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-green-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Low</Text>
        </View>

        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-yellow-100 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Medium</Text>
        </View>

        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-red-600 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>High</Text>
        </View>
        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-blue-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Flight Path</Text>
        </View>

      </View>
      
      <View className="flex-col mt-4 bg-white h-[150px] w-[380px] rounded-2xl p-4 shadow-custom border-2 border-gray-300">
        <View className="bg-greenColor shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
          <Text className="text-left text-white text-md font-bold">Density Overview</Text>
        </View>
        

        <View className="flex-row justify-between items-center mt-2 h-[70px] w-full">
          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Low</Text>
            <Text className='text-base font-medium'>{density.low}</Text>
          </View>

          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Medium</Text>
            <Text className='text-base font-medium'>{density.medium}</Text>
          </View>

          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>High</Text>
            <Text className='text-base font-medium'>{density.high}</Text>
          </View>
        </View>
        {latestDetection && (
          <View className="mt-2">
            <Text className='text-xs text-gray-700 text-center'>
              File: {latestDetection[1]} ({latestDetection[3]})
            </Text>
            <Text className='text-xs text-gray-500 text-center mt-1'>
              Detected on {formatAmPm(latestDetection[2])}
            </Text>
          </View>
        )}
      </View>
    </ScrollView> 
  )
}

export default Mapscreen
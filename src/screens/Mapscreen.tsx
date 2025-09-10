import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { View, Text, ActivityIndicator, Pressable, ScrollView, RefreshControl } from 'react-native'
import { API_BASE } from '../config'
import { Platform } from 'react-native'

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

type GMapPoint = { lat: number, lng: number }
type PolylineResponse = { detection_id: number, points: GMapPoint[], bounds?: { min_lat: number, min_lng: number, max_lat: number, max_lng: number } | null }

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
  const [details, setDetails] = useState<DetectionDetailRow[]>([])
  const [polyline, setPolyline] = useState<GMapPoint[]>([])
  const [bounds, setBounds] = useState<PolylineResponse['bounds']>(null)
  const [heatPoints, setHeatPoints] = useState<Array<{ lat: number, lng: number, weight: number }>>([])
  const [mapsAvailable, setMapsAvailable] = useState<boolean>(false)

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
        setDetails([])
        setPolyline([])
        setBounds(null)
        setHeatPoints([])
        return
      }
      const detId = latest[0]
      // fetch session details (for detection_details stats)
      const res2 = await fetch(`${API_BASE}/detection/${detId}`)
      const j2 = await res2.json()
      setLatestDetection(latest)
      setDetails((j2?.detection_details ?? []) as DetectionDetailRow[])

      // fetch google-maps-ready polyline
      const res3 = await fetch(`${API_BASE}/detection/${detId}/gmap-polyline`)
      if (res3.ok) {
        const j3: PolylineResponse = await res3.json()
        setPolyline(j3?.points ?? [])
        setBounds(j3?.bounds ?? null)
      } else {
        setPolyline([])
        setBounds(null)
      }

      // generate heatmap points (do not persist)
      const res4 = await fetch(`${API_BASE}/detection/${detId}/generate-heatmap?grid_size_m=10&persist=false`, { method: 'POST' })
      if (res4.ok) {
        const j4 = await res4.json()
        setHeatPoints(Array.isArray(j4?.points) ? j4.points : [])
      } else {
        setHeatPoints([])
      }
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
    const byFrame: Record<number, number> = {}
    details.forEach(d => {
      const f = d[2]
      byFrame[f] = (byFrame[f] || 0) + 1
    })
    let low = 0, medium = 0, high = 0
    Object.values(byFrame).forEach(count => {
      if (count <= 2) low += 1
      else if (count <= 5) medium += 1
      else high += 1
    })
    const gpsPoints = polyline.length
    return { low, medium, high, gpsPoints }
  }, [details, polyline])

  // Check map library availability once
  useEffect(() => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const maps = require('react-native-maps')
      if (maps?.default) setMapsAvailable(true)
    } catch {
      setMapsAvailable(false)
    }
  }, [])

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
            {latestDetection ? `Path points: ${density.gpsPoints}` : 'No session'}
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

      {/* Map view */}
      <View className="flex-col mt-2 bg-white h-[380px] w-[380px] rounded-2xl overflow-hidden shadow-custom border-2 border-gray-300">
        {mapsAvailable ? (
          <MapSection polyline={polyline} bounds={bounds} heat={heatPoints} />
        ) : (
          <LeafletWebMap polyline={polyline} heat={heatPoints} />
        )}
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

// Separate small component to avoid static import of react-native-maps when missing
function MapSection({ polyline, bounds, heat }: { polyline: GMapPoint[], bounds: PolylineResponse['bounds'], heat: Array<{ lat: number, lng: number, weight: number }> }) {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { default: MapView, Polyline, Heatmap, PROVIDER_GOOGLE } = require('react-native-maps')
  const initialRegion = (() => {
    if (bounds && isFinite(bounds.min_lat) && isFinite(bounds.max_lat) && isFinite(bounds.min_lng) && isFinite(bounds.max_lng)) {
      const lat = (bounds.min_lat + bounds.max_lat) / 2
      const lng = (bounds.min_lng + bounds.max_lng) / 2
      const latDelta = Math.max(0.002, (bounds.max_lat - bounds.min_lat) * 1.2)
      const lngDelta = Math.max(0.002, (bounds.max_lng - bounds.min_lng) * 1.2)
      return { latitude: lat, longitude: lng, latitudeDelta: latDelta, longitudeDelta: lngDelta }
    }
    const p = polyline[0]
    return { latitude: (p?.lat ?? 14.5995), longitude: (p?.lng ?? 120.9842), latitudeDelta: 0.05, longitudeDelta: 0.05 }
  })()

  const coords = polyline.map(p => ({ latitude: p.lat, longitude: p.lng }))
  const heatPoints = heat.map(h => ({ latitude: h.lat, longitude: h.lng, weight: h.weight }))

  const supportsHeatmap = typeof Heatmap !== 'undefined'

  return (
    <MapView style={{ width: '100%', height: '100%' }} provider={PROVIDER_GOOGLE} initialRegion={initialRegion}>
      {coords.length > 1 && (
        <Polyline coordinates={coords} strokeColor="#2563eb" strokeWidth={4} />
      )}
      {heatPoints.length > 0 && supportsHeatmap && (
        <Heatmap points={heatPoints} radius={30} opacity={0.7} gradientColors={["#22c55e", "#eab308", "#ef4444"]} />
      )}
    </MapView>
  )
}

// WebView Leaflet fallback for Expo Go
function LeafletWebMap({ polyline, heat }: { polyline: GMapPoint[], heat: Array<{ lat: number, lng: number, weight: number }> }) {
  // Lazy require so Expo Go users can install it easily; guard if missing
  let WebViewComp: any = null
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    WebViewComp = require('react-native-webview').WebView
  } catch (e) {
    return (
      <View className='flex-1 items-center justify-center p-4'>
        <Text className='text-center text-gray-700'>WebView not installed.</Text>
        <Text className='text-center text-gray-500 mt-2'>Run: npx expo install react-native-webview</Text>
      </View>
    )
  }
  const center = polyline[0] || { lat: 14.5995, lng: 120.9842 }
  const coordsJson = JSON.stringify(polyline.map(p => [p.lat, p.lng]))
  const heatJson = JSON.stringify(heat.map(h => [h.lat, h.lng, h.weight]))
  const html = `<!DOCTYPE html>
  <html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <style>html, body, #map { height: 100%; margin: 0; padding: 0; }</style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const map = L.map('map').setView([${center.lat}, ${center.lng}], 17);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 20 }).addTo(map);
      const coords = ${coordsJson};
      if (coords.length > 1) {
        const poly = L.polyline(coords, { color: '#2563eb', weight: 3 }).addTo(map);
        map.fitBounds(poly.getBounds(), { padding: [20, 20] });
      }
      const heat = ${heatJson};
      if (heat.length > 0) {
        L.heatLayer(heat, { radius: 20, blur: 15, maxZoom: 18 }).addTo(map);
      }
    </script>
  </body>
  </html>`
  return <WebViewComp originWhitelist={["*"]} source={{ html }} style={{ width: '100%', height: '100%' }} />
}
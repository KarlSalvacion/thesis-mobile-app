import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { View, Text, ActivityIndicator, Pressable } from 'react-native';
import { API_BASE } from '../config';

// Types
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
];

type GMapPoint = { lat: number, lng: number };
type PolylineResponse = { detection_id: number, points: GMapPoint[], bounds?: { min_lat: number, min_lng: number, max_lat: number, max_lng: number } | null };

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
];

const Mapscreen = () => {
  const [scrollEnabled, setScrollEnabled] = useState(true);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [latestDetection, setLatestDetection] = useState<DetectionRow | null>(null);
  const [details, setDetails] = useState<DetectionDetailRow[]>([]);
  const [polyline, setPolyline] = useState<GMapPoint[]>([]);
  const [bounds, setBounds] = useState<PolylineResponse['bounds']>(null);
  const [heatPoints, setHeatPoints] = useState<Array<{ lat: number, lng: number, weight: number }>>([]);
  const [mapsAvailable, setMapsAvailable] = useState<boolean>(false);

  // Check map library availability once, but force LeafletWebMap in Expo Go
  useEffect(() => {
    const isExpoGo = typeof navigator !== 'undefined' && navigator.product === 'ReactNative' && ((global as any)?.Expo || (global as any)?.expo);
    if (isExpoGo) {
      setMapsAvailable(false);
    } else {
      try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const maps = require('react-native-maps');
        if (maps?.default) setMapsAvailable(true);
      } catch {
        setMapsAvailable(false);
      }
    }
  }, []);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    try {
      if (!opts?.silent) setLoading(true);
      setError('');
      const res = await fetch(`${API_BASE}/detections/`);
      const json = await res.json();
      const rows: DetectionRow[] = json?.detections ?? [];
      const latest = rows?.[0] ?? null;
      if (!latest) {
        setError('No detection sessions found.');
        setLatestDetection(null);
        setDetails([]);
        setPolyline([]);
        setBounds(null);
        setHeatPoints([]);
        return;
      }
      const detId = latest[0];
      // fetch session details (for detection_details stats)
      const res2 = await fetch(`${API_BASE}/detection/${detId}`);
      const j2 = await res2.json();
      setLatestDetection(latest);
      setDetails((j2?.detection_details ?? []) as DetectionDetailRow[]);

      // fetch google-maps-ready polyline
      const res3 = await fetch(`${API_BASE}/detection/${detId}/gmap-polyline`);
      if (res3.ok) {
        const j3: PolylineResponse = await res3.json();
        setPolyline(j3?.points ?? []);
        setBounds(j3?.bounds ?? null);
      } else {
        setPolyline([]);
        setBounds(null);
      }

      // generate heatmap points (do not persist)
      const res4 = await fetch(`${API_BASE}/detection/${detId}/generate-heatmap?grid_size_m=10&persist=false`, { method: 'POST' });
      if (res4.ok) {
        const j4 = await res4.json();
        setHeatPoints(Array.isArray(j4?.points) ? j4.points : []);
      } else {
        setHeatPoints([]);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to load map data');
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const density = useMemo(() => {
    const byFrame: Record<number, number> = {};
    details.forEach(d => {
      const f = d[2];
      byFrame[f] = (byFrame[f] || 0) + 1;
    });
    let low = 0, medium = 0, high = 0;
    Object.values(byFrame).forEach(count => {
      if (count <= 2) low += 1;
      else if (count <= 5) medium += 1;
      else high += 1;
    });
    const gpsPoints = polyline.length;
    return { low, medium, high, gpsPoints };
  }, [details, polyline]);

  function formatAmPm(ts?: string | null) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      const dateStr = d.toLocaleDateString();
      const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
      return `${dateStr} ${timeStr}`;
    } catch {
      return String(ts);
    }
  }

  return (
    <View className="flex-1 w-full bg-bgColor1 items-center justify-start pt-6 pb-4">
      {/* Map view placed where the green section was */}
      <View className='h-[310px] w-[95vw] max-w-[420px] rounded-lg overflow-hidden bg-white shadow-custom border-2 border-gray-300 items-center justify-center'>
        <LeafletWebMap polyline={polyline} heat={heatPoints} setScrollEnabled={setScrollEnabled} />
        {/* Overlay loading/error/info on top of map */}
        <View style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', alignItems: 'center', justifyContent: 'center', pointerEvents: 'box-none' }} pointerEvents="box-none">
          {loading ? (
            <ActivityIndicator color="#2563eb" />
          ) : error ? (
            <Text className='text-center text-red-600 bg-white/80 px-4 py-2 rounded'>{error}</Text>
          ) : null}
        </View>
      </View>
      <Pressable onPress={() => load()} className='mt-4 px-6 py-2 bg-gray-700 rounded-md w-[95vw] max-w-[420px]'>
        <Text className='text-white font-medium text-center'>Refresh</Text>
      </Pressable>

      <View className='flex-row items-center justify-between w-[95vw] max-w-[420px] mt-4 mb-2'>
        <View className='flex-row items-center'>
          <View className='bg-green-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Low</Text>
        </View>
        <View className='flex-row items-center'>
          <View className='bg-yellow-100 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Medium</Text>
        </View>
        <View className='flex-row items-center'>
          <View className='bg-red-600 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>High</Text>
        </View>
        <View className='flex-row items-center'>
          <View className='bg-blue-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Flight Path</Text>
        </View>
      </View>

      <View className="flex-col bg-white min-h-[120px] w-[95vw] max-w-[420px] rounded-2xl p-4 shadow-custom border-2 border-gray-300 mt-2">
        <View className="bg-greenColor shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
          <Text className="text-left text-white text-md font-bold">Density Overview</Text>
        </View>
        <View className="flex-row justify-between items-center mt-2 w-full">
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Low</Text>
            <Text className='text-base font-medium'>{density.low}</Text>
          </View>
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Medium</Text>
            <Text className='text-base font-medium'>{density.medium}</Text>
          </View>
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
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
    </View>
  );
};

export default Mapscreen;

// WebView Leaflet fallback for Expo Go
function LeafletWebMap({ polyline, heat, setScrollEnabled }: { polyline: GMapPoint[], heat: Array<{ lat: number, lng: number, weight: number }>, setScrollEnabled: (enabled: boolean) => void }) {
  let WebViewComp: any = null;
  try {
    WebViewComp = require('react-native-webview').WebView;
  } catch (e) {
    return (
      <View className='flex-1 items-center justify-center p-4'>
        <Text className='text-center text-gray-700'>WebView not installed.</Text>
        <Text className='text-center text-gray-500 mt-2'>Run: npx expo install react-native-webview</Text>
      </View>
    );
  }
  const center = polyline[0] || { lat: 14.5995, lng: 120.9842 };
  const coordsJson = JSON.stringify(polyline.map(p => [p.lat, p.lng]));
  const heatJson = JSON.stringify(heat.map(h => [h.lat, h.lng, h.weight]));
  // Use Google Satellite tiles
  const html = `<!DOCTYPE html>
  <html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <style>html, body, #map { height: 100%; margin: 0; padding: 0; touch-action: none; }</style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const map = L.map('map', { zoomControl: true }).setView([${center.lat}, ${center.lng}], 17);
      // Google Satellite tiles
      L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0','mt1','mt2','mt3'],
        attribution: 'Map data ©2025 Google',
      }).addTo(map);
      const coords = ${coordsJson};
      if (coords.length > 1) {
        const poly = L.polyline(coords, { color: '#2563eb', weight: 3 }).addTo(map);
        map.fitBounds(poly.getBounds(), { padding: [20, 20] });
      }
      const heat = ${heatJson};
      if (heat.length > 0) {
        L.heatLayer(heat, { radius: 20, blur: 15, maxZoom: 18 }).addTo(map);
      }
      // Prevent parent scroll when interacting with map
      document.getElementById('map').addEventListener('touchstart', function() {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage('disableScroll');
      });
      document.getElementById('map').addEventListener('touchend', function() {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage('enableScroll');
      });
    </script>
  </body>
  </html>`;
  const onMessage = (event: any) => {
    if (!setScrollEnabled) return;
    if (event?.nativeEvent?.data === 'disableScroll') setScrollEnabled(false);
    if (event?.nativeEvent?.data === 'enableScroll') setScrollEnabled(true);
  };
  return <WebViewComp originWhitelist={["*"]} source={{ html }} style={{ width: 380, height: 310 }} onMessage={onMessage} />;
}
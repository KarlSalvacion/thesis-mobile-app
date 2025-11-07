import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { Dimensions } from 'react-native';
import { View, Text, ActivityIndicator, Pressable, ScrollView, RefreshControl, Modal, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { useRoute } from '@react-navigation/native';
import { API_BASE } from '../config';
import { useSession } from '../context/SessionContext';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

/**
 * Mapscreen - Displays GPS-based heatmap of unique weed detections
 * 
 * This screen implements a sophisticated weed tracking and mapping system:
 * 
 * 1. SRT File Integration:
 *    - Reads SRT subtitle files uploaded with MP4 videos
 *    - Extracts GPS coordinates (latitude, longitude) + timestamps from each frame
 *    - Matches timestamps (not frame numbers) with detection timestamps from Roboflow
 * 
 * 2. Why Timestamp Matching Instead of Frame Numbers:
 *    - Original drone video: 30 FPS, 1900 frames
 *    - SRT file: 1900 entries (one per original frame)
 *    - Processed video: 10 FPS (config.py), only ~633 frames
 *    - Frame mismatch: Detection frame 63 ≠ SRT frame 63
 *    - Solution: Match by timestamp (both start at 00:00:00,000)
 *    - Frame 63 at 10 FPS = 6.3s = matches SRT entry at 00:00:06,300 (frame ~189 at 30 FPS)
 * 
 * 3. Unique Weed Detection:
 *    - Uses IoU (Intersection over Union) algorithm to track the same weed across multiple frames
 *    - Prevents counting the same weed multiple times
 *    - Groups detections within frame_gap (default: 10 frames) with similar bounding boxes
 *    - Validates tracking using GPS distance (weeds shouldn't move >2 meters)
 * 
 * 4. Heatmap Generation:
 *    - Groups unique weeds into spatial grid cells (default: 5m x 5m)
 *    - Each grid cell shows the number of UNIQUE weeds detected in that area
 *    - Color coding: Green (low: ≤2) -> Yellow (medium: 3-5) -> Red (high: >5)
 *    - Uses Leaflet.heat library with custom gradient for visualization
 * 
 * 5. Data Flow:
 *    - Backend: /detection/{id}/unique-weeds-heatmap endpoint
 *    - Matches SRT timestamps with detection timestamps (±100ms tolerance)
 *    - Calculates unique weeds using tracking algorithm
 *    - Returns heatmap points with weight = unique weed count per location
 * 
 * Example: If the same weed appears in frames 10-20, it's counted as 1 unique weed,
 * not 11 separate detections. The heatmap shows actual weed distribution, not detection density.
 */

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
  result_size_bytes: number | null,
  has_srt_data: boolean | null
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
  // User location state
  const [showUserLocation, setShowUserLocation] = useState(false);
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [locationError, setLocationError] = useState<string>('');
  const [toggleDisabled, setToggleDisabled] = useState(false);
  
  // Real-time location tracking when toggled on
  useEffect(() => {
    let isMounted = true;
    let locationSubscription: Location.LocationSubscription | null = null;
    
    const startLocationTracking = async () => {
      setToggleDisabled(true);
      if (!showUserLocation) {
        // Stop tracking when toggled off
        if (locationSubscription) {
          locationSubscription.remove();
          locationSubscription = null;
        }
        setUserLocation(null);
        setLocationError('');
        setToggleDisabled(false);
        return;
      }
      
      try {
        setLocationError('');
        let { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== 'granted') {
          setLocationError('Permission to access location was denied');
          setShowUserLocation(false);
          setToggleDisabled(false);
          return;
        }
        
        // Start watching location with real-time updates
        locationSubscription = await Location.watchPositionAsync(
          {
            accuracy: Location.Accuracy.High,
            timeInterval: 2000, // Update every 2 seconds
            distanceInterval: 5, // Update when moved 5 meters
          },
          (loc) => {
            if (isMounted) {
              setUserLocation({ lat: loc.coords.latitude, lng: loc.coords.longitude });
              console.log('📍 [LOCATION] Updated:', loc.coords.latitude, loc.coords.longitude);
            }
          }
        );
        
        console.log('📍 [LOCATION] Started real-time tracking');
      } catch (e: any) {
        setLocationError(e?.message || 'Failed to get location');
        setShowUserLocation(false);
      }
      setToggleDisabled(false);
    };
    
    startLocationTracking();
    
    return () => {
      isMounted = false;
      if (locationSubscription) {
        locationSubscription.remove();
        console.log('📍 [LOCATION] Stopped real-time tracking');
      }
    };
  }, [showUserLocation]);
  const { selectedDetection, sessions, refreshSessions, setSelectedDetection } = useSession();
  const insets = useSafeAreaInsets();
  const [scrollEnabled, setScrollEnabled] = useState(true);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');
  const [details, setDetails] = useState<DetectionDetailRow[]>([]);
  const [polyline, setPolyline] = useState<GMapPoint[]>([]);
  const [bounds, setBounds] = useState<PolylineResponse['bounds']>(null);
  const [heatPoints, setHeatPoints] = useState<Array<{ lat: number, lng: number, weight: number }>>([]);
  const [mapsAvailable, setMapsAvailable] = useState<boolean>(false);
  const [uniqueWeedCount, setUniqueWeedCount] = useState<number>(0);
  const [totalDetections, setTotalDetections] = useState<number>(0);
  const [sessionModalVisible, setSessionModalVisible] = useState<boolean>(false);

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

  const loadMapData = useCallback(async (detection: DetectionRow) => {
    try {
      setLoading(true);
      setError('');

      // Clear previous map/heat immediately to avoid stale display
      setPolyline([]);
      setHeatPoints([]);
      setBounds(null);
      setUniqueWeedCount(0);
      setTotalDetections(0);

      const detId = detection[0];
      
      // fetch session details (for detection_details stats)
      const res2 = await fetch(`${API_BASE}/detection/${detId}`);
      if (!res2.ok) throw new Error('Failed to fetch detection session')
      const j2 = await res2.json();
      
      // Attach cloud urls to display
      const detectionTuple = j2?.detection ?? [];
      ;(detection as any).cloud_secure_url = detectionTuple[13];
      ;(detection as any).cloud_annotated_url = detectionTuple[14];
      
      console.log('🔍 [MAP DEBUG] Detection tuple length:', detectionTuple.length);
      console.log('🔍 [MAP DEBUG] Has SRT data:', detection[10]);
      console.log('🔍 [MAP DEBUG] Cloud URLs:', {
        secure: detectionTuple[13],
        annotated: detectionTuple[14]
      });
      
      setDetails((j2?.detection_details ?? []) as DetectionDetailRow[]);

      // Check if this detection has SRT data before trying to fetch it
      if (detection[10]) { // has_srt_data field
        // Try to get SRT polyline - if missing, clear previous polyline/heat
        const res3 = await fetch(`${API_BASE}/detection/${detId}/gmap-polyline`);
        if (res3.ok) {
          const j3: PolylineResponse = await res3.json();
          setPolyline(j3?.points ?? []);
          setBounds(j3?.bounds ?? null);

          // Generate heatmap based on unique weeds per GPS location
          // MORE AGGRESSIVE parameters for 10 FPS drone video:
          // - grid_size_m=2.0: 2-meter grid cells for agricultural field scale
          // - iou_threshold=0.5: More lenient matching (50% overlap allows for angle/distance changes)
          // - frame_gap=20: At 10 FPS, 20 frames = 2.0 seconds (track same weed across longer timespan)
          const res4 = await fetch(`${API_BASE}/detection/${detId}/unique-weeds-heatmap?grid_size_m=2.0&iou_threshold=0.5&frame_gap=20`);
          if (res4.ok) {
            const j4 = await res4.json();
            const heatmapPoints = (j4?.points ?? []).map((point: any) => ({ lat: point.lat, lng: point.lng, weight: point.unique_count || point.weight || 1 }));
            setHeatPoints(heatmapPoints);
            setUniqueWeedCount(j4?.unique_weed_count ?? 0);
            setTotalDetections(j4?.total_detections ?? 0);
          } else {
            // fallback: clear heat
            setHeatPoints([]);
            setUniqueWeedCount(0);
            setTotalDetections(0);
          }
        } else {
          // SRT data exists but polyline fetch failed
          setPolyline([]);
          setBounds(null);
          setHeatPoints([]);
          setUniqueWeedCount(0);
          setTotalDetections(0);
        }
      } else {
        // No SRT data: clear polyline and heat
        setPolyline([]);
        setBounds(null);
        setHeatPoints([]);
        setUniqueWeedCount(0);
        setTotalDetections(0);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to load map data');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load map data when selected detection changes
  useEffect(() => {
    if (selectedDetection) {
      loadMapData(selectedDetection);
    } else {
      // Clear all data when no detection is selected
      setPolyline([]);
      setHeatPoints([]);
      setBounds(null);
      setDetails([]);
      setUniqueWeedCount(0);
      setTotalDetections(0);
      setError('');
    }
  }, [selectedDetection, loadMapData]);

  // Handle navigation params
  const route: any = useRoute();
  useEffect(() => {
    const idParam = route?.params?.detectionId;
    if (typeof idParam === 'number') {
      // Find the detection with this ID and set it as selected
      const detection = sessions.find(s => s[0] === idParam);
      if (detection) {
        setSelectedDetection(detection);
      }
    }
  }, [route?.params, sessions, setSelectedDetection]);

  const density = useMemo(() => {
    // Calculate density based on TOTAL UNIQUE WEEDS in each category, not grid cell count
    if (heatPoints.length === 0) {
      return { low: 0, medium: 0, high: 0, gpsPoints: polyline.length };
    }
    
    let low = 0, medium = 0, high = 0;
    
    // Count total weeds (not grid cells) in each density category
    heatPoints.forEach(point => {
      const weedCount = point.weight;  // Number of unique weeds in this location
      
      if (weedCount <= 2) {
        low += weedCount;  // Add the actual number of weeds, not just 1
      } else if (weedCount <= 5) {
        medium += weedCount;
      } else {
        high += weedCount;
      }
    });
    
    const gpsPoints = polyline.length;
    return { low, medium, high, gpsPoints };
  }, [heatPoints, polyline]);

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
    <SafeAreaView className="flex-1 bg-bgColor1" edges={['top']}>
      <ScrollView 
        className="flex-1"
        contentContainerStyle={{ alignItems: 'center', paddingTop: 24, paddingBottom: 16 }}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => refreshSessions()}
            colors={['#2563eb']}
            tintColor="#2563eb"
          />
        }
      >
      {/* Map view placed where the green section was */}
      <View style={{
        height: 310,
        width: 380,
        borderRadius: 16,
        overflow: 'hidden',
        backgroundColor: 'white',
        borderWidth: 2,
        borderColor: '#d1d5db',
        alignItems: 'center',
        justifyContent: 'center',
        shadowColor: '#000',
        shadowOpacity: 0.08,
        shadowRadius: 8,
        shadowOffset: {width: 0, height: 2},
        position: 'relative'
      }}>
        <LeafletWebMap 
          polyline={polyline} 
          heat={heatPoints} 
          setScrollEnabled={setScrollEnabled}
          userLocation={showUserLocation && userLocation ? userLocation : null}
          centerOn={showUserLocation && userLocation ? userLocation : null}
        />
        {/* Toggle user location button overlay */}
        <View style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }}>
          <Pressable
            onPress={() => {
              if (toggleDisabled) return;
              setShowUserLocation((v) => !v);
              // Temporarily disable button to prevent rapid toggles during map recentering
              setToggleDisabled(true);
              setTimeout(() => {
                setToggleDisabled(false);
              }, 1000); // Re-enable after 1 second
            }}
            style={{ backgroundColor: showUserLocation ? '#2563eb' : '#fff', borderRadius: 24, padding: 8, borderWidth: 1, borderColor: '#2563eb', elevation: 2, opacity: toggleDisabled ? 0.5 : 1 }}
            disabled={toggleDisabled}
          >
            <Ionicons name="locate" size={24} color={showUserLocation ? '#fff' : '#2563eb'} />
          </Pressable>
        </View>
        {/* Overlay loading/error/info on top of map */}
        <View style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', alignItems: 'center', justifyContent: 'center', pointerEvents: 'box-none' }} pointerEvents="box-none">
          {loading ? (
            <ActivityIndicator color="#2563eb" />
          ) : error ? (
            <Text className='text-center text-red-600 bg-white/80 px-4 py-2 rounded'>{error}</Text>
          ) : locationError ? (
            <Text className='text-center text-red-600 bg-white/80 px-4 py-2 rounded'>{locationError}</Text>
          ) : selectedDetection && !selectedDetection[10] ? (
            <Text className='text-center text-gray-600 bg-white/80 px-4 py-2 rounded'>No GPS data available for this session</Text>
          ) : null}
        </View>
      </View>
      <Pressable onPress={async () => { await refreshSessions(); }} className='mt-4 px-6 py-2 bg-gray-700 rounded-md w-[95vw] max-w-[420px]'>
        <Text className='text-white font-medium text-center'>Refresh Sessions</Text>
      </Pressable>

      <Pressable onPress={() => setSessionModalVisible(true)} className='mt-3 px-6 py-2 bg-gray-100 rounded-md w-[95vw] max-w-[420px]'>
        <Text className='text-gray-700 font-medium text-center'>Select Session</Text>
      </Pressable>


      {/* Session Selection Modal */}
      <Modal visible={sessionModalVisible} transparent={true} animationType="slide" onRequestClose={() => setSessionModalVisible(false)}>
        <View className="flex-1 bg-black/60 justify-end">
          <View className="bg-white rounded-t-2xl p-4 max-h-3/4">
            <Text className="text-lg font-semibold mb-2">Select Detection Session</Text>
            <ScrollView style={{ maxHeight: 360 }}>
              {sessions.length === 0 && (
                <View className="p-4"><Text className="text-gray-500">No sessions available.</Text></View>
              )}
              {sessions.map((s) => (
                <Pressable key={s[0]} onPress={() => {
                    setSessionModalVisible(false);
                    setSelectedDetection(s);
                  }} className="p-3 border-b border-gray-100">
                  <View className="flex-row items-center justify-between">
                    <View className="flex-1">
                      <Text className="font-medium">{s[1]}</Text>
                      <Text className="text-xs text-gray-500">{new Date(String(s[2])).toLocaleString()} • {s[3]}</Text>
                    </View>
                    <View className="flex-row items-center">
                      <Text className="text-sm text-gray-400 mr-3">{s[6]} detections</Text>
                      <Pressable
                        onPress={(e) => {
                          e.stopPropagation();
                          Alert.alert(
                            'Delete Session',
                            `Are you sure you want to delete "${s[1]}"?\n\nThis will permanently delete all data including:\n• Detection details\n• GPS tracks\n• Heatmaps\n\nThis action cannot be undone.`,
                            [
                              { text: 'Cancel', style: 'cancel' },
                              {
                                text: 'Delete',
                                style: 'destructive',
                                onPress: async () => {
                                  try {
                                    const response = await fetch(`${API_BASE}/detection/${s[0]}`, {
                                      method: 'DELETE',
                                    });
                                    if (response.ok) {
                                      await refreshSessions();
                                      if (selectedDetection && selectedDetection[0] === s[0]) {
                                        setSelectedDetection(null);
                                      }
                                      Alert.alert('Success', 'Session deleted successfully');
                                    } else {
                                      Alert.alert('Error', 'Failed to delete session');
                                    }
                                  } catch (error) {
                                    Alert.alert('Error', 'Failed to delete session');
                                  }
                                },
                              },
                            ]
                          );
                        }}
                        className="p-2"
                      >
                        <Ionicons name="trash-outline" size={20} color="#ef4444" />
                      </Pressable>
                    </View>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
            <Pressable className="mt-3 p-3 bg-gray-100 rounded-lg" onPress={() => setSessionModalVisible(false)}>
              <Text className="text-center text-gray-700">Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      <View className='flex-row flex-wrap items-center justify-between w-[95vw] max-w-[420px] mt-4 mb-2'>
        <View className='flex-row items-center mb-1'>
          <View className='bg-green-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>Low</Text>
        </View>
        <View className='flex-row items-center mb-1'>
          <View className='bg-yellow-100 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>Medium</Text>
        </View>
        <View className='flex-row items-center mb-1'>
          <View className='bg-red-600 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>High</Text>
        </View>
        <View className='flex-row items-center mb-1'>
          <View className='bg-blue-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>Path</Text>
        </View>
        <View className='flex-row items-center mb-1'>
          <View className='bg-green-500 h-[12px] w-[12px] rounded-full border-2 border-white shadow'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>Start</Text>
        </View>
        <View className='flex-row items-center mb-1'>
          <View className='bg-red-500 h-[12px] w-[12px] rounded-full border-2 border-white shadow'/>
          <Text className='text-xs ml-2 font-medium text-gray-700'>End</Text>
        </View>
      </View>

      <View className="flex-col bg-white min-h-[120px] w-[95vw] max-w-[420px] rounded-2xl p-4 shadow-custom border-2 border-gray-300 mt-2">
        <View className="bg-greenColor shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
          <Text className="text-left text-white text-md font-bold">Density Overview</Text>
        </View>
        <View className="flex-row justify-between items-center mt-2 w-full">
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
            <Text className='text-xs font-bold text-gray-600'>Low Density</Text>
            <Text className='text-[10px] text-gray-500'>(1-2 per area)</Text>
            <Text className='text-base font-medium mt-1'>{density.low}</Text>
            <Text className='text-[9px] text-gray-400'>weeds</Text>
          </View>
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
            <Text className='text-xs font-bold text-gray-600'>Medium</Text>
            <Text className='text-[10px] text-gray-500'>(3-5 per area)</Text>
            <Text className='text-base font-medium mt-1'>{density.medium}</Text>
            <Text className='text-[9px] text-gray-400'>weeds</Text>
          </View>
          <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
            <Text className='text-xs font-bold text-gray-600'>High Density</Text>
            <Text className='text-[10px] text-gray-500'>(6+ per area)</Text>
            <Text className='text-base font-medium mt-1'>{density.high}</Text>
            <Text className='text-[9px] text-gray-400'>weeds</Text>
          </View>
        </View>
        {selectedDetection && (
          <View className="mt-2">
            <Text className='text-xs text-gray-700 text-center'>
              File: {selectedDetection[1]} ({selectedDetection[3]})
            </Text>
            <Text className='text-xs text-gray-500 text-center mt-1'>
              Detected on {formatAmPm(selectedDetection[2])}
            </Text>
            <View className="flex-row items-center justify-center mt-1">
              {selectedDetection[10] ? (
                <>
                  <View className="w-2 h-2 bg-green-500 rounded-full mr-1" />
                  <Text className='text-xs text-green-600 font-medium'>GPS Data Available</Text>
                </>
              ) : (
                <>
                  <View className="w-2 h-2 bg-gray-400 rounded-full mr-1" />
                  <Text className='text-xs text-gray-500 font-medium'>No GPS Data</Text>
                </>
              )}
            </View>
          </View>
        )}
      </View>

      {/* Unique Weeds Information Card */}
      {uniqueWeedCount > 0 && (
        <View className="flex-col bg-white min-h-[100px] w-[95vw] max-w-[420px] rounded-2xl p-4 shadow-custom border-2 border-gray-300 mt-2">
          <View className="bg-blue-600 shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
            <Text className="text-left text-white text-md font-bold">Unique Weed Analysis</Text>
          </View>
          <View className="flex-row justify-between items-center mt-2 w-full">
            <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-blue-50">
              <Text className='text-xs font-bold text-gray-600'>Estimated Unique Weeds</Text>
              <Text className='text-2xl font-bold text-blue-600'>{uniqueWeedCount}</Text>
              <Text className='text-[9px] text-gray-400 mt-1'>Tracked across frames</Text>
            </View>
            <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-gray-50">
              <Text className='text-xs font-bold text-gray-600'>Total Detections</Text>
              <Text className='text-2xl font-bold text-gray-700'>{totalDetections}</Text>
              <Text className='text-[9px] text-gray-400 mt-1'>All raw detections</Text>
            </View>
            <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-green-50">
              <Text className='text-xs font-bold text-gray-600'>Reduction</Text>
              <Text className='text-2xl font-bold text-green-600'>
                {totalDetections > 0 ? Math.round((1 - uniqueWeedCount / totalDetections) * 100) : 0}%
              </Text>
              <Text className='text-[9px] text-gray-400 mt-1'>Duplicate removal</Text>
            </View>
          </View>
          <View className="bg-blue-50 rounded-lg p-2 mt-3">
            <Text className='text-[10px] text-gray-600 text-center'>
              💡 Note: Density totals ({density.low + density.medium + density.high}) show unique weeds categorized by spatial concentration
            </Text>
          </View>
          <Text className='text-xs text-gray-500 text-center mt-2'>
            Heatmap shows unique weeds by tracking the same weed across frames
          </Text>
        </View>
      )}
    </ScrollView>
    </SafeAreaView>
  );
};

export default Mapscreen;

// WebView Leaflet fallback for Expo Go
function LeafletWebMap({ polyline, heat, setScrollEnabled, userLocation, centerOn }: {
  polyline: GMapPoint[],
  heat: Array<{ lat: number, lng: number, weight: number }>,
  setScrollEnabled: (enabled: boolean) => void,
  userLocation?: { lat: number, lng: number } | null,
  centerOn?: { lat: number, lng: number } | null
}) {
  let WebViewComp: any = null;
  try {
    WebViewComp = require('react-native-webview').WebView;
  } catch (e) {
    return (
      <View style={{flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16}}>
        <Text style={{textAlign: 'center', color: '#374151'}}>WebView not installed.</Text>
        <Text style={{textAlign: 'center', color: '#6b7280', marginTop: 8}}>Run: npx expo install react-native-webview</Text>
      </View>
    );
  }
  const center = centerOn || (polyline[0] ? polyline[0] : { lat: 14.5995, lng: 120.9842 });
  const coordsJson = JSON.stringify(polyline.map(p => [p.lat, p.lng]));
  const heatJson = JSON.stringify(heat.map(h => [h.lat, h.lng, h.weight]));
  const userLocJson = userLocation ? JSON.stringify([userLocation.lat, userLocation.lng]) : 'null';
  // Use Google Satellite tiles
  const html = `<!DOCTYPE html>
  <html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.fullscreen@2.4.0/Control.FullScreen.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <script src="https://unpkg.com/leaflet.fullscreen@2.4.0/Control.FullScreen.js"></script>
    <style>html, body { height: 100%; margin: 0; padding: 0; touch-action: none; } #map { height: 100%; width: 100%; box-sizing: border-box; }</style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const coords = ${coordsJson};
  const map = L.map('map', { zoomControl: true, fullscreenControl: true }).setView([${center.lat}, ${center.lng}], 17);
      // User marker logic
      const userLoc = ${userLocJson};
      let userMarker = null;
      if (userLoc) {
        userMarker = L.marker(userLoc, {
          icon: L.divIcon({
            className: 'custom-user-icon',
            html: '<div style="background-color: #2563eb; width: 14px; height: 14px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>'
          })
        }).addTo(map).bindPopup('Your Location');
        map.setView(userLoc, 18, { animate: true });
      } else if (coords.length > 1) {
        // If not showing user location, fit to polyline as before
        const poly = L.polyline(coords, { color: '#2563eb', weight: 3 });
        map.fitBounds(poly.getBounds(), { padding: [20, 20] });
      }
      // Google Satellite tiles
      L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0','mt1','mt2','mt3'],
        attribution: 'Map data ©2025 Google',
      }).addTo(map);
      if (coords.length > 1) {
        const poly = L.polyline(coords, { color: '#2563eb', weight: 3 }).addTo(map);
        map.fitBounds(poly.getBounds(), { padding: [20, 20] });
        // Add start marker (green)
        const startCoord = coords[0];
        const startIcon = L.divIcon({
          className: 'custom-icon',
          html: '<div style="background-color: #22c55e; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        });
        L.marker([startCoord[0], startCoord[1]], { icon: startIcon }).addTo(map)
          .bindPopup('Flight Start');
        // Add end marker (red)
        const endCoord = coords[coords.length - 1];
        const endIcon = L.divIcon({
          className: 'custom-icon',
          html: '<div style="background-color: #ef4444; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        });
        L.marker([endCoord[0], endCoord[1]], { icon: endIcon }).addTo(map)
          .bindPopup('Flight End');
      }
      const heat = ${heatJson};
      if (heat.length > 0) {
        // More precise heatmap to show individual detections along flight path
        L.heatLayer(heat, { 
          radius: 6,            // Reduced radius for smaller, tighter heat points
          blur: 6,              // Slightly less blur to keep points distinct
          maxZoom: 18,
          max: 4,               // Lower max to make low-density areas more visible
          gradient: {           // Custom gradient: green (low) -> yellow -> red (high)
            0.0: 'green',
            0.3: 'lime',
            0.5: 'yellow',
            0.7: 'orange',
            1.0: 'red'
          }
        }).addTo(map);
        // Add small markers at exact grid cell centers for clarity
        heat.forEach(point => {
          const color = point.weight <= 2 ? '#22c55e' :   // green
                        point.weight <= 5 ? '#eab308' :   // yellow
                        '#ef4444';                         // red
          L.circleMarker([point.lat, point.lng], {
            radius: 3, // smaller marker radius
            fillColor: color,
            color: 'white',
            weight: 1,
            fillOpacity: 0.85
          }).addTo(map).bindPopup(point.weight + ' estimated unique weeds');
        });
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
  return <WebViewComp
    originWhitelist={["*"]}
    source={{ html }}
    style={{ width: 380, height: 310, backgroundColor: 'white' }}
    allowsFullscreenVideo={true}
    javaScriptEnabled={true}
    domStorageEnabled={true}
    mediaPlaybackRequiresUserAction={false}
    />;
}
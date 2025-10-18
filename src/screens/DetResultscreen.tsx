import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { View, Text, ActivityIndicator, ScrollView, RefreshControl, Image, TouchableOpacity, Modal, Dimensions, Alert, Linking, Platform } from 'react-native';
import { Ionicons, FontAwesome6 } from '@expo/vector-icons';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import { Video, ResizeMode } from 'expo-av';
import * as FileSystem from 'expo-file-system';
import * as Sharing from 'expo-sharing';
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
  result_size_bytes: number | null,
  has_srt_data: boolean | null
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
  const navigation = useNavigation()
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string>('')
  const [latestDetection, setLatestDetection] = useState<DetectionRow | null>(null)
  const [details, setDetails] = useState<DetectionDetailRow[]>([])
  const [frames, setFrames] = useState<FrameMetadataRow[]>([])
  const [isModalVisible, setIsModalVisible] = useState<boolean>(false)
  const [exporting, setExporting] = useState<boolean>(false)
  const [uniqueWeedCount, setUniqueWeedCount] = useState<number | null>(null)
  const [uniqueWeedData, setUniqueWeedData] = useState<any>(null)

  // Get screen dimensions for modal sizing
  const { width: screenWidth, height: screenHeight } = Dimensions.get('window')
  
  // DJI Mini 4 Pro aspect ratio is 4:3
  const djiAspectRatio = 4 / 3

  // Action Handlers
  const handleViewMap = useCallback(() => {
    if (!latestDetection) {
      Alert.alert('No Data', 'No detection session available.')
      return
    }
    
    const detectionId = latestDetection[0]
    const hasGPS = latestDetection[10]
    
    if (!hasGPS) {
      Alert.alert(
        'GPS Data Required',
        'This detection has no GPS data. Upload a video with SRT file to view map data.',
        [{ text: 'OK' }]
      )
      return
    }
    
    // Navigate to Map screen
    (navigation as any).navigate('Map', { 
      detectionId,
      autoFocus: true 
    })
  }, [latestDetection, navigation])

  const handleExport = useCallback(async () => {
    if (!latestDetection) {
      Alert.alert('No Data', 'No detection session available to export.')
      return
    }

    const detectionId = latestDetection[0]

    Alert.alert(
      'Export Format',
      'Choose export format:',
      [
        {
          text: 'JSON',
          onPress: () => exportReport(detectionId, 'json')
        },
        {
          text: 'CSV',
          onPress: () => exportReport(detectionId, 'csv')
        },
        {
          text: 'PDF',
          onPress: () => exportReport(detectionId, 'pdf')
        },
        {
          text: 'Cancel',
          style: 'cancel'
        }
      ]
    )
  }, [latestDetection])

  const exportReport = async (detectionId: number, format: string) => {
    try {
      setExporting(true)
      const url = `${API_BASE}/detection/${detectionId}/export?format=${format}`
      
      console.log(`📥 Exporting ${format.toUpperCase()} report...`)
      
      const filename = `detection_report_${detectionId}.${format}`
      const fileUri = `${FileSystem.documentDirectory}${filename}`
      
      // Download the file
      const downloadResult = await FileSystem.downloadAsync(url, fileUri)
      
      if (downloadResult.status === 200) {
        console.log('✅ Report downloaded:', downloadResult.uri)
        
        // Check if sharing is available
        const canShare = await Sharing.isAvailableAsync()
        
        if (canShare) {
          await Sharing.shareAsync(downloadResult.uri, {
            mimeType: format === 'json' ? 'application/json' : 
                     format === 'csv' ? 'text/csv' : 
                     'application/pdf',
            dialogTitle: `Export Detection Report (${format.toUpperCase()})`
          })
        } else {
          Alert.alert(
            'Export Complete',
            `Report saved to:\n${downloadResult.uri}`,
            [
              { text: 'OK' }
            ]
          )
        }
      } else {
        throw new Error(`Download failed with status: ${downloadResult.status}`)
      }
    } catch (error: any) {
      console.error('❌ Export error:', error)
      
      if (error.message?.includes('reportlab')) {
        Alert.alert(
          'PDF Export Unavailable',
          'PDF export requires additional setup on the server. Try JSON or CSV format instead.',
          [{ text: 'OK' }]
        )
      } else {
        Alert.alert(
          'Export Failed',
          error.message || 'Could not export report. Please try again.',
          [{ text: 'OK' }]
        )
      }
    } finally {
      setExporting(false)
    }
  }

  const handleShare = useCallback(async () => {
    if (!latestDetection) {
      Alert.alert('No Data', 'No detection session available to share.')
      return
    }

    const detectionId = latestDetection[0]

    try {
      setExporting(true)
      
      console.log('📤 Creating share package...')
      const response = await fetch(`${API_BASE}/detection/${detectionId}/share`, {
        method: 'POST'
      })
      
      if (!response.ok) {
        throw new Error(`Share failed: ${response.status}`)
      }
      
      const shareData = await response.json()
      console.log('✅ Share package created:', shareData)
      
      const shareMessage = shareData.share_message || 
        `🌿 Weed Detection Results\n\nFile: ${latestDetection[1]}\nDetected: ${details.length} weeds\n\nView: ${shareData.media_urls?.annotated || 'N/A'}`
      
      // Check if native sharing is available
      const canShare = await Sharing.isAvailableAsync()
      
      if (canShare && shareData.media_urls?.annotated) {
        // Download annotated media first
        const filename = `detection_${detectionId}_annotated.${latestDetection[3] === 'video' ? 'mp4' : 'jpg'}`
        const fileUri = `${FileSystem.cacheDirectory}${filename}`
        
        try {
          const downloadResult = await FileSystem.downloadAsync(shareData.media_urls.annotated, fileUri)
          
          if (downloadResult.status === 200) {
            await Sharing.shareAsync(downloadResult.uri, {
              mimeType: latestDetection[3] === 'video' ? 'video/mp4' : 'image/jpeg',
              dialogTitle: 'Share Detection Results'
            })
          } else {
            // Fallback to URL only
            Alert.alert(
              'Share Results',
              shareMessage,
              [
                {
                  text: 'Copy Link',
                  onPress: () => {
                    // In a real app, you'd copy to clipboard here
                    Alert.alert('Link', shareData.media_urls?.annotated || 'No link available')
                  }
                },
                { text: 'Cancel', style: 'cancel' }
              ]
            )
          }
        } catch (downloadError) {
          console.error('Download error:', downloadError)
          // Fallback to text share
          Alert.alert('Share Results', shareMessage, [{ text: 'OK' }])
        }
      } else {
        // Fallback to alert with message
        Alert.alert(
          'Share Results',
          shareMessage,
          [
            {
              text: 'Open Link',
              onPress: () => {
                const url = shareData.media_urls?.annotated || shareData.media_urls?.original
                if (url) {
                  Linking.openURL(url)
                }
              }
            },
            { text: 'OK' }
          ]
        )
      }
    } catch (error: any) {
      console.error('❌ Share error:', error)
      Alert.alert(
        'Share Failed',
        error.message || 'Could not create share package. Please try again.',
        [{ text: 'OK' }]
      )
    } finally {
      setExporting(false)
    }
  }, [latestDetection, details])

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
      
      // Fetch unique weed count for video detections
      if (latest[3] === 'video') {
        try {
          const res3 = await fetch(`${API_BASE}/detection/${detId}/unique-weeds`)
          if (res3.ok) {
            const uniqueData = await res3.json()
            setUniqueWeedCount(uniqueData.unique_weed_count)
            setUniqueWeedData(uniqueData)
            console.log('✅ Unique weeds:', uniqueData.unique_weed_count, 'from', uniqueData.total_detections, 'detections')
          }
        } catch (e) {
          console.warn('Could not fetch unique weed count:', e)
        }
      } else {
        // For images, unique count = total detections
        setUniqueWeedCount(null)
        setUniqueWeedData(null)
      }
      
      // Attach cloud info if available (backend returns session with detection tuple)
      // Detection tuple indices: id, filename, timestamp, file_type, summary, total_frames, total_detections, processing_time, input_size_bytes, result_size_bytes, has_srt_data, cloud_public_id, cloud_resource_type, cloud_secure_url
  // Map cloud fields from the backend detection tuple. New DB adds cloud_annotated_url at index 14.
  ;(latest as any).cloud_public_id = (j2?.detection ?? [])[11]
  ;(latest as any).cloud_resource_type = (j2?.detection ?? [])[12]
  ;(latest as any).cloud_secure_url = (j2?.detection ?? [])[13]
  ;(latest as any).cloud_annotated_url = (j2?.detection ?? [])[14]
    } catch (e: any) {
      setError(e?.message || 'Failed to load results')
    } finally {
      if (!opts?.silent) setLoading(false)
    }
    return () => {
      cancelled = true
    }
  }, [])

  // Auto-refresh when screen comes into focus
  useFocusEffect(
    useCallback(() => {
      load()
    }, [load])
  )

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
        {/* Media Container - Expandable with DJI Mini 4 Pro aspect ratio */}
        <View className="w-full items-center mb-6">
          <TouchableOpacity 
            onPress={() => setIsModalVisible(true)}
            activeOpacity={0.8}
            className="w-full max-w-md"
          >
            <View 
              className="bg-gray-800 rounded-2xl shadow-lg overflow-hidden"
              style={{ 
                width: '100%', 
                aspectRatio: djiAspectRatio 
              }}
            >
              {latestDetection && latestDetection[3] === 'image' ? (
                <Image
                  source={{ uri: (latestDetection as any).cloud_annotated_url || (latestDetection as any).cloud_secure_url || `${API_BASE}/uploads/${latestDetection[1]}` }}
                  resizeMode="cover"
                  style={{ width: '100%', height: '100%' }}
                  onError={(error) => {
                    console.log('Image load error:', error)
                    Alert.alert('Error', 'Failed to load image')
                  }}
                />
              ) : latestDetection && latestDetection[3] === 'video' && (latestDetection as any).cloud_secure_url ? (
                <Video
                  source={{ uri: (latestDetection as any).cloud_annotated_url || (latestDetection as any).cloud_secure_url }}
                  style={{ width: '100%', height: '100%' }}
                  resizeMode={ResizeMode.COVER}
                  shouldPlay={false}
                  isLooping={true}
                  isMuted={true}
                  onError={(error) => {
                    console.log('Video load error:', error)
                    Alert.alert('Error', 'Failed to load video')
                  }}
                />
              ) : (
                <View className="flex-1 items-center justify-center">
                  <Ionicons name="play-circle" size={64} color="white" />
                  <Text className="text-white text-lg font-medium mt-3 text-center">
                    {latestDetection?.[3] === 'video' ? 'Detection Video' : 'Media preview unavailable'}
                  </Text>
                  <Text className="text-gray-300 text-xs mt-1 px-3 text-center">
                    {latestDetection?.[3] === 'video'
                      ? 'Tap to expand and play video'
                      : 'No media available for preview'}
                  </Text>
                </View>
              )}
              
              {/* Expand indicator overlay */}
              <View className="absolute top-2 right-2 bg-black/50 rounded-full p-2">
                <Ionicons name="expand" size={20} color="white" />
              </View>
            </View>
          </TouchableOpacity>
        </View>

        {/* Fullscreen Modal */}
        <Modal
          visible={isModalVisible}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setIsModalVisible(false)}
        >
          <View className="flex-1 bg-black/90 justify-center items-center">
            <TouchableOpacity 
              className="absolute top-12 right-4 z-10 bg-black/50 rounded-full p-3"
              onPress={() => setIsModalVisible(false)}
            >
              <Ionicons name="close" size={24} color="white" />
            </TouchableOpacity>
            
            <View 
              className="w-full max-w-full mx-4"
              style={{ 
                aspectRatio: djiAspectRatio,
                maxHeight: screenHeight * 0.8,
                maxWidth: screenWidth * 0.95
              }}
            >
              {latestDetection && latestDetection[3] === 'image' ? (
                <Image
                  source={{ uri: (latestDetection as any).cloud_annotated_url || (latestDetection as any).cloud_secure_url || `${API_BASE}/uploads/${latestDetection[1]}` }}
                  resizeMode="contain"
                  style={{ width: '100%', height: '100%' }}
                  onError={(error) => {
                    console.log('Modal image load error:', error)
                    Alert.alert('Error', 'Failed to load image in fullscreen')
                  }}
                />
              ) : latestDetection && latestDetection[3] === 'video' && (latestDetection as any).cloud_secure_url ? (
                <Video
                  source={{ uri: (latestDetection as any).cloud_annotated_url || (latestDetection as any).cloud_secure_url }}
                  style={{ width: '100%', height: '100%' }}
                  resizeMode={ResizeMode.CONTAIN}
                  shouldPlay={true}
                  isLooping={true}
                  isMuted={false}
                  useNativeControls={true}
                  onError={(error) => {
                    console.log('Modal video load error:', error)
                    Alert.alert('Error', 'Failed to load video in fullscreen')
                  }}
                />
              ) : (
                <View className="flex-1 items-center justify-center bg-gray-800 rounded-lg">
                  <Ionicons name="alert-circle" size={64} color="white" />
                  <Text className="text-white text-lg font-medium mt-3 text-center">
                    Media Unavailable
                  </Text>
                  <Text className="text-gray-300 text-sm mt-1 px-4 text-center">
                    The media file could not be loaded for preview
                  </Text>
                </View>
              )}
            </View>
          </View>
        </Modal>

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
                    {uniqueWeedCount !== null ? uniqueWeedCount : (summary?.totalWeeds ?? 0)}
                  </Text>
                </View>
                <Text className="text-sm text-gray-600 text-center">
                  {uniqueWeedCount !== null ? 'Unique Weeds' : 'Total Weeds'}
                </Text>
                {uniqueWeedCount !== null && uniqueWeedData && (
                  <Text className="text-xs text-gray-500 text-center mt-1">
                    ({uniqueWeedData.total_detections} detections)
                  </Text>
                )}
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
              {latestDetection && (
                <View className="flex-row items-center justify-center mt-2">
                  {latestDetection[10] ? (
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
              )}
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
              <TouchableOpacity 
                className="bg-green-50 border border-green-200 rounded-lg p-3"
                onPress={handleViewMap}
                disabled={exporting}
              >
                <View className="flex-row items-center">
                  <FontAwesome6 name="map-marker-alt" size={20} color="rgb(37, 165, 120)" />
                  <Text className="text-green-700 font-medium ml-3 flex-1">
                    View on Map
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(37, 165, 120)" />
                </View>
              </TouchableOpacity>
              
              <TouchableOpacity 
                className="bg-blue-50 border border-blue-200 rounded-lg p-3"
                onPress={handleExport}
                disabled={exporting}
              >
                <View className="flex-row items-center">
                  <FontAwesome6 name="download" size={20} color="rgb(59, 130, 246)" />
                  <Text className="text-blue-700 font-medium ml-3 flex-1">
                    {exporting ? 'Exporting...' : 'Export Report'}
                  </Text>
                  {exporting ? (
                    <ActivityIndicator size="small" color="rgb(59, 130, 246)" />
                  ) : (
                    <Ionicons name="chevron-forward" size={20} color="rgb(59, 130, 246)" />
                  )}
                </View>
              </TouchableOpacity>
              
              <TouchableOpacity 
                className="bg-orange-50 border border-orange-200 rounded-lg p-3"
                onPress={handleShare}
                disabled={exporting}
              >
                <View className="flex-row items-center">
                  <FontAwesome6 name="share" size={20} color="rgb(245, 101, 101)" />
                  <Text className="text-orange-700 font-medium ml-3 flex-1">
                    Share Results
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(245, 101, 101)" />
                </View>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </View>
    </ScrollView>
  )
}

export default DetectionResults
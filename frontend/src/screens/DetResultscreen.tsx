import React, { useEffect, useMemo, useState, useCallback } from 'react'
import * as ScreenOrientation from 'expo-screen-orientation'
import {
  View,
  Text,
  ActivityIndicator,
  ScrollView,
  RefreshControl,
  Modal,
  Dimensions,
  Alert,
  Linking,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useNavigation } from '@react-navigation/native'
import * as FileSystem from 'expo-file-system/legacy'
import * as Sharing from 'expo-sharing'
import { API_BASE } from '../config'
import { useSession } from '../context/SessionContext'
import {
  DetectionDetailRow,
  DetectionRow,
  FrameMetadataRow,
  UniqueWeedPayload,
} from '../components/detresults/types'
import {
  buildDetectionSummary,
  fetchDetectionResultsData,
  formatAmPm,
} from '../services/detResultsService'
import DetMediaPreviewCard from '../components/detresults/DetMediaPreviewCard'
import DetFullscreenMediaModal from '../components/detresults/DetFullscreenMediaModal'
import DetSessionSelectionModal from '../components/detresults/DetSessionSelectionModal'
import DetSummaryCard from '../components/detresults/DetSummaryCard'
import DetSpeciesBreakdownCard from '../components/detresults/DetSpeciesBreakdownCard'
import DetActionsCard from '../components/detresults/DetActionsCard'
import DetExportOverlay from '../components/detresults/DetExportOverlay'

const DetectionResults = () => {
  const navigation = useNavigation()
  const { selectedDetection, sessions, refreshSessions, setSelectedDetection } = useSession()
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  const [details, setDetails] = useState<DetectionDetailRow[]>([])
  const [frames, setFrames] = useState<FrameMetadataRow[]>([])
  const [isModalVisible, setIsModalVisible] = useState<boolean>(false)
  const [sessionModalVisible, setSessionModalVisible] = useState<boolean>(false)
  const [exporting, setExporting] = useState<boolean>(false)
  const [exportCancelToken, setExportCancelToken] = useState<AbortController | null>(null)
  const [uniqueWeedCount, setUniqueWeedCount] = useState<number | null>(null)
  const [uniqueWeedData, setUniqueWeedData] = useState<UniqueWeedPayload | null>(null)

  const { width: screenWidth, height: screenHeight } = Dimensions.get('window')

  useEffect(() => {
    if (isModalVisible) {
      ScreenOrientation.unlockAsync()
    } else {
      ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.PORTRAIT_UP)
    }

    return () => {
      ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.PORTRAIT_UP)
    }
  }, [isModalVisible])

  const handleImageError = useCallback((err: any) => {
    console.log('Image load error:', err)
  }, [])

  const handleVideoError = useCallback((err: any) => {
    console.log('Video load error:', err)
  }, [])

  const loadDetectionData = useCallback(async (detection: DetectionRow) => {
    try {
      setLoading(true)
      setError('')

      const payload = await fetchDetectionResultsData(detection)
      setFrames(payload.frames)
      setDetails(payload.details)
      setUniqueWeedCount(payload.uniqueWeedCount)
      setUniqueWeedData(payload.uniqueWeedData)
    } catch (e: any) {
      setError(e?.message || 'Failed to load session')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedDetection) {
      loadDetectionData(selectedDetection as DetectionRow)
    } else {
      setDetails([])
      setFrames([])
      setUniqueWeedCount(null)
      setUniqueWeedData(null)
      setError('')
    }
  }, [selectedDetection, loadDetectionData])

  const handleViewMap = useCallback(() => {
    if (!selectedDetection) {
      Alert.alert('No Data', 'No detection session available.')
      return
    }

    const detectionId = selectedDetection[0]
    const hasGPS = selectedDetection[10]

    if (!hasGPS) {
      Alert.alert(
        'GPS Data Required',
        'This detection has no GPS data. Upload a video with SRT file to view map data.',
        [{ text: 'OK' }]
      )
      return
    }

    ;(navigation as any).navigate('Map', {
      detectionId,
      autoFocus: true,
    })
  }, [selectedDetection, navigation])

  const handleOpenSelectSession = useCallback(async () => {
    await refreshSessions()
    setSessionModalVisible(true)
  }, [refreshSessions])

  const cancelExport = useCallback(() => {
    if (exportCancelToken) {
      exportCancelToken.abort()
      setExportCancelToken(null)
      setExporting(false)
      console.log('Export cancelled by user')
    }
  }, [exportCancelToken])

  const exportReport = async (detectionId: number, format: string) => {
    try {
      setExporting(true)

      const abortController = new AbortController()
      setExportCancelToken(abortController)

      const url = `${API_BASE}/detection/${detectionId}/export?format=${format}`
      const filename = `detection_report_${detectionId}.${format}`
      const fileUri = `${FileSystem.documentDirectory}${filename}`

      const downloadResult = await FileSystem.downloadAsync(url, fileUri)

      if (abortController.signal.aborted) {
        return
      }

      if (downloadResult.status === 200) {
        const canShare = await Sharing.isAvailableAsync()
        if (canShare) {
          await Sharing.shareAsync(downloadResult.uri, {
            mimeType:
              format === 'json'
                ? 'application/json'
                : format === 'csv'
                  ? 'text/csv'
                  : 'application/pdf',
            dialogTitle: `Export Detection Report (${format.toUpperCase()})`,
          })
        } else {
          Alert.alert('Export Complete', `Report saved to:\n${downloadResult.uri}`, [{ text: 'OK' }])
        }
      } else {
        throw new Error(`Download failed with status: ${downloadResult.status}`)
      }
    } catch (error: any) {
      if (error.name === 'AbortError' || error.message?.includes('aborted')) {
        return
      }

      if (error.message?.includes('reportlab')) {
        Alert.alert(
          'PDF Export Unavailable',
          'PDF export requires additional setup on the server. Try JSON or CSV format instead.',
          [{ text: 'OK' }]
        )
      } else {
        Alert.alert('Export Failed', error.message || 'Could not export report. Please try again.', [{ text: 'OK' }])
      }
    } finally {
      setExporting(false)
      setExportCancelToken(null)
    }
  }

  const handleExport = useCallback(async () => {
    if (!selectedDetection) {
      Alert.alert('No Data', 'No detection session available to export.')
      return
    }

    const detectionId = selectedDetection[0]

    Alert.alert('Export Format', 'Choose export format:', [
      { text: 'JSON', onPress: () => exportReport(detectionId, 'json') },
      { text: 'CSV', onPress: () => exportReport(detectionId, 'csv') },
      { text: 'PDF', onPress: () => exportReport(detectionId, 'pdf') },
      { text: 'Cancel', style: 'cancel' },
    ])
  }, [selectedDetection])

  const handleShare = useCallback(async () => {
    if (!selectedDetection) {
      Alert.alert('No Data', 'No detection session available to share.')
      return
    }

    const detectionId = selectedDetection[0]

    try {
      setExporting(true)

      const response = await fetch(`${API_BASE}/detection/${detectionId}/share`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(`Share failed: ${response.status}`)
      }

      const shareData = await response.json()
      const shareMessage =
        shareData.share_message ||
        `Weed Detection Results\n\nFile: ${selectedDetection[1]}\nDetected: ${details.length} weeds\n\nView: ${shareData.media_urls?.annotated || 'N/A'}`

      const canShare = await Sharing.isAvailableAsync()

      if (canShare && shareData.media_urls?.annotated) {
        const filename = `detection_${detectionId}_annotated.${selectedDetection[3] === 'video' ? 'mp4' : 'jpg'}`
        const fileUri = `${FileSystem.cacheDirectory}${filename}`

        try {
          const downloadResult = await FileSystem.downloadAsync(shareData.media_urls.annotated, fileUri)
          if (downloadResult.status === 200) {
            await Sharing.shareAsync(downloadResult.uri, {
              mimeType: selectedDetection[3] === 'video' ? 'video/mp4' : 'image/jpeg',
              dialogTitle: 'Share Detection Results',
            })
          } else {
            Alert.alert('Share Results', shareMessage, [
              {
                text: 'Copy Link',
                onPress: () => {
                  Alert.alert('Link', shareData.media_urls?.annotated || 'No link available')
                },
              },
              { text: 'Cancel', style: 'cancel' },
            ])
          }
        } catch {
          Alert.alert('Share Results', shareMessage, [{ text: 'OK' }])
        }
      } else {
        Alert.alert('Share Results', shareMessage, [
          {
            text: 'Open Link',
            onPress: () => {
              const url = shareData.media_urls?.annotated || shareData.media_urls?.original
              if (url) Linking.openURL(url)
            },
          },
          { text: 'OK' },
        ])
      }
    } catch (error: any) {
      Alert.alert('Share Failed', error.message || 'Could not create share package. Please try again.', [
        { text: 'OK' },
      ])
    } finally {
      setExporting(false)
    }
  }, [selectedDetection, details])

  const summary = useMemo(
    () => buildDetectionSummary((selectedDetection as DetectionRow | null) ?? null, details),
    [selectedDetection, details]
  )

  return (
    <SafeAreaView className="flex-1 bg-bgColor1" edges={['top']}>
      <ScrollView
        className="flex-1"
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={() => refreshSessions()} />}
      >
        <View className="flex-1 justify-start items-center pb-8 px-4" style={{ paddingTop: 48 }}>
          <DetMediaPreviewCard
            selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
            screenHeight={screenHeight}
            onOpenFullscreen={() => setIsModalVisible(true)}
            onImageError={handleImageError}
            onVideoError={handleVideoError}
          />

          <DetSessionSelectionModal
            visible={sessionModalVisible}
            sessions={(sessions as DetectionRow[]) ?? []}
            selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
            onClose={() => setSessionModalVisible(false)}
            onSelectSession={(session) => setSelectedDetection(session)}
            onClearSelection={() => setSelectedDetection(null)}
            onRefreshSessions={refreshSessions}
            formatAmPm={formatAmPm}
          />

          <DetFullscreenMediaModal
            visible={isModalVisible}
            selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
            screenWidth={screenWidth}
            screenHeight={screenHeight}
            onClose={() => setIsModalVisible(false)}
            onVideoError={handleVideoError}
          />

          {loading && (
            <View className="w-full max-w-md mb-6">
              <View className="bg-white rounded-2xl shadow-lg p-6 items-center">
                <ActivityIndicator />
                <Text className="text-gray-600 mt-2">Loading results...</Text>
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

          <DetSummaryCard
            summary={summary}
            selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
            uniqueWeedCount={uniqueWeedCount}
            uniqueWeedData={uniqueWeedData}
            formatAmPm={formatAmPm}
          />

          <DetSpeciesBreakdownCard summary={summary} />

          <DetActionsCard
            exporting={exporting}
            onViewMap={handleViewMap}
            onSelectSession={handleOpenSelectSession}
            onExport={handleExport}
            onCancelExport={cancelExport}
            onShare={handleShare}
          />
        </View>

        <DetExportOverlay visible={exporting} onCancel={cancelExport} />
      </ScrollView>
    </SafeAreaView>
  )
}

export default DetectionResults

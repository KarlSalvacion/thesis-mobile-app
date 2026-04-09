import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { View, Text, Pressable, ScrollView, RefreshControl } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useRoute } from '@react-navigation/native'
import { useSession } from '../context/SessionContext'
import MapViewport from '../components/map/MapViewport'
import MapLegend from '../components/map/MapLegend'
import DensityOverviewCard from '../components/map/DensityOverviewCard'
import UniqueWeedAnalysisCard from '../components/map/UniqueWeedAnalysisCard'
import SessionSelectionModal from '../components/map/SessionSelectionModal'
import { DetectionRow, HeatPoint, GMapPoint } from '../components/map/types'
import { useRealtimeUserLocation } from '../hooks/useRealtimeUserLocation'
import {
  computeDensityStats,
  createEmptyMapData,
  fetchMapDataForDetection,
  formatDateTime,
} from '../services/mapScreenService'

const Mapscreen = () => {
  const { selectedDetection, sessions, refreshSessions, setSelectedDetection } = useSession()
  const [scrollEnabled, setScrollEnabled] = useState(true)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  const [polyline, setPolyline] = useState<GMapPoint[]>([])
  const [heatPoints, setHeatPoints] = useState<HeatPoint[]>([])
  const [uniqueWeedCount, setUniqueWeedCount] = useState<number>(0)
  const [totalDetections, setTotalDetections] = useState<number>(0)
  const [sessionModalVisible, setSessionModalVisible] = useState<boolean>(false)

  const {
    showUserLocation,
    setShowUserLocation,
    userLocation,
    locationError,
    toggleDisabled,
    setToggleDisabled,
  } = useRealtimeUserLocation()

  const clearMapState = useCallback(() => {
    const empty = createEmptyMapData()
    setPolyline(empty.polyline)
    setHeatPoints(empty.heatPoints)
    setUniqueWeedCount(empty.uniqueWeedCount)
    setTotalDetections(empty.totalDetections)
    setError('')
  }, [])

  const loadMapData = useCallback(async (detection: DetectionRow) => {
    try {
      setLoading(true)
      setError('')

      const empty = createEmptyMapData()
      setPolyline(empty.polyline)
      setHeatPoints(empty.heatPoints)
      setUniqueWeedCount(empty.uniqueWeedCount)
      setTotalDetections(empty.totalDetections)

      const payload = await fetchMapDataForDetection(detection)
      setPolyline(payload.polyline)
      setHeatPoints(payload.heatPoints)
      setUniqueWeedCount(payload.uniqueWeedCount)
      setTotalDetections(payload.totalDetections)
    } catch (e: any) {
      setError(e?.message || 'Failed to load map data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedDetection) {
      loadMapData(selectedDetection as DetectionRow)
    } else {
      clearMapState()
    }
  }, [selectedDetection, loadMapData, clearMapState])

  const route: any = useRoute()
  useEffect(() => {
    const idParam = route?.params?.detectionId
    if (typeof idParam === 'number') {
      const detection = (sessions as DetectionRow[]).find((s) => s[0] === idParam)
      if (detection) {
        setSelectedDetection(detection)
      }
    }
  }, [route?.params, sessions, setSelectedDetection])

  const density = useMemo(
    () => computeDensityStats(heatPoints, polyline),
    [heatPoints, polyline]
  )

  const onRefresh = useCallback(async () => {
    await refreshSessions()
  }, [refreshSessions])

  return (
    <SafeAreaView className="flex-1 bg-bgColor1" edges={['top']}>
      <ScrollView
        className="flex-1"
        scrollEnabled={scrollEnabled}
        contentContainerStyle={{ alignItems: 'center', paddingTop: 24, paddingBottom: 16 }}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={onRefresh}
            colors={['#2563eb']}
            tintColor="#2563eb"
          />
        }
      >
        <MapViewport
          polyline={polyline}
          heatPoints={heatPoints}
          loading={loading}
          error={error}
          locationError={locationError}
          selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
          showUserLocation={showUserLocation}
          userLocation={userLocation}
          toggleDisabled={toggleDisabled}
          setShowUserLocation={(updater) => setShowUserLocation(updater)}
          setToggleDisabled={setToggleDisabled}
          setScrollEnabled={setScrollEnabled}
        />

        <Pressable
          onPress={async () => {
            await refreshSessions()
          }}
          className="mt-4 px-6 py-2 bg-gray-700 rounded-md w-[95vw] max-w-[420px]"
        >
          <Text className="text-white font-medium text-center">Refresh Sessions</Text>
        </Pressable>

        <Pressable
          onPress={() => setSessionModalVisible(true)}
          className="mt-3 px-6 py-2 bg-gray-100 rounded-md w-[95vw] max-w-[420px]"
        >
          <Text className="text-gray-700 font-medium text-center">Select Session</Text>
        </Pressable>

        <SessionSelectionModal
          visible={sessionModalVisible}
          sessions={(sessions as DetectionRow[]) ?? []}
          selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
          onClose={() => setSessionModalVisible(false)}
          onSelectSession={(session) => {
            setSessionModalVisible(false)
            setSelectedDetection(session)
          }}
          onClearSelected={() => setSelectedDetection(null)}
          onAfterDeleteRefresh={refreshSessions}
        />

        <MapLegend />

        <DensityOverviewCard
          density={density}
          selectedDetection={(selectedDetection as DetectionRow | null) ?? null}
          formatDateTime={formatDateTime}
        />

        <UniqueWeedAnalysisCard
          uniqueWeedCount={uniqueWeedCount}
          totalDetections={totalDetections}
          density={density}
        />
      </ScrollView>
    </SafeAreaView>
  )
}

export default Mapscreen

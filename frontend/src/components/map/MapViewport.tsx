import React from 'react'
import { View, Text, ActivityIndicator, Pressable } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import LeafletWebMap from './LeafletWebMap'
import { DetectionRow, GMapPoint, HeatPoint } from './types'

type Props = {
  polyline: GMapPoint[]
  heatPoints: HeatPoint[]
  loading: boolean
  error: string
  locationError: string
  selectedDetection: DetectionRow | null
  showUserLocation: boolean
  userLocation: { lat: number; lng: number } | null
  toggleDisabled: boolean
  setShowUserLocation: (updater: (prev: boolean) => boolean) => void
  setToggleDisabled: (disabled: boolean) => void
  setScrollEnabled: (enabled: boolean) => void
}

const MapViewport = ({
  polyline,
  heatPoints,
  loading,
  error,
  locationError,
  selectedDetection,
  showUserLocation,
  userLocation,
  toggleDisabled,
  setShowUserLocation,
  setToggleDisabled,
  setScrollEnabled,
}: Props) => {
  return (
    <View
      style={{
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
        shadowOffset: { width: 0, height: 2 },
        position: 'relative',
      }}
    >
      <LeafletWebMap
        polyline={polyline}
        heat={heatPoints}
        setScrollEnabled={setScrollEnabled}
        userLocation={showUserLocation && userLocation ? userLocation : null}
        centerOn={showUserLocation && userLocation ? userLocation : null}
      />

      <View style={{ position: 'absolute', top: 12, right: 12, zIndex: 10 }}>
        <Pressable
          onPress={() => {
            if (toggleDisabled) return
            setShowUserLocation((v) => !v)
            setToggleDisabled(true)
            setTimeout(() => {
              setToggleDisabled(false)
            }, 1000)
          }}
          style={{
            backgroundColor: showUserLocation ? '#2563eb' : '#fff',
            borderRadius: 24,
            padding: 8,
            borderWidth: 1,
            borderColor: '#2563eb',
            elevation: 2,
            opacity: toggleDisabled ? 0.5 : 1,
          }}
          disabled={toggleDisabled}
        >
          <Ionicons name="locate" size={24} color={showUserLocation ? '#fff' : '#2563eb'} />
        </Pressable>
      </View>

      <View
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          alignItems: 'center',
          justifyContent: 'center',
          pointerEvents: 'box-none',
        }}
        pointerEvents="box-none"
      >
        {loading ? (
          <ActivityIndicator color="#2563eb" />
        ) : error ? (
          <Text className="text-center text-red-600 bg-white/80 px-4 py-2 rounded">{error}</Text>
        ) : locationError ? (
          <Text className="text-center text-red-600 bg-white/80 px-4 py-2 rounded">{locationError}</Text>
        ) : selectedDetection && !selectedDetection[10] ? (
          <Text className="text-center text-gray-600 bg-white/80 px-4 py-2 rounded">No GPS data available for this session</Text>
        ) : null}
      </View>
    </View>
  )
}

export default MapViewport

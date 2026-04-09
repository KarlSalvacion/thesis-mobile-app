import React from 'react'
import { View, Text, TouchableOpacity } from 'react-native'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'

type Props = {
  exporting: boolean
  onViewMap: () => void
  onSelectSession: () => void
  onExport: () => void
  onCancelExport: () => void
  onShare: () => void
}

const DetActionsCard = ({
  exporting,
  onViewMap,
  onSelectSession,
  onExport,
  onCancelExport,
  onShare,
}: Props) => {
  return (
    <View className="w-full max-w-md">
      <View className="bg-white rounded-2xl shadow-lg p-6">
        <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">Actions</Text>

        <View className="space-y-3">
          <TouchableOpacity className="bg-green-50 border border-green-200 rounded-lg p-3" onPress={onViewMap} disabled={exporting}>
            <View className="flex-row items-center">
              <Ionicons name="map" size={24} color="rgb(37, 165, 120)" />
              <Text className="text-green-700 font-medium ml-3 flex-1">View on Map</Text>
              <Ionicons name="chevron-forward" size={20} color="rgb(37, 165, 120)" />
            </View>
          </TouchableOpacity>

          <TouchableOpacity className="bg-gray-50 border border-gray-200 rounded-lg p-3" onPress={onSelectSession} disabled={exporting}>
            <View className="flex-row items-center">
              <FontAwesome6 name="list" size={20} color="rgb(107, 114, 128)" />
              <Text className="text-gray-700 font-medium ml-3 flex-1">Select Session</Text>
              <Ionicons name="chevron-forward" size={20} color="rgb(107, 114, 128)" />
            </View>
          </TouchableOpacity>

          <TouchableOpacity className="bg-blue-50 border border-blue-200 rounded-lg p-3" onPress={exporting ? onCancelExport : onExport}>
            <View className="flex-row items-center">
              <FontAwesome6 name={exporting ? 'times' : 'download'} size={20} color="rgb(59, 130, 246)" />
              <Text className="text-blue-700 font-medium ml-3 flex-1">{exporting ? 'Cancel Export' : 'Export Report'}</Text>
              {exporting ? (
                <Ionicons name="close" size={20} color="rgb(239, 68, 68)" />
              ) : (
                <Ionicons name="chevron-forward" size={20} color="rgb(59, 130, 246)" />
              )}
            </View>
          </TouchableOpacity>

          <TouchableOpacity className="bg-orange-50 border border-orange-200 rounded-lg p-3" onPress={onShare} disabled={exporting}>
            <View className="flex-row items-center">
              <FontAwesome6 name="share" size={20} color="rgb(245, 101, 101)" />
              <Text className="text-orange-700 font-medium ml-3 flex-1">Share Results</Text>
              <Ionicons name="chevron-forward" size={20} color="rgb(245, 101, 101)" />
            </View>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  )
}

export default DetActionsCard

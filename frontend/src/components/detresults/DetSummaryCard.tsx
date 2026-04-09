import React from 'react'
import { View, Text } from 'react-native'
import { DetectionRow, DetectionSummary, UniqueWeedPayload } from './types'

type Props = {
  summary: DetectionSummary | null
  selectedDetection: DetectionRow | null
  uniqueWeedCount: number | null
  uniqueWeedData: UniqueWeedPayload | null
  formatAmPm: (ts?: string | null) => string
}

const DetSummaryCard = ({
  summary,
  selectedDetection,
  uniqueWeedCount,
  uniqueWeedData,
  formatAmPm,
}: Props) => {
  return (
    <View className="w-full max-w-md mb-6">
      <View className="bg-white rounded-2xl shadow-lg p-6">
        <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">Detection Summary</Text>

        <View className="flex-row justify-between items-center mb-4">
          <View className="items-center flex-1">
            <View className="bg-green-100 rounded-full w-16 h-16 items-center justify-center mb-2">
              <Text className="text-2xl font-bold text-green-600">
                {uniqueWeedCount !== null ? uniqueWeedCount : (summary?.totalWeeds ?? 0)}
              </Text>
            </View>
            <Text className="text-sm text-gray-600 text-center">
              {uniqueWeedCount !== null ? 'Estimated Unique Weeds' : 'Total Weeds'}
            </Text>
            {uniqueWeedCount !== null && uniqueWeedData && (
              <Text className="text-xs text-gray-500 text-center mt-1">
                ({uniqueWeedData.total_detections} detections)
                {uniqueWeedData.no_gps_data && <Text className="text-orange-600"> • No GPS data</Text>}
              </Text>
            )}
          </View>

          <View className="items-center flex-1">
            <View className="bg-blue-100 rounded-full w-16 h-16 items-center justify-center mb-2">
              <Text className="text-lg font-bold text-blue-600">{summary?.confidence ?? 0}%</Text>
            </View>
            <Text className="text-sm text-gray-600 text-center">Confidence</Text>
          </View>
        </View>

        <View className="bg-gray-50 rounded-lg p-3">
          <Text className="text-xs text-gray-600 text-center">
            {selectedDetection ? `File: ${selectedDetection[1]} (${selectedDetection[3]})` : ''}
          </Text>
          <Text className="text-xs text-gray-500 text-center mt-1">
            {summary?.timestamp ? `Detected on ${formatAmPm(summary.timestamp)}` : 'No recent session'}
          </Text>
          {selectedDetection && (
            <View className="flex-row items-center justify-center mt-2">
              {selectedDetection[10] ? (
                <>
                  <View className="w-2 h-2 bg-green-500 rounded-full mr-1" />
                  <Text className="text-xs text-green-600 font-medium">GPS Data Available</Text>
                </>
              ) : (
                <>
                  <View className="w-2 h-2 bg-gray-400 rounded-full mr-1" />
                  <Text className="text-xs text-gray-500 font-medium">No GPS Data</Text>
                </>
              )}
            </View>
          )}
        </View>
      </View>
    </View>
  )
}

export default DetSummaryCard

import React from 'react'
import { View, Text } from 'react-native'
import { DetectionSummary } from './types'

type Props = {
  summary: DetectionSummary | null
}

const DetSpeciesBreakdownCard = ({ summary }: Props) => {
  return (
    <View className="w-full max-w-md mb-6">
      <View className="bg-white rounded-2xl shadow-lg p-6">
        <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">Weed Species Detected</Text>

        {(summary?.species ?? []).map((species, index) => (
          <View key={index} className="mb-4 last:mb-0">
            <View className="flex-row items-center justify-between mb-2">
              <View className="flex-row items-center">
                <View className={`w-4 h-4 rounded-full ${species.color} mr-3`} />
                <Text className="text-base font-medium text-gray-800">{species.name}</Text>
              </View>
              <Text className="text-lg font-bold text-gray-700">{species.count}</Text>
            </View>

            <View className="flex-row items-center justify-between">
              <View className="flex-1 bg-gray-200 rounded-full h-2 mr-3">
                <View
                  className={`h-2 rounded-full ${species.color}`}
                  style={{ width: `${Math.min(100, Math.max(0, species.confidence))}%` }}
                />
              </View>
              <Text className="text-sm text-gray-600 min-w-[50px] text-right">{species.confidence}%</Text>
            </View>
          </View>
        ))}

        {(!summary || (summary.species?.length ?? 0) === 0) && (
          <Text className="text-center text-gray-500">No detections available.</Text>
        )}
      </View>
    </View>
  )
}

export default DetSpeciesBreakdownCard

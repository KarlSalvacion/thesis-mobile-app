import React from 'react'
import { View, Text } from 'react-native'
import { DensityStats } from './types'

type Props = {
  uniqueWeedCount: number
  totalDetections: number
  density: DensityStats
}

const UniqueWeedAnalysisCard = ({ uniqueWeedCount, totalDetections, density }: Props) => {
  if (uniqueWeedCount <= 0) return null

  return (
    <View className="flex-col bg-white min-h-[100px] w-[95vw] max-w-[420px] rounded-2xl p-4 shadow-custom border-2 border-gray-300 mt-2">
      <View className="bg-blue-600 shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
        <Text className="text-left text-white text-md font-bold">Unique Weed Analysis</Text>
      </View>
      <View className="flex-row justify-between items-center mt-2 w-full">
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-blue-50">
          <Text className="text-xs font-bold text-gray-600">Estimated Unique Weeds</Text>
          <Text className="text-2xl font-bold text-blue-600">{uniqueWeedCount}</Text>
          <Text className="text-[9px] text-gray-400 mt-1">Tracked across frames</Text>
        </View>
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-gray-50">
          <Text className="text-xs font-bold text-gray-600">Total Detections</Text>
          <Text className="text-2xl font-bold text-gray-700">{totalDetections}</Text>
          <Text className="text-[9px] text-gray-400 mt-1">All raw detections</Text>
        </View>
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2 bg-green-50">
          <Text className="text-xs font-bold text-gray-600">Reduction</Text>
          <Text className="text-2xl font-bold text-green-600">
            {totalDetections > 0 ? Math.round((1 - uniqueWeedCount / totalDetections) * 100) : 0}%
          </Text>
          <Text className="text-[9px] text-gray-400 mt-1">Duplicate removal</Text>
        </View>
      </View>
      <View className="bg-blue-50 rounded-lg p-2 mt-3">
        <Text className="text-[10px] text-gray-600 text-center">
          Note: Density totals ({density.low + density.medium + density.high}) show unique weeds categorized by spatial concentration
        </Text>
      </View>
      <Text className="text-xs text-gray-500 text-center mt-2">
        Heatmap shows unique weeds by tracking the same weed across frames
      </Text>
    </View>
  )
}

export default UniqueWeedAnalysisCard

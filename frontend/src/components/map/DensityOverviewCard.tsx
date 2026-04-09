import React from 'react'
import { View, Text } from 'react-native'
import { DensityStats, DetectionRow } from './types'

type Props = {
  density: DensityStats
  selectedDetection: DetectionRow | null
  formatDateTime: (ts?: string | null) => string
}

const DensityOverviewCard = ({ density, selectedDetection, formatDateTime }: Props) => {
  return (
    <View className="flex-col bg-white min-h-[120px] w-[95vw] max-w-[420px] rounded-2xl p-4 shadow-custom border-2 border-gray-300 mt-2">
      <View className="bg-greenColor shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
        <Text className="text-left text-white text-md font-bold">Density Overview</Text>
      </View>
      <View className="flex-row justify-between items-center mt-2 w-full">
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
          <Text className="text-xs font-bold text-gray-600">Low Density</Text>
          <Text className="text-[10px] text-gray-500">(≤2 per area)</Text>
          <Text className="text-base font-medium mt-1">{density.low}</Text>
          <Text className="text-[9px] text-gray-400">weeds</Text>
        </View>
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
          <Text className="text-xs font-bold text-gray-600">Medium</Text>
          <Text className="text-[10px] text-gray-500">(3 per area)</Text>
          <Text className="text-base font-medium mt-1">{density.medium}</Text>
          <Text className="text-[9px] text-gray-400">weeds</Text>
        </View>
        <View className="flex-1 flex-col justify-center items-center mx-1 rounded-md py-2">
          <Text className="text-xs font-bold text-gray-600">High Density</Text>
          <Text className="text-[10px] text-gray-500">(≥4 per area)</Text>
          <Text className="text-base font-medium mt-1">{density.high}</Text>
          <Text className="text-[9px] text-gray-400">weeds</Text>
        </View>
      </View>
      {selectedDetection && (
        <View className="mt-2">
          <Text className="text-xs text-gray-700 text-center">
            File: {selectedDetection[1]} ({selectedDetection[3]})
          </Text>
          <Text className="text-xs text-gray-500 text-center mt-1">Detected on {formatDateTime(selectedDetection[2])}</Text>
          <View className="flex-row items-center justify-center mt-1">
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
        </View>
      )}
    </View>
  )
}

export default DensityOverviewCard

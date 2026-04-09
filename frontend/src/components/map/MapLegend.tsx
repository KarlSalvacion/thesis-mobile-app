import React from 'react'
import { View, Text } from 'react-native'

const MapLegend = () => {
  return (
    <View className="flex-row flex-wrap items-center justify-between w-[95vw] max-w-[420px] mt-4 mb-2">
      <View className="flex-row items-center mb-1">
        <View className="bg-green-700 h-[14px] w-[18px] rounded-md" />
        <Text className="text-xs ml-2 font-medium text-gray-700">Low</Text>
      </View>
      <View className="flex-row items-center mb-1">
        <View className="bg-yellow-100 h-[14px] w-[18px] rounded-md" />
        <Text className="text-xs ml-2 font-medium text-gray-700">Medium</Text>
      </View>
      <View className="flex-row items-center mb-1">
        <View className="bg-red-600 h-[14px] w-[18px] rounded-md" />
        <Text className="text-xs ml-2 font-medium text-gray-700">High</Text>
      </View>
      <View className="flex-row items-center mb-1">
        <View className="bg-blue-700 h-[14px] w-[18px] rounded-md" />
        <Text className="text-xs ml-2 font-medium text-gray-700">Path</Text>
      </View>
      <View className="flex-row items-center mb-1">
        <View className="bg-green-500 h-[12px] w-[12px] rounded-full border-2 border-white shadow" />
        <Text className="text-xs ml-2 font-medium text-gray-700">Start</Text>
      </View>
      <View className="flex-row items-center mb-1">
        <View className="bg-red-500 h-[12px] w-[12px] rounded-full border-2 border-white shadow" />
        <Text className="text-xs ml-2 font-medium text-gray-700">End</Text>
      </View>
    </View>
  )
}

export default MapLegend

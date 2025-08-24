import React from 'react'
import { View, Text } from 'react-native'

const DetectionResults = () => {
  return (
    <View className="flex-1 justify-center items-center bg-green-50">
      <Text className="text-2xl font-bold text-green-800 mb-4">
        Detection Results
      </Text>
      <Text className="text-green-600 text-center px-6">
        View your detection results and analysis here.
      </Text>
    </View>
  )
}

export default DetectionResults
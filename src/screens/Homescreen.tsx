import React from 'react'
import { View, Text } from 'react-native'

const Homescreen = () => {
  return (
    <View className="flex-1 justify-center items-center bg-gray-50">
      <Text className="text-2xl font-bold text-gray-800 mb-4">
        Welcome to Home Screen
      </Text>
      <Text className="text-gray-600 text-center px-6">
        This is your main home screen. Start building your app here!
      </Text>
    </View>
  )
}

export default Homescreen

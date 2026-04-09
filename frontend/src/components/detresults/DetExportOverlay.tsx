import React from 'react'
import { View, Text, ActivityIndicator, TouchableOpacity } from 'react-native'

type Props = {
  visible: boolean
  onCancel: () => void
}

const DetExportOverlay = ({ visible, onCancel }: Props) => {
  if (!visible) return null

  return (
    <View className="absolute inset-0 bg-black/50 flex items-center justify-center z-50">
      <View className="bg-white rounded-2xl p-6 mx-4 shadow-xl">
        <View className="items-center">
          <ActivityIndicator size="large" color="#2563eb" />
          <Text className="text-lg font-semibold text-gray-800 mt-4 mb-2">Generating Report</Text>
          <Text className="text-sm text-gray-600 text-center mb-4">Preparing File...</Text>
          <TouchableOpacity className="bg-red-50 border border-red-200 rounded-lg px-4 py-2" onPress={onCancel}>
            <Text className="text-red-700 font-medium">Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  )
}

export default DetExportOverlay

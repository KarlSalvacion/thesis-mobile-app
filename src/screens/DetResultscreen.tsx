import React from 'react'
import { View, Text, ScrollView } from 'react-native'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'

const DetectionResults = () => {
  // Mock detection data - replace with actual model results
  const detectionData = {
    totalWeeds: 15,
    confidence: 87.5,
    timestamp: '08/17/25',
    species: [
      { name: 'Echinichloa Colona', count: 8, confidence: 92.3, color: 'bg-red-500' },
      { name: 'Echinicloa Glabresence', count: 4, confidence: 85.7, color: 'bg-orange-500' },
      { name: 'Echinicloa Crus-Galli', count: 3, confidence: 78.9, color: 'bg-yellow-500' }
    ]
  }

  return (
    <ScrollView className="flex-1 bg-bgColor1" showsVerticalScrollIndicator={false}>
      <View className="flex-1 justify-start items-center pt-12 pb-8 px-4">
        {/* Video Placeholder */}
        <View className="w-full items-center mb-6">
          <View className="bg-gray-800 rounded-2xl shadow-lg w-full max-w-md h-64 items-center justify-center">
            <Ionicons name="play-circle" size={64} color="white" />
            <Text className="text-white text-lg font-medium mt-3">
              Detection Video
            </Text>
            <Text className="text-gray-300 text-sm mt-1">
              Tap to play analysis footage
            </Text>
          </View>
        </View>

        {/* Header */}
    

        {/* Summary Stats */}
        <View className="w-full max-w-md mb-6">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Detection Summary
            </Text>
            
            <View className="flex-row justify-between items-center mb-4">
              <View className="items-center flex-1">
                <View className="bg-green-100 rounded-full w-16 h-16 items-center justify-center mb-2">
                  <Text className="text-2xl font-bold text-green-600">
                    {detectionData.totalWeeds}
                  </Text>
                </View>
                <Text className="text-sm text-gray-600 text-center">Total Weeds</Text>
              </View>
              
              <View className="items-center flex-1">
                <View className="bg-blue-100 rounded-full w-16 h-16 items-center justify-center mb-2">
                  <Text className="text-lg font-bold text-blue-600">
                    {detectionData.confidence}%
                  </Text>
                </View>
                <Text className="text-sm text-gray-600 text-center">Confidence</Text>
              </View>
            </View>

            <View className="bg-gray-50 rounded-lg p-3">
              <Text className="text-xs text-gray-500 text-center">
                Detected on {detectionData.timestamp}
              </Text>
            </View>
          </View>
        </View>

        {/* Species Breakdown */}
        <View className="w-full max-w-md mb-6">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Weed Species Detected
            </Text>
            
            {detectionData.species.map((species, index) => (
              <View key={index} className="mb-4 last:mb-0">
                <View className="flex-row items-center justify-between mb-2">
                  <View className="flex-row items-center">
                    <View className={`w-4 h-4 rounded-full ${species.color} mr-3`} />
                    <Text className="text-base font-medium text-gray-800">
                      {species.name}
                    </Text>
                  </View>
                  <Text className="text-lg font-bold text-gray-700">
                    {species.count}
                  </Text>
                </View>
                
                <View className="flex-row items-center justify-between">
                  <View className="flex-1 bg-gray-200 rounded-full h-2 mr-3">
                    <View 
                      className={`h-2 rounded-full ${species.color}`}
                      style={{ width: `${species.confidence}%` }}
                    />
                  </View>
                  <Text className="text-sm text-gray-600 min-w-[50px] text-right">
                    {species.confidence}%
                  </Text>
                </View>
              </View>
            ))}
          </View>
        </View>

        {/* Action Buttons */}
        <View className="w-full max-w-md">
          <View className="bg-white rounded-2xl shadow-lg p-6">
            <Text className="text-lg font-semibold text-gray-700 mb-4 text-center">
              Actions
            </Text>
            
            <View className="space-y-3">
              <View className="bg-green-50 border border-green-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="map-marker-alt" size={20} color="rgb(37, 165, 120)" />
                  <Text className="text-green-700 font-medium ml-3 flex-1">
                    View on Map
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(37, 165, 120)" />
                </View>
              </View>
              
              <View className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="download" size={20} color="rgb(59, 130, 246)" />
                  <Text className="text-blue-700 font-medium ml-3 flex-1">
                    Export Report
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(59, 130, 246)" />
                </View>
              </View>
              
              <View className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                <View className="flex-row items-center">
                  <FontAwesome6 name="share" size={20} color="rgb(245, 101, 101)" />
                  <Text className="text-orange-700 font-medium ml-3 flex-1">
                    Share Results
                  </Text>
                  <Ionicons name="chevron-forward" size={20} color="rgb(245, 101, 101)" />
                </View>
              </View>
            </View>
          </View>
        </View>
      </View>
    </ScrollView>
  )
}

export default DetectionResults
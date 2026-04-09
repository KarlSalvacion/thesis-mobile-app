import React from 'react'
import { View, Text, Image, TouchableOpacity } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { Video, ResizeMode } from 'expo-av'
import { DetectionRow } from './types'

type Props = {
  selectedDetection: DetectionRow | null
  screenHeight: number
  onOpenFullscreen: () => void
  onImageError: (error: any) => void
  onVideoError: (error: any) => void
}

const DetMediaPreviewCard = ({
  selectedDetection,
  screenHeight,
  onOpenFullscreen,
  onImageError,
  onVideoError,
}: Props) => {
  return (
    <View className="w-full items-center mb-6">
      <TouchableOpacity onPress={onOpenFullscreen} activeOpacity={0.8} className="w-full max-w-md">
        <View
          className="bg-gray-800 rounded-2xl shadow-lg overflow-hidden"
          style={{
            width: '100%',
            minHeight: 200,
            maxHeight: screenHeight * 0.5,
          }}
        >
          {selectedDetection && selectedDetection[3] === 'image' ? (
            <Image
              source={{ uri: (selectedDetection as any).cloud_annotated_url || (selectedDetection as any).cloud_secure_url }}
              resizeMode="contain"
              style={{ width: '100%', height: '100%', minHeight: 200 }}
              onError={onImageError}
            />
          ) : selectedDetection && selectedDetection[3] === 'video' && (selectedDetection as any).cloud_secure_url ? (
            <Video
              source={{ uri: (selectedDetection as any).cloud_annotated_url || (selectedDetection as any).cloud_secure_url }}
              style={{ width: '100%', height: 300 }}
              resizeMode={ResizeMode.CONTAIN}
              shouldPlay={false}
              isLooping={true}
              isMuted={true}
              onError={onVideoError}
            />
          ) : (
            <View style={{ width: '100%', height: 250 }} className="items-center justify-center">
              <Ionicons name="play-circle" size={64} color="white" />
              <Text className="text-white text-lg font-medium mt-3 text-center">
                {selectedDetection?.[3] === 'video' ? 'Detection Video' : 'Media preview unavailable'}
              </Text>
              <Text className="text-gray-300 text-xs mt-1 px-3 text-center">
                {selectedDetection?.[3] === 'video' ? 'Tap to expand and play video' : 'No media available for preview'}
              </Text>
            </View>
          )}

          <View className="absolute top-2 right-2 bg-black/50 rounded-full p-2">
            <Ionicons name="expand" size={20} color="white" />
          </View>
        </View>
      </TouchableOpacity>
    </View>
  )
}

export default DetMediaPreviewCard

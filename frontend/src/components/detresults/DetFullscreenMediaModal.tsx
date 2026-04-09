import React from 'react'
import { Modal, View, Text, TouchableOpacity } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { Video, ResizeMode } from 'expo-av'
import ZoomableImage from '../ZoomableImage'
import { DetectionRow } from './types'

type Props = {
  visible: boolean
  selectedDetection: DetectionRow | null
  screenWidth: number
  screenHeight: number
  onClose: () => void
  onVideoError: (error: any) => void
}

const DetFullscreenMediaModal = ({
  visible,
  selectedDetection,
  screenWidth,
  screenHeight,
  onClose,
  onVideoError,
}: Props) => {
  return (
    <Modal visible={visible} transparent={true} animationType="fade" onRequestClose={onClose}>
      <View className="flex-1 bg-black justify-center items-center">
        <TouchableOpacity className="absolute top-12 right-4 z-10 bg-black/50 rounded-full p-3" onPress={onClose}>
          <Ionicons name="close" size={24} color="white" />
        </TouchableOpacity>

        <View
          style={{
            width: screenWidth,
            height: screenHeight,
            justifyContent: 'center',
            alignItems: 'center',
          }}
        >
          {selectedDetection && selectedDetection[3] === 'image' ? (
            <ZoomableImage
              uri={(selectedDetection as any).cloud_annotated_url || (selectedDetection as any).cloud_secure_url}
              style={{ width: '100%', height: '100%' }}
              resizeMode="contain"
            />
          ) : selectedDetection && selectedDetection[3] === 'video' && (selectedDetection as any).cloud_secure_url ? (
            <Video
              source={{ uri: (selectedDetection as any).cloud_annotated_url || (selectedDetection as any).cloud_secure_url }}
              style={{
                width: screenWidth * 0.95,
                height: screenHeight * 0.8,
              }}
              resizeMode={ResizeMode.CONTAIN}
              shouldPlay={true}
              isLooping={true}
              isMuted={false}
              useNativeControls={true}
              onError={onVideoError}
            />
          ) : (
            <View className="flex-1 items-center justify-center bg-gray-800 rounded-lg mx-4">
              <Ionicons name="alert-circle" size={64} color="white" />
              <Text className="text-white text-lg font-medium mt-3 text-center">Media Unavailable</Text>
              <Text className="text-gray-300 text-sm mt-1 px-4 text-center">
                The media file could not be loaded for preview
              </Text>
            </View>
          )}
        </View>
      </View>
    </Modal>
  )
}

export default DetFullscreenMediaModal

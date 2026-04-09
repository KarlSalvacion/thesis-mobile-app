import React from 'react'
import { View, Text, Pressable, ActivityIndicator } from 'react-native'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'
import { HomeStatus, SelectedFile } from './types'

type Props = {
  status: HomeStatus
  isBusy: boolean
  selectedMedia: SelectedFile | null
  selectedSrt: SelectedFile | null
  onPickMedia: () => void
  onPickSrt: () => void
  onRemoveMedia: () => void
  onRemoveSrt: () => void
}

const HomeUploadPickers = ({
  status,
  isBusy,
  selectedMedia,
  selectedSrt,
  onPickMedia,
  onPickSrt,
  onRemoveMedia,
  onRemoveSrt,
}: Props) => {
  return (
    <View className="flex-row gap-4 mb-4 w-full">
      <View className="flex-1">
        <Text className="text-sm font-semibold text-gray-700 mb-2.5 text-center">Media File</Text>
        <Pressable
          onPress={onPickMedia}
          disabled={isBusy}
          className={`h-[100px] items-center justify-center rounded-lg border-2 border-greenColor ${isBusy ? 'bg-gray-300' : 'bg-bgColor1'}`}
        >
          {status === 'picking' && !selectedMedia ? (
            <View className="items-center justify-center">
              <ActivityIndicator size="large" color="rgb(37, 165, 120)" />
              <Text className="text-greenColor font-bold text-xs text-center mt-2 px-2">Loading...</Text>
            </View>
          ) : (
            <>
              <FontAwesome6 name="file-video" size={32} color="rgb(37, 165, 120)" />
              <Text className="text-greenColor font-bold text-xs text-center mt-2 px-2">Choose video/image</Text>
            </>
          )}
        </Pressable>

        {selectedMedia && (
          <View className="bg-white border border-gray-200 rounded-lg p-2.5 mt-3">
            <View className="flex-row items-center justify-between mb-1">
              <Text className="text-gray-800 font-medium text-xs flex-1" numberOfLines={1}>
                {selectedMedia.name}
              </Text>
              {status !== 'uploading' && (
                <Pressable onPress={onRemoveMedia} className="ml-2">
                  <Ionicons name="close" size={18} color="#9CA3AF" />
                </Pressable>
              )}
            </View>
            <Text className="text-gray-500 text-xs mt-0.5">
              {selectedMedia.size ? `${(selectedMedia.size / (1024 * 1024)).toFixed(2)} MB` : 'Size unknown'}
            </Text>
            {selectedMedia.size && selectedMedia.size > 500 * 1024 * 1024 && (
              <Text className="text-orange-600 text-xs mt-1 font-semibold">Large file - may take time</Text>
            )}
          </View>
        )}
      </View>

      <View className="flex-1">
        <Text className="text-sm font-semibold text-gray-700 mb-2.5 text-center">SRT (Optional)</Text>
        <Pressable
          onPress={onPickSrt}
          disabled={isBusy}
          className={`h-[100px] items-center justify-center rounded-lg border-2 border-blue-500 ${isBusy ? 'bg-gray-300' : 'bg-blue-50'}`}
        >
          {status === 'picking' && selectedMedia && !selectedSrt ? (
            <View className="items-center justify-center">
              <ActivityIndicator size="large" color="rgb(59, 130, 246)" />
              <Text className="text-blue-600 font-bold text-xs text-center mt-2 px-2">Loading...</Text>
            </View>
          ) : (
            <>
              <FontAwesome6 name="file-lines" size={32} color="rgb(59, 130, 246)" />
              <Text className="text-blue-600 font-bold text-xs text-center mt-2 px-2">Choose SRT file</Text>
            </>
          )}
        </Pressable>

        {selectedSrt && (
          <View className="bg-white border border-gray-200 rounded-lg p-2.5 mt-3">
            <View className="flex-row items-center justify-between mb-1">
              <Text className="text-gray-800 font-medium text-xs flex-1" numberOfLines={1}>
                {selectedSrt.name}
              </Text>
              {status !== 'uploading' && (
                <Pressable onPress={onRemoveSrt} className="ml-2">
                  <Ionicons name="close" size={18} color="#9CA3AF" />
                </Pressable>
              )}
            </View>
            <Text className="text-gray-500 text-xs mt-0.5">
              {selectedSrt.size ? `${(selectedSrt.size / 1024).toFixed(2)} KB` : 'Size unknown'}
            </Text>
          </View>
        )}
      </View>
    </View>
  )
}

export default HomeUploadPickers

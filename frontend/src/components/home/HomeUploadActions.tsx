import React from 'react'
import { View, Text, Pressable, ActivityIndicator } from 'react-native'
import { HomeStatus, SelectedFile } from './types'

type Props = {
  status: HomeStatus
  progress: number
  message: string
  selectedMedia: SelectedFile | null
  selectedSrt: SelectedFile | null
  hasAnyFile: boolean
  fileNamesMatch: boolean
  canUpload: boolean
  isBusy: boolean
  onUpload: () => void
  onReset: () => void
}

const HomeUploadActions = ({
  status,
  progress,
  message,
  selectedMedia,
  selectedSrt,
  hasAnyFile,
  fileNamesMatch,
  canUpload,
  isBusy,
  onUpload,
  onReset,
}: Props) => {
  const selectedMediaName = selectedMedia?.name.toLowerCase() ?? ''
  const isImage = /\.(jpg|jpeg|png|bmp|gif)$/i.test(selectedMediaName)
  const isVideo = /\.(mp4|mov|avi|mkv)$/i.test(selectedMediaName)

  return (
    <>
      {selectedSrt && selectedMedia && !fileNamesMatch && (
        <View className="bg-orange-50 border border-orange-300 rounded-lg p-3 mb-4 w-full">
          <Text className="text-orange-700 font-semibold text-xs">File names do not match. GPS data may not sync correctly.</Text>
        </View>
      )}

      <Pressable
        onPress={onUpload}
        disabled={!canUpload}
        className={`mt-3 h-[48px] w-full justify-center items-center px-4 py-2 rounded-lg mb-3 ${!canUpload ? 'bg-darkgrayColor' : 'bg-greenColor'}`}
      >
        <View className="flex-row items-center">
          {status === 'uploading' && (
            <View className="mr-2">
              <ActivityIndicator color="#fff" />
            </View>
          )}
          <Text className="text-white font-semibold text-lg">{status === 'uploading' ? 'Uploading...' : 'Upload All Files'}</Text>
        </View>
      </Pressable>

      {status === 'uploading' && (
        <View className="w-full h-3 bg-gray-200 rounded-full overflow-hidden mb-3">
          <View style={{ width: `${progress}%` }} className="h-3 bg-blue-600" />
        </View>
      )}

      {selectedSrt && !selectedMedia && (
        <View className="w-full bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-3">
          <Text className="text-yellow-800 text-sm font-medium">SRT file requires a media file</Text>
          <Text className="text-yellow-700 text-xs mt-1">Please select a video or image file first.</Text>
        </View>
      )}

      {selectedSrt && selectedMedia && isImage && (
        <View className="w-full bg-red-50 border border-red-300 rounded-lg p-3 mb-3">
          <Text className="text-red-800 text-sm font-medium">SRT files cannot be used with images</Text>
          <Text className="text-red-700 text-xs mt-1">SRT files provide GPS data for video mapping only.</Text>
        </View>
      )}

      {selectedMedia && !selectedSrt && isVideo && (
        <View className="w-full bg-blue-50 border border-blue-300 rounded-lg p-3 mb-3">
          <Text className="text-blue-800 text-sm font-medium">Video without GPS data</Text>
          <Text className="text-blue-700 text-xs mt-1">Upload an SRT file to enable map visualization of detection locations.</Text>
        </View>
      )}

      {!!message && (
        <View className="w-full bg-white border border-gray-200 rounded-lg p-3 mb-2">
          <Text className={`text-sm text-center ${status === 'success' ? 'text-green-700' : status === 'error' ? 'text-red-700' : 'text-gray-700'}`}>
            {message}
          </Text>
        </View>
      )}

      {(hasAnyFile || status === 'success' || status === 'error') && (
        <Pressable onPress={onReset} disabled={isBusy} className={`px-6 py-3 rounded-lg mt-3 ${isBusy ? 'bg-gray-300' : 'bg-gray-600'}`}>
          <Text className="text-white font-medium text-base">Reset</Text>
        </Pressable>
      )}
    </>
  )
}

export default HomeUploadActions

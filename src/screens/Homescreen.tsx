import React, { useEffect, useRef, useState } from 'react'
import { View, Text, Pressable, ActivityIndicator } from 'react-native'
import * as DocumentPicker from 'expo-document-picker'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'

type SelectedFile = {
  uri: string
  name: string
  size?: number | null
}

const Homescreen = () => {
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null)
  const [status, setStatus] = useState<'idle' | 'picking' | 'ready' | 'uploading' | 'success' | 'error'>('idle')
  const [progress, setProgress] = useState<number>(0)
  const [message, setMessage] = useState<string>('')
  const progressTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (progressTimerRef.current !== null) clearInterval(progressTimerRef.current)
    }
  }, [])

  const pickVideo = async () => {
    try {
      setMessage('')
      setStatus('picking')
      const result = await DocumentPicker.getDocumentAsync({
        type: 'video/*',
        multiple: false,
        copyToCacheDirectory: true
      })

      if (result.canceled) {
        setStatus(selectedFile ? 'ready' : 'idle')
        return
      }

      const file = result.assets?.[0]
      if (file) {
        setSelectedFile({ uri: file.uri, name: file.name ?? 'video', size: file.size })
        setStatus('ready')
      } else {
        setStatus('idle')
      }
    } catch (err) {
      setMessage('Failed to pick a video.')
      setStatus('error')
    }
  }

  const mockUpload = async () => {
    if (!selectedFile) return
    setStatus('uploading')
    setProgress(0)
    setMessage('')

    // Simulate uploading to a backend server
    let current = 0
    progressTimerRef.current = setInterval(() => {
      current = Math.min(current + Math.random() * 20 + 5, 100)
      setProgress(current)
      if (current >= 100 && progressTimerRef.current !== null) {
        clearInterval(progressTimerRef.current)
        progressTimerRef.current = null
        setStatus('success')
        setMessage('Upload complete (mock).')
      }
    }, 400) as unknown as number
  }

  const reset = () => {
    if (progressTimerRef.current !== null) {
      clearInterval(progressTimerRef.current)
      progressTimerRef.current = null
    }
    setSelectedFile(null)
    setProgress(0)
    setMessage('')
    setStatus('idle')
  }

  const isBusy = status === 'picking' || status === 'uploading'

  return (
    <View className="flex-1 justify-center items-center bg-bgColor1">
      <View className="justify-center items-center bg-white h-100 py-4 rounded-xl shadow-custom ">
      <Ionicons name="cloud-upload" size={64} color="rgb(37, 165, 120)" className=" mt-4 mx-auto" />
        <Text className="text-2xl font-bold text-gray-800 mb-4">
          Upload Drone Footage
        </Text>
        <Text className="text-gray-600 text-center px-6 mb-6">
          Pick a video and upload it to the mock backend.
        </Text>

        <Pressable
          onPress={pickVideo}
          disabled={isBusy}
          className={`w-[310px] h-[200px] items-center justify-center rounded-md mb-3 border-2 border-greenColor ${isBusy ? 'bg-gray-300' : 'bg-bgColor1'}`}
        >
          <FontAwesome6 name='file-video' size={48} color='rgb(37, 165, 120)' />

          <Text className="text-greenColor font-bold center text-lg text-center mt-4">
            {status === 'picking' ? 'Opening picker...' : 'Choose video file'}
          </Text>
        </Pressable>

        {selectedFile && (
          <View className="w-72 bg-white border border-gray-200 rounded-md p-3 mb-3">
            <Text className="text-gray-800 font-medium" numberOfLines={1}>{selectedFile.name}</Text>
            <Text className="text-gray-500 text-xs">
              {selectedFile.size ? `${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB` : 'Size unknown'}
            </Text>
          </View>
        )}

        <Pressable
          onPress={mockUpload}
          disabled={!selectedFile || status === 'uploading'}
          className={` mt-4 h-[45px] w-[310px] justify-center items-center px-4 py-2 rounded-md mb-3 ${(!selectedFile || status === 'uploading') ? 'bg-darkgrayColor' : 'bg-greenColor'}`}
        >
          <View className="flex-row items-center">
            {status === 'uploading' && (
              <View className="mr-2">
                <ActivityIndicator color="#fff" />
              </View>
            )}
            <Text className="text-white font-semibold text-lg">
              {status === 'uploading' ? 'Uploading...' : 'Upload'}
            </Text>
          </View>
        </Pressable>

        {status === 'uploading' && (
          <View className="w-72 h-3 bg-gray-200 rounded-full overflow-hidden mb-3">
            <View style={{ width: `${progress}%` }} className="h-3 bg-blue-600" />
          </View>
        )}

        {!!message && (
          <Text className={`mt-1 ${status === 'success' ? 'text-green-700' : status === 'error' ? 'text-red-700' : 'text-gray-700'}`}>
            {message}
          </Text>
        )}

        {(selectedFile || status === 'success' || status === 'error') && (
          <Pressable onPress={reset} disabled={isBusy} className={`px-4 py-2 rounded-md mt-4 ${isBusy ? 'bg-gray-300' : 'bg-gray-600'}`}>
            <Text className="text-white font-medium">Reset</Text>
          </Pressable>
        )}
      </View>

    </View>
  )
}

export default Homescreen

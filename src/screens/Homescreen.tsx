import React, { useEffect, useRef, useState } from 'react'
import { View, Text, Pressable, ActivityIndicator, ScrollView } from 'react-native'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import * as FileSystem from 'expo-file-system'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'
import SrtDebugViewer from '../components/SrtDebugViewer'
function guessMimeType(name: string): string {
  const lower = name.toLowerCase()
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg'
  if (lower.endsWith('.png')) return 'image/png'
  if (lower.endsWith('.bmp')) return 'image/bmp'
  if (lower.endsWith('.gif')) return 'image/gif'
  if (lower.endsWith('.mp4')) return 'video/mp4'
  if (lower.endsWith('.mov')) return 'video/quicktime'
  if (lower.endsWith('.avi')) return 'video/x-msvideo'
  if (lower.endsWith('.mkv')) return 'video/x-matroska'
  if (lower.endsWith('.srt')) return 'text/plain'
  return 'application/octet-stream'
}

async function ensureLocalFilePath(uri: string, fallbackName: string): Promise<string> {
  // Expo FileSystem can upload content:// URIs directly on Android when using uploadAsync.
  // Still, when it's a remote or non-file scheme, copy it to cache to be safe.
  try {
    if (uri.startsWith('file://') || uri.startsWith('content://')) return uri
    const dest = `${FileSystem.cacheDirectory}${fallbackName}`
    await FileSystem.copyAsync({ from: uri, to: dest })
    return dest
  } catch {
    return uri
  }
}

import { API_BASE } from '../config'

async function uploadFileToApi(uri: string, name: string) {
  const type = guessMimeType(name)
  const fileUri = await ensureLocalFilePath(uri, name)
  const result = await FileSystem.uploadAsync(`${API_BASE}/upload/`, fileUri, {
    httpMethod: 'POST',
    uploadType: FileSystem.FileSystemUploadType.MULTIPART,
    fieldName: 'file',
    mimeType: type,
    parameters: {},
    headers: { Accept: 'application/json' },
  })
  if (result.status !== 200) throw new Error(`Upload failed: ${result.status}`)
  return JSON.parse(result.body)
}

async function uploadSrtToApi(detectionId: number, uri: string, name: string) {
  const fileUri = await ensureLocalFilePath(uri, name)
  const result = await FileSystem.uploadAsync(`${API_BASE}/upload-srt/`, fileUri, {
    httpMethod: 'POST',
    uploadType: FileSystem.FileSystemUploadType.MULTIPART,
    fieldName: 'srt_file',
    mimeType: 'text/plain',
    parameters: { detection_id: String(detectionId) },
    headers: { Accept: 'application/json' },
  })
  if (result.status !== 200) throw new Error(`SRT upload failed: ${result.status}`)
  return JSON.parse(result.body)
}

type SelectedFile = {
  uri: string
  name: string
  size?: number | null
  type: 'media' | 'srt'
}

const Homescreen = () => {
  const [selectedMedia, setSelectedMedia] = useState<SelectedFile | null>(null)
  const [selectedSrt, setSelectedSrt] = useState<SelectedFile | null>(null)
  const [status, setStatus] = useState<'idle' | 'picking' | 'ready' | 'uploading' | 'success' | 'error'>('idle')
  const [progress, setProgress] = useState<number>(0)
  const [message, setMessage] = useState<string>('')
  const progressTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (progressTimerRef.current !== null) clearInterval(progressTimerRef.current)
    }
  }, [])

  const pickMedia = async () => {
    try {
      setMessage('')
      setStatus('picking')

      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync()
      if (permission.status !== 'granted') {
        setStatus(selectedMedia || selectedSrt ? 'ready' : 'idle')
        setMessage('Permission to access media library is required.')
        return
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.All,
        allowsEditing: false,
        quality: 1
      })

      if (result.canceled) {
        setStatus((selectedMedia || selectedSrt) ? 'ready' : 'idle')
        return
      }

      const asset = result.assets?.[0]
      if (asset) {
        const inferredName = asset.uri.split('/')?.pop() || (asset.type === 'video' ? 'video.mp4' : 'image.jpg')
        let size: number | null | undefined = undefined
        try {
          const info: any = await FileSystem.getInfoAsync(asset.uri)
          size = typeof info?.size === 'number' ? info.size : undefined
        } catch {}

        if (asset.type === 'video' || asset.type === 'image') {
          setSelectedMedia({
            uri: asset.uri,
            name: inferredName,
            size,
            type: 'media'
          })
          setStatus('ready')
        } else {
          setMessage('Please select a valid video or image file.')
          setStatus('error')
        }
      } else {
        setStatus('idle')
      }
    } catch (err) {
      setMessage('Failed to pick a media file.')
      setStatus('error')
    }
  }

  const pickSrt = async () => {
    try {
      setMessage('')
      setStatus('picking')
      const result = await DocumentPicker.getDocumentAsync({
        type: [

          (DocumentPicker as any).types?.allFiles || 'public.item',
          // iOS UTTypes
          'public.item',
          'public.data',
          'public.content',
          'public.text',
          'public.plain-text',
          'public.json',
          'public.srt',
          // Common MIME types
          'text/plain',
          'application/json',
          '*/*',
        ],
        multiple: false,
        copyToCacheDirectory: true
      })

      if (result.canceled) {
        setStatus((selectedMedia || selectedSrt) ? 'ready' : 'idle')
        return
      }

      const file = result.assets?.[0]
      if (file) {
        setSelectedSrt({
          uri: file.uri,
          name: file.name ?? 'subtitle.srt',
          size: file.size,
          type: 'srt'
        })
        setStatus('ready')
      } else {
        setStatus('idle')
      }
    } catch (err) {
      setMessage('Failed to pick an SRT file.')
      setStatus('error')
    }
  }

  const mockUpload = async () => {
    if (!selectedMedia && !selectedSrt) return
    try {
      setStatus('uploading')
      setProgress(10)
      setMessage('')

      let detectionId: number | null = null
      if (selectedMedia) {
        const res = await uploadFileToApi(selectedMedia.uri, selectedMedia.name)
        detectionId = res?.detection_id ?? null
      }
      setProgress(60)

      if (selectedSrt && detectionId) {
        await uploadSrtToApi(detectionId, selectedSrt.uri, selectedSrt.name)
      }
      setProgress(100)
      setStatus('success')
      setMessage('Upload complete.')
    } catch (e: any) {
      setStatus('error')
      setMessage(e?.message || 'Upload failed')
    } finally {
      if (progressTimerRef.current !== null) {
        clearInterval(progressTimerRef.current)
        progressTimerRef.current = null
      }
    }
  }

  const reset = () => {
    if (progressTimerRef.current !== null) {
      clearInterval(progressTimerRef.current)
      progressTimerRef.current = null
    }
    setSelectedMedia(null)
    setSelectedSrt(null)
    setProgress(0)
    setMessage('')
    setStatus('idle')
  }

  const isBusy = status === 'picking' || status === 'uploading'
  const hasAnyFile = selectedMedia || selectedSrt

  return (
    <View className="flex-1 bg-bgColor1">
      <ScrollView 
        contentContainerStyle={{ alignItems: 'center', paddingVertical: 24 }}
        showsVerticalScrollIndicator={false}
        >
        <View className="justify-center items-center bg-white h-auto py-4 rounded-xl shadow-custom">
        <Ionicons name="cloud-upload" size={64} color="rgb(37, 165, 120)" className="mt-4 mx-auto" />
        <Text className="text-2xl font-bold text-gray-800 mb-4">
          Upload Media & Subtitles
        </Text>
        <Text className="text-gray-600 text-center px-6 mb-6">
          Pick a video/photo and upload SRT subtitle file.
        </Text>

        {/* Media Picker */}
        <View className="mb-4">
          <Text className="text-lg font-semibold text-gray-700 mb-2 text-center">Media File</Text>
          <Pressable
            onPress={pickMedia}
            disabled={isBusy}
            className={`w-[310px] h-[150px] items-center justify-center rounded-md mb-3 border-2 border-greenColor ${isBusy ? 'bg-gray-300' : 'bg-bgColor1'}`}
          >
            <FontAwesome6 name='file-video' size={40} color='rgb(37, 165, 120)' />

            <Text className="text-greenColor font-bold center text-base text-center mt-3">
              {status === 'picking' ? 'Opening picker...' : 'Choose video/image file'}
            </Text>
          </Pressable>

          {selectedMedia && (
            <View className="w-72 bg-white border border-gray-200 rounded-md p-3 mb-3">
              <Text className="text-gray-800 font-medium" numberOfLines={1}>{selectedMedia.name}</Text>
              <Text className="text-gray-500 text-xs">
                {selectedMedia.size ? `${(selectedMedia.size / (1024 * 1024)).toFixed(2)} MB` : 'Size unknown'}
              </Text>
            </View>
          )}
        </View>

        {/* SRT File Picker */}
        <View className="mb-4">
          <Text className="text-lg font-semibold text-gray-700 mb-2 text-center">Subtitle File (SRT)</Text>
          <Pressable
            onPress={pickSrt}
            disabled={isBusy}
            className={`w-[310px] h-[100px] items-center justify-center rounded-md mb-3 border-2 border-blue-500 ${isBusy ? 'bg-gray-300' : 'bg-blue-50'}`}
          >
            <FontAwesome6 name='file-lines' size={32} color='rgb(59, 130, 246)' />

            <Text className="text-blue-600 font-bold center text-base text-center mt-2">
              {status === 'picking' ? 'Opening picker...' : 'Choose SRT file'}
            </Text>
          </Pressable>

          {selectedSrt && (
            <View className="w-72 bg-white border border-gray-200 rounded-md p-3 mb-3">
              <Text className="text-gray-800 font-medium" numberOfLines={1}>{selectedSrt.name}</Text>
              <Text className="text-gray-500 text-xs">
                {selectedSrt.size ? `${(selectedSrt.size / 1024).toFixed(2)} KB` : 'Size unknown'}
              </Text>
            </View>
          )}

          {/* Parsed SRT Preview */}
          {selectedSrt && (
            <SrtDebugViewer srtUri={selectedSrt.uri} srtName={selectedSrt.name} />
          )}
        </View>

        <Pressable
          onPress={mockUpload}
          disabled={!hasAnyFile || status === 'uploading'}
          className={`mt-4 h-[45px] w-[310px] justify-center items-center px-4 py-2 rounded-md mb-3 ${(!hasAnyFile || status === 'uploading') ? 'bg-darkgrayColor' : 'bg-greenColor'}`}
        >
          <View className="flex-row items-center">
            {status === 'uploading' && (
              <View className="mr-2">
                <ActivityIndicator color="#fff" />
              </View>
            )}
            <Text className="text-white font-semibold text-lg">
              {status === 'uploading' ? 'Uploading...' : 'Upload All Files'}
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

        {(hasAnyFile || status === 'success' || status === 'error') && (
          <Pressable onPress={reset} disabled={isBusy} className={`px-4 py-2 rounded-md mt-4 ${isBusy ? 'bg-gray-300' : 'bg-gray-600'}`}>
            <Text className="text-white font-medium">Reset</Text>
          </Pressable>
        )}
        </View>
      </ScrollView>
    </View>
  )
}

export default Homescreen

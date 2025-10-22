import React, { useEffect, useRef, useState, useCallback } from 'react'
import { View, Text, Pressable, ActivityIndicator, ScrollView, RefreshControl, Alert } from 'react-native'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import * as FileSystem from 'expo-file-system'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'
import { Video } from 'react-native-compressor'
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

console.log('API_BASE =', API_BASE)

// Automatic client-side video compression handler
async function handleClientCompression(jobId: string, result: any, onProgress?: (message: string) => void): Promise<any> {
  if (!result.needs_client_compression) {
    // No compression needed (image or already has annotated URL)
    console.log('ℹ️  [COMPRESS] No client compression needed')
    return result
  }
  
  try {
    // Step 1: Download temp video from backend
    onProgress?.('Downloading video for compression...')
    const downloadUrl = `${API_BASE}/download-temp-video/${jobId}`
    const localPath = `${FileSystem.cacheDirectory}temp_${jobId}.mp4`
    
    console.log(`📥 [COMPRESS] Downloading temp video from: ${downloadUrl}`)
    const downloadResult = await FileSystem.downloadAsync(downloadUrl, localPath)
    
    if (downloadResult.status !== 200) {
      throw new Error(`Download failed: ${downloadResult.status}`)
    }
    
    const fileInfo = await FileSystem.getInfoAsync(localPath)
    const downloadedSize = fileInfo.exists ? (fileInfo as any).size : 0
    console.log(`📥 [COMPRESS] Downloaded: ${(downloadedSize / (1024*1024)).toFixed(2)} MB`)
    
    // Step 2: Compress with react-native-compressor
    onProgress?.('Compressing video (high quality)...')
    console.log('🗜️  [COMPRESS] Starting HIGH QUALITY compression with react-native-compressor')
    
    const compressedPath = await Video.compress(
      localPath,
      {
        compressionMethod: 'auto',
        maxSize: 1920, // Maintain 1080p resolution
        bitrate: 8000000, // 8 Mbps - high quality for readable annotations
        minimumFileSizeForCompress: 0, // Always compress
      },
      (progress) => {
        const percent = (progress * 100).toFixed(0)
        console.log(`🗜️  [COMPRESS] Progress: ${percent}%`)
        onProgress?.(`Compressing video... ${percent}%`)
      }
    )
    
    const compressedInfo = await FileSystem.getInfoAsync(compressedPath)
    const compressedSize = compressedInfo.exists ? (compressedInfo as any).size : 0
    const compressionRatio = downloadedSize > 0 ? (downloadedSize / compressedSize).toFixed(1) : '0'
    console.log(`✅ [COMPRESS] Compressed: ${(compressedSize / (1024*1024)).toFixed(2)} MB (${compressionRatio}x smaller)`)
    
    // Step 3: Upload compressed video back to backend
    onProgress?.('Uploading compressed video...')
    console.log('📤 [COMPRESS] Uploading compressed video to backend')
    
    const uploadResult = await FileSystem.uploadAsync(
      `${API_BASE}/upload-compressed-video/${jobId}`,
      compressedPath,
      {
        httpMethod: 'POST',
        uploadType: FileSystem.FileSystemUploadType.MULTIPART,
        fieldName: 'compressed_video',
        mimeType: 'video/mp4',
        headers: { Accept: 'application/json' },
      }
    )
    
    if (uploadResult.status !== 200) {
      throw new Error(`Upload failed: ${uploadResult.status}`)
    }
    
    const uploadResponse = JSON.parse(uploadResult.body)
    console.log('✅ [COMPRESS] Upload complete:', uploadResponse.annotated_url)
    
    // Step 4: Cleanup temp files
    try {
      await FileSystem.deleteAsync(localPath, { idempotent: true })
      await FileSystem.deleteAsync(compressedPath, { idempotent: true })
      console.log('🧹 [COMPRESS] Cleaned up temp files')
    } catch (e) {
      console.warn('⚠️  [COMPRESS] Cleanup warning:', e)
    }
    
    // Update result with annotated URL from compressed video
    result.cloud_annotated_url = uploadResponse.annotated_url
    onProgress?.('Video compression complete!')
    
    return result
    
  } catch (error: any) {
    console.error('❌ [COMPRESS] Error:', error)
    onProgress?.(`Compression error: ${error.message || 'Unknown error'}`)
    // Return original result even if compression fails
    // The detection results are still valid, just no annotated video
    return result
  }
}

async function uploadFileToApi(uri: string, name: string, onProgress?: (message: string) => void) {
  console.log('📤 [UPLOAD] Starting upload...')
  console.log('📤 [UPLOAD] File:', name)
  console.log('📤 [UPLOAD] API Endpoint:', `${API_BASE}/upload/`)
  
  const type = guessMimeType(name)
  console.log('📤 [UPLOAD] MIME Type:', type)
  
  const fileUri = await ensureLocalFilePath(uri, name)
  console.log('📤 [UPLOAD] Local file URI:', fileUri)
  
  console.log('📤 [UPLOAD] Sending request to backend...')
  const startTime = Date.now()
  
  const result = await FileSystem.uploadAsync(`${API_BASE}/upload/`, fileUri, {
    httpMethod: 'POST',
    uploadType: FileSystem.FileSystemUploadType.MULTIPART,
    fieldName: 'file',
    mimeType: type,
    parameters: {},
    headers: { Accept: 'application/json' },
  })
  
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2)
  console.log(`📤 [UPLOAD] Response received in ${elapsed}s`)
  console.log('📤 [UPLOAD] Status:', result.status)
  
  if (result.status !== 200) {
    console.error('❌ [UPLOAD] Upload failed with status:', result.status)
    throw new Error(`Upload failed: ${result.status}`)
  }
  
  const uploadResult = JSON.parse(result.body)
  const jobId = uploadResult.job_id
  console.log('✅ [UPLOAD] Upload successful! Job ID:', jobId)
  console.log('✅ [UPLOAD] Message:', uploadResult.message)
  
  // Step 2: Poll for results
  onProgress?.('Processing video... This may take 3-10 minutes')
  console.log('📊 [POLLING] Starting to poll for results...')
  
  let pollCount = 0
  const maxPolls = 40 // 20 minutes max (30 seconds * 40 = 1200s)
  
  while (pollCount < maxPolls) {
    await new Promise(resolve => setTimeout(resolve, 30000)) // Wait 30 seconds
    pollCount++
    
    console.log(`📊 [POLLING] Poll attempt ${pollCount}/${maxPolls}`)
    
    const statusResponse = await fetch(`${API_BASE}/job-status/${jobId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    
    if (!statusResponse.ok) {
      console.error('❌ [POLLING] Status check failed:', statusResponse.status)
      throw new Error(`Status check failed: ${statusResponse.status}`)
    }
    
    const status = await statusResponse.json()
    console.log(`📊 [POLLING] Status: ${status.status}, Progress: ${status.progress}`)
    
    // Update progress message
    if (status.progress) {
      onProgress?.(status.progress)
    }
    
    if (status.status === 'completed') {
      console.log('✅ [POLLING] Processing completed!')
      console.log('✅ [POLLING] Summary:', status.result.summary)
      console.log('✅ [POLLING] Detection ID:', status.result.detection_id)
      
      // AUTOMATIC CLIENT-SIDE COMPRESSION
      // If backend flagged this job for client compression, handle it automatically
      let finalResult = status.result
      if (status.result.needs_client_compression) {
        console.log('🗜️  [AUTO] Starting automatic client-side compression workflow')
        finalResult = await handleClientCompression(jobId, status.result, onProgress)
      }
      
      return finalResult
    } else if (status.status === 'failed') {
      console.error('❌ [POLLING] Processing failed:', status.error)
      throw new Error(`Processing failed: ${status.error}`)
    }
    
    // Update time remaining estimate
    const minutesElapsed = (pollCount * 30) / 60
    onProgress?.(`Processing... ${minutesElapsed.toFixed(1)} min elapsed`)
  }
  
  throw new Error('Processing timeout - took longer than 20 minutes')
}

async function uploadCombinedFiles(mediaFile: SelectedFile, srtFile: SelectedFile, onProgress?: (message: string) => void) {
  console.log('📤 [COMBINED] Starting combined upload...')
  console.log('📤 [COMBINED] Media file:', mediaFile.name)
  console.log('📤 [COMBINED] SRT file:', srtFile.name)
  console.log('📤 [COMBINED] API Endpoint:', `${API_BASE}/upload-combined/`)
  
  // Prepare form data for multipart upload
  const formData = new FormData()
  
  // Add media file
  const mediaUri = await ensureLocalFilePath(mediaFile.uri, mediaFile.name)
  const mediaType = guessMimeType(mediaFile.name)
  console.log('📤 [COMBINED] Media MIME Type:', mediaType)
  
  formData.append('media_file', {
    uri: mediaUri,
    name: mediaFile.name,
    type: mediaType,
  } as any)
  
  // Add SRT file
  const srtUri = await ensureLocalFilePath(srtFile.uri, srtFile.name)
  formData.append('srt_file', {
    uri: srtUri,
    name: srtFile.name,
    type: 'text/plain',
  } as any)

  console.log('📤 [COMBINED] Sending request to backend...')
  const startTime = Date.now()

  // Step 1: Upload and get job ID
  const uploadResponse = await fetch(`${API_BASE}/upload-combined/`, {
    method: 'POST',
    body: formData,
    headers: {
      'Content-Type': 'multipart/form-data',
      Accept: 'application/json',
    },
  })

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2)
  console.log(`📤 [COMBINED] Upload response received in ${elapsed}s`)
  console.log('📤 [COMBINED] Status:', uploadResponse.status)

  if (!uploadResponse.ok) {
    const errorText = await uploadResponse.text()
    console.error('❌ [COMBINED] Upload failed:', uploadResponse.status, errorText)
    throw new Error(`Upload failed: ${uploadResponse.status} - ${errorText}`)
  }

  const uploadResult = await uploadResponse.json()
  const jobId = uploadResult.job_id
  console.log('✅ [COMBINED] Upload successful! Job ID:', jobId)
  console.log('✅ [COMBINED] Message:', uploadResult.message)

  // Step 2: Poll for results
  onProgress?.('Processing video... This may take 3-10 minutes')
  console.log('📊 [POLLING] Starting to poll for results...')
  
  let pollCount = 0
  const maxPolls = 40 // 20 minutes max (30 seconds * 40 = 1200s)
  
  while (pollCount < maxPolls) {
    await new Promise(resolve => setTimeout(resolve, 30000)) // Wait 30 seconds
    pollCount++
    
    console.log(`📊 [POLLING] Poll attempt ${pollCount}/${maxPolls}`)
    
    const statusResponse = await fetch(`${API_BASE}/job-status/${jobId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    
    if (!statusResponse.ok) {
      console.error('❌ [POLLING] Status check failed:', statusResponse.status)
      throw new Error(`Status check failed: ${statusResponse.status}`)
    }
    
    const status = await statusResponse.json()
    console.log(`📊 [POLLING] Status: ${status.status}, Progress: ${status.progress}`)
    
    // Update progress message
    if (status.progress) {
      onProgress?.(status.progress)
    }
    
    if (status.status === 'completed') {
      console.log('✅ [POLLING] Processing completed!')
      console.log('✅ [POLLING] Summary:', status.result.summary)
      console.log('✅ [POLLING] Detection ID:', status.result.detection_id)
      
      // AUTOMATIC CLIENT-SIDE COMPRESSION
      // If backend flagged this job for client compression, handle it automatically
      let finalResult = status.result
      if (status.result.needs_client_compression) {
        console.log('🗜️  [AUTO] Starting automatic client-side compression workflow')
        finalResult = await handleClientCompression(jobId, status.result, onProgress)
      }
      
      return finalResult
    } else if (status.status === 'failed') {
      console.error('❌ [POLLING] Processing failed:', status.error)
      throw new Error(`Processing failed: ${status.error}`)
    }
    
    // Update time remaining estimate
    const minutesElapsed = (pollCount * 30) / 60
    onProgress?.(`Processing... ${minutesElapsed.toFixed(1)} min elapsed`)
  }
  
  throw new Error('Processing timeout - took longer than 20 minutes')
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
          // Don't compress yet - just store the original file
          // Compression will happen when user clicks Upload button
          setSelectedMedia({
            uri: asset.uri,
            name: inferredName,
            size: size,
            type: 'media'
          })
          setStatus('ready')
          setMessage(`${asset.type === 'video' ? 'Video' : 'Image'} selected. Ready to upload.`)
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
      console.log('🚀 [UPLOAD START] ================================================')
      console.log('🚀 [UPLOAD START] Initiating upload process...')
      const uploadStartTime = Date.now()
      
      setStatus('uploading')
      setProgress(10)
      setMessage('Preparing files...')

      // Validate upload combination
      if (selectedSrt && !selectedMedia) {
        console.error('❌ [VALIDATION] SRT file without media')
        throw new Error('SRT file cannot be uploaded without a media file')
      }

      const isVideo = selectedMedia?.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)
      const isImage = selectedMedia?.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i)

      console.log('📋 [VALIDATION] File type:', isVideo ? 'VIDEO' : isImage ? 'IMAGE' : 'UNKNOWN')
      console.log('📋 [VALIDATION] Has SRT:', !!selectedSrt)

      if (selectedSrt && isImage) {
        console.error('❌ [VALIDATION] SRT with image not allowed')
        throw new Error('SRT files can only be uploaded with video files, not images')
      }

      setProgress(30)

      // Compress video if needed (only for video files)
      let mediaUriToUpload = selectedMedia?.uri
      let mediaSizeToUpload = selectedMedia?.size || 0
      
      if (selectedMedia && isVideo) {
        console.log('🎬 [COMPRESSION] Starting video compression...')
        console.log('🎬 [COMPRESSION] Original size:', ((selectedMedia.size || 0) / (1024 * 1024)).toFixed(2), 'MB')
        
        setMessage('Compressing video...')
        setProgress(35)
        
        try {
          const compressedUri = await Video.compress(
            selectedMedia.uri,
            {
              compressionMethod: 'auto',
              maxSize: 1920,
              bitrate: 5000000,
            },
            (progress) => {
              const compressProgress = 35 + (progress * 0.25) // 35% to 60%
              setProgress(compressProgress)
              setMessage(`Compressing video... ${(progress * 100).toFixed(0)}%`)
              console.log(`🎬 [COMPRESSION] Progress: ${(progress * 100).toFixed(0)}%`)
            }
          )
          
          const compressedInfo = await FileSystem.getInfoAsync(compressedUri)
          const compressedSize = compressedInfo.exists ? compressedInfo.size : 0
          
          console.log('✅ [COMPRESSION] Compressed size:', (compressedSize / (1024 * 1024)).toFixed(2), 'MB')
          
          if (selectedMedia.size) {
            console.log('✅ [COMPRESSION] Compression ratio:', ((compressedSize / selectedMedia.size) * 100).toFixed(1) + '%')
          }
          
          mediaUriToUpload = compressedUri
          mediaSizeToUpload = compressedSize
          
          setMessage('Compression complete. Uploading...')
          setProgress(60)
        } catch (compressionError) {
          console.warn('⚠️ [COMPRESSION] Failed, using original video:', compressionError)
          setMessage('Compression skipped. Uploading original...')
        }
      }

      setProgress(isVideo ? 65 : 30)
      setMessage('Uploading to server...')

      // Use combined upload endpoint if both files are selected
      if (selectedMedia && selectedSrt) {
        console.log('📦 [MODE] Using combined upload (media + SRT)')
        
        // Create modified media object with compressed URI
        const mediaToUpload = {
          ...selectedMedia,
          uri: mediaUriToUpload || selectedMedia.uri,
          size: mediaSizeToUpload
        }
        
        const result = await uploadCombinedFiles(mediaToUpload, selectedSrt, (progressMsg) => {
          setMessage(progressMsg)
        })
        setMessage(result.message || 'Upload complete with GPS data.')
      } else if (selectedMedia) {
        console.log('📦 [MODE] Using single file upload (media only)')
        const result = await uploadFileToApi(mediaUriToUpload || selectedMedia.uri, selectedMedia.name, (progressMsg) => {
          setMessage(progressMsg)
        })
        setMessage(result.message || `${result.summary} (No GPS data - image only or video without SRT)`)
      }

      const totalTime = ((Date.now() - uploadStartTime) / 1000).toFixed(2)
      console.log(`✅ [UPLOAD COMPLETE] Total time: ${totalTime}s`)
      console.log('✅ [UPLOAD COMPLETE] ================================================')

      setProgress(100)
      setStatus('success')
    } catch (e: any) {
      console.error('❌ [UPLOAD ERROR] ================================================')
      console.error('❌ [UPLOAD ERROR]', e)
      console.error('❌ [UPLOAD ERROR] Message:', e?.message)
      console.error('❌ [UPLOAD ERROR] ================================================')
      
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

  const onRefresh = useCallback(async () => {
    // Soft refresh UI state; optionally ping backend to ensure API_BASE is reachable
    try {
      setStatus('idle')
      setMessage('')
      // Optional: await fetch(`${API_BASE}/detections/`).catch(() => {})
    } catch {}
  }, [])

  return (
    <View className="flex-1 bg-bgColor1">
      <ScrollView 
        contentContainerStyle={{ alignItems: 'center', paddingVertical: 24 }}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={false} onRefresh={onRefresh} />}>
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
        <View className="mb-4 items-center">
          <Text className="text-lg font-semibold text-gray-700 mb-2 text-center">Subtitle File (SRT)</Text>
          <Text className="text-xs text-gray-500 text-center mb-2 px-4">
            Optional for videos. Provides GPS coordinates for mapping. Cannot be used with images.
          </Text>
          <Pressable
            onPress={pickSrt}
            disabled={isBusy}
            className={`w-[310px] h-[100px] items-center justify-center rounded-md mb-3 border-2 border-blue-500 ${isBusy ? 'bg-gray-300' : 'bg-blue-50'}`}
          >
            <FontAwesome6 name='file-lines' size={32} color='rgb(59, 130, 246)' />

            <Text className="text-blue-600 font-bold center text-base text-center mt-2">
              {status === 'picking' ? 'Opening picker...' : 'Choose SRT file (Optional)'}
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
          disabled={!hasAnyFile || status === 'uploading' || 
            (selectedSrt && !selectedMedia) ||
            (selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i))}
          className={`mt-4 h-[45px] w-[310px] justify-center items-center px-4 py-2 rounded-md mb-3 ${(!hasAnyFile || status === 'uploading' || 
            (selectedSrt && !selectedMedia) ||
            (selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i))) ? 'bg-darkgrayColor' : 'bg-greenColor'}`}
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

        {/* Validation warnings */}
        {selectedSrt && !selectedMedia && (
          <View className="w-72 bg-yellow-50 border border-yellow-300 rounded-md p-3 mb-3">
            <Text className="text-yellow-800 text-sm font-medium">⚠️ SRT file requires a media file</Text>
            <Text className="text-yellow-700 text-xs">Please select a video or image file first.</Text>
          </View>
        )}
        
        {selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i) && (
          <View className="w-72 bg-red-50 border border-red-300 rounded-md p-3 mb-3">
            <Text className="text-red-800 text-sm font-medium">❌ SRT files cannot be used with images</Text>
            <Text className="text-red-700 text-xs">SRT files provide GPS data for video mapping only.</Text>
          </View>
        )}

        {selectedMedia && !selectedSrt && !!selectedMedia.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i) && (
          <View className="w-72 bg-blue-50 border border-blue-300 rounded-md p-3 mb-3">
            <Text className="text-blue-800 text-sm font-medium">ℹ️ Video without GPS data</Text>
            <Text className="text-blue-700 text-xs">Upload an SRT file to enable map visualization of detection locations.</Text>
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

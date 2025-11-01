import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { View, Text, Pressable, ActivityIndicator, ScrollView, RefreshControl, Alert } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import * as FileSystem from 'expo-file-system'
import { Ionicons, FontAwesome6 } from '@expo/vector-icons'
import { Video, Image as CompressorImage } from 'react-native-compressor'
import { useSession } from '../context/SessionContext'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { saveActiveJob, getActiveJob, clearActiveJob } from '../utils/jobRecovery'
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
  // Update job stage to compression
  await saveActiveJob(jobId, 'compression')
  
  if (!result.needs_client_compression) {
    // No compression needed (image or already has annotated URL)
    console.log('ℹ️  [COMPRESS] No client compression needed')
    await clearActiveJob()
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
    
    // Step 2: Compress with react-native-compressor - balanced settings for all files
    const fileSizeMB = downloadedSize / (1024 * 1024)
    let compressionSettings: any
    
    // Adjust compression settings based on file size for stability
    if (fileSizeMB > 200) {
      onProgress?.('Compressing large video (high quality)...')
      console.log('🗜️  [COMPRESS] Starting HIGH QUALITY compression for large file:', fileSizeMB.toFixed(2), 'MB')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,  // Keep 1080p for better quality
        bitrate: 7000000, // 7 Mbps for large files - high quality
        minimumFileSizeForCompress: 0,
      }
    } else if (fileSizeMB > 100) {
      onProgress?.('Compressing video (high quality)...')
      console.log('🗜️  [COMPRESS] Starting HIGH QUALITY compression:', fileSizeMB.toFixed(2), 'MB')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,  // 1080p
        bitrate: 8000000, // 8 Mbps
        minimumFileSizeForCompress: 0,
      }
    } else {
      onProgress?.('Compressing video (maximum quality)...')
      console.log('🗜️  [COMPRESS] Starting MAXIMUM QUALITY compression:', fileSizeMB.toFixed(2), 'MB')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,  // Standard 1080p
        bitrate: 9000000, // 9 Mbps for smaller files
        minimumFileSizeForCompress: 0,
      }
    }
    
    let compressedPath: string
    try {
      compressedPath = await Video.compress(
        localPath,
        compressionSettings,
        (progress) => {
          const percent = (progress * 100).toFixed(0)
          console.log(`🗜️  [COMPRESS] Progress: ${percent}%`)
          onProgress?.(`Compressing video... ${percent}%`)
        }
      )
    } catch (compressError: any) {
      console.error('❌ [COMPRESS] Compression failed:', compressError)
      // Clean up downloaded file
      try {
        await FileSystem.deleteAsync(localPath, { idempotent: true })
      } catch (e) {
        console.warn('⚠️  [COMPRESS] Cleanup warning:', e)
      }
      throw new Error(`Compression failed: ${compressError.message || 'Unknown error'}`)
    }
    
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
    
    // Clear active job after successful compression
    await clearActiveJob()
    
    return result
    
  } catch (error: any) {
    console.error('❌ [COMPRESS] Error:', error)
    onProgress?.(`Compression error: ${error.message || 'Unknown error'}`)
    // Return original result even if compression fails
    // The detection results are still valid, just no annotated video
    // Keep job in storage in case user wants to retry
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
  
  // Save job ID to local storage for recovery
  await saveActiveJob(jobId, 'processing')
  
  // Step 2: Poll for results
  const isVideo = name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)
  const processingMessage = isVideo ? 'Processing video... This may take 3-10 minutes' : 'Processing image... This may take 1-3 minutes'
  onProgress?.(processingMessage)
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
        // Job cleared inside handleClientCompression after upload completes
      } else {
        // No compression needed, clear job now
        await clearActiveJob()
        console.log('🗑️  [COMBINED] Cleared job from AsyncStorage (no compression needed)')
      }
      
      return finalResult
    } else if (status.status === 'failed') {
      console.error('❌ [POLLING] Processing failed:', status.error)
      await clearActiveJob()
      console.log('🗑️  [COMBINED] Cleared failed job from AsyncStorage')
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

  // Save job ID to local storage for recovery
  await saveActiveJob(jobId, 'processing')
  console.log('💾 [COMBINED] Saved job to AsyncStorage for recovery')

  // Step 2: Poll for results
  const isVideo = mediaFile.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)
  const processingMessage = isVideo ? 'Processing video... This may take 3-10 minutes' : 'Processing image... This may take 1-3 minutes'
  onProgress?.(processingMessage)
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
  const { refreshSessions, setSelectedDetection, sessions } = useSession();
  const insets = useSafeAreaInsets();
  const [selectedMedia, setSelectedMedia] = useState<SelectedFile | null>(null)
  const [selectedSrt, setSelectedSrt] = useState<SelectedFile | null>(null)
  const [status, setStatus] = useState<'idle' | 'picking' | 'ready' | 'uploading' | 'success' | 'error'>('idle')
  const [progress, setProgress] = useState<number>(0)
  const [message, setMessage] = useState<string>('')
  const progressTimerRef = useRef<number | null>(null)

  // Helper function to auto-select newly uploaded session
  const autoSelectSession = async (detection_id: number) => {
    try {
      const { API_BASE } = await import('../config');
      const res = await fetch(`${API_BASE}/detections/`);
      const json = await res.json();
      const updatedSessions = json?.detections ?? [];
      
      const newSession = updatedSessions.find((s: any) => s[0] === detection_id);
      if (newSession) {
        setSelectedDetection(newSession);
        console.log('✅ [AUTO-SELECT] Selected session:', detection_id);
      }
    } catch (error) {
      console.error('❌ [AUTO-SELECT] Failed:', error);
    }
  }

  // Check for pending jobs on mount
  useEffect(() => {
    checkForPendingJobs()
    return () => {
      if (progressTimerRef.current !== null) clearInterval(progressTimerRef.current)
    }
  }, [])

  const checkForPendingJobs = async () => {
    console.log('🔍 [RECOVERY] checkForPendingJobs called')
    try {
      // Check for active job stored locally
      const activeJob = await getActiveJob()
      console.log('🔍 [RECOVERY] getActiveJob result:', activeJob)
      if (!activeJob) {
        console.log('🔍 [RECOVERY] No active job found in AsyncStorage')
        return
      }

      const { job_id, stage } = activeJob
      console.log(`📋 [RECOVERY] Found active job: ${job_id}, stage: ${stage}`)

      // Check job status on server
      console.log(`🔍 [RECOVERY] Fetching job status from: ${API_BASE}/job-status/${job_id}`)
      const statusResponse = await fetch(`${API_BASE}/job-status/${job_id}`)
      console.log(`🔍 [RECOVERY] Status response OK:`, statusResponse.ok)
      if (!statusResponse.ok) {
        console.log('📋 [RECOVERY] Job not found on server, clearing local storage')
        await clearActiveJob()
        return
      }

      const jobStatus = await statusResponse.json()
      console.log(`📋 [RECOVERY] Job status:`, jobStatus.status)
      console.log(`📋 [RECOVERY] needs_client_compression:`, jobStatus.needs_client_compression)
      console.log(`📋 [RECOVERY] temp_video_path:`, jobStatus.temp_video_path)
      console.log(`📋 [RECOVERY] Full jobStatus:`, JSON.stringify(jobStatus, null, 2))

      // Check for jobs waiting for client compression (top-level field from backend)
      if (jobStatus.status === 'completed' && jobStatus.needs_client_compression) {
        Alert.alert(
          'Resume Upload?',
          'Your video is processed and ready for compression. Would you like to continue?',
          [
            {
              text: 'Cancel Job',
              style: 'destructive',
              onPress: async () => {
                await clearActiveJob()
                console.log('🗑️  [RECOVERY] User cancelled compression, cleared AsyncStorage')
                
                // Optionally clean up temp video on backend
                try {
                  await fetch(`${API_BASE}/cancel-job/${job_id}`, { method: 'POST' })
                } catch (error) {
                  console.log('⚠️  [RECOVERY] Could not notify backend of cancellation')
                }
                
                setStatus('idle')
                setMessage('')
              }
            },
            {
              text: 'Resume',
              onPress: async () => {
                setStatus('uploading')
                setMessage('Resuming compression...')
                try {
                  // Create result object with needs_client_compression flag
                  const resumeResult = {
                    ...jobStatus.result,
                    needs_client_compression: true
                  }
                  
                  const finalResult = await handleClientCompression(job_id, resumeResult, (msg) => {
                    setMessage(msg)
                  })
                  
                  await clearActiveJob()
                  setStatus('success')
                  setMessage('Upload completed successfully!')
                  await refreshSessions()
                  
                  // Auto-select the resumed session
                  if (finalResult?.detection_id) {
                    await autoSelectSession(finalResult.detection_id)
                  }
                } catch (error: any) {
                  console.error('❌ [RECOVERY] Resume failed:', error)
                  setStatus('error')
                  setMessage(`Resume failed: ${error.message}`)
                }
              }
            }
          ]
        )
      } else if (jobStatus.status === 'processing' || jobStatus.status === 'queued') {
        // Still processing inference - resume polling
        Alert.alert(
          'Resume Processing?',
          'Your previous upload is still being processed. Would you like to continue monitoring?',
          [
            {
              text: 'Cancel Job',
              style: 'destructive',
              onPress: async () => {
                try {
                  // Clear AsyncStorage immediately
                  await clearActiveJob()
                  console.log('🗑️  [RECOVERY] User cancelled, cleared AsyncStorage')
                  
                  // Optionally abort the backend job
                  try {
                    const abortResponse = await fetch(`${API_BASE}/cancel-job/${job_id}`, {
                      method: 'POST'
                    })
                    if (abortResponse.ok) {
                      console.log('� [RECOVERY] Backend job cancelled successfully')
                    }
                  } catch (error) {
                    console.log('⚠️  [RECOVERY] Could not cancel backend job (may already be complete)')
                  }
                  
                  setStatus('idle')
                  setMessage('')
                } catch (error) {
                  console.error('❌ [RECOVERY] Error cancelling job:', error)
                }
              }
            },
            {
              text: 'Resume',
              onPress: async () => {
                try {
                  setStatus('uploading')
                  setMessage(jobStatus.progress || 'Processing...')
                  console.log('📋 [RECOVERY] Resuming polling for job:', job_id)
                  
                  // Resume polling from where it left off
                  let pollCount = 0
                  const maxPolls = 40 // 20 minutes max
                  
                  while (pollCount < maxPolls) {
                    await new Promise(resolve => setTimeout(resolve, 30000)) // Wait 30 seconds
                    pollCount++
                    
                    console.log(`📊 [RECOVERY POLLING] Poll attempt ${pollCount}/${maxPolls}`)
                    
                    const statusResponse = await fetch(`${API_BASE}/job-status/${job_id}`)
                    if (!statusResponse.ok) {
                      throw new Error(`Status check failed: ${statusResponse.status}`)
                    }
                    
                    const status = await statusResponse.json()
                    console.log(`📊 [RECOVERY POLLING] Status: ${status.status}`)
                    
                    if (status.progress) {
                      setMessage(status.progress)
                    }
                    
                    if (status.status === 'completed') {
                      console.log('✅ [RECOVERY POLLING] Processing completed!')
                      
                      // Check if compression is needed
                      let finalResult = status.result
                      if (status.needs_client_compression || status.result?.needs_client_compression) {
                        console.log('🗜️  [RECOVERY] Starting client-side compression')
                        const resumeResult = {
                          ...status.result,
                          needs_client_compression: true
                        }
                        finalResult = await handleClientCompression(job_id, resumeResult, (msg) => {
                          setMessage(msg)
                        })
                      } else {
                        await clearActiveJob()
                      }
                      
                      setStatus('success')
                      setMessage('Processing completed successfully!')
                      await refreshSessions()
                      
                      // Auto-select the resumed session
                      if (finalResult?.detection_id) {
                        await autoSelectSession(finalResult.detection_id)
                      }
                      break
                    } else if (status.status === 'failed') {
                      await clearActiveJob()
                      setStatus('error')
                      setMessage(`Processing failed: ${status.error}`)
                      break
                    }
                    
                    const minutesElapsed = (pollCount * 30) / 60
                    setMessage(`Processing... ${minutesElapsed.toFixed(1)} min elapsed`)
                  }
                  
                  if (pollCount >= maxPolls) {
                    setStatus('error')
                    setMessage('Processing timeout - took longer than 20 minutes')
                  }
                } catch (error: any) {
                  console.error('❌ [RECOVERY POLLING] Error:', error)
                  setStatus('error')
                  setMessage(`Resume failed: ${error.message}`)
                }
              }
            }
          ]
        )
      } else if (jobStatus.status === 'completed' && !jobStatus.needs_client_compression) {
        // Already fully completed, just clear
        console.log('📋 [RECOVERY] Job already completed, clearing local storage')
        await clearActiveJob()
        await refreshSessions()
      } else if (jobStatus.status === 'failed') {
        // Failed, clear storage
        await clearActiveJob()
      }
    } catch (error) {
      console.error('📋 [RECOVERY] Error checking pending jobs:', error)
    }
  }

  // Deprecated - use helper functions instead
  const saveActiveJobOld = async (job_id: string, stage: 'upload' | 'processing' | 'compression') => {
    await saveActiveJob(job_id, stage)
  }

  const clearActiveJobOld = async () => {
    await clearActiveJob()
  }

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
        // Try to preserve an actual filename provided by the picker (if present).
        // Fall back to the URI last segment, sanitizing query params. If still missing,
        // use a sensible default based on media type so the name stays stable.
        const maybeFileName = (asset as any).fileName || (asset as any).filename || (asset as any).name
        let inferredName = ''

        if (maybeFileName && typeof maybeFileName === 'string' && maybeFileName.trim() !== '') {
          inferredName = maybeFileName
        } else if (asset.uri && typeof asset.uri === 'string') {
          // strip query params and fragments
          const uriPart = asset.uri.split('?')[0].split('#')[0]
          inferredName = uriPart.split('/')?.pop() || ''
        }

        // Ensure we have a fallback name with an extension
        if (!inferredName) {
          inferredName = asset.type === 'video' ? 'video.mp4' : 'image.jpg'
        }

        // If name has no extension, append one based on asset.type
        if (!/\.[a-z0-9]+$/i.test(inferredName)) {
          inferredName = inferredName + (asset.type === 'video' ? '.mp4' : '.jpg')
        }
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

      // Validate that SRT and MP4 files have the exact same name except for extension
      if (selectedSrt && selectedMedia && isVideo) {
        const mediaName = selectedMedia.name.toLowerCase()
        const srtName = selectedSrt.name.toLowerCase()
        
        // Remove extensions
        const mediaBaseName = mediaName.replace(/\.(mp4|mov|avi|mkv)$/, '')
        const srtBaseName = srtName.replace(/\.srt$/, '')
        
        console.log('📋 [VALIDATION] Media base name:', mediaBaseName)
        console.log('📋 [VALIDATION] SRT base name:', srtBaseName)
        
        if (mediaBaseName !== srtBaseName) {
          console.error('❌ [VALIDATION] File names do not match')
          throw new Error(`File names must match exactly (except extension). Media: "${selectedMedia.name}", SRT: "${selectedSrt.name}"`)
        }
        
        console.log('✅ [VALIDATION] File names match correctly')
      }

      setProgress(30)

      // Compress video if needed (only for video files)
      let mediaUriToUpload = selectedMedia?.uri
      let mediaSizeToUpload = selectedMedia?.size || 0
      
      if (selectedMedia && isVideo) {
        const fileSizeMB = (selectedMedia.size || 0) / (1024 * 1024)
        console.log('🎬 [COMPRESSION] Starting video compression...')
        console.log('🎬 [COMPRESSION] Original size:', fileSizeMB.toFixed(2), 'MB')
        
        setMessage('Compressing video...')
        setProgress(35)
        
        try {
          // Dynamic compression settings based on file size
          let compressSettings: any
          if (fileSizeMB > 200) {
            console.log('🎬 [COMPRESSION] Using high quality settings for large file')
            compressSettings = {
              compressionMethod: 'auto',
              maxSize: 1080,  // Keep 1080p for better quality
              bitrate: 7000000, // 7 Mbps
            }
          } else if (fileSizeMB > 100) {
            console.log('🎬 [COMPRESSION] Using high quality settings')
            compressSettings = {
              compressionMethod: 'auto',
              maxSize: 1080,  // 1080p
              bitrate: 8000000, // 8 Mbps
            }
          } else {
            console.log('🎬 [COMPRESSION] Using maximum quality settings')
            compressSettings = {
              compressionMethod: 'auto',
              maxSize: 1080,  // 1080p
              bitrate: 9000000, // 9 Mbps
            }
          }
          
          const compressedUri = await Video.compress(
            selectedMedia.uri,
            compressSettings,
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
        } catch (compressionError: any) {
          console.warn('⚠️ [COMPRESSION] Failed, using original video:', compressionError)
          setMessage('Compression failed. Uploading original...')
          setProgress(60)
        }
      }

      // Compress images client-side to avoid backend 413 errors (Roboflow size limits)
      else if (selectedMedia && isImage) {
        const fileSizeMB = (selectedMedia.size || 0) / (1024 * 1024)
        console.log('🖼️ [COMPRESSION] Starting image compression...')
        console.log('🖼️ [COMPRESSION] Original size:', fileSizeMB.toFixed(2), 'MB')

        setMessage('Compressing image...')
        setProgress(40)

        try {
          // Choose compression parameters based on size
          let quality = 0.8
          let maxWidth = 1920
          if (fileSizeMB > 5) {
            quality = 0.6
            maxWidth = 1280
          } else if (fileSizeMB > 2) {
            quality = 0.75
            maxWidth = 1600
          }

          // CompressorImage.compress returns a local URI for the compressed image
          const compressedUri = await CompressorImage.compress(selectedMedia.uri, {
            compressFormat: 'JPEG',
            quality: quality,
            maxWidth: maxWidth,
            // let library choose maxHeight to preserve aspect ratio
          } as any)

          console.log('✅ [COMPRESSION] Compressed image URI:', compressedUri)

          // Copy compressed file to cache with the original filename so upload preserves name
          const cacheDest = `${FileSystem.cacheDirectory}${selectedMedia.name}`
          try {
            await FileSystem.copyAsync({ from: compressedUri, to: cacheDest })
            const info = await FileSystem.getInfoAsync(cacheDest)
            mediaUriToUpload = cacheDest
            mediaSizeToUpload = info.exists ? info.size : mediaSizeToUpload
            console.log('✅ [COMPRESSION] Copied compressed image to cache:', cacheDest)
          } catch (copyErr) {
            console.warn('⚠️ [COMPRESSION] Failed to copy compressed image to cache, using compressed URI directly', copyErr)
            mediaUriToUpload = compressedUri
            try {
              const info = await FileSystem.getInfoAsync(compressedUri)
              mediaSizeToUpload = info.exists ? info.size : mediaSizeToUpload
            } catch {}
          }

          setMessage('Compression complete. Uploading...')
          setProgress(60)
        } catch (compressionError: any) {
          console.warn('⚠️ [COMPRESSION] Image compression failed, uploading original:', compressionError)
          setMessage('Image compression failed. Uploading original...')
          setProgress(60)
        }
      }

      setProgress(isVideo ? 65 : 30)
      setMessage('Uploading to server...')

      // Declare result variable at higher scope
      let result: any = null;

      // Use combined upload endpoint if both files are selected
      if (selectedMedia && selectedSrt) {
        console.log('📦 [MODE] Using combined upload (media + SRT)')
        
        // Create modified media object with compressed URI
        const mediaToUpload = {
          ...selectedMedia,
          uri: mediaUriToUpload || selectedMedia.uri,
          size: mediaSizeToUpload
        }
        
        result = await uploadCombinedFiles(mediaToUpload, selectedSrt, (progressMsg) => {
          setMessage(progressMsg)
        })
        setMessage(result.message || 'Upload complete with GPS data.')
      } else if (selectedMedia) {
        console.log('📦 [MODE] Using single file upload (media only)')
        result = await uploadFileToApi(mediaUriToUpload || selectedMedia.uri, selectedMedia.name, (progressMsg) => {
          setMessage(progressMsg)
        })
        setMessage(result.message || `${result.summary} (No GPS data - image only or video without SRT)`)
      }

      const totalTime = ((Date.now() - uploadStartTime) / 1000).toFixed(2)
      console.log(`✅ [UPLOAD COMPLETE] Total time: ${totalTime}s`)
      console.log('✅ [UPLOAD COMPLETE] ================================================')

      setProgress(100)
      setStatus('success')
      
      // Clear file selections after successful upload
      setSelectedMedia(null)
      setSelectedSrt(null)
      
      // Refresh sessions to include the new upload
      await refreshSessions();
      
      // Auto-select the newly uploaded session
      if (result?.detection_id) {
        // Get the updated sessions list after refresh
        const { API_BASE } = await import('../config');
        const res = await fetch(`${API_BASE}/detections/`);
        const json = await res.json();
        const updatedSessions = json?.detections ?? [];
        
        const newSession = updatedSessions.find((s: any) => s[0] === result.detection_id);
        if (newSession) {
          setSelectedDetection(newSession);
          console.log('✅ [AUTO-SELECT] Selected newly uploaded session:', result.detection_id);
        }
      }
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
  
  // Check if file names match (for video + SRT combinations)
  const fileNamesMatch = useMemo(() => {
    if (!selectedSrt || !selectedMedia) return true // No SRT file, so no validation needed
    if (!selectedMedia.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)) return true // Not a video file
    
    const mediaName = selectedMedia.name.toLowerCase()
    const srtName = selectedSrt.name.toLowerCase()
    const mediaBaseName = mediaName.replace(/\.(mp4|mov|avi|mkv)$/, '')
    const srtBaseName = srtName.replace(/\.srt$/, '')
    
    return mediaBaseName === srtBaseName
  }, [selectedMedia, selectedSrt])

  const onRefresh = useCallback(async () => {
    // Soft refresh UI state; optionally ping backend to ensure API_BASE is reachable
    try {
      setStatus('idle')
      setMessage('')
      // Optional: await fetch(`${API_BASE}/detections/`).catch(() => {})
    } catch {}
  }, [])

  return (
    <SafeAreaView className="flex-1 bg-bgColor1" edges={['top']}>
      <ScrollView 
        contentContainerStyle={{ alignItems: 'center', paddingTop: 16, paddingBottom: 16, paddingHorizontal: 16 }}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={false} onRefresh={onRefresh} />}>
        

        {/* App Branding - Improved Visibility */}
        <View className="w-full max-w-md mb-6 items-center">
          <View
            style={{
              backgroundColor: '#25A578',
              borderRadius: 18,
              paddingVertical: 18,
              paddingHorizontal: 32,
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'center',
              shadowColor: '#000',
              shadowOffset: { width: 0, height: 2 },
              shadowOpacity: 0.18,
              shadowRadius: 6,
              elevation: 6,
              marginBottom: 0,
            }}
          >
            <FontAwesome6 name="seedling" size={36} color="#fff" style={{ textShadowColor: '#1a5c3a', textShadowOffset: { width: 1, height: 2 }, textShadowRadius: 4 }} />
            <Text
              style={{
                color: '#fff',
                fontSize: 36,
                fontWeight: 'bold',
                marginLeft: 14,
                letterSpacing: 2,
                textShadowColor: '#1a5c3a',
                textShadowOffset: { width: 1, height: 2 },
                textShadowRadius: 4,
                fontFamily: 'System',
              }}
            >
              WEEDEFY
            </Text>
          </View>
          <Text style={{ color: '#25A578', marginTop: 8, fontWeight: '600', fontSize: 16, letterSpacing: 1 }}>
            Smart Weed Detection System
          </Text>
        </View>

        <View className="justify-center items-center bg-white w-full max-w-md h-auto py-6 px-4 rounded-2xl shadow-custom border-2 border-gray-200">
        <Ionicons name="cloud-upload" size={56} color="rgb(37, 165, 120)" className="mb-3" />
        <Text className="text-2xl font-bold text-gray-800 mb-2 text-center">
          Upload Media & Subtitles
        </Text>
        <Text className="text-gray-600 text-center px-4 mb-4">
          Pick a video/photo and upload SRT subtitle file.
        </Text>

        {/* File Pickers - Side by Side */}
        <View className="flex-row gap-4 mb-4 w-full">
          {/* Media Picker */}
          <View className="flex-1">
            <Text className="text-sm font-semibold text-gray-700 mb-2.5 text-center">Media File</Text>
            <Pressable
              onPress={pickMedia}
              disabled={isBusy}
              className={`h-[100px] items-center justify-center rounded-lg border-2 border-greenColor ${isBusy ? 'bg-gray-300' : 'bg-bgColor1'}`}
            >
              <FontAwesome6 name='file-video' size={32} color='rgb(37, 165, 120)' />
              <Text className="text-greenColor font-bold text-xs text-center mt-2 px-2">
                {status === 'picking' ? 'Opening...' : 'Choose video/image'}
              </Text>
            </Pressable>

            {selectedMedia && (
              <View className="bg-white border border-gray-200 rounded-lg p-2.5 mt-3">
                <Text className="text-gray-800 font-medium text-xs" numberOfLines={1}>{selectedMedia.name}</Text>
                <Text className="text-gray-500 text-xs mt-0.5">
                  {selectedMedia.size ? `${(selectedMedia.size / (1024 * 1024)).toFixed(2)} MB` : 'Size unknown'}
                </Text>
              </View>
            )}
          </View>

          {/* SRT File Picker */}
          <View className="flex-1">
            <Text className="text-sm font-semibold text-gray-700 mb-2.5 text-center">SRT (Optional)</Text>
            <Pressable
              onPress={pickSrt}
              disabled={isBusy}
              className={`h-[100px] items-center justify-center rounded-lg border-2 border-blue-500 ${isBusy ? 'bg-gray-300' : 'bg-blue-50'}`}
            >
              <FontAwesome6 name='file-lines' size={32} color='rgb(59, 130, 246)' />
              <Text className="text-blue-600 font-bold text-xs text-center mt-2 px-2">
                {status === 'picking' ? 'Opening...' : 'Choose SRT file'}
              </Text>
            </Pressable>

            {selectedSrt && (
              <View className="bg-white border border-gray-200 rounded-lg p-2.5 mt-3">
                <Text className="text-gray-800 font-medium text-xs" numberOfLines={1}>{selectedSrt.name}</Text>
                <Text className="text-gray-500 text-xs mt-0.5">
                  {selectedSrt.size ? `${(selectedSrt.size / 1024).toFixed(2)} KB` : 'Size unknown'}
                </Text>
              </View>
            )}
          </View>
        </View>

        <Pressable
          onPress={mockUpload}
          disabled={!hasAnyFile || status === 'uploading' || 
            (selectedSrt && !selectedMedia) ||
            (selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i)) ||
            !fileNamesMatch}
          className={`mt-3 h-[48px] w-full justify-center items-center px-4 py-2 rounded-lg mb-3 ${(!hasAnyFile || status === 'uploading' || 
            (selectedSrt && !selectedMedia) ||
            (selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i)) ||
            !fileNamesMatch) ? 'bg-darkgrayColor' : 'bg-greenColor'}`}
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
          <View className="w-full h-3 bg-gray-200 rounded-full overflow-hidden mb-3">
            <View style={{ width: `${progress}%` }} className="h-3 bg-blue-600" />
          </View>
        )}

        {/* Validation warnings */}
        {selectedSrt && !selectedMedia && (
          <View className="w-full bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-3">
            <Text className="text-yellow-800 text-sm font-medium">⚠️ SRT file requires a media file</Text>
            <Text className="text-yellow-700 text-xs mt-1">Please select a video or image file first.</Text>
          </View>
        )}
        
        {selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i) && (
          <View className="w-full bg-red-50 border border-red-300 rounded-lg p-3 mb-3">
            <Text className="text-red-800 text-sm font-medium">❌ SRT files cannot be used with images</Text>
            <Text className="text-red-700 text-xs mt-1">SRT files provide GPS data for video mapping only.</Text>
          </View>
        )}

        {selectedMedia && !selectedSrt && !!selectedMedia.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i) && (
          <View className="w-full bg-blue-50 border border-blue-300 rounded-lg p-3 mb-3">
            <Text className="text-blue-800 text-sm font-medium">ℹ️ Video without GPS data</Text>
            <Text className="text-blue-700 text-xs mt-1">Upload an SRT file to enable map visualization of detection locations.</Text>
          </View>
        )}

        {/* File name validation warning */}
        {selectedSrt && selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i) && (() => {
          const mediaName = selectedMedia.name.toLowerCase()
          const srtName = selectedSrt.name.toLowerCase()
          const mediaBaseName = mediaName.replace(/\.(mp4|mov|avi|mkv)$/, '')
          const srtBaseName = srtName.replace(/\.srt$/, '')
          
          if (mediaBaseName !== srtBaseName) {
            return (
              <View className="w-full bg-red-50 border border-red-300 rounded-lg p-3 mb-3">
                <Text className="text-red-800 text-sm font-medium">❌ File names do not match</Text>
                <Text className="text-red-700 text-xs mt-1">
                  SRT and video files must have the exact same name (except extension). 
                  Current: "{selectedMedia.name}" and "{selectedSrt.name}"
                </Text>
              </View>
            )
          }
          return null
        })()}

        {!!message && (
          <View className="w-full bg-white border border-gray-200 rounded-lg p-3 mb-2">
            <Text className={`text-sm text-center ${status === 'success' ? 'text-green-700' : status === 'error' ? 'text-red-700' : 'text-gray-700'}`}>
              {message}
            </Text>
          </View>
        )}

        {(hasAnyFile || status === 'success' || status === 'error') && (
          <Pressable onPress={reset} disabled={isBusy} className={`px-6 py-3 rounded-lg mt-3 ${isBusy ? 'bg-gray-300' : 'bg-gray-600'}`}>
            <Text className="text-white font-medium text-base">Reset</Text>
          </Pressable>
        )}
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}

export default Homescreen

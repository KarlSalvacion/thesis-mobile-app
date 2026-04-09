import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { View, Text, ScrollView, RefreshControl, Alert } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import * as FileSystem from 'expo-file-system/legacy'
import { Image as CompressorImage, Video } from 'react-native-compressor'
import { useSession } from '../context/SessionContext'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { getActiveJob, clearActiveJob } from '../utils/jobRecovery'
import { API_BASE } from '../config'
import HomeBranding from '../components/home/HomeBranding'
import HomeUploadPickers from '../components/home/HomeUploadPickers'
import HomeUploadActions from '../components/home/HomeUploadActions'
import { SelectedFile } from '../components/home/types'
import { handleClientCompression, uploadCombinedFiles, uploadFileToApi } from '../services/homeUploadService'

const Homescreen = () => {
  const { refreshSessions, setSelectedDetection, setNavigationLocked } = useSession();
  useSafeAreaInsets();
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

  const pickMedia = async () => {
    try {
      setMessage('')
      setStatus('picking')
      setNavigationLocked(true) // Lock navigation during file picking
      setMessage('Opening file picker...')

      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync()
      if (permission.status !== 'granted') {
        setStatus(selectedMedia || selectedSrt ? 'ready' : 'idle')
        setMessage('Permission to access media library is required.')
        setNavigationLocked(false) // Unlock on error
        return
      }

      setMessage('Selecting file... This may take a moment for large files')
      
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.All,
        allowsEditing: false,
        quality: 1,
        // Optimize: Don't load full image into memory for preview
        exif: false,
        base64: false,
      })

      if (result.canceled) {
        setStatus((selectedMedia || selectedSrt) ? 'ready' : 'idle')
        setMessage('')
        setNavigationLocked(false) // Unlock on cancel
        return
      }

      const asset = result.assets?.[0]
      if (asset) {
        setMessage('Reading file information...')
        
        // Get file info asynchronously with shorter timeout for images (2s), longer for videos (5s)
        let size: number | null = null
        let inferredName = ''
        
        try {
          // Optimize: Use shorter timeout for images since they load faster
          const timeoutDuration = asset.type === 'image' ? 2000 : 5000
          const infoPromise = FileSystem.getInfoAsync(asset.uri)
          const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Timeout')), timeoutDuration)
          )
          
          const info: any = await Promise.race([infoPromise, timeoutPromise])
          size = typeof info?.size === 'number' ? info.size : null
          
          // Validate file size (max 1GB for stability)
          if (size && size > 1024 * 1024 * 1024) {
            setStatus('error')
            setMessage('File too large. Maximum file size is 1GB.')
            setNavigationLocked(false) // Unlock on error
            return
          }
          
          // Show file size in MB
          if (size) {
            const sizeMB = (size / (1024 * 1024)).toFixed(2)
            console.log(`📁 [FILE INFO] Size: ${sizeMB} MB`)
          }
        } catch (err) {
          console.warn('⚠️  [FILE INFO] Could not read file size:', err)
          // Continue without size info
        }

        // Extract filename
        const maybeFileName = (asset as any).fileName || (asset as any).filename || (asset as any).name
        
        if (maybeFileName && typeof maybeFileName === 'string' && maybeFileName.trim() !== '') {
          inferredName = maybeFileName
        } else if (asset.uri && typeof asset.uri === 'string') {
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

        // Validate media type
        if (asset.type === 'video' || asset.type === 'image') {
          // Show file info
          const fileType = asset.type === 'video' ? 'Video' : 'Image'
          const sizeInfo = size ? ` (${(size / (1024 * 1024)).toFixed(2)} MB)` : ''
          
          setSelectedMedia({
            uri: asset.uri,
            name: inferredName,
            size: size,
            type: 'media'
          })
          setStatus('ready')
          setMessage(`${fileType} selected${sizeInfo}. Ready to upload.`)
          setNavigationLocked(false) // Unlock after successful selection
          
          // Warn if file is very large
          if (size && size > 500 * 1024 * 1024) { // > 500MB
            console.warn(`⚠️  [FILE INFO] Large file detected: ${(size / (1024 * 1024)).toFixed(2)} MB`)
            setMessage(`${fileType} selected${sizeInfo}. Large file - upload may take several minutes.`)
          }
        } else {
          setMessage('Please select a valid video or image file.')
          setStatus('error')
          setNavigationLocked(false) // Unlock on error
        }
      } else {
        setStatus('idle')
        setMessage('')
        setNavigationLocked(false) // Unlock if no asset
      }
    } catch (err: any) {
      console.error('❌ [PICK MEDIA] Error:', err)
      setMessage(`Failed to pick file: ${err.message || 'Unknown error'}`)
      setStatus('error')
      setNavigationLocked(false) // Unlock on error
    }
  }

  const pickSrt = async () => {
    try {
      setMessage('')
      setStatus('picking')
      setNavigationLocked(true) // Lock navigation during file picking
      setMessage('Opening file picker...')
      
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          (DocumentPicker as any).types?.allFiles || 'public.item',
          'public.item',
          'public.data',
          'public.content',
          'public.text',
          'public.plain-text',
          'text/plain',
          'application/x-subrip',
          '*/*',
        ],
        multiple: false,
        copyToCacheDirectory: false // Don't copy immediately - faster picker response
      })

      if (result.canceled) {
        setStatus((selectedMedia || selectedSrt) ? 'ready' : 'idle')
        setMessage('')
        setNavigationLocked(false) // Unlock on cancel
        return
      }

      const file = result.assets?.[0]
      if (file) {
        setMessage('Validating SRT file...')
        
        // Validate SRT file
        const fileName = file.name ?? 'subtitle.srt'
        if (!fileName.toLowerCase().endsWith('.srt')) {
          setStatus('error')
          setMessage('Please select a valid .srt file.')
          setNavigationLocked(false) // Unlock on error
          return
        }
        
        // Validate file size (max 10MB for SRT)
        if (file.size && file.size > 10 * 1024 * 1024) {
          setStatus('error')
          setMessage('SRT file too large. Maximum size is 10MB.')
          setNavigationLocked(false) // Unlock on error
          return
        }
        
        // Validate filename matches media (if media already selected)
        if (selectedMedia) {
          const mediaBaseName = selectedMedia.name.toLowerCase().replace(/\.(mp4|mov|avi|mkv|jpg|jpeg|png|bmp|gif)$/, '')
          const srtBaseName = fileName.toLowerCase().replace(/\.srt$/, '')
          
          if (mediaBaseName !== srtBaseName) {
            Alert.alert(
              'File Name Mismatch',
              `SRT filename "${fileName}" does not match media filename "${selectedMedia.name}".\n\nThey must have the same name (except extension).\n\nDo you want to continue anyway?`,
              [
                { text: 'Cancel', style: 'cancel', onPress: () => {
                  setStatus('ready')
                  setMessage('SRT file selection cancelled.')
                  setNavigationLocked(false) // Unlock on cancel
                }},
                { text: 'Continue', onPress: () => {
                  setSelectedSrt({
                    uri: file.uri,
                    name: fileName,
                    size: file.size,
                    type: 'srt'
                  })
                  setStatus('ready')
                  setMessage('⚠️  Warning: Filenames do not match. GPS data may not sync correctly.')
                  setNavigationLocked(false) // Unlock after selection
                }}
              ]
            )
            return
          }
        }
        
        setSelectedSrt({
          uri: file.uri,
          name: fileName,
          size: file.size,
          type: 'srt'
        })
        setStatus('ready')
        const sizeInfo = file.size ? ` (${(file.size / 1024).toFixed(2)} KB)` : ''
        setMessage(`SRT file selected${sizeInfo}`)
        setNavigationLocked(false) // Unlock after successful selection
      } else {
        setStatus('idle')
        setMessage('')
        setNavigationLocked(false) // Unlock if no file
      }
    } catch (err: any) {
      console.error('❌ [PICK SRT] Error:', err)
      setMessage(`Failed to pick SRT file: ${err.message || 'Unknown error'}`)
      setStatus('error')
      setNavigationLocked(false) // Unlock on error
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
          
          // Final size check - videos should be under 200MB after compression
          const MAX_VIDEO_SIZE_MB = 200
          const compressedSizeMB = compressedSize / (1024 * 1024)
          
          if (compressedSizeMB > MAX_VIDEO_SIZE_MB) {
            console.error(`❌ [COMPRESSION] Compressed video still too large: ${compressedSizeMB.toFixed(2)} MB (max: ${MAX_VIDEO_SIZE_MB} MB)`)
            setStatus('error')
            setMessage(`Video is too large even after compression (${compressedSizeMB.toFixed(1)} MB). Please select a shorter video or lower quality source file.`)
            return
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
            
            // Final size check - images should be under 10MB after compression (Roboflow limit)
            const MAX_IMAGE_SIZE_MB = 10
            const compressedSizeMB = mediaSizeToUpload / (1024 * 1024)
            
            if (compressedSizeMB > MAX_IMAGE_SIZE_MB) {
              console.error(`❌ [COMPRESSION] Compressed image still too large: ${compressedSizeMB.toFixed(2)} MB (max: ${MAX_IMAGE_SIZE_MB} MB)`)
              setStatus('error')
              setMessage(`Image is too large even after compression (${compressedSizeMB.toFixed(1)} MB). Please select a smaller image or lower resolution.`)
              return
            }
            
            console.log(`✅ [COMPRESSION] Final image size: ${compressedSizeMB.toFixed(2)} MB (within ${MAX_IMAGE_SIZE_MB} MB limit)`)
          } catch (copyErr) {
            console.warn('⚠️ [COMPRESSION] Failed to copy compressed image to cache, using compressed URI directly', copyErr)
            mediaUriToUpload = compressedUri
            try {
              const info = await FileSystem.getInfoAsync(compressedUri)
              mediaSizeToUpload = info.exists ? info.size : mediaSizeToUpload
              
              // Final size check on the compressed URI
              const MAX_IMAGE_SIZE_MB = 10
              const compressedSizeMB = mediaSizeToUpload / (1024 * 1024)
              
              if (compressedSizeMB > MAX_IMAGE_SIZE_MB) {
                console.error(`❌ [COMPRESSION] Compressed image still too large: ${compressedSizeMB.toFixed(2)} MB (max: ${MAX_IMAGE_SIZE_MB} MB)`)
                setStatus('error')
                setMessage(`Image is too large even after compression (${compressedSizeMB.toFixed(1)} MB). Please select a smaller image or lower resolution.`)
                return
              }
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
      
      // Wait a moment for database to fully update (especially after compression)
      await new Promise(resolve => setTimeout(resolve, 500))
      
      // Refresh sessions to include the new upload
      console.log('🔄 [AUTO-SELECT] Refreshing sessions...')
      await refreshSessions();
      
      // Wait another moment for context to update
      await new Promise(resolve => setTimeout(resolve, 300))
      
      // Auto-select the newly uploaded session
      if (result?.detection_id) {
        console.log('🔍 [AUTO-SELECT] Fetching updated sessions for detection_id:', result.detection_id)
        // Get the updated sessions list after refresh
        const { API_BASE } = await import('../config');
        
        // Fetch the specific detection to ensure we have the latest data
        console.log('🔍 [AUTO-SELECT] Fetching specific detection data...')
        const detectionRes = await fetch(`${API_BASE}/detection/${result.detection_id}`);
        if (detectionRes.ok) {
          const detectionJson = await detectionRes.json();
          const specificDetection = detectionJson?.detection;
          if (specificDetection) {
            setSelectedDetection(specificDetection);
            console.log('✅ [AUTO-SELECT] Selected specific detection with latest data:', result.detection_id);
            console.log('✅ [AUTO-SELECT] cloud_annotated_url:', specificDetection[14]);
            return; // Successfully selected, exit early
          }
        }
        
        // Fallback: get from full list if specific fetch failed
        console.log('🔍 [AUTO-SELECT] Fallback: fetching from full sessions list...')
        const res = await fetch(`${API_BASE}/detections/`);
        const json = await res.json();
        const updatedSessions = json?.detections ?? [];
        
        console.log('🔍 [AUTO-SELECT] Total sessions found:', updatedSessions.length)
        const newSession = updatedSessions.find((s: any) => s[0] === result.detection_id);
        if (newSession) {
          setSelectedDetection(newSession);
          console.log('✅ [AUTO-SELECT] Selected newly uploaded session:', result.detection_id);
          console.log('✅ [AUTO-SELECT] Session data:', newSession);
        } else {
          console.warn('⚠️  [AUTO-SELECT] Session not found for detection_id:', result.detection_id);
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
  const isImageWithSrt = !!selectedSrt && !!selectedMedia && !!selectedMedia.name.toLowerCase().match(/\.(jpg|jpeg|png|bmp|gif)$/i)
  
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

      const canUpload =
        !!hasAnyFile &&
        status !== 'uploading' &&
        !(selectedSrt && !selectedMedia) &&
        !isImageWithSrt &&
        fileNamesMatch

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
        <HomeBranding />

        <View className="justify-center items-center bg-white w-full max-w-md h-auto py-6 px-4 rounded-2xl shadow-custom border-2 border-gray-200">
        <Text className="text-2xl font-bold text-gray-800 mb-2 text-center">
          Upload Media & Subtitles
        </Text>
        <Text className="text-gray-600 text-center px-4 mb-4">
          Pick a video/photo and upload SRT subtitle file.
        </Text>
        <HomeUploadPickers
          status={status}
          isBusy={isBusy}
          selectedMedia={selectedMedia}
          selectedSrt={selectedSrt}
          onPickMedia={pickMedia}
          onPickSrt={pickSrt}
          onRemoveMedia={() => {
            setSelectedMedia(null)
            setMessage('')
            setStatus(selectedSrt ? 'ready' : 'idle')
          }}
          onRemoveSrt={() => {
            setSelectedSrt(null)
            if (!selectedMedia) {
              setMessage('')
              setStatus('idle')
            }
          }}
        />

        <HomeUploadActions
          status={status}
          progress={progress}
          message={message}
          selectedMedia={selectedMedia}
          selectedSrt={selectedSrt}
          hasAnyFile={!!hasAnyFile}
          fileNamesMatch={fileNamesMatch}
          canUpload={canUpload}
          isBusy={isBusy}
          onUpload={mockUpload}
          onReset={reset}
        />
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}

export default Homescreen

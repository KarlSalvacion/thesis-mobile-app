import * as FileSystem from 'expo-file-system/legacy'
import { Video } from 'react-native-compressor'
import { API_BASE } from '../config'
import { saveActiveJob, clearActiveJob } from '../utils/jobRecovery'
import { SelectedFile } from '../components/home/types'

type ProgressCallback = (message: string) => void

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
  try {
    if (uri.startsWith('file://') || uri.startsWith('content://')) return uri
    const dest = `${FileSystem.cacheDirectory}${fallbackName}`
    await FileSystem.copyAsync({ from: uri, to: dest })
    return dest
  } catch {
    return uri
  }
}

export async function handleClientCompression(
  jobId: string,
  result: any,
  onProgress?: ProgressCallback
): Promise<any> {
  await saveActiveJob(jobId, 'compression')

  if (!result.needs_client_compression) {
    await clearActiveJob()
    return result
  }

  try {
    onProgress?.('Downloading video for compression...')
    const downloadUrl = `${API_BASE}/download-temp-video/${jobId}`
    const localPath = `${FileSystem.cacheDirectory}temp_${jobId}.mp4`

    const downloadResult = await FileSystem.downloadAsync(downloadUrl, localPath)

    if (downloadResult.status !== 200) {
      throw new Error(`Download failed: ${downloadResult.status}`)
    }

    const fileInfo = await FileSystem.getInfoAsync(localPath)
    const downloadedSize = fileInfo.exists ? (fileInfo as any).size : 0

    const fileSizeMB = downloadedSize / (1024 * 1024)
    let compressionSettings: any

    if (fileSizeMB > 200) {
      onProgress?.('Compressing large video (high quality)...')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,
        bitrate: 7000000,
        minimumFileSizeForCompress: 0,
      }
    } else if (fileSizeMB > 100) {
      onProgress?.('Compressing video (high quality)...')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,
        bitrate: 8000000,
        minimumFileSizeForCompress: 0,
      }
    } else {
      onProgress?.('Compressing video (maximum quality)...')
      compressionSettings = {
        compressionMethod: 'auto',
        maxSize: 1080,
        bitrate: 9000000,
        minimumFileSizeForCompress: 0,
      }
    }

    let compressedPath: string
    try {
      compressedPath = await Video.compress(localPath, compressionSettings, (progress) => {
        const percent = (progress * 100).toFixed(0)
        onProgress?.(`Compressing video... ${percent}%`)
      })
    } catch (compressError: any) {
      try {
        await FileSystem.deleteAsync(localPath, { idempotent: true })
      } catch {}
      throw new Error(`Compression failed: ${compressError.message || 'Unknown error'}`)
    }

    const compressedInfo = await FileSystem.getInfoAsync(compressedPath)
    const compressedSize = compressedInfo.exists ? (compressedInfo as any).size : 0

    if (downloadedSize > 0 && compressedSize > 0) {
      const compressionRatio = (downloadedSize / compressedSize).toFixed(1)
      console.log(`Compressed ${(compressedSize / (1024 * 1024)).toFixed(2)} MB (${compressionRatio}x smaller)`)
    }

    onProgress?.('Uploading compressed video...')

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

    try {
      await FileSystem.deleteAsync(localPath, { idempotent: true })
      await FileSystem.deleteAsync(compressedPath, { idempotent: true })
    } catch {}

    await new Promise((resolve) => setTimeout(resolve, 500))

    const statusResponse = await fetch(`${API_BASE}/job-status/${jobId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })

    if (statusResponse.ok) {
      const updatedStatus = await statusResponse.json()
      if (updatedStatus.result) {
        result = updatedStatus.result
      } else {
        result.cloud_annotated_url = uploadResponse.annotated_url
      }
    } else {
      result.cloud_annotated_url = uploadResponse.annotated_url
    }

    onProgress?.('Video compression complete!')
    await clearActiveJob()
    return result
  } catch (error: any) {
    onProgress?.(`Compression error: ${error.message || 'Unknown error'}`)
    return result
  }
}

export async function uploadFileToApi(uri: string, name: string, onProgress?: ProgressCallback) {
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

  if (result.status !== 200) {
    throw new Error(`Upload failed: ${result.status}`)
  }

  const uploadResult = JSON.parse(result.body)
  const jobId = uploadResult.job_id

  await saveActiveJob(jobId, 'processing')

  const isVideo = name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)
  const processingMessage = isVideo
    ? 'Processing video... This may take 3-10 minutes'
    : 'Processing image... This may take 1-3 minutes'
  onProgress?.(processingMessage)

  let pollCount = 0
  const maxPolls = 40

  while (pollCount < maxPolls) {
    await new Promise((resolve) => setTimeout(resolve, 30000))
    pollCount++

    const statusResponse = await fetch(`${API_BASE}/job-status/${jobId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })

    if (!statusResponse.ok) {
      throw new Error(`Status check failed: ${statusResponse.status}`)
    }

    const status = await statusResponse.json()

    if (status.progress) {
      onProgress?.(status.progress)
    }

    if (status.status === 'completed') {
      let finalResult = status.result
      if (status.result.needs_client_compression) {
        finalResult = await handleClientCompression(jobId, status.result, onProgress)
      } else {
        await clearActiveJob()
      }
      return finalResult
    }

    if (status.status === 'failed') {
      await clearActiveJob()
      throw new Error(`Processing failed: ${status.error}`)
    }

    const minutesElapsed = (pollCount * 30) / 60
    onProgress?.(`Processing... ${minutesElapsed.toFixed(1)} min elapsed`)
  }

  throw new Error('Processing timeout - took longer than 20 minutes')
}

export async function uploadCombinedFiles(
  mediaFile: SelectedFile,
  srtFile: SelectedFile,
  onProgress?: ProgressCallback
) {
  const formData = new FormData()

  const mediaUri = await ensureLocalFilePath(mediaFile.uri, mediaFile.name)
  const mediaType = guessMimeType(mediaFile.name)

  formData.append('media_file', {
    uri: mediaUri,
    name: mediaFile.name,
    type: mediaType,
  } as any)

  const srtUri = await ensureLocalFilePath(srtFile.uri, srtFile.name)
  formData.append('srt_file', {
    uri: srtUri,
    name: srtFile.name,
    type: 'text/plain',
  } as any)

  const uploadResponse = await fetch(`${API_BASE}/upload-combined/`, {
    method: 'POST',
    body: formData,
    headers: {
      'Content-Type': 'multipart/form-data',
      Accept: 'application/json',
    },
  })

  if (!uploadResponse.ok) {
    const errorText = await uploadResponse.text()
    throw new Error(`Upload failed: ${uploadResponse.status} - ${errorText}`)
  }

  const uploadResult = await uploadResponse.json()
  const jobId = uploadResult.job_id

  await saveActiveJob(jobId, 'processing')

  const isVideo = mediaFile.name.toLowerCase().match(/\.(mp4|mov|avi|mkv)$/i)
  const processingMessage = isVideo
    ? 'Processing video... This may take 3-10 minutes'
    : 'Processing image... This may take 1-3 minutes'
  onProgress?.(processingMessage)

  let pollCount = 0
  const maxPolls = 40

  while (pollCount < maxPolls) {
    await new Promise((resolve) => setTimeout(resolve, 30000))
    pollCount++

    const statusResponse = await fetch(`${API_BASE}/job-status/${jobId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })

    if (!statusResponse.ok) {
      throw new Error(`Status check failed: ${statusResponse.status}`)
    }

    const status = await statusResponse.json()

    if (status.progress) {
      onProgress?.(status.progress)
    }

    if (status.status === 'completed') {
      let finalResult = status.result
      if (status.result.needs_client_compression) {
        finalResult = await handleClientCompression(jobId, status.result, onProgress)
      }
      return finalResult
    }

    if (status.status === 'failed') {
      throw new Error(`Processing failed: ${status.error}`)
    }

    const minutesElapsed = (pollCount * 30) / 60
    onProgress?.(`Processing... ${minutesElapsed.toFixed(1)} min elapsed`)
  }

  throw new Error('Processing timeout - took longer than 20 minutes')
}

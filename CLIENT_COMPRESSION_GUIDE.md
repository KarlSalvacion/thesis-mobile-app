# Client-Side Video Compression Implementation Guide

## Overview
This guide shows how to implement client-side video compression using react-native-compressor after backend inference and stitching.

## Workflow

```
1. User uploads video → Backend
2. Backend: Inference + Stitching (720p, mp4v codec) 
3. Backend: Returns job_id + temp_video_path
4. Mobile: Downloads temp video
5. Mobile: Compresses with react-native-compressor (H.264)
6. Mobile: Uploads compressed video → Backend
7. Backend: Uploads to Cloudinary
8. Done! ✅
```

## Benefits
- ✅ Offloads CPU/GPU work from backend
- ✅ Works on free hosting tiers (Render, etc.)
- ✅ Faster for users (parallel processing)
- ✅ Better compression (native H.264 encoder)

---

## Backend Changes (Already Done ✅)

### 1. Removed FFmpeg Compression
**File: `backend/video_utils.py`**
- Removed all FFmpeg H.264 compression code
- Now only stitches with OpenCV (mp4v codec)

### 2. Added New Endpoints
**File: `backend/main.py`**

```python
@app.get("/download-temp-video/{job_id}")
# Downloads temp annotated video for compression

@app.post("/upload-compressed-video/{job_id}")
# Receives compressed video from client
```

### 3. Modified Background Processing
- Stores `temp_video_path` in job data
- Returns `needs_client_compression: true` flag
- Doesn't cleanup temp video until client uploads compressed version

---

## Mobile App Changes (TODO)

### Add to Homescreen.tsx:

```typescript
import { Video } from 'react-native-compressor';
import * as FileSystem from 'expo-file-system';

// After polling completes and gets result:
async function handleVideoCompression(jobId: string, result: any) {
  if (!result.needs_client_compression) {
    // No compression needed (image or already compressed)
    return result;
  }
  
  try {
    setMessage('Downloading video for compression...');
    
    // Step 1: Download temp video from backend
    const downloadUrl = `${API_BASE}/download-temp-video/${jobId}`;
    const localPath = `${FileSystem.cacheDirectory}temp_${jobId}.mp4`;
    
    console.log(`📥 [COMPRESS] Downloading temp video from: ${downloadUrl}`);
    const downloadResult = await FileSystem.downloadAsync(downloadUrl, localPath);
    
    if (downloadResult.status !== 200) {
      throw new Error(`Download failed: ${downloadResult.status}`);
    }
    
    const downloadedSize = (await FileSystem.getInfoAsync(localPath)).size;
    console.log(`📥 [COMPRESS] Downloaded: ${(downloadedSize / (1024*1024)).toFixed(2)} MB`);
    
    // Step 2: Compress with react-native-compressor
    setMessage('Compressing video...');
    console.log('🗜️  [COMPRESS] Starting compression with react-native-compressor');
    
    const compressedPath = await Video.compress(
      localPath,
      {
        compressionMethod: 'auto', // 'auto' or 'manual'
        bitrate: 4000000, // 4 Mbps (good quality)
        maxSize: 1280, // Max width/height (already 720p)
        minimumFileSizeForCompress: 0, // Always compress
      },
      (progress) => {
        console.log(`🗜️  [COMPRESS] Progress: ${(progress * 100).toFixed(0)}%`);
        setMessage(`Compressing video... ${(progress * 100).toFixed(0)}%`);
      }
    );
    
    const compressedSize = (await FileSystem.getInfoAsync(compressedPath)).size;
    const compressionRatio = downloadedSize / compressedSize;
    console.log(`✅ [COMPRESS] Compressed: ${(compressedSize / (1024*1024)).toFixed(2)} MB (${compressionRatio.toFixed(1)}x smaller)`);
    
    // Step 3: Upload compressed video back to backend
    setMessage('Uploading compressed video...');
    console.log('📤 [COMPRESS] Uploading to backend');
    
    const uploadResult = await FileSystem.uploadAsync(
      `${API_BASE}/upload-compressed-video/${jobId}`,
      compressedPath,
      {
        httpMethod: 'POST',
        uploadType: FileSystem.FileSystemUploadType.MULTIPART,
        fieldName: 'compressed_video',
        mimeType: 'video/mp4',
      }
    );
    
    if (uploadResult.status !== 200) {
      throw new Error(`Upload failed: ${uploadResult.status}`);
    }
    
    const uploadResponse = JSON.parse(uploadResult.body);
    console.log('✅ [COMPRESS] Upload complete:', uploadResponse.annotated_url);
    
    // Step 4: Cleanup temp files
    try {
      await FileSystem.deleteAsync(localPath);
      await FileSystem.deleteAsync(compressedPath);
    } catch (e) {
      console.warn('Cleanup error:', e);
    }
    
    // Update result with annotated URL
    result.cloud_annotated_url = uploadResponse.annotated_url;
    setMessage('Processing complete!');
    
    return result;
    
  } catch (error) {
    console.error('❌ [COMPRESS] Error:', error);
    setMessage(`Compression error: ${error.message}`);
    // Return original result even if compression fails
    return result;
  }
}

// Modify uploadFileToApi function:
async function uploadFileToApi(uri: string, name: string, onProgress?: (message: string) => void) {
  // ... existing upload code ...
  
  // After polling loop completes:
  if (status.status === 'completed') {
    console.log('✅ [POLLING] Processing completed!');
    let result = status.result;
    
    // Handle client-side compression if needed
    if (result.needs_client_compression) {
      console.log('🗜️  [COMPRESS] Starting client-side compression workflow');
      result = await handleVideoCompression(jobId, result);
    }
    
    return result;
  }
  
  // ... rest of code ...
}

// Do the same for uploadCombinedFiles!
```

---

## Testing

1. **Upload a video** (62 seconds, 18MB input)
2. **Backend logs should show:**
   ```
   Stitched video size: 55.23 MB (720p, mp4v codec)
   ✅ Skipping backend compression - client will compress
   ⚠️  Waiting for client to compress and upload
   ```

3. **Mobile app logs should show:**
   ```
   📥 [COMPRESS] Downloaded: 55.23 MB
   🗜️  [COMPRESS] Starting compression
   🗜️  [COMPRESS] Progress: 50%
   ✅ [COMPRESS] Compressed: 18.45 MB (3.0x smaller)
   📤 [COMPRESS] Uploading to backend
   ✅ [COMPRESS] Upload complete
   ```

4. **Backend receives compressed video and uploads to Cloudinary**

---

## File Sizes Expected

| Stage | Size | Notes |
|-------|------|-------|
| Original input | 18 MB | User's video |
| Backend stitch (720p, mp4v) | ~55 MB | Uncompressed |
| Client compressed (H.264) | ~20-25 MB | Good quality |
| Cloudinary upload | ~20-25 MB | Final |

---

## Advantages Over Backend Compression

1. **CPU/Memory**: Offloaded to user's device
2. **Hosting**: Works on free tiers (no heavy processing)
3. **Speed**: User sees progress, feels faster
4. **Quality**: Native H.264 encoder often better quality
5. **Parallel**: User can compress while backend prepares next task

---

## Error Handling

- If download fails → Show error, return original result
- If compression fails → Show error, return original result  
- If upload fails → Retry 3 times, then show error

The app should always complete gracefully even if compression fails!

---

## Next Steps

1. Implement `handleVideoCompression()` function
2. Integrate into both `uploadFileToApi` and `uploadCombinedFiles`
3. Test with various video sizes
4. Add progress indicators in UI
5. Handle edge cases (network errors, etc.)


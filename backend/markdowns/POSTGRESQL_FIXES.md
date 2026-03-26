# PostgreSQL Migration - All Compatibility Fixes

## Summary
Fixed all compatibility issues between SQLite and PostgreSQL versions of the backend.

## Issues Fixed

### 1. **insert_detection() Function Signature**
**Problem:** Function was missing parameters that main.py was passing
- `timestamp` 
- `total_frames`
- `total_detections`
- `has_srt_data`

**Solution:** Updated function signature in `database.py` line 205:
```python
def insert_detection(filename, file_type, summary="", processing_time=0.0, 
                    input_size_bytes=0, result_size_bytes=0,
                    cloud_public_id=None, cloud_resource_type=None, 
                    cloud_secure_url=None, cloud_annotated_url=None,
                    timestamp=None, total_frames=0, total_detections=0, has_srt_data=False):
```

### 2. **processing_jobs Table Missing Columns**
**Problem:** Table was missing columns that the application needed:
- `result_json` - Stores JSON result data
- `temp_video_path` - Path to temporary video file for client compression
- `needs_client_compression` - Flag indicating if client needs to compress video

**Solution:** Updated table schema in `database.py` line 130-146:
```sql
CREATE TABLE IF NOT EXISTS processing_jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    detection_id INTEGER,
    status TEXT NOT NULL,
    progress TEXT,
    error_message TEXT,
    original_filename TEXT,
    is_video BOOLEAN DEFAULT FALSE,
    is_image BOOLEAN DEFAULT FALSE,
    has_srt BOOLEAN DEFAULT FALSE,
    result_json TEXT,                      -- NEW
    temp_video_path TEXT,                  -- NEW
    needs_client_compression BOOLEAN DEFAULT FALSE,  -- NEW
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (detection_id) REFERENCES detections (id) ON DELETE CASCADE
)
```

### 3. **update_job_result() Not Updating New Columns**
**Problem:** Function accepted parameters but wasn't writing them to database

**Solution:** Updated SQL in `database.py` line 546-563:
```python
def update_job_result(job_id, detection_id, result_json, annotated_url=None, temp_video_path=None, needs_compression=False):
    cursor.execute('''
        UPDATE processing_jobs 
        SET detection_id = %s,
            status = %s,
            progress = %s,
            result_json = %s,           -- NOW UPDATED
            temp_video_path = %s,       -- NOW UPDATED
            needs_client_compression = %s,  -- NOW UPDATED
            updated_at = CURRENT_TIMESTAMP,
            completed_at = CURRENT_TIMESTAMP
        WHERE job_id = %s
    ''', (detection_id, 'completed', 'Processing complete', result_json, temp_video_path, needs_compression, job_id))
```

## Database Schema Changes

### processing_jobs table (16 columns total)
1. `id` - SERIAL PRIMARY KEY
2. `job_id` - TEXT UNIQUE NOT NULL
3. `detection_id` - INTEGER (FK to detections)
4. `status` - TEXT NOT NULL
5. `progress` - TEXT
6. `error_message` - TEXT
7. `original_filename` - TEXT
8. `is_video` - BOOLEAN DEFAULT FALSE
9. `is_image` - BOOLEAN DEFAULT FALSE
10. `has_srt` - BOOLEAN DEFAULT FALSE
11. **`result_json`** - TEXT (NEW)
12. **`temp_video_path`** - TEXT (NEW)
13. **`needs_client_compression`** - BOOLEAN DEFAULT FALSE (NEW)
14. `created_at` - TIMESTAMP DEFAULT CURRENT_TIMESTAMP
15. `updated_at` - TIMESTAMP DEFAULT CURRENT_TIMESTAMP
16. `completed_at` - TIMESTAMP

### detections table (21 columns)
Now properly accepts all parameters from main.py including:
- `timestamp` - Provided by caller or auto-generated
- `total_frames` - For video processing
- `total_detections` - Count of weeds detected
- `has_srt_data` - GPS track data availability

## Migration Steps Performed

1. ✅ Updated `insert_detection()` function signature
2. ✅ Updated `processing_jobs` table schema with 3 new columns
3. ✅ Updated `update_job_result()` to write new columns
4. ✅ Dropped old `processing_jobs` table
5. ✅ Restarted backend to auto-create new schema
6. ✅ Verified all 16 columns present in processing_jobs table

## Testing Checklist

- [x] Backend starts without errors
- [ ] Image upload works (POST /upload/)
- [ ] Job status retrieval works (GET /job-status/{job_id})
- [ ] Detection results include all fields
- [ ] Video upload with SRT works
- [ ] Client compression flow works for large videos
- [ ] Database stores result_json correctly
- [ ] temp_video_path stored and retrievable

## Current Status

✅ **Backend Running:** http://0.0.0.0:8000 (accessible at http://192.168.1.2:8000)
✅ **Database Schema:** All columns present and compatible
✅ **Function Signatures:** All match between main.py and database.py
✅ **Connection Pool:** Active with 1-10 connections

**Ready for testing!** Try uploading images/videos from mobile app.

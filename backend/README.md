# Enhanced Weed Detection Backend System

A comprehensive backend system for weed detection using computer vision and GPS metadata from drone footage.

## 🚀 Features

- **Multi-format Support**: Process both images and videos
- **GPS Integration**: Parse SRT subtitle files for geolocation data
- **Detailed Detection Storage**: Store individual weed detections with coordinates and confidence scores
- **Metadata Tracking**: Camera settings, timestamps, and environmental data
- **RESTful API**: Complete API for frontend integration
- **SQLite Database**: Efficient local storage with proper indexing

## 🏗️ System Architecture

### Database Schema

The system uses three main tables:

1. **`detections`** - Main detection sessions
   - Session metadata (filename, timestamp, file type)
   - Processing statistics (frames, detections, processing time)
   - Summary information

2. **`frame_metadata`** - GPS and camera data from SRT files
   - GPS coordinates (latitude, longitude, altitude)
   - Camera settings (ISO, shutter speed, f-number, focal length)
   - Timestamps and frame numbers

3. **`detection_details`** - Individual weed detections
   - Weed classification and confidence scores
   - Bounding box coordinates (both absolute and normalized)
   - Frame association and timestamps

### File Processing Flow

```
Video/Image Upload → Weed Detection → Store Results → Upload SRT → Link Metadata
       ↓                    ↓              ↓            ↓           ↓
   File Storage      AI Inference    Session Data   GPS Data   Complete Dataset
```

## 📁 Project Structure

```
backend/
├── app/
│   └── main.py            # FastAPI application entrypoint
├── config/
│   └── settings.py        # Environment and runtime settings
├── db/
│   ├── database.py        # PostgreSQL database operations and schema
│   └── database_sqlite_backup.py
├── inference/
│   └── engine.py          # AI model integration (Roboflow)
├── utils/
│   ├── cloudinary_utils.py
│   ├── srt_parser.py
│   ├── video_utils.py
│   └── monitor_memory.py
├── main.py                # Compatibility entrypoint (imports app.main)
├── requirements.txt       # Python dependencies
└── uploads/               # Optional local file storage directory
```

## 🛠️ Installation & Setup

### Prerequisites

- Python 3.8+
- Roboflow API key
- FastAPI and dependencies

### Installation

1. **Clone and navigate to the project:**
   ```bash
   cd backend
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your Roboflow API key:**
   Edit `config/settings.py` and replace the API key with your own.

4. **Initialize the database:**
   ```bash
   python -m backend.db.database
   ```

5. **Run the system:**
   ```bash
   python -m uvicorn backend.app.main:app --reload
   ```

The API will be available at `http://localhost:8000`

## 🔌 API Endpoints

### File Upload & Processing

#### `POST /upload/`
Upload and process video/image files for weed detection.

**Request:**
- `file`: Video or image file (MP4, AVI, JPG, PNG, etc.)

**Response:**
```json
{
  "filename": "DJI_20250807151240_0329_D.MP4",
  "detection_id": 1,
  "detections": [...],
  "file_type": "video",
  "summary": "Detected 12 objects across 150 frames",
  "total_frames": 150,
  "total_detections": 12,
  "processing_time": 8.2
}
```

#### `POST /upload-srt/`
Upload SRT subtitle file to associate GPS/camera metadata with a detection session.

**Request:**
- `detection_id`: Integer ID of the detection session
- `srt_file`: SRT subtitle file

**Response:**
```json
{
  "message": "SRT file uploaded successfully",
  "detection_id": 1,
  "frames_processed": 150,
  "first_frame": {...},
  "last_frame": {...}
}
```

### Data Retrieval

#### `GET /detections/`
Get all detection sessions.

#### `GET /detection/{detection_id}`
Get complete details of a specific detection session including:
- Session metadata
- Frame metadata (GPS, camera settings)
- Individual weed detections

#### `GET /statistics/`
Get overall system statistics:
- Total sessions and detections
- Weed class distribution
- File type distribution

#### `GET /detections/class/{weed_class}`
Get all detections of a specific weed class across all sessions.

## 📊 SRT File Format

The system parses DJI drone SRT subtitle files containing:

- **Frame information**: Frame count and timing
- **GPS coordinates**: Latitude, longitude, altitude
- **Camera settings**: ISO, shutter speed, f-number, focal length
- **Timestamps**: Precise frame timing

**Example SRT format:**
```
1
00:00:00,000 --> 00:00:00,033
<font size="28">FrameCnt: 1, DiffTime: 33ms
2025-08-07 15:12:40.929
[iso: 100] [shutter: 1/2500.0] [fnum: 1.7] [ev: -1.0] [color_md: default] [focal_len: 24.00] [latitude: 13.821601] [longitude: 121.231932] [rel_alt: 3.000 abs_alt: 187.202] [ct: 5566] </font>
```

## 🧪 Testing

Run the comprehensive test suite:

```bash
python test_enhanced_system.py
```

This will test:
- Database structure and operations
- SRT file parsing
- Complete workflow integration
- Data insertion and retrieval

## 🔍 Usage Examples

### 1. Upload Video for Detection

```bash
curl -X POST "http://localhost:8000/upload/" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@DJI_20250807151240_0329_D.MP4"
```

### 2. Upload SRT File

```bash
curl -X POST "http://localhost:8000/upload-srt/" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "detection_id=1" \
     -F "srt_file=@DJI_20250807151240_0329_D.srt"
```

### 3. Get Detection Details

```bash
curl -X GET "http://localhost:8000/detection/1"
```

### 4. Get Statistics

```bash
curl -X GET "http://localhost:8000/statistics/"
```

## 🌱 Weed Detection Classes

The system supports various weed classifications including:
- **Amaranthus** (Pigweed)
- **Echinochloa** (Barnyard grass)
- **Other agricultural weeds**

## 🗺️ Heatmap Generation

With GPS coordinates from SRT files, you can:
- Generate field heatmaps showing weed density
- Track weed distribution patterns
- Analyze field coverage and detection efficiency
- Export data for GIS applications

## 🔧 Configuration

### Database
- **File**: `weed_detection.db`
- **Type**: SQLite3
- **Location**: Project root directory

### Model Settings
- **Confidence threshold**: 40% (configurable in `inference.py`)
- **Overlap threshold**: 30% (configurable in `inference.py`)
- **Video FPS**: 5 frames per second (configurable)

## 📈 Performance

- **Processing time**: Typically 2-10 seconds per video depending on length
- **Storage efficiency**: Optimized database schema with proper indexing
- **Scalability**: SQLite with connection pooling for concurrent requests

## 🚨 Error Handling

The system includes comprehensive error handling for:
- Invalid file formats
- Corrupted SRT files
- Database connection issues
- Model inference failures
- Missing dependencies

## 🔮 Future Enhancements

- **Real-time processing**: Stream video processing
- **Batch operations**: Process multiple files simultaneously
- **Export formats**: CSV, GeoJSON, KML export
- **Cloud integration**: AWS S3, Google Cloud Storage
- **Advanced analytics**: Machine learning insights and trends

## 📞 Support

For issues and questions:
1. Check the test output for errors
2. Verify database initialization
3. Ensure all dependencies are installed
4. Check Roboflow API key validity

## 📄 License

This project is part of a thesis research project on automated weed detection using drone imagery and computer vision.

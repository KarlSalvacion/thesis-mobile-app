# Weed Detection Mobile App

A comprehensive mobile application for weed detection using AI, with GPS tracking and real-time visualization.

## 🏗️ Project Structure

This project consists of two main components:

- **Mobile App** (React Native/Expo) - Frontend mobile application
- **Backend API** (FastAPI/Python) - AI processing and data storage

```
thesis-mobile-app/
├── src/                    # React Native frontend
│   ├── screens/           # App screens
│   ├── components/        # Reusable components
│   ├── navigation/        # Navigation setup
│   └── assets/            # Images, fonts, etc.
├── backend/               # Python FastAPI backend
│   ├── main.py           # API endpoints
│   ├── inference.py      # AI model
│   └── database.py       # Data storage
├── setup-backend.bat     # Backend setup script
├── run-backend.bat       # Backend run script
└── package.json          # Node.js dependencies
```

## 🚀 Quick Start

### Prerequisites

- **Node.js** (v18 or higher)
- **Python** (v3.8 or higher)
- **FFmpeg** (for video processing)
- **Expo Go** app on your mobile device

### 1. Setup Frontend

```bash
# Install Node.js dependencies
npm install

# Start Expo development server
npm start
```

### 2. Setup Backend

**Windows** (Recommended):
```bash
# Run setup script (first time only)
setup-backend.bat

# Start backend server
run-backend.bat
```

**Manual Setup** (All platforms):
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# OR
source .venv/bin/activate      # Linux/Mac

# Install dependencies
pip install -r backend/requirements.txt

# Run server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

See [BACKEND_SETUP.md](BACKEND_SETUP.md) for detailed backend instructions.

### 3. Run Mobile App

1. Make sure backend is running on `http://localhost:8000`
2. Start Expo: `npm start`
3. Scan QR code with Expo Go app
4. Update backend URL in `src/config.ts` if needed

## 📱 Features

- 🎯 **AI Weed Detection** - Identify weeds in photos and videos
- 📍 **GPS Tracking** - SRT file support for drone footage
- 🗺️ **Map Visualization** - View detections on interactive maps
- 📊 **Statistics** - Track detection history and analytics
- ☁️ **Cloud Storage** - Automatic backup to Cloudinary
- 🎬 **Video Processing** - Frame-by-frame analysis with annotations

## 🔧 Configuration

### Backend Configuration

Edit `backend/config.py` or create `.env`:

```env
ROBOFLOW_API_KEY=your_api_key
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_secret
```

### Frontend Configuration

Edit `src/config.ts`:

```typescript
export const API_BASE_URL = 'http://192.168.1.100:8000'; // Your backend IP
```

## 📖 API Documentation

Once the backend is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🧪 Development

### Frontend
```bash
npm start          # Start Expo
npm run android    # Run on Android
npm run ios        # Run on iOS
```

### Backend
```bash
# With auto-reload
python -m uvicorn backend.main:app --reload

# Production mode
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## 📦 Dependencies

### Frontend
- React Native / Expo
- React Navigation
- NativeWind (Tailwind CSS)
- Expo Document Picker
- React Native Maps

### Backend
- FastAPI - Web framework
- Roboflow - AI model inference
- Cloudinary - Cloud storage
- Pillow - Image processing
- OpenCV - Video processing

## 🐛 Troubleshooting

### Backend Issues

**"Python not found"**
- Install Python from https://www.python.org/
- Check "Add Python to PATH" during installation

**"Module not found"**
- Activate virtual environment first
- Run `pip install -r backend/requirements.txt`

**"FFmpeg not found"**
- Download from https://ffmpeg.org/
- Add to system PATH

### Frontend Issues

**"Cannot connect to backend"**
- Make sure backend is running
- Update `API_BASE_URL` in `src/config.ts` with your computer's IP
- Check firewall settings

**"Expo Go crashes"**
- Clear cache: `npm start --clear`
- Restart Expo Go app
- Check for compatible versions

## 📄 Additional Documentation

- [Backend Setup Guide](BACKEND_SETUP.md) - Detailed backend setup
- [Backend API Documentation](backend/README.md) - API reference
- [Contributing Guide](CONTRIBUTING.md) - How to contribute (if you create one)

## 👥 Team

Developed by Karl Salvacion and Albert Lucido

## 📝 License

[Your License Here]

## 🙏 Acknowledgments

- Roboflow for AI model hosting
- Cloudinary for media storage
- Expo team for mobile development platform

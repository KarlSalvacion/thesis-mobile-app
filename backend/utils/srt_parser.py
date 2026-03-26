import re
from datetime import datetime
from typing import List, Dict, Optional

def parse_srt_file(srt_content: str) -> List[Dict]:
    """
    Parse SRT subtitle file content and extract frame metadata.
    
    Args:
        srt_content: Raw content of the SRT file
        
    Returns:
        List of dictionaries containing frame metadata
    """
    frames = []
    lines = srt_content.strip().split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
            
        # Check if this line is a frame number
        if line.isdigit():
            try:
                frame_number = int(line)
                
                # Next line should contain timestamp
                if i + 1 < len(lines):
                    timestamp_line = lines[i + 1].strip()
                    if '-->' in timestamp_line:
                        # Extract start time (we'll use this as frame timestamp)
                        start_time = timestamp_line.split('-->')[0].strip()
                        
                        # Next line should contain font tag with frame info
                        if i + 2 < len(lines):
                            font_line = lines[i + 2].strip()
                            
                            # Next line should contain date/time
                            if i + 3 < len(lines):
                                date_time_line = lines[i + 3].strip()
                                
                                # Next line should contain metadata
                                if i + 4 < len(lines):
                                    metadata_line = lines[i + 4].strip()
                                    
                                    # Parse metadata
                                    frame_data = parse_frame_metadata(frame_number, start_time, metadata_line)
                                    if frame_data:
                                        frames.append(frame_data)
                                        
                i += 5  # Skip to next frame (frame number, timestamp, font, date/time, metadata)
            except ValueError:
                i += 1
        else:
            i += 1
    
    return frames

def parse_frame_metadata(frame_number: int, timestamp: str, metadata_line: str) -> Optional[Dict]:
    """
    Parse individual frame metadata line and extract relevant information.
    
    Args:
        frame_number: Frame number from SRT
        timestamp: Timestamp string (HH:MM:SS,mmm)
        metadata_line: Line containing metadata in format like:
            [iso: 100] [shutter: 1/2500.0] [fnum: 1.7] [ev: -1.0] [color_md: default] [focal_len: 24.00] [latitude: 13.821601] [longitude: 121.231932] [rel_alt: 3.000 abs_alt: 187.202] [ct: 5566]
    
    Returns:
        Dictionary containing parsed metadata or None if parsing fails
    """
    try:
        # Parse camera and GPS parameters
        metadata = {}
        
        # ISO
        iso_match = re.search(r'\[iso: (\d+)\]', metadata_line)
        if iso_match:
            metadata['iso'] = int(iso_match.group(1))
            
        # Shutter speed
        shutter_match = re.search(r'\[shutter: ([^\]]+)\]', metadata_line)
        if shutter_match:
            metadata['shutter_speed'] = shutter_match.group(1)
            
        # F-number
        fnum_match = re.search(r'\[fnum: ([\d.]+)\]', metadata_line)
        if fnum_match:
            metadata['f_number'] = float(fnum_match.group(1))
            
        # Exposure value
        ev_match = re.search(r'\[ev: ([-\d.]+)\]', metadata_line)
        if ev_match:
            metadata['exposure_value'] = float(ev_match.group(1))
            
        # Focal length
        focal_match = re.search(r'\[focal_len: ([\d.]+)\]', metadata_line)
        if focal_match:
            metadata['focal_length'] = float(focal_match.group(1))
            
        # Color temperature
        ct_match = re.search(r'\[ct: (\d+)\]', metadata_line)
        if ct_match:
            metadata['color_temperature'] = int(ct_match.group(1))
            
        # GPS coordinates
        lat_match = re.search(r'\[latitude: ([\d.-]+)\]', metadata_line)
        if lat_match:
            metadata['latitude'] = float(lat_match.group(1))
            
        lon_match = re.search(r'\[longitude: ([\d.-]+)\]', metadata_line)
        if lon_match:
            metadata['longitude'] = float(lon_match.group(1))
            
        # Altitude
        rel_alt_match = re.search(r'\[rel_alt: ([\d.-]+)', metadata_line)
        if rel_alt_match:
            metadata['relative_altitude'] = float(rel_alt_match.group(1))
            
        abs_alt_match = re.search(r'abs_alt: ([\d.-]+)\]', metadata_line)
        if abs_alt_match:
            metadata['altitude'] = float(abs_alt_match.group(1))
        
        # Use the timestamp from the SRT file
        iso_timestamp = timestamp
        
        return {
            'frame_number': frame_number,
            'timestamp': iso_timestamp,
            'latitude': metadata.get('latitude'),
            'longitude': metadata.get('longitude'),
            'altitude': metadata.get('altitude'),
            'relative_altitude': metadata.get('relative_altitude'),
            'iso': metadata.get('iso'),
            'shutter_speed': metadata.get('shutter_speed'),
            'f_number': metadata.get('f_number'),
            'exposure_value': metadata.get('exposure_value'),
            'focal_length': metadata.get('focal_length'),
            'color_temperature': metadata.get('color_temperature')
        }
        
    except Exception as e:
        print(f"Error parsing frame {frame_number}: {e}")
        return None

def validate_srt_file(srt_content: str) -> bool:
    """
    Basic validation of SRT file format.
    
    Args:
        srt_content: Raw content of the SRT file
        
    Returns:
        True if file appears to be valid SRT format
    """
    lines = srt_content.strip().split('\n')
    
    # Check if we have at least some expected patterns
    has_frame_numbers = any(line.strip().isdigit() for line in lines)
    has_timestamps = any('-->' in line for line in lines)
    has_metadata = any('[' in line and ']' in line for line in lines)
    
    return has_frame_numbers and has_timestamps and has_metadata

if __name__ == "__main__":
    # Test with sample SRT content
    sample_srt = """1
00:00:00,000 --> 00:00:00,033
<font size="28">FrameCnt: 1, DiffTime: 33ms
2025-08-07 15:12:40.929
[iso: 100] [shutter: 1/2500.0] [fnum: 1.7] [ev: -1.0] [color_md: default] [focal_len: 24.00] [latitude: 13.821601] [longitude: 121.231932] [rel_alt: 3.000 abs_alt: 187.202] [ct: 5566] </font>

2
00:00:00,033 --> 00:00:00,066
<font size="28">FrameCnt: 2, DiffTime: 33ms
2025-08-07 15:12:40.964
[iso: 100] [shutter: 1/2500.0] [fnum: 1.7] [ev: -1.0] [color_md: default] [focal_len: 24.00] [latitude: 13.821601] [longitude: 121.231932] [rel_alt: 3.000 abs_alt: 187.202] [ct: 5566] </font>"""
    
    print("Testing SRT parser...")
    frames = parse_srt_file(sample_srt)
    print(f"Parsed {len(frames)} frames:")
    for frame in frames:
        print(f"  Frame {frame['frame_number']}: {frame['timestamp']} at {frame['latitude']}, {frame['longitude']}")

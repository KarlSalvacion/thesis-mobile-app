"""
Comprehensive Backend API Test
Tests ALL endpoints to ensure they work with PostgreSQL
"""
import requests
import json

API_BASE = "http://localhost:8000"

def test_endpoint(name, url, method="GET", data=None):
    """Test an endpoint and print results"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    try:
        if method == "GET":
            response = requests.get(url, timeout=5)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=5)
        elif method == "DELETE":
            response = requests.delete(url, timeout=5)
        
        print(f"Status: {response.status_code}")
        
        if response.ok:
            try:
                result = response.json()
                print(f"✅ SUCCESS")
                
                # Check specific response formats
                if 'detections' in result:
                    print(f"   Detections count: {len(result['detections'])}")
                    if result['detections']:
                        first = result['detections'][0]
                        print(f"   First detection type: {type(first)}")
                        if isinstance(first, list):
                            print(f"   First detection length: {len(first)}")
                            print(f"   First few fields: id={first[0]}, filename={first[1]}, file_type={first[3]}")
                
                if 'detection' in result:
                    det = result['detection']
                    print(f"   Detection type: {type(det)}")
                    if isinstance(det, list):
                        print(f"   Detection length: {len(det)}")
                        print(f"   Fields: id={det[0]}, filename={det[1]}, has_srt={det[10]}")
                
                if 'detection_details' in result:
                    details = result['detection_details']
                    print(f"   Detection details count: {len(details)}")
                    if details:
                        print(f"   First detail type: {type(details[0])}")
                        if isinstance(details[0], list):
                            print(f"   Detail structure: OK (tuple/array)")
                
                if 'srt_track' in result:
                    srt = result['srt_track']
                    if srt:
                        print(f"   SRT track type: {type(srt)}")
                        if isinstance(srt, list):
                            print(f"   SRT structure: OK (tuple/array)")
                
                if 'unique_weed_count' in result:
                    print(f"   Unique weeds: {result['unique_weed_count']}")
                    print(f"   Total detections: {result.get('total_detections', 'N/A')}")
                
                if 'points' in result:
                    print(f"   Points count: {len(result['points'])}")
                
            except Exception as e:
                print(f"   Response: {response.text[:200]}")
        else:
            print(f"❌ FAILED")
            print(f"   Error: {response.text[:200]}")
    
    except Exception as e:
        print(f"❌ ERROR: {e}")

# Test all endpoints
print("=" * 60)
print("COMPREHENSIVE BACKEND API TEST")
print("=" * 60)

# 1. List all detections
test_endpoint("GET /detections/", f"{API_BASE}/detections/")

# 2. Get specific detection (assuming ID 1 exists)
test_endpoint("GET /detection/1", f"{API_BASE}/detection/1")

# 3. Get detections with SRT
test_endpoint("GET /detections/with-srt/", f"{API_BASE}/detections/with-srt/")

# 4. Get specific detection (ID 2)
test_endpoint("GET /detection/2", f"{API_BASE}/detection/2")

# 5. Get unique weeds for detection 2
test_endpoint("GET /detection/2/unique-weeds", f"{API_BASE}/detection/2/unique-weeds?iou_threshold=0.5&frame_gap=20")

# 6. Get GPS polyline for detection with SRT (if exists)
test_endpoint("GET /detection/2/gmap-polyline", f"{API_BASE}/detection/2/gmap-polyline")

# 7. Get unique weeds heatmap
test_endpoint("GET /detection/2/unique-weeds-heatmap", 
              f"{API_BASE}/detection/2/unique-weeds-heatmap?grid_size_m=2.0&iou_threshold=0.5&frame_gap=20")

# 8. Get statistics
test_endpoint("GET /statistics/", f"{API_BASE}/statistics/")

# 9. Health check
test_endpoint("GET /health", f"{API_BASE}/health")

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
print("\nKey Checks:")
print("- All detections should be TUPLE/ARRAY format (not dict)")
print("- Detection details should be TUPLE/ARRAY format")
print("- SRT tracks should be TUPLE/ARRAY format")
print("- All endpoints should return 200 OK (or 404 if data doesn't exist)")

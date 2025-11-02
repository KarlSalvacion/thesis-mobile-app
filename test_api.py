import requests
import json

# Test /detections/ endpoint
response = requests.get("http://localhost:8000/detections/")
data = response.json()

print("=== /detections/ Response ===")
print(f"Status Code: {response.status_code}")
print(f"Number of detections: {len(data['detections'])}")

if data['detections']:
    first_detection = data['detections'][0]
    print(f"\nFirst detection type: {type(first_detection)}")
    print(f"First detection length: {len(first_detection) if isinstance(first_detection, list) else 'N/A'}")
    print(f"\nFirst detection content:")
    print(json.dumps(first_detection, indent=2))
    
    # Test if we can access by index (tuple/array access)
    if isinstance(first_detection, list):
        print(f"\n✅ SUCCESS: Response is a list/tuple!")
        print(f"  detection[0] (id): {first_detection[0]}")
        print(f"  detection[1] (filename): {first_detection[1]}")
        print(f"  detection[3] (file_type): {first_detection[3]}")
        print(f"  detection[10] (has_srt_data): {first_detection[10]}")
        print(f"  detection[14] (cloud_annotated_url): {first_detection[14]}")
    else:
        print(f"\n❌ FAIL: Response is a dict, not a list!")

# Test /detection/{id} endpoint
print("\n\n=== /detection/4 Response ===")
response2 = requests.get("http://localhost:8000/detection/4")
data2 = response2.json()
print(f"Status Code: {response2.status_code}")
print(f"Response keys: {data2.keys()}")

if 'detection' in data2:
    detection = data2['detection']
    print(f"\nDetection type: {type(detection)}")
    print(f"Detection length: {len(detection) if isinstance(detection, list) else 'N/A'}")
    print(f"\nDetection content:")
    print(json.dumps(detection, indent=2))
    
    if isinstance(detection, list):
        print(f"\n✅ SUCCESS: Single detection response is a list/tuple!")
        print(f"  detection[0] (id): {detection[0]}")
        print(f"  detection[1] (filename): {detection[1]}")
    else:
        print(f"\n❌ FAIL: Single detection response is a dict!")

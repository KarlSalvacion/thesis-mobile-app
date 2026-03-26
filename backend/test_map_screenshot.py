"""Test map screenshot generation for PDF export"""
import folium
from folium.plugins import HeatMap
import tempfile
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import platform

# Sample heatmap data
points = [
    {'lat': 14.5995, 'lng': 120.9842, 'weight': 3},
    {'lat': 14.5996, 'lng': 120.9843, 'weight': 2},
    {'lat': 14.5997, 'lng': 120.9844, 'weight': 4},
    {'lat': 14.5998, 'lng': 120.9845, 'weight': 1},
]

# Calculate center
avg_lat = sum(p['lat'] for p in points) / len(points)
avg_lng = sum(p['lng'] for p in points) / len(points)

# Create map
m = folium.Map(
    location=[avg_lat, avg_lng],
    zoom_start=17,
    max_zoom=20
)

# Add Google Satellite tiles
folium.TileLayer(
    tiles='https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    attr='Map data ©2025 Google',
    name='Google Satellite',
    max_zoom=20,
    subdomains=['mt0', 'mt1', 'mt2', 'mt3']
).add_to(m)

# Add heatmap
heat_data = [[p['lat'], p['lng'], p['weight']] for p in points]
HeatMap(
    heat_data,
    radius=6,
    blur=6,
    max_zoom=18,
    max=4,
    gradient={
        0.0: 'green',
        0.3: 'lime',
        0.5: 'yellow',
        0.7: 'orange',
        1.0: 'red'
    }
).add_to(m)

# Save to HTML
html_file = None
try:
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
        html_file = f.name
        m.save(html_file)
    
    print(f"📄 Map saved to: {html_file}")
    
    # Take screenshot
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1200,800')
    chrome_options.add_argument('--hide-scrollbars')
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(15)
    
    # Use file:// URL with proper path formatting
    file_url = f'file:///{html_file.replace(os.sep, "/")}' if platform.system() == 'Windows' else f'file://{html_file}'
    print(f"📄 Loading map from: {file_url}")
    
    driver.get(file_url)
    time.sleep(3)  # Wait for tiles to load
    
    screenshot_file = 'test_map_screenshot.png'
    driver.save_screenshot(screenshot_file)
    driver.quit()
    
    print(f"✅ Screenshot saved to: {screenshot_file}")
    print(f"✅ Test successful!")

finally:
    # Clean up
    if html_file and os.path.exists(html_file):
        os.unlink(html_file)
        print(f"🧹 Cleaned up temp HTML file")

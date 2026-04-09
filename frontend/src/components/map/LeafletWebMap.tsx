import React from 'react'
import { View, Text } from 'react-native'
import { GMapPoint, HeatPoint } from './types'

type Props = {
  polyline: GMapPoint[]
  heat: HeatPoint[]
  setScrollEnabled: (enabled: boolean) => void
  userLocation?: { lat: number; lng: number } | null
  centerOn?: { lat: number; lng: number } | null
}

const LeafletWebMap = ({ polyline, heat, setScrollEnabled, userLocation, centerOn }: Props) => {
  let WebViewComp: any = null
  try {
    WebViewComp = require('react-native-webview').WebView
  } catch {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 }}>
        <Text style={{ textAlign: 'center', color: '#374151' }}>WebView not installed.</Text>
        <Text style={{ textAlign: 'center', color: '#6b7280', marginTop: 8 }}>Run: npx expo install react-native-webview</Text>
      </View>
    )
  }

  const center = centerOn || (polyline[0] ? polyline[0] : { lat: 14.5995, lng: 120.9842 })
  const coordsJson = JSON.stringify(polyline.map((p) => [p.lat, p.lng]))
  const heatJson = JSON.stringify(heat.map((h) => [h.lat, h.lng, h.weight]))
  const userLocJson = userLocation ? JSON.stringify([userLocation.lat, userLocation.lng]) : 'null'

  const html = `<!DOCTYPE html>
  <html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.fullscreen@2.4.0/Control.FullScreen.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.heat/dist/leaflet-heat.js"></script>
    <script src="https://unpkg.com/leaflet.fullscreen@2.4.0/Control.FullScreen.js"></script>
    <style>html, body { height: 100%; margin: 0; padding: 0; touch-action: none; } #map { height: 100%; width: 100%; box-sizing: border-box; }</style>
  </head>
  <body>
    <div id="map"></div>
    <script>
      const coords = ${coordsJson};
      const userLoc = ${userLocJson};

      const map = L.map('map', {
        zoomControl: true,
        fullscreenControl: true,
        preferCanvas: true,
        zoomAnimation: true,
        fadeAnimation: true
      }).setView([${center.lat}, ${center.lng}], 17);

      L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', {
        maxZoom: 20,
        subdomains: ['mt0','mt1','mt2','mt3'],
        attribution: 'Map data ©2025 Google',
        keepBuffer: 2,
      }).addTo(map);

      if (userLoc) {
        L.marker(userLoc, {
          icon: L.divIcon({
            className: 'custom-user-icon',
            html: '<div style="background-color: #2563eb; width: 14px; height: 14px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>'
          })
        }).addTo(map).bindPopup('Your Location');
        map.setView(userLoc, 18, { animate: true, duration: 0.5 });
      } else if (coords.length > 1) {
        const poly = L.polyline(coords, { color: '#2563eb', weight: 3 });
        map.fitBounds(poly.getBounds(), { padding: [20, 20] });
      }

      if (coords.length > 1) {
        L.polyline(coords, { color: '#2563eb', weight: 3 }).addTo(map);

        const startCoord = coords[0];
        const startIcon = L.divIcon({
          className: 'custom-icon',
          html: '<div style="background-color: #22c55e; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        });
        L.marker([startCoord[0], startCoord[1]], { icon: startIcon }).addTo(map).bindPopup('Flight Start');

        const endCoord = coords[coords.length - 1];
        const endIcon = L.divIcon({
          className: 'custom-icon',
          html: '<div style="background-color: #ef4444; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.3);"></div>',
          iconSize: [14, 14],
          iconAnchor: [7, 7]
        });
        L.marker([endCoord[0], endCoord[1]], { icon: endIcon }).addTo(map).bindPopup('Flight End');
      }

      const heat = ${heatJson};
      if (heat.length > 0) {
        L.heatLayer(heat, {
          radius: 6,
          blur: 6,
          maxZoom: 18,
          max: 4,
          gradient: {
            0.0: 'green',
            0.3: 'lime',
            0.5: 'yellow',
            0.7: 'orange',
            1.0: 'red'
          }
        }).addTo(map);

        heat.forEach(point => {
          const color = point.weight <= 2 ? '#22c55e' : point.weight === 3 ? '#eab308' : '#ef4444';
          L.circleMarker([point.lat, point.lng], {
            radius: 3,
            fillColor: color,
            color: 'white',
            weight: 1,
            fillOpacity: 0.85
          }).addTo(map).bindPopup(point.weight + ' estimated unique weeds');
        });
      }

      document.getElementById('map').addEventListener('touchstart', function() {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage('disableScroll');
      });
      document.getElementById('map').addEventListener('touchend', function() {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage('enableScroll');
      });
    </script>
  </body>
  </html>`

  const onMessage = (event: any) => {
    if (event?.nativeEvent?.data === 'disableScroll') setScrollEnabled(false)
    if (event?.nativeEvent?.data === 'enableScroll') setScrollEnabled(true)
  }

  return (
    <WebViewComp
      originWhitelist={['*']}
      source={{ html }}
      style={{ width: 380, height: 310, backgroundColor: 'white' }}
      allowsFullscreenVideo={true}
      javaScriptEnabled={true}
      domStorageEnabled={true}
      mediaPlaybackRequiresUserAction={false}
      onMessage={onMessage}
    />
  )
}

export default LeafletWebMap

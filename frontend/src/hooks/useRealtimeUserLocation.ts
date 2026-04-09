import { useEffect, useState } from 'react'
import * as Location from 'expo-location'

type UseRealtimeUserLocationResult = {
  showUserLocation: boolean
  setShowUserLocation: (value: boolean | ((prev: boolean) => boolean)) => void
  userLocation: { lat: number; lng: number } | null
  locationError: string
  toggleDisabled: boolean
  setToggleDisabled: (value: boolean) => void
}

export function useRealtimeUserLocation(): UseRealtimeUserLocationResult {
  const [showUserLocation, setShowUserLocation] = useState(false)
  const [userLocation, setUserLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [locationError, setLocationError] = useState<string>('')
  const [toggleDisabled, setToggleDisabled] = useState(false)

  useEffect(() => {
    let isMounted = true
    let locationSubscription: Location.LocationSubscription | null = null

    const startLocationTracking = async () => {
      setToggleDisabled(true)
      if (!showUserLocation) {
        if (locationSubscription) {
          locationSubscription.remove()
          locationSubscription = null
        }
        setUserLocation(null)
        setLocationError('')
        setToggleDisabled(false)
        return
      }

      try {
        setLocationError('')
        const { status } = await Location.requestForegroundPermissionsAsync()
        if (status !== 'granted') {
          setLocationError('Permission to access location was denied')
          setShowUserLocation(false)
          setToggleDisabled(false)
          return
        }

        locationSubscription = await Location.watchPositionAsync(
          {
            accuracy: Location.Accuracy.High,
            timeInterval: 2000,
            distanceInterval: 5,
          },
          (loc) => {
            if (isMounted) {
              setUserLocation({ lat: loc.coords.latitude, lng: loc.coords.longitude })
            }
          }
        )
      } catch (e: any) {
        setLocationError(e?.message || 'Failed to get location')
        setShowUserLocation(false)
      }
      setToggleDisabled(false)
    }

    startLocationTracking()

    return () => {
      isMounted = false
      if (locationSubscription) {
        locationSubscription.remove()
      }
    }
  }, [showUserLocation])

  return {
    showUserLocation,
    setShowUserLocation,
    userLocation,
    locationError,
    toggleDisabled,
    setToggleDisabled,
  }
}

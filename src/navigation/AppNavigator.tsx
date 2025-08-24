import React, { useState } from 'react'
import { View } from 'react-native'
import Homescreen from '../screens/Homescreen'
import Mapscreen from '../screens/Mapscreen'
import DetectionResults from '../screens/DetResultscreen'
import NavigationBar from './NavigationBar'

const AppNavigator = () => {
  const [currentRoute, setCurrentRoute] = useState('Home')

  const renderScreen = () => {
    switch (currentRoute) {
      case 'Home':
        return <Homescreen />
      case 'Map':
        return <Mapscreen />
      case 'DetectionResults':
        return <DetectionResults />
      default:
        return <Homescreen />
    }
  }

  const handleNavigate = (route: string) => {
    setCurrentRoute(route)
  }

  return (
    <View className="flex-1">
      <View className="flex-1">
        {renderScreen()}
      </View>
      <NavigationBar 
        currentRoute={currentRoute} 
        onNavigate={handleNavigate} 
      />
    </View>
  )
}

export default AppNavigator
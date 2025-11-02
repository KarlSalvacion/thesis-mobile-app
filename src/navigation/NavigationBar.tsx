import React from 'react'
import { Ionicons } from '@expo/vector-icons'
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import Homescreen from '../screens/Homescreen'
import Mapscreen from '../screens/Mapscreen'
import DetectionResults from '../screens/DetResultscreen'
import { useSession } from '../context/SessionContext'

const Tab = createBottomTabNavigator()

const NavigationBar = () => {
  const { navigationLocked } = useSession()
  
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: 'rgb(37, 165, 120) ',
        tabBarInactiveTintColor: 'rgb(128, 134, 124)',
        tabBarLabelStyle: { fontSize: 12, fontWeight: '500' },
        tabBarIcon: ({ color, size }) => {
          let iconName: keyof typeof Ionicons.glyphMap = 'home'
          if (route.name === 'Home') iconName = 'home'
          else if (route.name === 'Map') iconName = 'map'
          else if (route.name === 'DetectionResults') iconName = 'stats-chart'
          return <Ionicons name={iconName} size={size ?? 24} color={color} />
        }
      })}
    >
      <Tab.Screen 
        name="Home" 
        component={Homescreen}
      />
      <Tab.Screen 
        name="Map" 
        component={Mapscreen}
        listeners={{
          tabPress: (e) => {
            if (navigationLocked) {
              e.preventDefault()
            }
          },
        }}
      />
      <Tab.Screen
        name="DetectionResults"
        component={DetectionResults}
        options={{ title: 'Results' }}
        listeners={{
          tabPress: (e) => {
            if (navigationLocked) {
              e.preventDefault()
            }
          },
        }}
      />
    </Tab.Navigator>
  )
}

export default NavigationBar
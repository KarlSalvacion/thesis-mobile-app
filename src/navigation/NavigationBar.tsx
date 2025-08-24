import React from 'react'
import { View, Text, TouchableOpacity, Pressable } from 'react-native'

interface NavigationBarProps {
  currentRoute: string
  onNavigate: (route: string) => void
}

const NavigationBar = ({ currentRoute, onNavigate }: NavigationBarProps) => {
  const tabs = [
    { name: 'Home', route: 'Home', icon: '🏠' },
    { name: 'Map', route: 'Map', icon: '🗺️' },
    { name: 'Results', route: 'DetectionResults', icon: '📊' }
  ]

  return (
    <View className="bg-white border-t border-gray-200 px-2 py-2">
      <View className="flex-row justify-around items-center">
        {tabs.map((tab) => (
          <Pressable
            key={tab.route}
            onPress={() => onNavigate(tab.route)}
            className={`flex-1 items-center py-2 px-1 ${
              currentRoute === tab.route ? 'opacity-100' : 'opacity-60'
            }`}
          >
            <Text className="text-2xl mb-1">{tab.icon}</Text>
            <Text 
              className={`text-xs font-medium ${
                currentRoute === tab.route 
                  ? 'text-blue-600' 
                  : 'text-gray-500'
              }`}
            >
              {tab.name}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  )
}

export default NavigationBar
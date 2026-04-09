import React from 'react'
import { View, Text } from 'react-native'
import { FontAwesome6 } from '@expo/vector-icons'

const HomeBranding = () => {
  return (
    <View className="w-full max-w-md mb-6 items-center">
      <View
        style={{
          backgroundColor: '#25A578',
          borderRadius: 18,
          paddingVertical: 18,
          paddingHorizontal: 32,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 2 },
          shadowOpacity: 0.18,
          shadowRadius: 6,
          elevation: 6,
          marginBottom: 0,
        }}
      >
        <FontAwesome6
          name="seedling"
          size={36}
          color="#fff"
          style={{ textShadowColor: '#1a5c3a', textShadowOffset: { width: 1, height: 2 }, textShadowRadius: 4 }}
        />
        <Text
          style={{
            color: '#fff',
            fontSize: 36,
            fontWeight: 'bold',
            marginLeft: 14,
            letterSpacing: 2,
            textShadowColor: '#1a5c3a',
            textShadowOffset: { width: 1, height: 2 },
            textShadowRadius: 4,
            fontFamily: 'System',
          }}
        >
          WEEDEFY
        </Text>
      </View>
      <Text style={{ color: '#25A578', marginTop: 8, fontWeight: '600', fontSize: 16, letterSpacing: 1 }}>
        Smart Weed Detection System
      </Text>
    </View>
  )
}

export default HomeBranding

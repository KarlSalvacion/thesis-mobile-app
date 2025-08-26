import React from 'react'
import { NavigationContainer } from '@react-navigation/native'
import NavigationBar from './NavigationBar'

const AppNavigator = () => {
  return (
    <NavigationContainer>
      <NavigationBar />
    </NavigationContainer>
  )
}

export default AppNavigator
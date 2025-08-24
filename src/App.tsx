import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native';
import './global.css';
import AppNavigator from './navigation/AppNavigator';

export default function App() {
  return (
    <SafeAreaView className='flex-1 bg-white'> 
      <StatusBar style="dark" />
      <AppNavigator />
    </SafeAreaView>
  );
}


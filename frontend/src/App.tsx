import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import './global.css';
import AppNavigator from './navigation/AppNavigator';
import { SessionProvider } from './context/SessionContext';

export default function App() {
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <StatusBar style="dark" />
        <AppNavigator />
      </SessionProvider>
    </SafeAreaProvider>
  );
}


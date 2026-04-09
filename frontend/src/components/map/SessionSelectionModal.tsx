import React from 'react'
import { Modal, View, Text, Pressable, ScrollView, Alert } from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import { API_BASE } from '../../config'
import { DetectionRow } from './types'

type Props = {
  visible: boolean
  sessions: DetectionRow[]
  selectedDetection: DetectionRow | null
  onClose: () => void
  onSelectSession: (session: DetectionRow) => void
  onClearSelected: () => void
  onAfterDeleteRefresh: () => Promise<void>
}

const SessionSelectionModal = ({
  visible,
  sessions,
  selectedDetection,
  onClose,
  onSelectSession,
  onClearSelected,
  onAfterDeleteRefresh,
}: Props) => {
  const handleDelete = (session: DetectionRow) => {
    Alert.alert(
      'Delete Session',
      `Are you sure you want to delete "${session[1]}"?\n\nThis will permanently delete all data including:\n• Detection details\n• GPS tracks\n• Heatmaps\n\nThis action cannot be undone.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              const response = await fetch(`${API_BASE}/detection/${session[0]}`, { method: 'DELETE' })
              if (response.ok) {
                await onAfterDeleteRefresh()
                if (selectedDetection && selectedDetection[0] === session[0]) {
                  onClearSelected()
                }
                Alert.alert('Success', 'Session deleted successfully')
              } else {
                Alert.alert('Error', 'Failed to delete session')
              }
            } catch {
              Alert.alert('Error', 'Failed to delete session')
            }
          },
        },
      ]
    )
  }

  return (
    <Modal visible={visible} transparent={true} animationType="slide" onRequestClose={onClose}>
      <View className="flex-1 bg-black/60 justify-end">
        <View className="bg-white rounded-t-2xl p-4 max-h-3/4">
          <Text className="text-lg font-semibold mb-2">Select Detection Session</Text>
          <ScrollView style={{ maxHeight: 360 }}>
            {sessions.length === 0 && (
              <View className="p-4">
                <Text className="text-gray-500">No sessions available.</Text>
              </View>
            )}
            {sessions.map((session) => (
              <Pressable
                key={session[0]}
                onPress={() => {
                  onClose()
                  onSelectSession(session)
                }}
                className="p-3 border-b border-gray-100"
              >
                <View className="flex-row items-center justify-between">
                  <View className="flex-1">
                    <Text className="font-medium">{session[1]}</Text>
                    <Text className="text-xs text-gray-500">
                      {new Date(String(session[2])).toLocaleString()} • {session[3]}
                    </Text>
                  </View>
                  <View className="flex-row items-center">
                    <Text className="text-sm text-gray-400 mr-3">{session[6]} detections</Text>
                    <Pressable
                      onPress={(e) => {
                        e.stopPropagation()
                        handleDelete(session)
                      }}
                      className="p-2"
                    >
                      <Ionicons name="trash-outline" size={20} color="#ef4444" />
                    </Pressable>
                  </View>
                </View>
              </Pressable>
            ))}
          </ScrollView>
          <Pressable className="mt-3 p-3 bg-gray-100 rounded-lg" onPress={onClose}>
            <Text className="text-center text-gray-700">Close</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  )
}

export default SessionSelectionModal

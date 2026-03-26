import React, { useEffect, useState } from 'react'
import { View, Text, ScrollView } from 'react-native'
import { parseSrtString, readSrtFileToString, SrtParseResult } from './SrtParser'

type Props = {
  srtUri?: string | null
  srtName?: string | null
}

const SrtDebugViewer: React.FC<Props> = ({ srtUri, srtName }) => {
  const [result, setResult] = useState<SrtParseResult | null>(null)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    let mounted = true
    async function run() {
      setError('')
      setResult(null)
      if (!srtUri) return
      try {
        const content = await readSrtFileToString(srtUri)
        const parsed = parseSrtString(content)
        if (mounted) setResult(parsed)
      } catch (e: any) {
        if (mounted) setError(e?.message || 'Failed to read/parse SRT')
      }
    }
    run()
    return () => { mounted = false }
  }, [srtUri])

  if (!srtUri) return null

  const maxPreview = 20
  const cues = result?.cues || []
  const errors = result?.errors || []

  return (
    <View className="w-72 bg-white border border-gray-200 rounded-md p-3 mb-3">
      <Text className="text-gray-800 font-semibold mb-2" numberOfLines={1}>
        Parsed SRT: {srtName || 'subtitle.srt'}
      </Text>
      {error ? (
        <Text className="text-red-600">{error}</Text>
      ) : result ? (
        <>
          <Text className="text-xs text-gray-700 mb-2">
            Cues: {cues.length}{errors.length ? `, Errors: ${errors.length}` : ''}
          </Text>
          <ScrollView className="max-h-60">
            {cues.slice(0, maxPreview).map((c) => (
              <View key={`${c.index}-${c.startMs}`} className="mb-1">
                <Text className="text-[10px] text-gray-800" numberOfLines={1}>
                  {c.index}. {c.start} → {c.end}
                </Text>
                <Text className="text-[10px] text-gray-600" numberOfLines={2}>
                  {c.text}
                </Text>
              </View>
            ))}
            {cues.length > maxPreview && (
              <Text className="text-[10px] text-gray-500 mt-1">…and {cues.length - maxPreview} more</Text>
            )}
          </ScrollView>
        </>
      ) : (
        <Text className="text-gray-600">Parsing...</Text>
      )}
    </View>
  )
}

export default SrtDebugViewer



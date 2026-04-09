export type SelectedFile = {
  uri: string
  name: string
  size?: number | null
  type: 'media' | 'srt'
}

export type HomeStatus = 'idle' | 'picking' | 'ready' | 'uploading' | 'success' | 'error'

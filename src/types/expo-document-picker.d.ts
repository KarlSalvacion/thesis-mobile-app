declare module 'expo-document-picker' {
  export type DocumentPickerAsset = {
    uri: string
    name?: string
    size?: number
    mimeType?: string
    file?: any
  }

  export type DocumentPickerResult =
    | { canceled: true }
    | { canceled: false; assets: DocumentPickerAsset[] }

  export function getDocumentAsync(options?: {
    type?: string | string[]
    multiple?: boolean
    copyToCacheDirectory?: boolean
  }): Promise<DocumentPickerResult>
}



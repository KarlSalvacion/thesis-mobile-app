// SRT parser and viewer utilities

export type SrtCue = {
  index: number
  startMs: number
  endMs: number
  start: string
  end: string
  text: string
}

export type SrtParseResult = {
  cues: SrtCue[]
  errors: string[]
}

const TIME_REGEX = /^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})/

function msToTimestamp(totalMs: number): string {
  if (!isFinite(totalMs)) return '00:00:00,000'
  const ms = Math.floor(totalMs % 1000)
  const totalSeconds = Math.floor(totalMs / 1000)
  const s = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  const m = totalMinutes % 60
  const h = Math.floor(totalMinutes / 60)
  const pad = (n: number, l = 2) => String(n).padStart(l, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms, 3)}`
}

export function parseSrtString(input: string): SrtParseResult {
  // Try library-based parsing first for broader SRT variants (e.g., DJI telemetry)
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const subtitlesParser = require('subtitles-parser')
    const cues = (subtitlesParser.fromSrt(input, true) || []).map((c: any, idx: number) => {
      const index = typeof c.id === 'number' ? c.id : idx + 1
      const startMs = typeof c.startTime === 'number' ? c.startTime : parseInt(c.startTime)
      const endMs = typeof c.endTime === 'number' ? c.endTime : parseInt(c.endTime)
      return {
        index,
        startMs,
        endMs,
        start: msToTimestamp(startMs),
        end: msToTimestamp(endMs),
        text: String(c.text ?? ''),
      } as SrtCue
    })
    return { cues, errors: [] }
  } catch {}

  const normalized = input.replace(/\r\n|\r/g, '\n').trim()
  const lines = normalized.split('\n')
  const cues: SrtCue[] = []
  const errors: string[] = []

  let i = 0
  while (i < lines.length) {
    // Skip empty lines between blocks
    while (i < lines.length && lines[i].trim() === '') i++
    if (i >= lines.length) break

    // Index line (optional in some SRTs). If not numeric, treat as timing line.
    let index = cues.length + 1
    const maybeIndex = lines[i].trim()
    if (/^\d+$/.test(maybeIndex)) {
      index = parseInt(maybeIndex, 10)
      i++
    }
    if (i >= lines.length) break

    const timeLine = lines[i].trim()
    const match = TIME_REGEX.exec(timeLine)
    if (!match) {
      errors.push(`Cue ${index}: invalid time line: "${timeLine}"`)
      // Try to recover by skipping until next blank line
      while (i < lines.length && lines[i].trim() !== '') i++
      continue
    }
    i++

    const [
      , sh, sm, ss, sms,
      eh, em, es, ems,
    ] = match

    const toMs = (h: string, m: string, s: string, ms: string) =>
      parseInt(h) * 3600000 + parseInt(m) * 60000 + parseInt(s) * 1000 + parseInt(ms)

    const startMs = toMs(sh, sm, ss, sms)
    const endMs = toMs(eh, em, es, ems)

    const textLines: string[] = []
    while (i < lines.length && lines[i].trim() !== '') {
      textLines.push(lines[i])
      i++
    }

    const text = textLines.join('\n').trim()
    cues.push({
      index,
      startMs,
      endMs,
      start: `${sh}:${sm}:${ss},${sms}`,
      end: `${eh}:${em}:${es},${ems}`,
      text,
    })

    // Skip blank line separating cues
    while (i < lines.length && lines[i].trim() === '') i++
  }

  return { cues, errors }
}

export async function readSrtFileToString(uri: string): Promise<string> {
  // Dynamically import to avoid bundling if unused
  const FileSystem = await import('expo-file-system')
  const { exists, uri: normalized } = await ensureFileExists(uri)
  if (!exists) throw new Error('File does not exist: ' + uri)
  return await FileSystem.readAsStringAsync(normalized, { encoding: FileSystem.EncodingType.UTF8 })
}

async function ensureFileExists(uri: string): Promise<{ exists: boolean; uri: string }> {
  const FileSystem = await import('expo-file-system')
  const info = await FileSystem.getInfoAsync(uri)
  return { exists: !!info.exists, uri }
}



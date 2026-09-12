import fs from 'node:fs'

const center = fs.readFileSync(new URL('../src/components/NotificationCenter.jsx', import.meta.url), 'utf8')
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  ['version', version.includes("APP_VERSION = '1.31.9'")],
  ['base output -25%', center.includes('const SOUND_BASE_OUTPUT = 0.75')],
  ['tone bus exists', center.includes('let audioToneBus = null')],
  ['compressor feeds master', center.includes('audioCompressor.connect(audioMaster)')],
  ['master feeds destination', center.includes('audioMaster.connect(audioContext.destination)')],
  ['voices feed tone bus', center.includes('envelope.connect(audioToneBus)')],
  ['volume scales post-compressor output', center.includes('SOUND_BASE_OUTPUT * (normalized / 100)')],
  ['0-200 range retained', center.includes('SOUND_VOLUME_MIN = 0') && center.includes('SOUND_VOLUME_MAX = 200')],
  ['device setting retained', center.includes("DEVICE_VOLUME_KEY = 'elfar:notification-device-volume'")],
  ['native notifications are silent', center.includes('silent: true')],
]

let failed = 0
for (const [label, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}: ${label}`)
  if (!ok) failed++
}
if (failed) process.exit(1)
console.log(`PASS: ${checks.length}/${checks.length}`)

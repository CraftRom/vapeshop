import fs from 'node:fs'

const center = fs.readFileSync(new URL('../src/components/NotificationCenter.jsx', import.meta.url), 'utf8')
const version = fs.readFileSync(new URL('../src/version.js', import.meta.url), 'utf8')

const checks = [
  // Тут було точне 1.32.1 — падало на кожному випуску панелі.
  ['версія панелі задана', /APP_VERSION = '\d+\.\d+\.\d+'/.test(version)],
  ['базова гучність на 25% тихіша', center.includes('const SOUND_BASE_OUTPUT = 0.75')],
  ['спільна шина звуків існує', center.includes('let audioToneBus = null')],
  ['компресор іде на загальну гучність', center.includes('audioCompressor.connect(audioMaster)')],
  ['загальна гучність іде на вихід', center.includes('audioMaster.connect(audioContext.destination)')],
  ['голоси звуків ідуть через спільну шину', center.includes('envelope.connect(audioToneBus)')],
  ['гучність масштабує сигнал після компресора', center.includes('SOUND_BASE_OUTPUT * (normalized / 100)')],
  ['діапазон 0–200 збережено', center.includes('SOUND_VOLUME_MIN = 0') && center.includes('SOUND_VOLUME_MAX = 200')],
  ['налаштування пристрою збережено', center.includes("DEVICE_VOLUME_KEY = 'elfar:notification-device-volume'")],
  ['системні сповіщення без власного звуку', center.includes('silent: true')],
]

let failed = 0
for (const [label, ok] of checks) {
  console.log(`  ${ok ? '✓' : '✗'} ${label}`)
  if (!ok) failed++
}
console.log(`\nГУЧНІСТЬ СПОВІЩЕНЬ: ${failed ? `ПРОВАЛЕНО: ${failed}` : 'усе витримано'}`)
if (failed) process.exit(1)

// Standalone contract check: node miniapp/tests/chat-video.mjs
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const chat = read('../src/screens/Chat.jsx')
const api = read('../src/api.js')
const dash = read('../../dashboard/src/components/ChatAttachment.jsx')
const nginx = read('../../deploy/nginx/app.conf.template')
const shop = read('../../backend/api/routers/shop.py')
const support = read('../../backend/api/routers/shop_support.py')
const bot = read('../../backend/bot/handlers/chat.py')
let count = 0
function check(result, label) { assert.ok(result, label); count++ }
check(chat.includes("kind === 'video'") && chat.includes('<video src={src} controls'), 'MiniApp inline video player')
check(chat.includes('playsInline') && chat.includes('preload="metadata"'), 'mobile playback/seek controls')
check(chat.includes('URL.revokeObjectURL') && dash.includes('URL.revokeObjectURL'), 'both clients release blob URLs')
check(chat.includes("if (kind === 'photo') fetchMedia()") && dash.includes("if (kind === 'photo') load()"), 'videos are never eagerly fetched')
check(chat.includes('chatMedia(order.id, file, support)') && chat.includes('video/mp4'), 'attachments in both MiniApp rooms')
check(api.includes('`/support/threads/${orderId}/media`') && api.includes('`/orders/${orderId}/chat/media`'), 'two authenticated upload endpoints')
check(api.includes('60000') && api.includes('signalAuthFailure'), 'slow video download and auth revocation')
check(dash.includes('authorizedFetch(fileUrl') && dash.includes('<video controls'), 'dashboard video uses authenticated proxy')
check(shop.includes('async def order_chat_media(') && support.includes('async def upload_media('), 'API upload routes are present')
check(nginx.includes("media-src 'self' blob:") && nginx.includes('client_max_body_size 18M'), 'CSP video and narrowly scoped upload size')
check(bot.includes('F.video_note | F.animation'), 'Telegram video-note and animation routing')
console.log(`CHAT VIDEO: ${count}/${count}`)

/*
 * VexCom — command center for all-day outdoor use.  pages/index.js
 *
 * One COMMAND pill (voice input). Four quick-command shortcuts (extensible).
 * Fleet status + time bar. Color-coded state machine. Adaptive polling.
 * Offline-resilient. Built for hiking and biking — glance comprehension at speed.
 *
 * Extensible: add a capability by adding one entry to QUICK_COMMANDS.
 * Each entry: {label, action: 'ASK'|'VOICE'|'NAV', params: {...}}
 *
 * 480×480 round · circle-safe · Zepp OS
 * NOTE: written without a simulator — verify in `zeus dev`.
 */
import { createWidget, widget, prop, align } from '@zos/ui'
import { push } from '@zos/router'
import { create, id, codec } from '@zos/media'
import { readFileSync } from '@zos/fs'
import { BasePage } from '@zeppos/zml/base-page'
import { title, pill, megaPill, pane, COLOR, TYPE, stateColors } from './style'

// ── quick-command registry — add capabilities here ──
const QUICK_COMMANDS = [
  { label: 'status',  action: 'ASK',   params: { message: 'status' } },
  { label: 'fleet',   action: 'ASK',   params: { message: 'fleet status — who is online?' } },
  { label: 'work',    action: 'ASK',   params: { message: 'work status — any updates?' } },
  { label: 'msg',     action: 'NAV',   params: { url: 'pages/menu' } },
]
const MAX_REC_MS = 60000
const POLL_FAST = 5000
const POLL_SLOW = 15000
const POLL_CAP_MS = 90000
const OFFLINE_RETRY = 30000
const OFFLINE_CAP_MS = 600000
const VOICE_FILE = 'voice.opus'
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

function b64encode(buf) {
  const bytes = new Uint8Array(buf)
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i]; const b1 = bytes[i + 1]; const b2 = bytes[i + 2]
    out += B64[b0 >> 2]
    out += B64[((b0 & 3) << 4) | (b1 === undefined ? 0 : b1 >> 4)]
    out += b1 === undefined ? '=' : B64[((b1 & 15) << 2) | (b2 === undefined ? 0 : b2 >> 6)]
    out += b1 === undefined || b2 === undefined ? '=' : B64[b2 & 63]
  }
  return out
}

// ── vibration fallback (API may not exist on all devices) ──
let _vibrate
try { const s = require('@zos/sensor'); _vibrate = s.vibrate } catch (e) { _vibrate = () => {} }

Page(
  BasePage({
    build() {
      this.state = 'IDLE'
      this.recording = false
      this.recorder = null
      this.recStart = 0
      this.recTimer = null
      this.pollTimer = null
      this.offlineTimer = null
      this.consecutiveFailures = 0
      this.fleet = []
      this.replyText = ''
      this.lastMsgId = 0

      // ── top bar: fleet dots + time ──
      title(30, 'starship Vex', TYPE.caption)

      this.fleetBar = createWidget(widget.TEXT, {
        x: 80, y: 30, w: 300, h: 24,
        text: '', text_size: 16, color: COLOR.dim,
        align_h: align.CENTER_H, align_v: align.CENTER_V,
      })
      this.timeBar = createWidget(widget.TEXT, {
        x: 360, y: 30, w: 100, h: 24,
        text: '', text_size: 16, color: COLOR.dim,
        align_h: align.RIGHT, align_v: align.CENTER_V,
      })

      // menu button — top right
      createWidget(widget.BUTTON, {
        x: 430, y: 28, w: 40, h: 28, radius: 14,
        text: '…', text_size: 18,
        normal_color: COLOR.navy, press_color: COLOR.navyHi,
        click_func: () => { this.cleanup(); push({ url: 'pages/menu' }) },
      })

      // ── the COMMAND pill ──
      this.pill = megaPill(82, 320, 148, 'COMMAND', () => this.toggleTalk())

      // ── quick-command pills ──
      this.cmdBtns = []
      const CMD_Y = 244
      const GAP = 6
      const BW = 108
      const TOTAL_W = QUICK_COMMANDS.length * BW + (QUICK_COMMANDS.length - 1) * GAP
      const START_X = Math.floor((480 - TOTAL_W) / 2)

      QUICK_COMMANDS.forEach((cmd, i) => {
        const b = pill(START_X + i * (BW + GAP), CMD_Y, BW, 40, cmd.label, 'navy', () => this.runCommand(cmd), TYPE.caption)
        this.cmdBtns.push(b)
      })

      // ── reply pane ──
      this.reply = pane(300, 100, 'vex', TYPE.body, () => {})

      // ── footer ──
      this.footer = createWidget(widget.TEXT, {
        x: 0, y: 420, w: 480, h: 30,
        text: '', text_size: 16, color: COLOR.dim,
        align_h: align.CENTER_H, align_v: align.CENTER_V,
      })

      // heartbeat: update clock every 30s
      this.clockTimer = setInterval(() => this.updateTime(), 30000)
      this.updateTime()
      this.setState('IDLE')
    },

    // ── time ──
    updateTime() {
      try {
        const d = new Date()
        const h = d.getHours(); const m = d.getMinutes()
        this.timeBar.setProperty(prop.TEXT, (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m)
      } catch (e) { /* Date may not be available */ }
    },

    // ── fleet display ──
    showFleet(data) {
      if (!data || !data.length) { this.fleetBar.setProperty(prop.TEXT, ''); return }
      this.fleet = data
      const parts = data.map(f => (f.online ? '●' : '○') + f.name)
      this.fleetBar.setProperty(prop.TEXT, parts.join('  '))
    },

    // ── extensible command runner ──
    runCommand(cmd) {
      if (cmd.action === 'NAV') { this.cleanup(); push(cmd.params); return }
      if (cmd.action === 'ASK') {
        this.setState('WAITING')
        const sessionId = 'wcmd' + Date.now()
        this.request({ method: 'ASK', params: { message: cmd.params.message, session_id: sessionId } })
          .then((data) => {
            this.consecutiveFailures = 0
            if (data && data.fleet) this.showFleet(data.fleet)
            if (data && data.reply) {
              this.replyText = data.reply
              this.reply.setProperty(prop.TEXT, data.reply)
              this.setState('REPLY')
              try { _vibrate('short') } catch (e) {}
            } else { this.setState('IDLE') }
          })
          .catch(() => {
            this.consecutiveFailures++
            if (this.consecutiveFailures >= 3) this.enterOffline()
            else this.setState('IDLE')
          })
      }
    },

    // ── state machine ──
    setState(s) {
      this.state = s
      const c = stateColors[s] || stateColors.IDLE
      this.pill.setProperty(prop.TEXT, c.text)
      this.pill.setProperty(prop.MORE, { normal_color: c.pill, press_color: c.pillHi })
      this.footer.setProperty(prop.TEXT, c.footer)
      if (c.reply !== undefined) this.reply.setProperty(prop.TEXT, c.reply)
    },

    // ── voice: tap to start, tap to stop (hold as long as you speak) ──
    toggleTalk() {
      if (this.recording) { this.stopRecord(true); return }
      if (this.state === 'REPLY' || this.state === 'AWAY') {
        this.setState('IDLE'); this.replyText = ''; return
      }
      try {
        this.recorder = create(id.RECORDER)
        this.recorder.setFormat(codec.OPUS, { target_file: 'data://' + VOICE_FILE })
        this.recorder.start()
        this.recording = true
        this.recStart = Date.now()
        this.setState('RECORDING')
        this.recTimer = setInterval(() => {
          const s = Math.floor((Date.now() - this.recStart) / 1000)
          this.pill.setProperty(prop.TEXT, s + 's')
          if (s * 1000 >= MAX_REC_MS) this.stopRecord(true)
        }, 500)
      } catch (e) {
        this.setState('MIC_FAIL')
        this.footer.setProperty(prop.TEXT, 'mic error: ' + e)
      }
    },

    stopRecord(sendAfter) {
      if (this.recTimer) { clearInterval(this.recTimer); this.recTimer = null }
      this.recording = false
      try { this.recorder && this.recorder.stop() } catch (e) {}
      if (sendAfter) this.sendVoice()
    },

    // ── voice clip → /voice → STT → mesh → reply ──
    sendVoice() {
      let b64
      try {
        const buf = readFileSync({ path: VOICE_FILE })
        if (!buf || !buf.byteLength) { this.setState('IDLE'); this.footer.setProperty(prop.TEXT, 'nothing recorded'); return }
        b64 = b64encode(buf)
      } catch (e) {
        this.setState('IDLE'); this.footer.setProperty(prop.TEXT, 'read failed'); return
      }
      this.stopPolling()
      this.consecutiveFailures = 0
      this.setState('WAITING')
      const sessionId = 'wv' + Date.now()
      this.request({ method: 'VOICE', params: { b64, session_id: sessionId } })
        .then((data) => {
          this.consecutiveFailures = 0
          if (!data) { this.setState('IDLE'); return }
          if (data.fleet) this.showFleet(data.fleet)
          if (data.transcribed) this.footer.setProperty(prop.TEXT, 'heard: ' + data.transcribed.slice(0, 60))
          if (data.mode === 'relay' && data.msg_id) {
            this.startPolling(data.msg_id)
          } else if (data.mode === 'empty') {
            this.setState('REPLY'); this.reply.setProperty(prop.TEXT, '(silence — try again)')
          } else if (data.reply) {
            this.replyText = data.reply; this.setState('REPLY')
            this.reply.setProperty(prop.TEXT, data.reply)
            try { _vibrate('short') } catch (e) {}
          }
        })
        .catch(() => {
          this.consecutiveFailures++
          if (this.consecutiveFailures >= 3) this.enterOffline()
          else this.setState('IDLE')
        })
    },

    // ── adaptive polling ──
    startPolling(sinceId) {
      const startedAt = Date.now()
      let fast = true
      const tick = () => {
        const elapsed = Date.now() - startedAt
        if (elapsed > POLL_CAP_MS) { this.stopPolling(); this.setState('AWAY'); return }
        if (elapsed > 30000 && fast) { fast = false; clearInterval(this.pollTimer); this.pollTimer = setInterval(tick, POLL_SLOW) }
        this.request({ method: 'POLL', params: { since_id: sinceId } })
          .then((data) => {
            this.consecutiveFailures = 0
            const replies = (data && data.replies) || []
            if (replies.length) {
              this.stopPolling()
              this.replyText = replies[replies.length - 1].body
              this.reply.setProperty(prop.TEXT, this.replyText)
              this.setState('REPLY')
              try { _vibrate('short') } catch (e) {}
            }
          })
          .catch(() => { this.consecutiveFailures++; if (this.consecutiveFailures >= 3) this.enterOffline() })
      }
      this.pollTimer = setInterval(tick, POLL_FAST)
    },

    stopPolling() { if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null } },

    // ── offline recovery ──
    enterOffline() {
      this.stopPolling()
      this.setState('OFFLINE')
      const startedAt = Date.now()
      this.offlineTimer = setInterval(() => {
        if (Date.now() - startedAt > OFFLINE_CAP_MS) {
          clearInterval(this.offlineTimer); this.offlineTimer = null
          this.setState('IDLE'); this.footer.setProperty(prop.TEXT, 'offline — tap COMMAND to retry'); return
        }
        this.request({ method: 'PING', params: {} })
          .then(() => {
            this.consecutiveFailures = 0
            clearInterval(this.offlineTimer); this.offlineTimer = null
            this.setState('IDLE'); this.footer.setProperty(prop.TEXT, 'back online')
          })
          .catch(() => {})
      }, OFFLINE_RETRY)
    },

    cleanup() {
      if (this.recording) this.stopRecord(false)
      this.stopPolling()
      if (this.offlineTimer) { clearInterval(this.offlineTimer); this.offlineTimer = null }
    },

    onDestroy() {
      if (this.clockTimer) clearInterval(this.clockTimer)
      this.cleanup()
    },
  })
)

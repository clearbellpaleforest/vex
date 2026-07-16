/*
 * VexCom — watch UI for 480x480 CIRCULAR display.  pages/index.js
 *
 * All widgets centered within 280px safe band (x:100-380).
 * Round display clips corners — stay away from edges.
 */
import { createWidget, widget, align, prop, text_style } from '@zos/ui'
import { BasePage } from '@zeppos/zml/base-page'

const CX = 240  // center x

Page(
  BasePage({
    build() {
      this.target = 'barrow'

      // Title
      createWidget(widget.TEXT, {
        x: 120, y: 40, w: 240, h: 30,
        text: 'VexCom', text_size: 24, color: 0xffaf00,
        align_h: align.CENTER_H, align_v: align.CENTER_V,
      })

      // Vex selector — 3 buttons, tightly centered
      createWidget(widget.BUTTON, {
        x: 100, y: 80, w: 86, h: 32, radius: 14,
        text: 'Barrow', text_size: 14,
        normal_color: 0xffaf00, press_color: 0xcc8800,
        click_func: () => this.select('barrow'),
      })
      createWidget(widget.BUTTON, {
        x: 196, y: 80, w: 86, h: 32, radius: 14,
        text: 'Thorne', text_size: 14,
        normal_color: 0x2a2a3e, press_color: 0x3a3a4e,
        click_func: () => this.select('thorne'),
      })
      createWidget(widget.BUTTON, {
        x: 292, y: 80, w: 86, h: 32, radius: 14,
        text: 'Mesh', text_size: 14,
        normal_color: 0x2a2a3e, press_color: 0x3a3a4e,
        click_func: () => this.loadMesh(),
      })

      // Indicator dot under active
      this.indicator = createWidget(widget.FILL_RECT, {
        x: 100, y: 114, w: 86, h: 3, radius: 1,
        color: 0xffaf00,
      })

      // Reply area — centered, narrower
      this.reply = createWidget(widget.TEXT, {
        x: 120, y: 130, w: 240, h: 290,
        text: 'pick a vex', text_size: 18, color: 0x888888,
        align_h: align.CENTER_H, align_v: align.TOP,
        text_style: text_style.WRAP,
      })

      // Separator
      createWidget(widget.FILL_RECT, {
        x: 140, y: 430, w: 200, h: 1, radius: 0,
        color: 0x222222,
      })

      // 5 quick prompts — tiny row at bottom, centered
      const prompts = ['status','work','news','memory','howru']
      prompts.forEach((p, i) => {
        createWidget(widget.BUTTON, {
          x: 100 + i * 56, y: 438, w: 50, h: 30, radius: 8,
          text: p, text_size: 11,
          normal_color: 0x1b3a4b, press_color: 0x2a5a72,
          click_func: () => this.ask(p),
        })
      })
    },

    select(who) {
      this.target = who
      const pos = { barrow: 100, thorne: 196, mesh: 292 }
      this.indicator.setProperty(prop.MORE, {
        x: pos[who] || 100, w: 86, h: 3,
        color: who === 'barrow' ? 0xffaf00 : (who === 'thorne' ? 0x7ec8e3 : 0xc084fc),
      })
    },

    ask(message) {
      const method = message === 'status' ? 'PING' : (message === 'work' ? 'ASK' : 'ASK')
      const label = method === 'PING' ? 'checking ' : 'asking '
      this.reply.setProperty(prop.TEXT, '--- ' + label + this.target + ' ---')
      const params = { message, target: this.target }
      if (message === 'work') params.message = 'what are you working on?'
      if (message === 'news') params.message = 'any news?'
      if (message === 'memory') params.message = 'memory check'
      if (message === 'howru') params.message = 'how are you?'
      this.request({ method, params })
        .then((data) => {
          this.reply.setProperty(prop.TEXT, (data && data.reply) || '(no reply)')
        })
        .catch((err) => {
          this.reply.setProperty(prop.TEXT, 'error:\n' + String(err).slice(0, 100))
        })
    },

    loadMesh() {
      this.select('mesh')
      this.reply.setProperty(prop.TEXT, '--- mesh ---')
      this.request({ method: 'MESH', params: { target: this.target } })
        .then((data) => {
          const msgs = (data && data.messages) || []
          if (!msgs.length) {
            this.reply.setProperty(prop.TEXT, '(no messages)')
            return
          }
          const lines = []
          const start = msgs.length > 6 ? msgs.length - 6 : 0
          for (let i = start; i < msgs.length; i++) {
            const m = msgs[i]
            const who = (m.sender || '?').replace('vex@', '').substring(0, 8)
            const txt = (m.body || '').substring(0, 45)
            lines.push(who + ': ' + txt)
          }
          this.reply.setProperty(prop.TEXT, lines.join('\n'))
        })
        .catch((err) => {
          this.reply.setProperty(prop.TEXT, 'mesh error:\n' + String(err).slice(0, 80))
        })
    },
  })
)

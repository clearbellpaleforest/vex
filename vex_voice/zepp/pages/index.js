/*
 * VexCom — device app (watch UI).  pages/index.js
 *
 * Barrow / Thorne / Mesh selector, prompts, and full mesh chat view.
 */
import { createWidget, widget, align, prop, text_style } from '@zos/ui'
import { BasePage } from '@zeppos/zml/base-page'

const PROMPTS = [
  'status',
  'what are you working on?',
  'any news?',
  'memory check',
  'how are you?',
]

Page(
  BasePage({
    build() {
      this.target = 'barrow'

      // Title
      createWidget(widget.TEXT, {
        x: 0, y: 6, w: 480, h: 26,
        text: 'VexCom', text_size: 22, color: 0xffaf00,
        align_h: align.CENTER_H, align_v: align.CENTER_V,
      })

      // Barrow button
      createWidget(widget.BUTTON, {
        x: 8, y: 34, w: 150, h: 26, radius: 10,
        text: 'Barrow', text_size: 15,
        normal_color: 0x2a2a3e, press_color: 0x3a3a4e,
        click_func: () => this.select('barrow'),
      })

      // Thorne button
      createWidget(widget.BUTTON, {
        x: 164, y: 34, w: 150, h: 26, radius: 10,
        text: 'Thorne', text_size: 15,
        normal_color: 0x2a2a3e, press_color: 0x3a3a4e,
        click_func: () => this.select('thorne'),
      })

      // Mesh button
      createWidget(widget.BUTTON, {
        x: 320, y: 34, w: 152, h: 26, radius: 10,
        text: 'Mesh', text_size: 15,
        normal_color: 0x2a1a3e, press_color: 0x3a2a4e,
        click_func: () => this.loadMesh(),
      })

      // Selection indicator
      this.indicator = createWidget(widget.FILL_RECT, {
        x: 8, y: 62, w: 150, h: 2, radius: 1,
        color: 0xffaf00,
      })

      // Reply / mesh area
      this.reply = createWidget(widget.TEXT, {
        x: 8, y: 68, w: 464, h: 400,
        text: 'pick a vex, tap a prompt', text_size: 16, color: 0x888888,
        align_h: align.CENTER_H, align_v: align.TOP,
        text_style: text_style.WRAP,
      })

      // Prompt buttons (after reply area, bottom row)
      PROMPTS.forEach((p, i) => {
        createWidget(widget.BUTTON, {
          x: 8 + i * 94, y: 445, w: 90, h: 28, radius: 8,
          text: p, text_size: 12,
          normal_color: 0x1b3a4b, press_color: 0x2a5a72,
          click_func: () => this.ask(p),
        })
      })
    },

    select(who) {
      this.target = who
      this.indicator.setProperty(prop.MORE, {
        x: who === 'barrow' ? 8 : 164,
        w: 150, h: 2,
        color: who === 'barrow' ? 0xffaf00 : 0x7ec8e3,
      })
    },

    ask(message) {
      const method = message === 'status' ? 'PING' : 'ASK'
      this.reply.setProperty(prop.TEXT, '--- ' + this.target + ' ---')
      this.request({ method, params: { message, target: this.target } })
        .then((data) => {
          this.reply.setProperty(prop.TEXT, (data && data.reply) || '(no reply)')
        })
        .catch((err) => {
          this.reply.setProperty(prop.TEXT, this.target + ' error:\n' + String(err).slice(0, 120))
        })
    },

    loadMesh() {
      this.indicator.setProperty(prop.MORE, { x: 320, w: 152, h: 2, color: 0xc084fc })
      this.reply.setProperty(prop.TEXT, '--- loading mesh ---')
      this.request({ method: 'MESH', params: { target: this.target } })
        .then((data) => {
          const msgs = (data && data.messages) || []
          if (!msgs.length) {
            this.reply.setProperty(prop.TEXT, '(no messages)')
            return
          }
          const lines = msgs.slice(-8).map(m => {
            const who = (m.sender || '?').replace('vex@', '').slice(0, 12)
            const txt = (m.body || '').slice(0, 60)
            return who + ': ' + txt
          })
          this.reply.setProperty(prop.TEXT, lines.join('\n'))
        })
        .catch((err) => {
          this.reply.setProperty(prop.TEXT, 'mesh error:\n' + String(err).slice(0, 100))
        })
    },
  })
)

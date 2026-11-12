// Hermes Agent Radio — the desktop half.
//
// The player is a plain web page served by the station (`/ink`), shown in the SDK's sandboxed frame.
// This file is only a host: it puts the bar under the composer, a full page in the workspace, a
// status-bar dot, and a way to detach the object into its own window. Nothing here holds state or decides what plays — the page reads
// `/now-playing.json` and writes through the station's own endpoints, so the dock, the page, the
// detached window and the public site cannot drift apart.
//
// Hook-free render trees only: hook-based components from the plugin realm mount as silent nulls in
// the shipped desktop release. Everything below is a plain element with inline styles, plus the
// SDK's own SandboxedFrame for the station pages.
//
// jsx-runtime contract: the THIRD argument is the key. Children always ride inside props.children.

import { jsx } from 'react/jsx-runtime'
import { SandboxedFrame } from '@hermes/plugin-sdk'

const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const COMPOSER_UNDERSIDE = 'composer.underside'
// The app's own area name (apps/desktop/src/sdk/areas.ts, STATUSBAR_AREAS.right). A different spelling
// is accepted by the registry and never shown (P-126).
const STATUSBAR_RIGHT = 'statusBar.right'

// The public station. A self-hosted one is set under Settings → Plugins → Hermes Agent Radio, kept in
// the plugin's own ctx.storage (see README).
const DEFAULT_STATION = 'https://hermesagentradio.com'
const STATION_KEY = 'stationUrl'
const DOCK_HEIGHT = 47
// Plain http only for a station on this machine, the same rule the tools' station_url follows.
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]'])

function el(tag, props, ...kids) {
  // A children array needs stable keys or React warns on every mount; position is stable here.
  const children =
    kids.length === 1
      ? kids[0]
      : kids.map((kid, index) =>
          // only elements get a key; a text child stays text (P-126: it became a typeless element)
          kid && typeof kid === 'object' && kid.key == null ? jsx(kid.type, kid.props, String(index)) : kid
        )
  return jsx(tag, { ...props, children })
}

// ctx.storage, set in register(). Plugin-scoped (hermes.plugin.<id>.*), not the shared web storage.
let storage = null

// A station address the player may embed, or null: https anywhere, http only on this machine, no
// credentials, query or fragment. The result has no trailing slash.
function normaliseStation(raw) {
  if (typeof raw !== 'string') return null
  const text = raw.trim()
  if (!text) return null
  let url
  try {
    url = new URL(text)
  } catch {
    return null
  }
  const secure = url.protocol === 'https:'
  const local = url.protocol === 'http:' && LOOPBACK_HOSTS.has(url.hostname)
  if (!secure && !local) return null
  if (url.username || url.password || url.search || url.hash) return null
  return (url.origin + url.pathname).replace(/\/+$/, '')
}

function savedStation() {
  try {
    return storage ? storage.get(STATION_KEY, '') : ''
  } catch {
    return ''
  }
}

function stationBase() {
  return normaliseStation(savedStation()) || DEFAULT_STATION
}

function pageUrl(query) {
  return stationBase() + '/ink' + (query ? '?' + query : '')
}

// Detach opens the page in the system browser: a real, movable, always-available window that
// survives a reload. Use the host's own call when it offers one (P-30). Otherwise fall back to
// window.open, which the app denies by design and hands to the same system browser.
let openWithHost = null

function openDetached(url) {
  if (openWithHost) {
    openWithHost(url)
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer,popup=yes,width=600,height=405,resizable=yes')
}

// Every station frame this plugin has mounted, and what it is. The station pages run in the SDK's
// sandboxed frame, so they have an opaque origin: a message is trusted only when its source IS one
// of these frames' windows, never by its origin or by anything the message says.
const frames = new Map()

function trackFrame(kind) {
  return (node) => {
    if (!node) {
      // React without ref cleanups calls back with null on unmount: drop whatever left the page.
      for (const known of frames.keys()) if (!known.isConnected) frames.delete(known)
      return
    }
    frames.set(node, kind)
    return () => frames.delete(node)
  }
}

function frameFor(source) {
  if (!source) return null
  for (const [node, kind] of frames) {
    if (node.isConnected && node.contentWindow === source) return { node, kind }
  }
  return null
}

// The expanded bar lifts out of the footer by the panel's own height, capped so it never takes more
// than about a third of the window (P-148). Only the frame that asked is resized.
const LIFT_CAP = 0.36

function liftDock(node, requested) {
  const cap = Math.max(DOCK_HEIGHT, Math.round(window.innerHeight * LIFT_CAP))
  const height = Math.min(cap, Math.max(DOCK_HEIGHT, Math.round(requested)))
  const open = height > DOCK_HEIGHT
  node.style.height = height + 'px'
  const holder = node.parentElement
  if (holder) {
    holder.style.height = height + 'px'
    // open, the panel brings its own surface and its crest sits on the app background
    holder.style.background = open ? 'transparent' : '#0a0a0a'
    holder.style.boxShadow = open ? 'none' : 'inset 0 1px 0 rgba(247,244,237,.09), 0 6px 18px rgba(0,0,0,.35)'
  }
}

// The station's own player page, in the SDK's sandboxed frame: scripts run, the origin is opaque, so
// the page cannot reach the app, its storage or the bridge. Audio starts from the listener's own
// click inside the frame, so no autoplay allowance is asked for.
function frame(src, style, title, kind) {
  return jsx(SandboxedFrame, {
    src,
    title: title || 'Hermes Radio',
    ref: trackFrame(kind),
    style: { border: '0', display: 'block', background: 'transparent', ...style }
  })
}

// 01 — the bar under the composer. This is the dock: always present, never in the way.
function Dock() {
  return el(
    'div',
    {
      style: {
        width: '100%',
        height: DOCK_HEIGHT + 'px',
        background: '#0a0a0a',
        transition: 'height .28s cubic-bezier(.3,.9,.2,1)',
        borderRadius: '12px',
        boxShadow: 'inset 0 1px 0 rgba(247,244,237,.09), 0 6px 18px rgba(0,0,0,.35)',
        overflow: 'hidden'
      }
    },
    frame(pageUrl('embed=1'), { width: '100%', height: DOCK_HEIGHT + 'px' }, 'Hermes Radio bar', 'dock')
  )
}

// 02 — the full page: the expanded panel, with the bar beneath it.
// One frame: the panel page in fill mode carries its own bar under the panel, so a second bar here
// would show twice, and without fill the panel sits at the bottom of a light page (P-126).
function PlayerPage() {
  return el(
    'div',
    { style: { display: 'flex', flexDirection: 'column', height: '100%', background: '#0f0f0f' } },
    frame(pageUrl('state=panel&fill=1'), { flex: '1', width: '100%', minHeight: '0' }, 'Hermes Radio', 'page')
  )
}

// 03 — a status-bar dot, so the station is visible when the composer is out of view.
function StatusRadio() {
  return el(
    'button',
    {
      type: 'button',
      title: 'Hermes Agent Radio',
      onClick: () => openDetached(pageUrl('state=pebble')),
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        height: '18px',
        padding: '0 7px',
        border: '0',
        borderRadius: '5px',
        background: 'transparent',
        color: 'inherit',
        font: '600 10px/1 ui-monospace, monospace',
        letterSpacing: '.14em',
        textTransform: 'uppercase',
        cursor: 'pointer'
      }
    },
    el('span', {
      style: {
        width: '7px',
        height: '7px',
        borderRadius: '50%',
        background: '#9135f5',
        boxShadow: '0 0 8px rgba(145,53,245,.9)'
      }
    }),
    'Radio'
  )
}

// Settings → Plugins → Hermes Agent Radio: the station the Desktop player embeds. Hook-free, like
// everything here: the input is uncontrolled and saves to ctx.storage as it is typed.
function StationSettings() {
  const saved = savedStation()
  const note = (text, bad) =>
    el('p', { 'data-radio-station-note': '1', style: { margin: '6px 0 0', fontSize: '12px', opacity: bad ? 1 : 0.7, color: bad ? '#e5484d' : 'inherit' } }, text)
  const hint = 'Empty uses the public station (' + DEFAULT_STATION + '). https anywhere; plain http only for a station on this machine. Applies the next time the player opens.'
  return el(
    'div',
    { style: { display: 'flex', flexDirection: 'column', gap: '6px', padding: '4px 0', maxWidth: '520px' } },
    el('label', { htmlFor: 'hermes-radio-station', style: { fontWeight: 600 } }, 'Station address (Desktop player)'),
    el('input', {
      id: 'hermes-radio-station',
      type: 'url',
      defaultValue: saved,
      placeholder: DEFAULT_STATION,
      spellCheck: false,
      style: { font: 'inherit', padding: '6px 8px', borderRadius: '6px', border: '1px solid rgba(127,127,127,.4)', background: 'transparent', color: 'inherit' },
      onChange: (event) => {
        const input = event.currentTarget
        const value = input.value.trim()
        const out = input.parentElement && input.parentElement.querySelector('[data-radio-station-note]')
        if (!value) {
          storage.remove(STATION_KEY)
          if (out) out.textContent = hint
          input.setAttribute('aria-invalid', 'false')
          return
        }
        const station = normaliseStation(value)
        input.setAttribute('aria-invalid', String(!station))
        if (station) storage.set(STATION_KEY, station)
        if (out) out.textContent = station ? 'Saved: ' + station + '. Applies the next time the player opens.' : 'Not saved: use https://…, or http:// only for localhost.'
      }
    }),
    note(hint, false)
  )
}

export default {
  id: 'hermes-agent-radio',
  name: 'Hermes Agent Radio',
  description: 'The station bar under the composer, a full player page, and a detached window.',
  register(ctx) {
    storage = ctx.storage || null
    openWithHost =
      ctx.os && typeof ctx.os.openExternal === 'function' ? (url) => ctx.os.openExternal(url) : null
    ctx.registerMany([
      {
        id: 'radio-dock',
        area: COMPOSER_UNDERSIDE,
        order: 40,
        render: () => el(Dock, {})
      },
      {
        id: 'radio-page',
        area: ROUTES_AREA,
        data: { path: '/radio' },
        render: () => el(PlayerPage, {})
      },
      {
        id: 'radio-nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/radio', label: 'Hermes Agent Radio', codicon: 'radio-tower' }
      },
      {
        id: 'radio-status',
        area: STATUSBAR_RIGHT,
        order: 140,
        // The element itself, not a nested component: the status bar shows a plugin component as an
        // error badge in the packaged app (P-126, seen 8 Nov), as the mixer plugin also found.
        render: () => StatusRadio()
      }
    ])
    if (storage && typeof ctx.registerSettingsPage === 'function') {
      ctx.registerSettingsPage({ id: 'station', title: 'Hermes Agent Radio', icon: 'radio-tower', render: () => StationSettings() })
    }

    // The detach control lives inside a frame, which cannot open a top-level window itself. Only this
    // plugin's own station frames may ask (matched by event.source, since a sandboxed frame's origin is
    // opaque), and the address opened is always built here: nothing in a message is opened.
    const onMessage = (event) => {
      const data = event.data
      if (!data || typeof data !== 'object') return
      const from = frameFor(event.source)
      if (!from) return
      if (data.type === 'hermes-radio:height' && typeof data.height === 'number') {
        if (from.kind === 'dock' && Number.isFinite(data.height)) liftDock(from.node, data.height)
        return
      }
      if (data.type === 'hermes-radio:detach') openDetached(pageUrl('state=pebble&popout=1'))
    }
    if (typeof ctx.addEventListener === 'function') ctx.addEventListener(window, 'message', onMessage)
    else window.addEventListener('message', onMessage)
  }
}

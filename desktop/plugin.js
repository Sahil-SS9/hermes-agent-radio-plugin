// Hermes Agent Radio — the desktop half.
//
// The player is a plain web page served by the station (`/ink`). This file is only a host: it puts
// the bar under the composer, a full page in the workspace, a status-bar dot, and a way to detach
// the object into its own window. Nothing here holds state or decides what plays — the page reads
// `/now-playing.json` and writes through the station's own endpoints, so the dock, the page, the
// detached window and the public site cannot drift apart.
//
// Hook-free render trees only: hook-based components from the plugin realm mount as silent nulls in
// the shipped desktop release. Everything below is a plain element with inline styles.
//
// jsx-runtime contract: the THIRD argument is the key. Children always ride inside props.children.

import { jsx } from 'react/jsx-runtime'

const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const COMPOSER_UNDERSIDE = 'composer.underside'
// The app's own area name (apps/desktop/src/sdk/areas.ts, STATUSBAR_AREAS.right). A different spelling
// is accepted by the registry and never shown (P-126).
const STATUSBAR_RIGHT = 'statusBar.right'

// The public station. A self-hosted one is set with localStorage 'devradio.station' (see README).
const DEFAULT_STATION = 'https://hermesagentradio.com'
const DOCK_HEIGHT = 47

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

function stationBase() {
  try {
    const stored = window.localStorage.getItem('devradio.station')
    if (stored) return stored.replace(/\/+$/, '')
  } catch {
    // A locked-down renderer can refuse localStorage; the default still works.
  }
  return DEFAULT_STATION
}

function stationOrigin() {
  try {
    return new URL(stationBase()).origin
  } catch {
    return null
  }
}

function isStationPage(origin, url) {
  const own = stationOrigin()
  return own !== null && origin === own && url.startsWith(stationBase() + '/')
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
  window.open(url, '_blank', 'noopener,noreferrer,popup=yes,width=640,height=470,resizable=yes')
}

function frame(src, style, title) {
  return el('iframe', {
    title: title || 'Hermes Radio',
    src,
    // The station's own player page; audio needs the autoplay allowance.
    style: { border: '0', display: 'block', background: 'transparent', ...style },
    allow: 'autoplay'
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
        borderRadius: '12px',
        boxShadow: 'inset 0 1px 0 rgba(247,244,237,.09), 0 6px 18px rgba(0,0,0,.35)',
        overflow: 'hidden'
      }
    },
    frame(pageUrl('embed=1'), { width: '100%', height: DOCK_HEIGHT + 'px' }, 'Hermes Radio bar')
  )
}

// 02 — the full page: the expanded panel, with the bar beneath it.
// One frame: the panel page in fill mode carries its own bar under the panel, so a second bar here
// would show twice, and without fill the panel sits at the bottom of a light page (P-126).
function PlayerPage() {
  return el(
    'div',
    { style: { display: 'flex', flexDirection: 'column', height: '100%', background: '#0f0f0f' } },
    frame(pageUrl('state=panel&fill=1'), { flex: '1', width: '100%', minHeight: '0' }, 'Hermes Radio')
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

export default {
  id: 'hermes-agent-radio',
  name: 'Hermes Agent Radio',
  description: 'The station bar under the composer, a full player page, and a detached window.',
  register(ctx) {
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

    // The detach control lives inside an iframe, which cannot open a top-level window itself.
    // Only the station's own frames may ask, and only for the station's own pages: any page shown
    // inside the app can post a message, and the host opens whatever it is given (P-126).
    window.addEventListener('message', (event) => {
      const data = event.data
      if (!data || typeof data !== 'object') return
      if (data.type !== 'hermes-radio:detach' || typeof data.url !== 'string') return
      if (isStationPage(event.origin, data.url)) openDetached(data.url)
    })
  }
}

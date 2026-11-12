// Behavioural harness for desktop/plugin.js, run by tests/test_desktop.py under node.
//
// It loads the real file with its two imports replaced by stand-ins (the jsx runtime records the
// tree; the SDK's SandboxedFrame is a marker function), with a fake window/document in which
// touching `localStorage` throws. Each check prints one line; any failure exits 1.

import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const DEFAULT = 'https://hermesagentradio.com'

let failures = 0
function check(name, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || detail === undefined ? '' : ' :: ' + detail}`)
  if (!ok) failures++
}

function load(saved) {
  function SandboxedFrame() {}
  const jsx = (type, props, key) => ({ type, props: props || {}, key: key ?? null })
  const listeners = []
  const opened = []
  const store = new Map(saved === undefined ? [] : [['stationUrl', saved]])
  const storage = {
    get: (k, d) => (store.has(k) ? store.get(k) : d),
    set: (k, v) => store.set(k, v),
    remove: (k) => store.delete(k)
  }
  const window = {
    innerHeight: 1000,
    addEventListener: (type, fn) => listeners.push([type, fn]),
    open: (url) => opened.push(['window.open', url])
  }
  Object.defineProperty(window, 'localStorage', {
    get() {
      throw new Error('raw localStorage touched')
    }
  })
  const document = {
    querySelectorAll() {
      throw new Error('document scan: frames must be matched by ref, not by selector')
    }
  }
  const sandbox = { window, document, URL, console, __deps: { jsx, SandboxedFrame }, __out: {} }
  const code = source
    .replace("import { jsx } from 'react/jsx-runtime'", 'const { jsx } = __deps')
    .replace("import { SandboxedFrame } from '@hermes/plugin-sdk'", 'const { SandboxedFrame } = __deps')
    .replace('export default {', '__out.plugin = {')
  vm.runInNewContext(code, sandbox)
  const plugin = sandbox.__out.plugin
  const registered = []
  const settings = []
  const ctx = {
    storage,
    os: { openExternal: (url) => opened.push(['openExternal', url]) },
    registerMany: (cs) => registered.push(...cs),
    registerSettingsPage: (page) => settings.push(page),
    addEventListener: (target, type, fn) => {
      if (target !== window) throw new Error('listener not on window')
      listeners.push([type, fn])
    }
  }
  plugin.register(ctx)
  return { plugin, registered, settings, listeners, opened, store, SandboxedFrame, window }
}

// Walk a render tree, calling function components (except the SandboxedFrame marker).
function expand(node, SandboxedFrame, out = []) {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) {
    node.forEach((n) => expand(n, SandboxedFrame, out))
    return out
  }
  if (typeof node.type === 'function' && node.type !== SandboxedFrame) {
    return expand(node.type(node.props), SandboxedFrame, out)
  }
  out.push(node)
  expand(node.props.children, SandboxedFrame, out)
  return out
}

function frames(env, id) {
  const c = env.registered.find((r) => r.id === id)
  return expand(c.render(), env.SandboxedFrame).filter((n) => n.type === env.SandboxedFrame)
}

function mount(frameNode) {
  // A fake iframe element for the frame's ref, inside a holder, as React would attach it.
  const holder = { style: {} }
  const contentWindow = { name: 'station-frame' }
  const node = { isConnected: true, contentWindow, parentElement: holder, style: {} }
  const cleanup = frameNode.props.ref(node)
  return { node, holder, contentWindow, cleanup }
}

function post(env, source, data, origin = 'null') {
  for (const [type, fn] of env.listeners) if (type === 'message') fn({ source, data, origin })
}

// 1. Every station frame is the SDK's SandboxedFrame; nothing renders a raw iframe or asks for autoplay.
{
  const env = load()
  const dock = frames(env, 'radio-dock')
  const page = frames(env, 'radio-page')
  check('dock renders one SandboxedFrame', dock.length === 1)
  check('page renders one SandboxedFrame', page.length === 1)
  const all = ['radio-dock', 'radio-page'].flatMap((id) =>
    expand(env.registered.find((r) => r.id === id).render(), env.SandboxedFrame)
  )
  check('no raw <iframe> element', !all.some((n) => n.type === 'iframe'))
  check('no allow/autoplay prop', ![...dock, ...page].some((n) => 'allow' in n.props || 'sandbox' in n.props))
  check('frames only pass SDK props', [...dock, ...page].every((n) => Object.keys(n.props).every((k) => ['src', 'title', 'style', 'ref'].includes(k))))
  check('dock src is the public bar', dock[0].props.src === DEFAULT + '/ink?embed=1', dock[0].props.src)
  check('page src is the public panel', page[0].props.src === DEFAULT + '/ink?state=panel&fill=1', page[0].props.src)
  check('frames are titled', [...dock, ...page].every((n) => typeof n.props.title === 'string' && n.props.title))
}

// 2. Messages are trusted by event.source (the frame's own window), never by origin or content.
{
  const env = load()
  const dock = mount(frames(env, 'radio-dock')[0])
  const page = mount(frames(env, 'radio-page')[0])
  post(env, dock.contentWindow, { type: 'hermes-radio:height', height: 200 })
  check('dock frame lifts itself (opaque origin "null")', dock.node.style.height === '200px' && dock.holder.style.height === '200px', JSON.stringify(dock.node.style))
  post(env, dock.contentWindow, { type: 'hermes-radio:height', height: 99999 })
  check('lift is capped', dock.node.style.height === '360px', dock.node.style.height)
  const before = page.node.style.height
  post(env, page.contentWindow, { type: 'hermes-radio:height', height: 300 })
  check('the full page is never resized by a height message', page.node.style.height === before)

  const stranger = { name: 'another frame' }
  post(env, stranger, { type: 'hermes-radio:height', height: 120 }, DEFAULT)
  check('a frame that is not ours cannot resize the dock, even with the station origin', dock.node.style.height === '360px')
  post(env, stranger, { type: 'hermes-radio:detach', url: DEFAULT + '/ink?state=pebble' }, DEFAULT)
  check('a frame that is not ours cannot detach, even with the station origin', env.opened.length === 0, JSON.stringify(env.opened))

  post(env, dock.contentWindow, { type: 'hermes-radio:detach', url: 'https://evil.example/phish' })
  check(
    'our frame detaches to the address built here, never the one in the message',
    env.opened.length === 1 && env.opened[0][0] === 'openExternal' && env.opened[0][1] === DEFAULT + '/ink?state=pebble&popout=1',
    JSON.stringify(env.opened)
  )
  post(env, dock.contentWindow, { type: 'hermes-radio:detach' })
  check('detach needs no url in the message', env.opened.length === 2)

  // Unmount: React 19 calls the ref cleanup; the window is no longer trusted afterwards.
  dock.cleanup()
  post(env, dock.contentWindow, { type: 'hermes-radio:detach' })
  check('an unmounted frame is forgotten', env.opened.length === 2)
  // React without ref cleanups calls back with null: a disconnected node is dropped.
  page.node.isConnected = false
  frames(env, 'radio-page')[0].props.ref(null)
  post(env, page.contentWindow, { type: 'hermes-radio:detach' })
  check('a disconnected frame is never trusted', env.opened.length === 2)
}

// 3. The self-hosted address comes from ctx.storage, with the tools' https/loopback rule.
{
  const cases = [
    [undefined, DEFAULT],
    ['', DEFAULT],
    ['http://127.0.0.1:8799', 'http://127.0.0.1:8799'],
    ['http://localhost:8799/', 'http://localhost:8799'],
    ['https://radio.example.org/', 'https://radio.example.org'],
    ['http://radio.example.org', DEFAULT],
    ['javascript:alert(1)', DEFAULT],
    ['https://user:pw@radio.example.org', DEFAULT],
    ['https://radio.example.org/?x=1', DEFAULT],
    ['not a url', DEFAULT]
  ]
  for (const [saved, base] of cases) {
    const env = load(saved)
    const src = frames(env, 'radio-dock')[0].props.src
    check(`station ${JSON.stringify(saved)} -> ${base}`, src === base + '/ink?embed=1', src)
  }
}

// 4. The settings page saves through ctx.storage only.
{
  const env = load()
  check('one settings page registered', env.settings.length === 1 && env.settings[0].title === 'Hermes Agent Radio')
  const tree = expand(env.settings[0].render(), env.SandboxedFrame)
  const input = tree.find((n) => n.type === 'input')
  check('settings page has an address input', Boolean(input))
  const note = { textContent: '' }
  const attrs = {}
  const target = (value) => ({
    value,
    setAttribute: (k, v) => (attrs[k] = v),
    parentElement: { querySelector: () => note }
  })
  input.props.onChange({ currentTarget: target('http://127.0.0.1:8799/') })
  check('a loopback address is saved, normalised', env.store.get('stationUrl') === 'http://127.0.0.1:8799', env.store.get('stationUrl'))
  input.props.onChange({ currentTarget: target('http://radio.example.org') })
  check('plain http off this machine is refused and not saved', env.store.get('stationUrl') === 'http://127.0.0.1:8799' && attrs['aria-invalid'] === 'true')
  input.props.onChange({ currentTarget: target('  ') })
  check('an empty field clears the saved address', !env.store.has('stationUrl'))
}

// 5. The file never touches raw localStorage (the fake window throws if it does) and imports only
//    the jsx runtime and the SDK.
{
  const imports = source.split('\n').filter((l) => l.startsWith('import '))
  check(
    'imports are the jsx runtime and the SDK only',
    JSON.stringify(imports) === JSON.stringify(["import { jsx } from 'react/jsx-runtime'", "import { SandboxedFrame } from '@hermes/plugin-sdk'"]),
    JSON.stringify(imports)
  )
  check('no localStorage in the source', !source.includes('localStorage'))
}

console.log(failures ? `${failures} FAILED` : 'ALL OK')
process.exit(failures ? 1 : 0)

import './style.css'

type Status = 'disconnected' | 'connecting' | 'connected' | 'error'

interface HvacState {
  occupation: number
  ventilation: number
  offset_temp: number
  window_alarm: number
  alarm: number
  count: number
}

interface Module {
  mac: string
  name: string | null
  label: string
  /** Favori ★ : en tête de liste, sans effet sur la connexion. */
  pinned: boolean
  rssi: number | null
  last_seen: number | null
  /** « Connexion auto » : connecté en permanence, pas de déconnexion possible. */
  auto_connect: boolean
  /** « Maintenir la connexion » : reste connecté entre les commandes jusqu'à « Se déconnecter ». */
  keep_connected: boolean
  /** Liaison tenue en mode maintien (connecté, et pas encore « Se déconnecter »). */
  held: boolean
  status: Status
  error: string | null
  state: HvacState | null
  last_ms: number | null
  blind: 'up' | 'down' | null
  points: Record<string, number>
}

type Bluetooth = 'on' | 'off' | 'absent' | 'unknown'

type ServerMessage =
  | { type: 'snapshot'; modules: Module[]; scanning: boolean; bluetooth?: Bluetooth }
  | { type: 'module'; module: Module }
  | { type: 'scanning'; scanning: boolean }
  | { type: 'bluetooth'; state: Bluetooth }

interface CommandResult {
  frame: string
  frames: string[]
  write_ms: number
  total_ms: number
}

const ACTION_TEXT: Record<string, string> = {
  'light:on': 'lumière allumée',
  'light:off': 'lumière éteinte',
  'blind:up': 'stores en montée',
  'blind:down': 'stores en descente',
  'blind:stop': 'stores arrêtés',
}

/** Au-delà, l'appui sur ▲/▼ oriente les lames au lieu de lancer la course (comme l'app d'origine). */
const LONG_PRESS_MS = 450

const modules = new Map<string, Module>()
const cards = new Map<string, Card>()

function el<T extends Element>(selector: string, root: ParentNode = document): T {
  const found = root.querySelector<T>(selector)
  if (!found) throw new Error(`élément introuvable : ${selector}`)
  return found
}

const displayName = (m: Module) => m.label || m.name || m.mac

// --- API ----------------------------------------------------------------------

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  if (!res.ok) throw new Error(text || `HTTP ${res.status}`)
  return (text ? JSON.parse(text) : {}) as T
}

const modulePath = (mac: string) => `/modules/${encodeURIComponent(mac)}`

// --- Toast ----------------------------------------------------------------------

const toastEl = el<HTMLOutputElement>('#toast')
let toastTimer: number | undefined

function toast(message: string, isError = false) {
  toastEl.textContent = message
  toastEl.classList.toggle('error', isError)
  toastEl.classList.add('visible')
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => toastEl.classList.remove('visible'), isError ? 5000 : 2500)
}

// --- Carte d'un module ------------------------------------------------------------

const template = el<HTMLTemplateElement>('#card-template')

const STATUS_TEXT: Record<Status, string> = {
  connected: 'Connecté',
  connecting: 'Connexion…',
  disconnected: 'Déconnecté',
  error: 'Injoignable',
}

type Setting = 'auto_connect' | 'keep_connected'

/** Le module doit rester connecté (et être reconnecté s'il décroche). */
const wanted = (m: Module) => m.auto_connect || (m.keep_connected && m.held)

function modeHint(m: Module): string {
  if (m.auto_connect) return 'Connecté en permanence : commandes immédiates.'
  if (m.keep_connected) return 'Reste connecté entre les commandes, jusqu’à « Se déconnecter ».'
  return 'Chaque commande se connecte (3 à 5 s), puis libère le module.'
}

function signalLevel(rssi: number | null): number {
  if (rssi === null) return 0
  if (rssi >= -65) return 4
  if (rssi >= -75) return 3
  if (rssi >= -85) return 2
  return 1
}

function hvacChips(s: HvacState): string[] {
  const chips = [s.occupation === 1 ? 'Occupé' : 'Inoccupé']
  chips.push(s.ventilation === 0 ? 'Ventilation arrêtée' : s.ventilation >= 4 ? 'Ventilation auto' : `Ventilation ${s.ventilation}`)
  const offset = s.offset_temp - 6
  chips.push(`Consigne ${offset > 0 ? '+' : offset < 0 ? '−' : '±'}${Math.abs(offset)}`)
  if (s.window_alarm) chips.push('Fenêtre ouverte')
  if (s.alarm) chips.push('Alarme')
  return chips
}

class Card {
  readonly el: HTMLElement
  private m: Module
  private queue: Promise<unknown> = Promise.resolve()
  private readonly label: HTMLInputElement
  private readonly pin: HTMLButtonElement
  private readonly linkButton: HTMLButtonElement
  private readonly settings: Record<Setting, HTMLInputElement>

  constructor(m: Module) {
    this.m = m
    this.el = (template.content.firstElementChild as HTMLElement).cloneNode(true) as HTMLElement
    this.label = el<HTMLInputElement>('.label', this.el)
    this.pin = el<HTMLButtonElement>('.pin', this.el)
    this.linkButton = el<HTMLButtonElement>('.link-btn', this.el)
    this.settings = {
      auto_connect: el<HTMLInputElement>('[data-setting="auto_connect"]', this.el),
      keep_connected: el<HTMLInputElement>('[data-setting="keep_connected"]', this.el),
    }
    this.bind()
    this.update(m)
  }

  /** Les commandes d'un même module partent dans l'ordre (ex. « + » puis « stop »). */
  private enqueue(kind: string, action: string, button?: HTMLElement, quiet = false) {
    button?.setAttribute('aria-busy', 'true')
    const job = this.queue.then(async () => {
      try {
        const r = await api<CommandResult>('POST', `${modulePath(this.m.mac)}/command`, { kind, action })
        if (!quiet) {
          const text = ACTION_TEXT[`${kind}:${action}`] ?? `${kind} ${action}`
          const reversed = r.frames.length > 1 ? ' (arrêt puis inversion)' : ''
          toast(`${displayName(this.m)} — ${text}${reversed} · ${r.total_ms} ms`)
        }
      } catch (e) {
        toast(`${displayName(this.m)} — ${e instanceof Error ? e.message : String(e)}`, true)
      } finally {
        button?.removeAttribute('aria-busy')
      }
    })
    this.queue = job
  }

  private bind() {
    for (const button of this.el.querySelectorAll<HTMLButtonElement>('[data-cmd]')) {
      button.addEventListener('click', () => {
        const [kind, action] = button.dataset.cmd!.split(':')
        this.enqueue(kind, action, button)
      })
    }

    // Variation : maintenir le bouton envoie up/down, le relâcher envoie stop (comme l'app d'origine).
    for (const button of this.el.querySelectorAll<HTMLButtonElement>('[data-hold]')) {
      const [kind, action] = button.dataset.hold!.split(':')
      let held = false
      const start = () => {
        if (held) return
        held = true
        button.classList.add('held')
        this.enqueue(kind, action, undefined, true)
      }
      const end = () => {
        if (!held) return
        held = false
        button.classList.remove('held')
        this.enqueue(kind, 'stop', undefined, true)
      }
      button.addEventListener('pointerdown', (e) => {
        button.setPointerCapture(e.pointerId)
        start()
      })
      button.addEventListener('pointerup', end)
      button.addEventListener('pointercancel', end)
      button.addEventListener('lostpointercapture', end)
      button.addEventListener('keydown', (e) => {
        if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) {
          e.preventDefault()
          start()
        }
      })
      button.addEventListener('keyup', (e) => {
        if (e.key === ' ' || e.key === 'Enter') end()
      })
      button.addEventListener('blur', end)
    }

    // Stores : clic = course / arrêt (bascule), appui long = orientation des lames tant qu'on maintient.
    for (const button of this.el.querySelectorAll<HTMLButtonElement>('[data-blind]')) {
      const direction = button.dataset.blind as 'up' | 'down'
      let timer: number | undefined
      let tilting = false
      let swallowClick = false
      button.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return
        button.setPointerCapture(e.pointerId)
        timer = window.setTimeout(() => {
          tilting = true
          button.classList.add('held')
          this.enqueue('blind', `rot_${direction}`, undefined, true)
        }, LONG_PRESS_MS)
      })
      const release = () => {
        window.clearTimeout(timer)
        if (!tilting) return
        tilting = false
        swallowClick = true
        button.classList.remove('held')
        this.enqueue('blind', 'rot_stop', undefined, true)
      }
      button.addEventListener('pointerup', release)
      button.addEventListener('pointercancel', release)
      button.addEventListener('lostpointercapture', release)
      button.addEventListener('contextmenu', (e) => e.preventDefault())
      button.addEventListener('click', () => {
        if (swallowClick) {
          swallowClick = false
          return
        }
        this.enqueue('blind', this.m.blind === direction ? 'stop' : direction, button)
      })
    }

    // « Se connecter » / « Se déconnecter » : mode « Maintenir la connexion » uniquement.
    this.linkButton.addEventListener('click', async () => {
      const action = this.m.status === 'connected' || wanted(this.m) ? 'disconnect' : 'connect'
      this.linkButton.setAttribute('aria-busy', 'true')
      try {
        await api('POST', `${modulePath(this.m.mac)}/${action}`)
      } catch (e) {
        toast(`${displayName(this.m)} — ${e instanceof Error ? e.message : String(e)}`, true)
      } finally {
        this.linkButton.removeAttribute('aria-busy')
      }
    })

    for (const [setting, input] of Object.entries(this.settings) as [Setting, HTMLInputElement][]) {
      input.addEventListener('change', async () => {
        input.setAttribute('aria-busy', 'true')
        try {
          await api('PATCH', modulePath(this.m.mac), { [setting]: input.checked })
        } catch (e) {
          this.update(this.m) // réaffiche le réglage en vigueur
          toast(`${displayName(this.m)} — ${e instanceof Error ? e.message : String(e)}`, true)
        } finally {
          input.removeAttribute('aria-busy')
        }
      })
    }

    this.pin.addEventListener('click', async () => {
      try {
        await api('PATCH', modulePath(this.m.mac), { pinned: !this.m.pinned })
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), true)
      }
    })

    this.label.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.label.blur()
      if (e.key === 'Escape') {
        this.label.value = this.m.label
        this.label.blur()
      }
    })
    this.label.addEventListener('change', async () => {
      try {
        await api('PATCH', modulePath(this.m.mac), { label: this.label.value })
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), true)
      }
    })
  }

  update(m: Module) {
    this.m = m
    this.el.dataset.status = m.status
    this.el.dataset.pinned = String(m.pinned)

    if (document.activeElement !== this.label) this.label.value = m.label
    this.label.placeholder = m.name ?? m.mac
    el('.meta', this.el).textContent = m.label ? `${m.name ?? '?'} · ${m.mac}` : m.mac

    this.pin.setAttribute('aria-pressed', String(m.pinned))
    const pinText = m.pinned ? 'Retirer des favoris' : 'Ajouter aux favoris (en tête de liste)'
    this.pin.title = pinText
    this.pin.setAttribute('aria-label', pinText)

    const statusText = el<HTMLSpanElement>('.status-text', this.el)
    statusText.textContent = m.status === 'disconnected' && wanted(m) ? 'Reconnexion…' : STATUS_TEXT[m.status]
    statusText.title = m.error ?? ''

    // Connexion auto : pas de déconnexion possible ; sans maintien, chaque commande se connecte seule.
    this.linkButton.hidden = !m.keep_connected || m.auto_connect
    if (wanted(m) || m.status === 'connected') this.linkButton.textContent = 'Se déconnecter'
    else this.linkButton.textContent = m.status === 'connecting' ? 'Connexion…' : 'Se connecter'
    this.linkButton.disabled = m.status === 'connecting' && !wanted(m)

    this.settings.auto_connect.checked = m.auto_connect
    // La connexion auto implique le maintien : affiché coché, et non modifiable tant qu'elle est active.
    this.settings.keep_connected.checked = m.keep_connected || m.auto_connect
    this.settings.keep_connected.disabled = m.auto_connect
    el('.mode-hint', this.el).textContent = modeHint(m)

    for (const button of this.el.querySelectorAll<HTMLButtonElement>('[data-blind]')) {
      button.setAttribute('aria-pressed', String(m.blind === button.dataset.blind))
    }
    el('.signal', this.el).setAttribute('data-level', String(signalLevel(m.rssi)))
    el('.rssi', this.el).textContent = m.rssi === null ? '' : `${m.rssi} dBm`
    el('.latency', this.el).textContent = m.last_ms === null ? '' : `· ${m.last_ms} ms`

    const hvac = el<HTMLDivElement>('.hvac', this.el)
    hvac.replaceChildren(
      ...(m.state ? hvacChips(m.state) : []).map((text) => {
        const chip = document.createElement('span')
        chip.className = 'chip'
        chip.textContent = text
        return chip
      }),
    )
  }
}

// --- Disposition -------------------------------------------------------------------

const pinnedGrid = el<HTMLDivElement>('#pinned .grid')
const othersGrid = el<HTMLDivElement>('#others .grid')

function layout() {
  const sorted = [...modules.values()].sort(
    (a, b) =>
      Number(b.pinned) - Number(a.pinned) ||
      (b.rssi ?? -999) - (a.rssi ?? -999) ||
      displayName(a).localeCompare(displayName(b)),
  )
  // Ne déplace que les cartes mal placées : déplacer un nœud lui fait perdre le focus.
  const next = new Map<HTMLElement, number>([[pinnedGrid, 0], [othersGrid, 0]])
  for (const m of sorted) {
    const card = cards.get(m.mac)
    if (!card) continue
    const grid = m.pinned ? pinnedGrid : othersGrid
    const index = next.get(grid)!
    if (grid.children[index] !== card.el) grid.insertBefore(card.el, grid.children[index] ?? null)
    next.set(grid, index + 1)
  }
  el<HTMLElement>('#pinned-empty').hidden = sorted.some((m) => m.pinned)
  el<HTMLElement>('#others').hidden = !sorted.some((m) => !m.pinned)
  el<HTMLElement>('#pinned').hidden = sorted.length === 0
  updateWelcome()
}

let scanning = false

/** Message d'accueil tant qu'aucun module n'est connu (premier lancement). */
function updateWelcome() {
  const welcome = el<HTMLParagraphElement>('#all-empty')
  welcome.hidden = modules.size > 0
  welcome.textContent = scanning
    ? 'Recherche des modules Arcom à proximité…'
    : 'Aucun module trouvé pour l’instant. Approchez-vous d’un module Arcom puis cliquez sur « Rechercher ». ' +
      'Ensuite, mettez le vôtre en favori avec l’étoile ★.'
}

const BLUETOOTH_TEXT: Partial<Record<Bluetooth, string>> = {
  off: 'Le Bluetooth de cet ordinateur est désactivé. Activez-le (Paramètres Windows › Bluetooth et appareils) : la télécommande reprendra toute seule.',
  absent: 'Aucun adaptateur Bluetooth détecté sur cet ordinateur : la télécommande en a besoin pour piloter les modules.',
}

function setBluetooth(state: Bluetooth) {
  const banner = el<HTMLDivElement>('#bt-banner')
  const text = BLUETOOTH_TEXT[state]
  banner.hidden = !text
  banner.textContent = text ?? ''
}

function upsert(m: Module): boolean {
  const previous = modules.get(m.mac)
  modules.set(m.mac, m)
  const card = cards.get(m.mac)
  if (card) {
    card.update(m)
  } else {
    cards.set(m.mac, new Card(m))
  }
  return !previous || previous.pinned !== m.pinned || previous.rssi !== m.rssi
}

// --- Serveur (WebSocket) -------------------------------------------------------------

const serverPill = el<HTMLSpanElement>('#server-pill')
const scanButton = el<HTMLButtonElement>('#scan')

function setServerUp(up: boolean) {
  serverPill.dataset.up = String(up)
  el('.text', serverPill).textContent = up ? 'Serveur connecté' : 'Serveur injoignable'
}

function setScanning(value: boolean) {
  scanning = value
  scanButton.disabled = value
  scanButton.setAttribute('aria-busy', String(value))
  el('.text', scanButton).textContent = value ? 'Recherche…' : 'Rechercher'
  updateWelcome()
}

function handle(msg: ServerMessage) {
  if (msg.type === 'snapshot') {
    const seen = new Set(msg.modules.map((m) => m.mac))
    for (const mac of [...modules.keys()]) {
      if (!seen.has(mac)) {
        cards.get(mac)?.el.remove()
        cards.delete(mac)
        modules.delete(mac)
      }
    }
    msg.modules.forEach(upsert)
    layout()
    setScanning(msg.scanning)
    if (msg.bluetooth) setBluetooth(msg.bluetooth)
  } else if (msg.type === 'module') {
    if (upsert(msg.module)) layout()
  } else if (msg.type === 'scanning') {
    setScanning(msg.scanning)
  } else if (msg.type === 'bluetooth') {
    setBluetooth(msg.state)
  }
}

let retryMs = 1000

function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`)
  ws.addEventListener('open', () => {
    retryMs = 1000
    setServerUp(true)
  })
  ws.addEventListener('message', (e) => handle(JSON.parse(e.data as string) as ServerMessage))
  ws.addEventListener('close', () => {
    setServerUp(false)
    window.setTimeout(connect, retryMs)
    retryMs = Math.min(retryMs * 2, 8000)
  })
}

scanButton.addEventListener('click', async () => {
  setScanning(true)
  try {
    const { modules: found } = await api<{ modules: Module[] }>('POST', '/scan', { duration: 8 })
    toast(`${found.length} module(s) connu(s)`)
  } catch (e) {
    toast(e instanceof Error ? e.message : String(e), true)
    setScanning(false)
  }
})

connect()

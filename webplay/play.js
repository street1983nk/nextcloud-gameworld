// Browser-Spike 04.2: Diagnose, Einzelspieler- und Mehrspieler-Start auf der eigenen Spielseite.
//
// Die Seite liest aus der Adresse nur zwei Werte (Whitelist): mode und build, dazu im
// Mehrspieler-Modus das Ein-Mal-Ticket aus dem Fragment (#t=...). Das Fragment geht nie
// an einen Server und wird sofort aus Adresszeile und Verlauf entfernt (T-04.2-38).
// Ticket, WS-Ticket und Passwort landen nie in console oder Diagnose (T-04.2-39).
// Nie die Argument-Helfer von launcher.js für die Adresse benutzen: Sie würden
// Name und Passwort aus der Adresse übernehmen (RESEARCH Pitfall 6).
//
// Reihenfolge ist Sicherheit: Direkt nach dem Anlegen des Launchers kommt der
// eigene WebSocket-Proxy, sonst nimmt launcher.js seinen fremden Standard-Proxy
// (D-01, Pitfall 5). Die CSP der Seite lässt fremde Hosts ohnehin nicht zu.

const BUILDS = new Set(['a', 'b']);
const DEFAULT_BUILD = 'b';
// Minetest Game; das Pack minetest.pack muss im Release-Ordner unter packs/ liegen.
const GAME_ID = 'minetest';
const WORLD_PATH = '/luanti/worlds/gameworld-spike';

const diagNode = document.getElementById('diag');
const statusNode = document.getElementById('status');

const query = new URLSearchParams(location.search); // nur mode und build
// Ticket aus dem Fragment lesen und sofort aus Adresszeile und Verlauf löschen, vor allem anderen.
const TICKET_PREFIX = '#t=';
let launchTicket = null;
if (location.hash.startsWith(TICKET_PREFIX)) {
  try {
    launchTicket = decodeURIComponent(location.hash.slice(TICKET_PREFIX.length));
  } catch {
    launchTicket = '';
  }
  history.replaceState(null, '', location.pathname + location.search);
}
// Mehrspieler (Ticket im Fragment) hat Vorrang vor mode=single.
const mode = launchTicket !== null ? 'multi' : query.get('mode') === 'single' ? 'single' : null;
const requestedBuild = query.get('build');
const build = BUILDS.has(requestedBuild) ? requestedBuild : DEFAULT_BUILD;

const diag = {
  build: build,
  mode: mode,
  crossOriginIsolated: self.crossOriginIsolated === true,
  sharedArrayBuffer: typeof SharedArrayBuffer,
  jspi: typeof WebAssembly === 'object' && 'Suspending' in WebAssembly,
  userAgent: navigator.userAgent,
  deviceMemory: 'deviceMemory' in navigator ? navigator.deviceMemory : null,
  maxTouchPoints: navigator.maxTouchPoints,
  release: null,
  error: null,
  timeline: [],
};
const progress = new Map();

// Millisekunden seit Beginn der Navigation (performance.timeOrigin).
function ms() {
  return Math.round(performance.now());
}

function logLine(event, extra) {
  console.info(JSON.stringify({ gameworldPlay: event, ms: ms(), ...extra }));
}

function render() {
  if (!diagNode) {
    return;
  }
  // launcher.js ersetzt beim Spielstart den ganzen body; die Diagnose bleibt sichtbar.
  if (!diagNode.isConnected) {
    document.body.appendChild(diagNode);
  }
  const lines = [
    `Build ${diag.build}${diag.release ? ` (${diag.release})` : ''}, Modus ${diag.mode ?? '-'}`,
    `crossOriginIsolated: ${diag.crossOriginIsolated}`,
    `SharedArrayBuffer: ${diag.sharedArrayBuffer}`,
    `JSPI: ${diag.jspi}`,
    `deviceMemory: ${diag.deviceMemory ?? '-'}, maxTouchPoints: ${diag.maxTouchPoints}`,
    `userAgent: ${diag.userAgent}`,
  ];
  for (const entry of diag.timeline) {
    lines.push(`${String(entry.ms).padStart(7)} ms  ${entry.event}`);
  }
  for (const [name, percent] of progress) {
    lines.push(`        ${name}: ${percent} %`);
  }
  if (diag.error) {
    lines.push(`Fehler: ${diag.error.name}: ${diag.error.message}`);
  }
  diagNode.textContent = lines.join('\n');
  diagNode.classList.toggle('error', diag.error !== null);
  // pointer-events ist aus, Touch kann nicht scrollen: immer ans Ende springen.
  diagNode.scrollTop = diagNode.scrollHeight;
}

function mark(event, extra = {}) {
  diag.timeline.push({ event: event, ms: ms() });
  logLine(event, extra);
  render();
}

function setStatus(text) {
  if (statusNode) {
    statusNode.textContent = text;
  }
}

function showError(err) {
  const name = err && err.name ? String(err.name) : 'Error';
  const message = err && err.message ? String(err.message) : String(err);
  diag.error = { name: name, message: message };
  setStatus('Gameworld konnte nicht starten.');
  logLine('error', { name: name, message: message });
  render();
}

window.addEventListener('error', (event) => {
  showError(event.error ?? { name: 'Error', message: event.message });
});
window.addEventListener('unhandledrejection', (event) => {
  showError(event.reason);
});

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Konnte ${src} nicht laden.`));
    document.head.appendChild(script);
  });
}

// Eigener Proxy: gleicher Host wie die Seite, Pfad .../play/ws neben dieser Seite.
function proxyUrl() {
  const url = new URL('ws', location.href);
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  url.search = '';
  url.hash = '';
  return url.href;
}

async function fetchRelease() {
  const response = await fetch(`release/${build}`, { cache: 'no-store', credentials: 'same-origin' });
  if (!response.ok) {
    throw new Error(`Build ${build} ist auf diesem Server nicht vorhanden.`);
  }
  const body = await response.json();
  if (typeof body.release !== 'string' || !/^[0-9a-f]{12}$/.test(body.release)) {
    throw new Error('Unerwartete Antwort zum Build.');
  }
  return body.release;
}

// Text für Kinder, wenn der Start scheitert; Einzelheiten nur in der Diagnose.
const TEXT_START_FAILED = 'Der Start hat nicht geklappt. Frag deine Eltern.';

// Gemeinsamer Teil beider Modi: Shim, Release, launcher.js, Launcher mit eigenem Proxy.
async function prepareLauncher(proxy) {
  if (!location.pathname.endsWith('/')) {
    throw new Error('Die Spielseite braucht eine Adresse, die auf / endet.');
  }
  setStatus('Gameworld wird geladen.');
  // iOS-Safari kennt kein Pointer-Lock-API (nur Maus-Umgebungen haben es); der
  // Emscripten-Teil von luanti-wasm ruft document.exitPointerLock.bind() ungeprueft
  // auf und stuerzt sonst nach der Installation ab (Beleg: iPhone, Safari 27.0.1).
  if (typeof document.exitPointerLock !== 'function') {
    document.exitPointerLock = function () {};
  }
  if (typeof Element.prototype.requestPointerLock !== 'function') {
    Element.prototype.requestPointerLock = function () {};
  }
  diag.release = await fetchRelease();
  mark('release_known');
  await loadScript(`static/${build}/${diag.release}/launcher.js`);
  mark('launcher_loaded');

  const launcher = new LuantiLauncher();
  // Eigener Proxy direkt nach dem Anlegen, vor allem anderen (D-01).
  launcher.setProxy(proxy);
  launcher.setConf('touch_controls', navigator.maxTouchPoints > 0 ? 'true' : 'auto');

  let firstOutput = false;
  launcher.onprogress = (name, fraction) => {
    const percent = Math.round(fraction * 100);
    const known = progress.has(name);
    progress.set(name, percent);
    if (!known) {
      mark(`progress_start:${name}`);
    } else if (percent >= 100) {
      mark(`progress_done:${name}`);
    } else {
      render();
    }
  };
  launcher.onprint = (text) => {
    if (!firstOutput && diag.timeline.some((entry) => entry.event === 'started')) {
      firstOutput = true;
      mark('first_output', { text: String(text).slice(0, 200) });
    }
  };
  launcher.onexit = (status) => {
    mark('exit', { status: status });
  };
  launcher.onerror = (message) => {
    showError({ name: 'LuantiError', message: message });
  };
  return launcher;
}

async function startSingle() {
  const launcher = await prepareLauncher(proxyUrl());
  launcher.onready = () => {
    mark('ready');
    const args = new LuantiArgs();
    args.go = true;
    args.gameid = GAME_ID;
    args.world = WORLD_PATH;
    args.name = 'gameworld';
    launcher.launch(args);
    mark('started');
  };
}

// Ticket gegen Spielername, Passwort (Variante B) und WS-Ticket tauschen.
async function redeemLaunchTicket(ticket) {
  const response = await fetch('launch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket: ticket }),
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (!response.ok) {
    // Nur der Status, nie der Body der Anfrage.
    throw new Error(`Spielstart abgelehnt (HTTP ${response.status}).`);
  }
  const body = await response.json();
  const valid =
    typeof body.player_name === 'string' &&
    typeof body.ws_ticket === 'string' &&
    typeof body.ws_path === 'string' &&
    body.ws_path.startsWith('/') &&
    typeof body.address === 'string' &&
    Number.isInteger(body.port);
  if (!valid) {
    throw new Error('Unerwartete Antwort zum Spielstart.');
  }
  return body;
}

// Proxy-Adresse am eigenen Host; das WS-Ticket steht nur in dieser Adresse.
function multiProxyUrl(wsPath, wsTicket) {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${location.host}${wsPath}?t=${encodeURIComponent(wsTicket)}`;
}

async function startMulti(ticket) {
  if (!ticket) {
    throw new Error('Kein Spielstart in der Adresse.');
  }
  let start = await redeemLaunchTicket(ticket);
  mark('launch_ok');
  const launcher = await prepareLauncher(multiProxyUrl(start.ws_path, start.ws_ticket));
  const args = new LuantiArgs();
  args.go = true;
  args.name = start.player_name;
  // Variante A ersetzt das Passwort am Proxy; Variante B bringt das eigene mit.
  args.password = start.password ?? 'gameworld';
  args.address = start.address;
  args.port = start.port;
  start = null;
  launcher.onready = () => {
    mark('ready');
    launcher.launch(args);
    mark('started');
  };
}

logLine('diag', {
  build: diag.build,
  mode: diag.mode,
  crossOriginIsolated: diag.crossOriginIsolated,
  sharedArrayBuffer: diag.sharedArrayBuffer,
  jspi: diag.jspi,
  userAgent: diag.userAgent,
  deviceMemory: diag.deviceMemory,
  maxTouchPoints: diag.maxTouchPoints,
});
mark('page_start');

if (mode === 'multi') {
  const ticket = launchTicket;
  launchTicket = null;
  startMulti(ticket).catch((err) => {
    showError(err);
    setStatus(TEXT_START_FAILED);
  });
} else if (mode === 'single') {
  startSingle().catch(showError);
} else {
  setStatus('Diese Seite öffnet Gameworld für dich.');
}

// Browser spike 04.2: diagnosis, single-player and multiplayer start on the own play page.
//
// The page reads only two values from the address (whitelist): mode and build, plus in
// multiplayer mode the one-time ticket from the fragment (#t=...). The fragment never goes
// to a server and is removed at once from the address bar and history (T-04.2-38).
// Ticket, WS ticket and password never end up in console or diagnosis (T-04.2-39).
// Never use the argument helpers of launcher.js for the address: they would
// take name and password from the address (RESEARCH Pitfall 6).
//
// Order is security: directly after creating the launcher comes the
// own WebSocket proxy, otherwise launcher.js takes its foreign default proxy
// (D-01, Pitfall 5). The CSP of the page does not allow foreign hosts anyway.

const BUILDS = new Set(['a', 'b']);
const DEFAULT_BUILD = 'b';
// Minetest Game; the pack minetest.pack must be in the release folder under packs/.
const GAME_ID = 'minetest';
const WORLD_PATH = '/luanti/worlds/gameworld-spike';

const diagNode = document.getElementById('diag');
const statusNode = document.getElementById('status');

const query = new URLSearchParams(location.search); // only mode and build
// Read the ticket from the fragment and delete it at once from address bar and history, before anything else.
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
// Multiplayer (ticket in the fragment) takes precedence over mode=single.
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

// Milliseconds since the start of the navigation (performance.timeOrigin).
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
  // launcher.js replaces the whole body on game start; the diagnosis stays visible.
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
  // pointer-events is off, touch cannot scroll: always jump to the end.
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

// Own proxy: same host as the page, path .../play/ws next to this page.
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

// Text for children when the start fails; details only in the diagnosis.
const TEXT_START_FAILED = 'Der Start hat nicht geklappt. Frag deine Eltern.';

// Common part of both modes: shim, release, launcher.js, launcher with own proxy.
async function prepareLauncher(proxy) {
  if (!location.pathname.endsWith('/')) {
    throw new Error('Die Spielseite braucht eine Adresse, die auf / endet.');
  }
  setStatus('Gameworld wird geladen.');
  // iOS Safari has no Pointer Lock API (only mouse environments have it); the
  // Emscripten part of luanti-wasm calls document.exitPointerLock.bind() unchecked
  // and otherwise crashes after the installation (evidence: iPhone, Safari 27.0.1).
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
  // Own proxy directly after creation, before anything else (D-01).
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

// Exchange the ticket for player name, password (variant B) and WS ticket.
async function redeemLaunchTicket(ticket) {
  const response = await fetch('launch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket: ticket }),
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (!response.ok) {
    // Only the status, never the body of the request.
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

// Proxy address on the own host; the WS ticket is only in this address.
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
  // Variant A replaces the password at the proxy; variant B brings its own.
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

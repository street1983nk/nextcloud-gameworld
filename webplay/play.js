// Browser-Spike 04.2: Diagnose und Einzelspieler-Start auf der eigenen Spielseite.
//
// Die Seite liest aus der Adresse nur zwei Werte (Whitelist): mode und build.
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
const mode = query.get('mode') === 'single' ? 'single' : null;
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

async function startSingle() {
  if (!location.pathname.endsWith('/')) {
    throw new Error('Die Spielseite braucht eine Adresse, die auf / endet.');
  }
  setStatus('Gameworld wird geladen.');
  diag.release = await fetchRelease();
  mark('release_known');
  await loadScript(`static/${build}/${diag.release}/launcher.js`);
  mark('launcher_loaded');

  const launcher = new LuantiLauncher();
  launcher.setProxy(proxyUrl());
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

if (mode === 'single') {
  startSingle().catch(showError);
} else {
  setStatus('Diese Seite öffnet Gameworld für dich.');
}

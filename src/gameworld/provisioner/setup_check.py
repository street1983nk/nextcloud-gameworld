"""Setup-Check: prüft Erreichbarkeit und Scope des Docker-Proxys ohne Nebenwirkungen.

Schreibende Anfragen gehen nur an die nicht existierende Ressource
``gameworld-probe-nonexistent``; ein korrekt gescopter Proxy reicht sie an den
Daemon durch, der mit 404 antwortet. Erwartete Statuscodes: 01-RESEARCH.md
Pattern 5 (im Spike gegen tecnativa/docker-socket-proxy v0.5.0 gemessen).
"""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import requests

MIN_API_VERSION = (1, 44)
DOCS_URL = "https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#setup-check"
DOCS = f"Anleitung: {DOCS_URL}"

# Messages as module constants (German = message ID, D-25); messages with data are
# templates with {name} placeholders, formatted at the call site. The guide link is
# a placeholder too, so "Anleitung:" is part of the translated text.
MSG_CONTAINERS_OK = "Zugriff auf Container ist erlaubt."
MSG_CONTAINERS_DENIED = f"Der Docker-Proxy erlaubt keinen Zugriff auf Container. Bitte CONTAINERS=1 setzen. {DOCS}"
MSG_POST_OK = "Schreibende Anfragen sind erlaubt."
MSG_POST_DENIED = (
    "Der Docker-Proxy erlaubt keine schreibenden Anfragen, Welten lassen sich so weder anlegen "
    f"noch starten. Bitte POST=1 setzen. {DOCS}"
)
MSG_IMAGES_OK = "Zugriff auf Images ist erlaubt."
MSG_IMAGES_DENIED = f"Der Docker-Proxy erlaubt keinen Zugriff auf Images. Bitte IMAGES=1 setzen. {DOCS}"
MSG_VOLUMES_OK = "Zugriff auf Volumes ist erlaubt."
MSG_VOLUMES_DENIED = (
    "Der Docker-Proxy erlaubt keinen Zugriff auf Volumes, Welten lassen sich so nicht löschen. "
    f"Bitte VOLUMES=1 setzen. {DOCS}"
)
MSG_EXEC_OK = "Befehle in Containern sind gesperrt."
MSG_EXEC_OPEN = f"Der Docker-Proxy ist zu weit offen: Befehle in Containern sind erlaubt. Bitte EXEC=0 setzen. {DOCS}"
MSG_INFO_OK = "Systeminformationen sind gesperrt."
MSG_INFO_OPEN = f"Der Docker-Proxy gibt Systeminformationen preis. Bitte INFO=0 setzen. {DOCS}"
MSG_NOT_CHECKED = f"Nicht geprüft: Erst POST=1 setzen, dann den Setup-Check erneut ausführen. {DOCS}"
MSG_DOCKER_SOCKET = (
    "Gameworld soll nie direkt mit dem Docker-Socket sprechen. Trage die Adresse des gescopten "
    f"Docker-Proxys ein, Standard tcp://gameworld-docker-proxy:2375. {DOCS}"
)
MSG_PROXY_EXPOSED = (
    "Der Docker-Proxy liegt auf einer Adresse außerhalb des privaten Netzes. Er darf nur im "
    f"Docker-Netz von Gameworld erreichbar sein. {DOCS}"
)
MSG_REACHABLE = "Der Docker-Proxy ist erreichbar."
TEXT_PROXY_DNS = (
    "Gameworld findet den Dienst {host} nicht. Er muss im selben Docker-Netz laufen wie "
    "Gameworld (das Netz des Deploy-Daemons, bei AIO nextcloud-aio). Anleitung: {docs_url}"
)
TEXT_PROXY_TIMEOUT = (
    "Der Docker-Proxy unter {host}:{port} antwortet nicht. Meist hängt er in einem anderen "
    "Docker-Netz, oder eine Firewall sperrt Port {port}. Anleitung: {docs_url}"
)
TEXT_PROXY_REFUSED = (
    "Der Docker-Proxy unter {host}:{port} nimmt keine Verbindung an. Läuft der Container "
    "gameworld-docker-proxy? Anleitung: {docs_url}"
)
TEXT_PROXY_UNREACHABLE = (
    "Gameworld erreicht den Docker-Proxy unter {docker_url} nicht. Bitte den Dienst "
    "gameworld-docker-proxy starten und GAMEWORLD_DOCKER_URL prüfen. Anleitung: {docs_url}"
)
TEXT_ENGINE_TOO_OLD = (
    "Docker-Engine zu alt, benötigt API 1.44 oder neuer (gemeldet: {shown}). "
    "Bitte Docker aktualisieren. Anleitung: {docs_url}"
)
# Without a readable version the inserted value is a German word, so this case is its own message.
MSG_ENGINE_VERSION_UNKNOWN = TEXT_ENGINE_TOO_OLD.format(shown="unbekannt", docs_url=DOCS_URL)
TEXT_API_SUPPORTED = "Docker-API {version} wird unterstützt."
TEXT_UNEXPECTED_ANSWER = "Unerwartete Antwort des Docker-Proxys auf {method} {path}: HTTP {code}. Anleitung: {docs_url}"
TEXT_REQUEST_FAILED = "Die Anfrage an den Docker-Proxy ({path}) ist fehlgeschlagen: {error_type}. Anleitung: {docs_url}"

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class CheckItem:
    id: str
    ok: bool
    severity: Severity
    message: str


@dataclass(frozen=True)
class SetupCheckResult:
    ok: bool
    items: list[CheckItem]


@dataclass(frozen=True)
class _Probe:
    id: str
    method: str
    path: str
    expected: int
    severity: Severity
    ok_message: str
    # Meldung für den bekannten Abweichungs-Code (403 bzw. 404/200).
    known_code: int
    known_message: str
    params: dict[str, str] | None = None


_LABEL_FILTER = json.dumps({"label": ["gameworld.managed=true"]})

_CONTAINERS = _Probe(
    id="containers",
    method="GET",
    path="/containers/json",
    params={"filters": _LABEL_FILTER},
    expected=200,
    severity="error",
    ok_message=MSG_CONTAINERS_OK,
    known_code=403,
    known_message=MSG_CONTAINERS_DENIED,
)
_POST = _Probe(
    id="post",
    method="POST",
    path="/containers/gameworld-probe-nonexistent/stop",
    expected=404,
    severity="error",
    ok_message=MSG_POST_OK,
    known_code=403,
    known_message=MSG_POST_DENIED,
)
_IMAGES = _Probe(
    id="images",
    method="GET",
    path="/images/json",
    expected=200,
    severity="error",
    ok_message=MSG_IMAGES_OK,
    known_code=403,
    known_message=MSG_IMAGES_DENIED,
)
_VOLUMES = _Probe(
    id="volumes",
    method="DELETE",
    path="/volumes/gameworld-probe-nonexistent",
    expected=404,
    severity="error",
    ok_message=MSG_VOLUMES_OK,
    known_code=403,
    known_message=MSG_VOLUMES_DENIED,
)
_EXEC = _Probe(
    id="exec",
    method="POST",
    path="/exec/gameworld-probe-nonexistent/start",
    expected=403,
    severity="warning",
    ok_message=MSG_EXEC_OK,
    known_code=404,
    known_message=MSG_EXEC_OPEN,
)
_INFO = _Probe(
    id="info",
    method="GET",
    path="/info",
    expected=403,
    severity="warning",
    ok_message=MSG_INFO_OK,
    known_code=200,
    known_message=MSG_INFO_OPEN,
)


def _http_base(docker_url: str) -> str:
    base = docker_url.rstrip("/")
    if base.startswith("tcp://"):
        return "http://" + base.removeprefix("tcp://")
    return base


# Private Netze, in denen ein gescopter Docker-Proxy liegen darf. Bewusst nicht
# ``ipaddress.is_private``: das zählt auch Dokumentationsnetze wie 203.0.113.0/24 dazu.
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")
)
_DEFAULT_PORT = 2375
_MAX_CAUSE_DEPTH = 10


def _host_port(docker_url: str) -> tuple[str, int]:
    """Host und Port aus der eigenen Konfiguration, nie aus Ausnahmetexten (T-06-40)."""
    try:
        parts = urlsplit(docker_url)
        host = parts.hostname or "gameworld-docker-proxy"
        port = parts.port or _DEFAULT_PORT
    except ValueError:
        return "gameworld-docker-proxy", _DEFAULT_PORT
    return host, port


def _causes(exc: BaseException) -> list[BaseException]:
    """Kette über __cause__, __context__ und urllib3-``reason``, höchstens zehn Glieder."""
    seen: list[BaseException] = []
    todo: list[BaseException] = [exc]
    while todo and len(seen) < _MAX_CAUSE_DEPTH:
        current = todo.pop(0)
        if any(current is known for known in seen):
            continue
        seen.append(current)
        for nxt in (current.__cause__, current.__context__, getattr(current, "reason", None)):
            if isinstance(nxt, BaseException):
                todo.append(nxt)
    return seen


def _has_cause(exc: BaseException, kind: type[BaseException]) -> bool:
    return any(isinstance(link, kind) for link in _causes(exc))


def check_docker_url(docker_url: str) -> CheckItem | None:
    """Warnt vor rohem Docker-Socket und vor Proxy-Adressen außerhalb privater Netze (T-06-39)."""
    try:
        parts = urlsplit(docker_url.strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme in {"unix", "npipe"}:
        return CheckItem(
            id="docker_url_socket",
            ok=False,
            severity="warning",
            message=MSG_DOCKER_SOCKET,
        )
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Hostname, etwa gameworld-docker-proxy: im Docker-Netz aufgelöst, kein Befund.
        return None
    if any(address in net for net in _PRIVATE_NETS):
        return None
    return CheckItem(
        id="docker_url_exposed",
        ok=False,
        severity="warning",
        message=MSG_PROXY_EXPOSED,
    )


def _parse_version(raw: object) -> tuple[int, ...] | None:
    if not isinstance(raw, str):
        return None
    try:
        return tuple(int(part) for part in raw.split("."))
    except ValueError:
        return None


class _Checker:
    def __init__(self, docker_url: str, timeout: float) -> None:
        self.docker_url = docker_url
        self.base = _http_base(docker_url)
        self.timeout = timeout
        self.session = requests.Session()
        # Keine Proxy-Variablen der Umgebung: der Docker-Proxy liegt im lokalen Netz.
        self.session.trust_env = False

    def request(self, method: str, path: str, params: dict[str, str] | None = None) -> requests.Response:
        return self.session.request(method, self.base + path, params=params, timeout=self.timeout)

    def unreachable(self, exc: BaseException | None = None) -> CheckItem:
        """Ursache getrennt melden; Texte fest, Host und Port nur aus der eigenen URL."""
        host, port = _host_port(self.docker_url)
        if exc is not None and _has_cause(exc, socket.gaierror):
            return CheckItem(
                id="proxy_dns",
                ok=False,
                severity="error",
                message=TEXT_PROXY_DNS.format(host=host, docs_url=DOCS_URL),
            )
        if exc is not None and _has_cause(exc, requests.exceptions.Timeout):
            return CheckItem(
                id="proxy_timeout",
                ok=False,
                severity="error",
                message=TEXT_PROXY_TIMEOUT.format(host=host, port=port, docs_url=DOCS_URL),
            )
        if exc is not None:
            return CheckItem(
                id="proxy_refused",
                ok=False,
                severity="error",
                message=TEXT_PROXY_REFUSED.format(host=host, port=port, docs_url=DOCS_URL),
            )
        return CheckItem(
            id="reachable",
            ok=False,
            severity="error",
            message=TEXT_PROXY_UNREACHABLE.format(docker_url=self.docker_url, docs_url=DOCS_URL),
        )

    def ping(self) -> CheckItem:
        try:
            response = self.request("GET", "/_ping")
        except requests.RequestException as exc:
            return self.unreachable(exc)
        if response.status_code != 200:
            return self.unreachable()
        return CheckItem(id="reachable", ok=True, severity="error", message=MSG_REACHABLE)

    def version(self) -> CheckItem:
        try:
            response = self.request("GET", "/version")
        except requests.RequestException as exc:
            return self._failed_request("version", "/version", exc)
        if response.status_code != 200:
            return self._unexpected("version", "error", "GET", "/version", response.status_code)
        try:
            raw = response.json().get("ApiVersion")
        except (ValueError, AttributeError):
            raw = None
        parsed = _parse_version(raw)
        if parsed is None or parsed < MIN_API_VERSION:
            message = (
                TEXT_ENGINE_TOO_OLD.format(shown=raw, docs_url=DOCS_URL)
                if isinstance(raw, str)
                else MSG_ENGINE_VERSION_UNKNOWN
            )
            return CheckItem(id="version", ok=False, severity="error", message=message)
        return CheckItem(id="version", ok=True, severity="error", message=TEXT_API_SUPPORTED.format(version=raw))

    def probe(self, probe: _Probe) -> CheckItem:
        try:
            response = self.request(probe.method, probe.path, probe.params)
        except requests.RequestException as exc:
            return self._failed_request(probe.id, probe.path, exc)
        code = response.status_code
        if code == probe.expected:
            return CheckItem(id=probe.id, ok=True, severity=probe.severity, message=probe.ok_message)
        if code == probe.known_code:
            return CheckItem(id=probe.id, ok=False, severity=probe.severity, message=probe.known_message)
        return self._unexpected(probe.id, "error", probe.method, probe.path, code)

    @staticmethod
    def _unexpected(item_id: str, severity: Severity, method: str, path: str, code: int) -> CheckItem:
        return CheckItem(
            id=item_id,
            ok=False,
            severity=severity,
            message=TEXT_UNEXPECTED_ANSWER.format(method=method, path=path, code=code, docs_url=DOCS_URL),
        )

    @staticmethod
    def _failed_request(item_id: str, path: str, exc: requests.RequestException) -> CheckItem:
        return CheckItem(
            id=item_id,
            ok=False,
            severity="error",
            message=TEXT_REQUEST_FAILED.format(path=path, error_type=type(exc).__name__, docs_url=DOCS_URL),
        )

    def run(self) -> list[CheckItem]:
        url_item = check_docker_url(self.docker_url)
        head = [url_item] if url_item is not None else []
        reachable = self.ping()
        if not reachable.ok:
            return [*head, reachable]
        items = [*head, reachable, self.version(), self.probe(_CONTAINERS)]
        post = self.probe(_POST)
        items += [post, self.probe(_IMAGES)]
        if post.ok:
            items += [self.probe(_VOLUMES), self.probe(_EXEC)]
        else:
            # Mit POST=0 sperrt tecnativa jede nicht lesende Methode; die Ergebnisse
            # wären Folgefehler (VOLUMES fälschlich fehlend, EXEC fälschlich gesperrt).
            items += [
                CheckItem(id=probe.id, ok=False, severity="warning", message=MSG_NOT_CHECKED)
                for probe in (_VOLUMES, _EXEC)
            ]
        items.append(self.probe(_INFO))
        return items


def run_setup_check(docker_url: str, timeout: float = 3.0) -> SetupCheckResult:
    """Führt alle Probes aus; keine Ausnahme verlässt diese Funktion."""
    checker = _Checker(docker_url, timeout)
    try:
        items = checker.run()
    except Exception:
        # Letzte Absicherung: ein Programmfehler darf die Seite nicht mit 500 beenden.
        items = [checker.unreachable()]
    finally:
        checker.session.close()
    ok = not any(not item.ok and item.severity == "error" for item in items)
    return SetupCheckResult(ok=ok, items=items)

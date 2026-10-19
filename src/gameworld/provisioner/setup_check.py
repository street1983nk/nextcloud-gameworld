"""Setup-Check: prüft Erreichbarkeit und Scope des Docker-Proxys ohne Nebenwirkungen.

Schreibende Anfragen gehen nur an die nicht existierende Ressource
``gameworld-probe-nonexistent``; ein korrekt gescopter Proxy reicht sie an den
Daemon durch, der mit 404 antwortet. Erwartete Statuscodes: 01-RESEARCH.md
Pattern 5 (im Spike gegen tecnativa/docker-socket-proxy v0.5.0 gemessen).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import requests

MIN_API_VERSION = (1, 44)
DOCS = "siehe docs/install.md"

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
    ok_message="Zugriff auf Container ist erlaubt.",
    known_code=403,
    known_message=f"Der Docker-Proxy erlaubt keinen Zugriff auf Container. Bitte CONTAINERS=1 setzen ({DOCS}).",
)
_POST = _Probe(
    id="post",
    method="POST",
    path="/containers/gameworld-probe-nonexistent/stop",
    expected=404,
    severity="error",
    ok_message="Schreibende Anfragen sind erlaubt.",
    known_code=403,
    known_message=(
        "Der Docker-Proxy erlaubt keine schreibenden Anfragen, Welten lassen sich so weder anlegen "
        f"noch starten. Bitte POST=1 setzen ({DOCS})."
    ),
)
_IMAGES = _Probe(
    id="images",
    method="GET",
    path="/images/json",
    expected=200,
    severity="error",
    ok_message="Zugriff auf Images ist erlaubt.",
    known_code=403,
    known_message=f"Der Docker-Proxy erlaubt keinen Zugriff auf Images. Bitte IMAGES=1 setzen ({DOCS}).",
)
_VOLUMES = _Probe(
    id="volumes",
    method="DELETE",
    path="/volumes/gameworld-probe-nonexistent",
    expected=404,
    severity="error",
    ok_message="Zugriff auf Volumes ist erlaubt.",
    known_code=403,
    known_message=(
        "Der Docker-Proxy erlaubt keinen Zugriff auf Volumes, Welten lassen sich so nicht löschen. "
        f"Bitte VOLUMES=1 setzen ({DOCS})."
    ),
)
_EXEC = _Probe(
    id="exec",
    method="POST",
    path="/exec/gameworld-probe-nonexistent/start",
    expected=403,
    severity="warning",
    ok_message="Befehle in Containern sind gesperrt.",
    known_code=404,
    known_message=(
        f"Der Docker-Proxy ist zu weit offen: Befehle in Containern sind erlaubt. Bitte EXEC=0 setzen ({DOCS})."
    ),
)
_INFO = _Probe(
    id="info",
    method="GET",
    path="/info",
    expected=403,
    severity="warning",
    ok_message="Systeminformationen sind gesperrt.",
    known_code=200,
    known_message=f"Der Docker-Proxy gibt Systeminformationen preis. Bitte INFO=0 setzen ({DOCS}).",
)

_NOT_CHECKED = "Nicht geprüft: Erst POST=1 setzen, dann den Setup-Check erneut ausführen."


def _http_base(docker_url: str) -> str:
    base = docker_url.rstrip("/")
    if base.startswith("tcp://"):
        return "http://" + base.removeprefix("tcp://")
    return base


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

    def unreachable(self) -> CheckItem:
        return CheckItem(
            id="reachable",
            ok=False,
            severity="error",
            message=(
                f"Gameworld erreicht den Docker-Proxy unter {self.docker_url} nicht. Bitte den Dienst "
                f"gameworld-docker-proxy starten und GAMEWORLD_DOCKER_URL prüfen ({DOCS})."
            ),
        )

    def ping(self) -> CheckItem:
        try:
            response = self.request("GET", "/_ping")
        except requests.RequestException:
            return self.unreachable()
        if response.status_code != 200:
            return self.unreachable()
        return CheckItem(id="reachable", ok=True, severity="error", message="Der Docker-Proxy ist erreichbar.")

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
            shown = raw if isinstance(raw, str) else "unbekannt"
            return CheckItem(
                id="version",
                ok=False,
                severity="error",
                message=(
                    f"Docker-Engine zu alt, benötigt API 1.44 oder neuer (gemeldet: {shown}). "
                    f"Bitte Docker aktualisieren ({DOCS})."
                ),
            )
        return CheckItem(id="version", ok=True, severity="error", message=f"Docker-API {raw} wird unterstützt.")

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
            message=f"Unerwartete Antwort des Docker-Proxys auf {method} {path}: HTTP {code} ({DOCS}).",
        )

    @staticmethod
    def _failed_request(item_id: str, path: str, exc: requests.RequestException) -> CheckItem:
        return CheckItem(
            id=item_id,
            ok=False,
            severity="error",
            message=f"Die Anfrage an den Docker-Proxy ({path}) ist fehlgeschlagen: {type(exc).__name__} ({DOCS}).",
        )

    def run(self) -> list[CheckItem]:
        reachable = self.ping()
        if not reachable.ok:
            return [reachable]
        items = [reachable, self.version(), self.probe(_CONTAINERS)]
        post = self.probe(_POST)
        items += [post, self.probe(_IMAGES)]
        if post.ok:
            items += [self.probe(_VOLUMES), self.probe(_EXEC)]
        else:
            # Mit POST=0 sperrt tecnativa jede nicht lesende Methode; die Ergebnisse
            # wären Folgefehler (VOLUMES fälschlich fehlend, EXEC fälschlich gesperrt).
            items += [
                CheckItem(id=probe.id, ok=False, severity="warning", message=_NOT_CHECKED)
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

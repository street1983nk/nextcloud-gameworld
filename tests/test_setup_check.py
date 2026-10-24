"""Setup-Check gegen einen lokalen Fake-Proxy: Meldungen, Folgefehler, Nebenwirkungsfreiheit."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import httpx
import pytest
import requests

from gameworld.provisioner.setup_check import (
    DOCS_URL,
    CheckItem,
    SetupCheckResult,
    check_docker_url,
    run_setup_check,
)
from tests.conftest import appapi_headers

PROBE = "gameworld-probe-nonexistent"

# Antworten eines korrekt gescopten tecnativa-Proxys (im Spike gemessen).
GOOD: dict[tuple[str, str], int] = {
    ("GET", "/_ping"): 200,
    ("GET", "/version"): 200,
    ("GET", "/containers/json"): 200,
    ("POST", f"/containers/{PROBE}/stop"): 404,
    ("GET", "/images/json"): 200,
    ("DELETE", f"/volumes/{PROBE}"): 404,
    ("POST", f"/exec/{PROBE}/start"): 403,
    ("GET", "/info"): 403,
}


@dataclass
class FakeProxy:
    url: str
    statuses: dict[tuple[str, str], int] = field(default_factory=lambda: dict(GOOD))
    api_version: str = "1.54"
    log: list[tuple[str, str]] = field(default_factory=list)

    def mutating_calls(self) -> list[str]:
        return [path for method, path in self.log if method in {"POST", "DELETE", "PUT"}]


def _handler(proxy: FakeProxy) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            proxy.log.append((self.command, self.path))
            path = urlsplit(self.path).path
            code = proxy.statuses.get((self.command, path), 403)
            if path == "/version" and code == 200:
                body = json.dumps({"ApiVersion": proxy.api_version}).encode()
            elif path == "/_ping" and code == 200:
                body = b"OK"
            else:
                body = b"{}"
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _answer
        do_POST = _answer
        do_DELETE = _answer

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

    return Handler


@pytest.fixture
def fake_proxy() -> Iterator[FakeProxy]:
    proxy = FakeProxy(url="")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(proxy))
    proxy.url = f"tcp://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield proxy
    finally:
        server.shutdown()
        server.server_close()
        # Nebenwirkungsfrei: schreibende Methoden nur auf die Probe-Ressource.
        assert all(PROBE in path for path in proxy.mutating_calls())


def _item(result: SetupCheckResult, item_id: str) -> CheckItem:
    matches = [item for item in result.items if item.id == item_id]
    assert len(matches) == 1, [item.id for item in result.items]
    return matches[0]


def _failed(result: SetupCheckResult, severity: str) -> list[CheckItem]:
    return [item for item in result.items if not item.ok and item.severity == severity]


def test_good_proxy_passes(fake_proxy: FakeProxy) -> None:
    result = run_setup_check(fake_proxy.url)
    assert result.ok is True
    assert [item.id for item in result.items] == [
        "reachable",
        "version",
        "containers",
        "post",
        "images",
        "volumes",
        "exec",
        "info",
    ]
    assert all(item.ok for item in result.items)


def test_missing_containers(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("GET", "/containers/json")] = 403
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    item = _item(result, "containers")
    assert (item.ok, item.severity) == (False, "error")
    assert "CONTAINERS=1" in item.message
    assert "docs/install.md" in item.message


def test_containers_probe_uses_label_filter(fake_proxy: FakeProxy) -> None:
    run_setup_check(fake_proxy.url)
    paths = [path for method, path in fake_proxy.log if urlsplit(path).path == "/containers/json"]
    assert len(paths) == 1
    assert "gameworld.managed" in httpx.URL(paths[0]).params["filters"]


def test_missing_post_reports_exactly_one_error(fake_proxy: FakeProxy) -> None:
    # tecnativa mit POST=0 sperrt alle schreibenden Methoden, also auch DELETE.
    for key in list(fake_proxy.statuses):
        if key[0] in {"POST", "DELETE"}:
            fake_proxy.statuses[key] = 403
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    errors = _failed(result, "error")
    assert [item.id for item in errors] == ["post"]
    assert "POST=1" in errors[0].message
    for item_id, forbidden in (("volumes", "VOLUMES=1"), ("exec", "EXEC=0")):
        item = _item(result, item_id)
        assert (item.ok, item.severity) == (False, "warning")
        assert "nicht geprüft" in item.message.lower()
        assert "POST=1" in item.message
        assert forbidden not in item.message
    # Die Folgeprobes wurden gar nicht erst gesendet.
    assert not [path for method, path in fake_proxy.log if method == "DELETE"]
    assert not [path for _, path in fake_proxy.log if path.startswith("/exec")]


def test_missing_images(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("GET", "/images/json")] = 403
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    item = _item(result, "images")
    assert (item.ok, item.severity) == (False, "error")
    assert "IMAGES=1" in item.message


def test_missing_volumes(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("DELETE", f"/volumes/{PROBE}")] = 403
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    item = _item(result, "volumes")
    assert (item.ok, item.severity) == (False, "error")
    assert "VOLUMES=1" in item.message
    assert [item.id for item in _failed(result, "error")] == ["volumes"]


def test_exec_open_is_a_warning(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("POST", f"/exec/{PROBE}/start")] = 404
    result = run_setup_check(fake_proxy.url)
    assert result.ok is True
    item = _item(result, "exec")
    assert (item.ok, item.severity) == (False, "warning")
    assert "EXEC=0" in item.message


def test_info_open_is_a_warning(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("GET", "/info")] = 200
    result = run_setup_check(fake_proxy.url)
    assert result.ok is True
    item = _item(result, "info")
    assert (item.ok, item.severity) == (False, "warning")
    assert "INFO=0" in item.message


def test_old_engine(fake_proxy: FakeProxy) -> None:
    fake_proxy.api_version = "1.43"
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    item = _item(result, "version")
    assert (item.ok, item.severity) == (False, "error")
    assert "Docker-Engine zu alt, benötigt API 1.44 oder neuer" in item.message


def test_api_version_compares_numerically(fake_proxy: FakeProxy) -> None:
    # Als Text wäre "1.100" kleiner als "1.44".
    fake_proxy.api_version = "1.100"
    assert _item(run_setup_check(fake_proxy.url), "version").ok is True


def test_unexpected_status_names_path_and_code(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("GET", "/images/json")] = 500
    result = run_setup_check(fake_proxy.url)
    item = _item(result, "images")
    assert (item.ok, item.severity) == (False, "error")
    assert "/images/json" in item.message
    assert "500" in item.message


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_unreachable_proxy_stops_after_one_item() -> None:
    # Echter abgelehnter Verbindungsaufbau; Windows wiederholt SYN auf geschlossene Ports
    # rund zwei Sekunden, daher großzügige Zeitgrenze.
    port = _closed_port()
    result = run_setup_check(f"tcp://127.0.0.1:{port}", timeout=5.0)
    assert result.ok is False
    assert len(result.items) == 1
    item = result.items[0]
    assert (item.id, item.ok, item.severity) == ("proxy_refused", False, "error")
    assert f"127.0.0.1:{port}" in item.message
    assert "gameworld-docker-proxy" in item.message
    assert item.message.endswith(f" Anleitung: {DOCS_URL}")


DOCS_SUFFIX = " Anleitung: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#setup-check"


def _dns_error() -> requests.ConnectionError:
    """Kette wie bei urllib3: gaierror -> NameResolutionError -> requests.ConnectionError."""
    try:
        try:
            try:
                raise socket.gaierror(11001, "getaddrinfo failed (geheimes Detail)")
            except socket.gaierror as exc:
                raise OSError("NameResolutionError") from exc
        except OSError as exc:
            raise requests.ConnectionError("Max retries exceeded (geheimes Detail)") from exc
    except requests.ConnectionError as exc:
        return exc


def _refused_error() -> requests.ConnectionError:
    try:
        try:
            raise ConnectionRefusedError(10061, "refused (geheimes Detail)")
        except ConnectionRefusedError as exc:
            raise requests.ConnectionError("Max retries exceeded (geheimes Detail)") from exc
    except requests.ConnectionError as exc:
        return exc


def _patch_request(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> list[str]:
    calls: list[str] = []

    def fake_request(self: requests.Session, method: str, url: str, **_: object) -> requests.Response:
        del self
        calls.append(f"{method} {url}")
        raise exc

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return calls


def test_dns_failure_names_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_request(monkeypatch, _dns_error())
    result = run_setup_check("tcp://gameworld-docker-proxy:2375")
    assert result.ok is False
    assert [item.id for item in result.items] == ["proxy_dns"]
    item = result.items[0]
    assert (item.ok, item.severity) == (False, "error")
    assert item.message == (
        "Gameworld findet den Dienst gameworld-docker-proxy nicht. Er muss im selben Docker-Netz laufen wie "
        "Gameworld (das Netz des Deploy-Daemons, bei AIO nextcloud-aio)." + DOCS_SUFFIX
    )
    assert "geheimes Detail" not in item.message
    assert len(calls) == 1


def test_dns_failure_uses_configured_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, _dns_error())
    item = run_setup_check("tcp://mein-proxy:2375").items[0]
    assert item.id == "proxy_dns"
    assert item.message.startswith("Gameworld findet den Dienst mein-proxy nicht.")
    assert "gameworld-docker-proxy" not in item.message


def test_dns_detection_follows_context_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    # gaierror nur über __context__ (ohne "from"), wie bei Retries möglich.
    try:
        try:
            raise socket.gaierror(-2, "Name or service not known")
        except socket.gaierror:
            raise requests.ConnectionError("x")  # noqa: B904
    except requests.ConnectionError as exc:
        _patch_request(monkeypatch, exc)
    assert run_setup_check("tcp://gameworld-docker-proxy:2375").items[0].id == "proxy_dns"


def test_connect_timeout_names_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, requests.ConnectTimeout("timed out (geheimes Detail)"))
    result = run_setup_check("tcp://gameworld-docker-proxy:2375")
    assert result.ok is False
    item = result.items[0]
    assert (item.id, item.ok, item.severity) == ("proxy_timeout", False, "error")
    assert item.message == (
        "Der Docker-Proxy unter gameworld-docker-proxy:2375 antwortet nicht. Meist hängt er in einem anderen "
        "Docker-Netz, oder eine Firewall sperrt Port 2375." + DOCS_SUFFIX
    )


def test_refused_asks_whether_proxy_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, _refused_error())
    result = run_setup_check("tcp://gameworld-docker-proxy:2375")
    assert result.ok is False
    item = result.items[0]
    assert (item.id, item.ok, item.severity) == ("proxy_refused", False, "error")
    assert item.message == (
        "Der Docker-Proxy unter gameworld-docker-proxy:2375 nimmt keine Verbindung an. Läuft der Container "
        "gameworld-docker-proxy?" + DOCS_SUFFIX
    )
    assert "geheimes Detail" not in item.message


def test_cyclic_cause_chain_does_not_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    first = requests.ConnectionError("a")
    second = OSError("b")
    first.__cause__ = second
    second.__cause__ = first
    _patch_request(monkeypatch, first)
    assert run_setup_check("tcp://gameworld-docker-proxy:2375").items[0].id == "proxy_refused"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("unix:///var/run/docker.sock", "docker_url_socket"),
        ("tcp://203.0.113.5:2375", "docker_url_exposed"),
        ("tcp://8.8.8.8:2375", "docker_url_exposed"),
        ("tcp://gameworld-docker-proxy:2375", None),
        ("tcp://10.0.0.5:2375", None),
        ("tcp://127.0.0.1:2375", None),
        ("tcp://172.18.0.4:2375", None),
        ("tcp://192.168.1.10:2375", None),
    ],
)
def test_check_docker_url(url: str, expected: str | None) -> None:
    item = check_docker_url(url)
    if expected is None:
        assert item is None
        return
    assert item is not None
    assert (item.id, item.ok, item.severity) == (expected, False, "warning")
    assert item.message.endswith(DOCS_SUFFIX)


def test_socket_warning_text() -> None:
    item = check_docker_url("unix:///var/run/docker.sock")
    assert item is not None
    assert item.message == (
        "Gameworld soll nie direkt mit dem Docker-Socket sprechen. Trage die Adresse des gescopten "
        "Docker-Proxys ein, Standard tcp://gameworld-docker-proxy:2375." + DOCS_SUFFIX
    )


def test_exposed_warning_text() -> None:
    item = check_docker_url("tcp://203.0.113.5:2375")
    assert item is not None
    assert item.message == (
        "Der Docker-Proxy liegt auf einer Adresse außerhalb des privaten Netzes. Er darf nur im "
        "Docker-Netz von Gameworld erreichbar sein." + DOCS_SUFFIX
    )


def test_url_warning_comes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, requests.ConnectTimeout("x"))
    result = run_setup_check("tcp://203.0.113.5:2375")
    assert [item.id for item in result.items] == ["docker_url_exposed", "proxy_timeout"]


def test_every_failed_message_links_the_guide(fake_proxy: FakeProxy) -> None:
    for key in list(fake_proxy.statuses):
        if key != ("GET", "/_ping"):
            fake_proxy.statuses[key] = 403
    fake_proxy.statuses[("GET", "/info")] = 200
    result = run_setup_check(fake_proxy.url)
    failed = [item for item in result.items if not item.ok]
    assert len(failed) >= 5
    for item in failed:
        assert item.message.endswith(DOCS_SUFFIX), item
        assert "siehe docs/install.md" not in item.message


def test_setup_check_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_request(monkeypatch, RuntimeError("Programmfehler"))
    result = run_setup_check("tcp://gameworld-docker-proxy:2375")
    assert result.ok is False
    assert [item.id for item in result.items] == ["reachable"]
    assert result.items[0].message.endswith(DOCS_SUFFIX)


def test_ping_error_status_counts_as_unreachable(fake_proxy: FakeProxy) -> None:
    fake_proxy.statuses[("GET", "/_ping")] = 502
    result = run_setup_check(fake_proxy.url)
    assert result.ok is False
    assert [item.id for item in result.items] == ["reachable"]
    assert len(fake_proxy.log) == 1


async def test_api_route_reports_result(
    client: httpx.AsyncClient, fake_proxy: FakeProxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", fake_proxy.url)
    fake_proxy.statuses[("GET", "/info")] = 200
    response = await client.get("/api/setup-check", headers=appapi_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    info = next(item for item in body["items"] if item["id"] == "info")
    assert info == {"id": "info", "ok": False, "severity": "warning", "message": info["message"]}
    assert "INFO=0" in info["message"]


async def test_api_route_is_200_when_proxy_is_down(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", f"tcp://127.0.0.1:{_closed_port()}")
    response = await client.get("/api/setup-check", headers=appapi_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert [item["id"] for item in body["items"]] == ["proxy_refused"]


async def test_api_route_requires_appapi_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/setup-check")
    assert response.status_code == 401

"""Phase-4-Spike: Spielzeit-Durchsetzung per Welt-Mod, live gegen Luanti 5.17.0 über den Dev-Proxy.

Aufruf aus dem Repo-Root: .venv/Scripts/python.exe -I .planning/phases/04-spielzeitlimits/spike/spike4.py
Legt Welt "spike4/w1" auf Port 30094 an und entfernt sie am Ende samt Volume.
"""

from __future__ import annotations

import io
import pathlib
import sys
import tarfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import docker  # noqa: E402
from session_probe import session  # noqa: E402

from gameworld.provisioner.access_mod import render_access_file  # noqa: E402
from gameworld.provisioner.archive import build_world_payload  # noqa: E402
from gameworld.provisioner.client import DockerProvisioner  # noqa: E402
from gameworld.provisioner.luanti_auth import make_verifier  # noqa: E402
from gameworld.provisioner.luanti_conf import render_minetest_conf, render_world_mt  # noqa: E402
from gameworld.provisioner.presets import MTG_KREATIV  # noqa: E402
from gameworld.provisioner.spec import DATA_DIR, resource_name  # noqa: E402
from tests.e2e.luanti_probe import join  # noqa: E402

INSTANCE, WORLD, PORT, HOST = "spike4", "w1", 30094, "127.0.0.1"
WDIR = f"{DATA_DIR}/.minetest/worlds/world"
PW = {"Mia": "Sonne-Baum-42", "Papa": "Mond-Wolke-17"}
T0 = time.monotonic()


def log(*args: object) -> None:
    print(f"[{time.monotonic() - T0:6.1f}s]", *args, flush=True)


def tar_of(files: dict[str, tuple[bytes, int, int]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, (data, uid, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.gid, info.mode, info.mtime = len(data), uid, 30000, mode, int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def rules(generation: int, players: dict[str, tuple[int, int, int, str, str]], world_line: str | None = None,
          complete: bool = True) -> bytes:
    lines = [f"gameworld-time 1 {generation} {int(time.time())}"]
    if world_line:
        lines.append(world_line)
    lines += [f"{n} {r} {u} {b} {why} {nxt}" for n, (r, u, b, why, nxt) in sorted(players.items())]
    if complete:
        lines.append("end")
    return ("\n".join(lines) + "\n").encode()


def read(container, path: str) -> str:
    try:
        stream, _ = container.get_archive(path)
    except docker.errors.NotFound:
        return "<fehlt>"
    with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
        member = tar.extractfile(tar.getmembers()[0])
        return member.read().decode() if member else ""


def ledger(container) -> dict[str, int]:
    out = {}
    for line in read(container, f"{WDIR}/gameworld_time_used.txt").splitlines()[1:-1]:
        name, secs = line.split()
        out[name] = int(secs)
    return out


def wait_ready(limit: float = 60) -> float:
    start = time.monotonic()
    while time.monotonic() - start < limit:
        try:
            if join(HOST, PORT, "Fremder", timeout=2)["result"] == "denied":
                return time.monotonic() - start
        except (TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Welt nicht bereit")


def main() -> None:
    prov = DockerProvisioner("tcp://127.0.0.1:23750", INSTANCE)
    client = docker.DockerClient(base_url="tcp://127.0.0.1:23750", version="auto")
    access = render_access_file(1, {n: make_verifier(n, p) for n, p in PW.items()})
    conf = render_minetest_conf("Spike4", "weltschluessel-geheim-xyz", MTG_KREATIV)
    payload = build_world_payload(MTG_KREATIV, conf, render_world_mt(MTG_KREATIV), access)
    prov.create_world_container(WORLD, PORT, payload)
    payload.archive.close()
    c = client.containers.get(resource_name(INSTANCE, WORLD))
    push = lambda data: prov.write_world_files(WORLD, tar_of({"gameworld_time.txt": (data, 0, 0o444)}))  # noqa: E731
    try:
        mod = (HERE / "time_mod.lua").read_bytes()
        conf_mod = b"name = gameworld_time\ndepends = gameworld_access\n"
        c.put_archive(WDIR, tar_of({"worldmods/gameworld_time/init.lua": (mod, 30000, 0o644),
                                    "worldmods/gameworld_time/mod.conf": (conf_mod, 30000, 0o644)}))
        # S1: Mia 40 s Kontingent, kein Fenster; Papa ohne Regeln.
        push(rules(1, {"Mia": (40, -1, 0, "ok", "Morgen-14:00")}))
        prov.start_world(WORLD)
        log("bereit nach", round(wait_ready(), 1), "s")
        diag = read(c, f"{WDIR}/gameworld_time_diag.txt")
        os_time = int(diag.split()[1])
        log("S0 Uhr: Container os.time - Host time.time =", os_time - int(time.time()), "s;", diag.replace("\n", " | "))

        log("S1 Mia mit 40 s Kontingent, halten bis 70 s:")
        log("  ", session(HOST, PORT, "Mia", PW["Mia"], hold=70))
        log("S2 sofortiger Rejoin Mia:", join(HOST, PORT, "Mia", PW["Mia"]))
        log("S3 Zaehlbuch:", ledger(c))

        log("S4 Neustart der Welt (stop/start):")
        prov.stop(WORLD)
        prov.start_world(WORLD)
        log("   bereit nach", round(wait_ready(), 1), "s; Zaehlbuch:", ledger(c))
        log("   Rejoin Mia nach Neustart:", join(HOST, PORT, "Mia", PW["Mia"]))
        log("   Papa ohne Regeln:", join(HOST, PORT, "Papa", PW["Papa"])["result"])

        basis = ledger(c).get("Mia", 0)
        until = int(time.time()) + 20
        push(rules(2, {"Mia": (300, until, basis, "ok", "Sa-10:00")}))
        log(f"S5 Mia neues Kontingent 300 s, Fenster endet in 20 s (basis {basis}), halten bis 45 s:")
        log("  ", session(HOST, PORT, "Mia", PW["Mia"], hold=45))

        log("S5b sofortiger Rejoin nach Kick (Wiederbeitritts-Sperre 2 s):", join(HOST, PORT, "Mia", PW["Mia"]))
        time.sleep(2.5)
        basis = ledger(c).get("Mia", 0)
        push(rules(3, {"Mia": (300, -1, basis, "ok", "-")}))
        result: dict[str, object] = {}
        worker = threading.Thread(target=lambda: result.update(session(HOST, PORT, "Mia", PW["Mia"], hold=40)))
        worker.start()
        time.sleep(10)
        pushed = time.monotonic()
        push(rules(4, {"Mia": (0, -1, ledger(c).get("Mia", 0), "ok", "Morgen-14:00")}))
        worker.join()
        log("S6 Live-Push Kontingent 0 nach 10 s online:", result, "Kick", round(time.monotonic() - pushed, 1),
            "s nach Push (Sitzungsende)")

        time.sleep(2.5)
        world_closed = "welt 0 welt Mi-10:00"
        push(rules(5, {"Papa": (-1, -1, 0, "frei", "-")}, world_line=world_closed))
        time.sleep(1)
        log("S7 Welt geschlossen: Mia", join(HOST, PORT, "Mia", PW["Mia"]))
        log("   Papa (frei):", join(HOST, PORT, "Papa", PW["Papa"])["result"])
        push(rules(6, {}, complete=False))
        time.sleep(6)
        log("S8 halbe Regeldatei: Mia", join(HOST, PORT, "Mia", PW["Mia"]).get("reason"),
            "| Papa", join(HOST, PORT, "Papa", PW["Papa"])["result"])
        before = ledger(c).get("Mia", 0)
        push(rules(7, {}))
        time.sleep(1)
        log("S9 Regeldatei leer (keine Regeln): Mia 30 s halten:", session(HOST, PORT, "Mia", PW["Mia"], hold=30))
        time.sleep(6)
        log("   Zaehlbuch-Zuwachs Mia nach 30 s Sitzung:", ledger(c).get("Mia", 0) - before, "s")
        logs = c.logs(tail=400).decode("utf-8", "replace")
        log("Fehler im Server-Log:", [l for l in logs.splitlines() if "ERROR" in l][:5])
    finally:
        tail = c.logs(tail=60).decode("utf-8", "replace").splitlines()
        log("Log-Ende:", *("\n    " + line for line in tail if "ERROR" in line or "rror" in line or "WARNING" in line))
        prov.remove_world(WORLD, keep_volume=False)
        log("aufgeraeumt")


if __name__ == "__main__":
    main()

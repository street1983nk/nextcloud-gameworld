"""Phase-4-Spike B: Absturz beim schnellen Wieder-Join nach einem Kick eingrenzen (ohne Zeit-Mod).

Kontrolle mit dem Stand von Phase 3 (nur gameworld_access + gameworld_status, Minetest Game kreativ):
A  normales Verlassen (DISCO), nach VERZUG Sekunden wieder beitreten
C  Kick durch den Zugangs-Mod (Widerruf), Wieder-Einladung, nach VERZUG Sekunden wieder beitreten
zuletzt: sofortiger Wieder-Join ohne Pause (erwartet: Absturz des Servers, Engine-Wettlauf)
Aufruf aus dem Repo-Root: .venv/Scripts/python.exe -I .planning/phases/04-spielzeitlimits/spike/spike4b.py [VERZUG]
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from session_probe import session  # noqa: E402
from spike4 import HOST, PORT, PW, WORLD, log, wait_ready  # noqa: E402

import docker  # noqa: E402
from gameworld.provisioner.access_mod import render_access_file  # noqa: E402
from gameworld.provisioner.archive import build_access_tar, build_world_payload  # noqa: E402
from gameworld.provisioner.client import DockerProvisioner  # noqa: E402
from gameworld.provisioner.luanti_auth import make_verifier  # noqa: E402
from gameworld.provisioner.luanti_conf import render_minetest_conf, render_world_mt  # noqa: E402
from gameworld.provisioner.presets import MTG_KREATIV  # noqa: E402
from gameworld.provisioner.spec import resource_name  # noqa: E402

DELAY = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0


def main() -> None:
    prov = DockerProvisioner("tcp://127.0.0.1:23750", "spike4")
    client = docker.DockerClient(base_url="tcp://127.0.0.1:23750", version="auto")
    verifiers = {n: make_verifier(n, p) for n, p in PW.items()}
    generation = 1
    conf = render_minetest_conf("Spike4b", "weltschluessel-geheim-xyz", MTG_KREATIV)
    payload = build_world_payload(MTG_KREATIV, conf, render_world_mt(MTG_KREATIV),
                                  render_access_file(generation, verifiers))
    prov.create_world_container(WORLD, PORT, payload)
    payload.archive.close()
    c = client.containers.get(resource_name("spike4", WORLD))

    def access(names: list[str]) -> None:
        nonlocal generation
        generation += 1
        prov.write_world_files(WORLD, build_access_tar(render_access_file(generation, {n: verifiers[n] for n in names})))

    def kicked_then_rejoin(label: str, delay: float) -> None:
        result: dict[str, object] = {}
        worker = threading.Thread(target=lambda: result.update(session(HOST, PORT, "Mia", PW["Mia"], hold=20)))
        worker.start()
        time.sleep(4)
        access(["Papa"])  # Widerruf: Zugangs-Mod kickt im 5-s-Takt
        worker.join()
        log(f"{label} Kick:", result.get("result"), [e for e in result.get("events", []) if e[1] == "kick"])
        access(["Mia", "Papa"])
        time.sleep(delay)
        log(f"{label} Wieder-Join nach {delay} s:", session(HOST, PORT, "Mia", PW["Mia"], hold=4).get("result"))
        log(f"{label} Server lebt:", c.reload() or c.status, session(HOST, PORT, "Papa", PW["Papa"], hold=2)["result"])

    try:
        prov.start_world(WORLD)
        log("bereit nach", round(wait_ready(), 1), "s")
        first = session(HOST, PORT, "Mia", PW["Mia"], hold=3)
        log("A erste Sitzung:", first["result"])
        time.sleep(DELAY)
        log(f"A nach {DELAY} s wieder:", session(HOST, PORT, "Mia", PW["Mia"], hold=3)["result"])
        time.sleep(DELAY)
        kicked_then_rejoin("C", DELAY)
        time.sleep(DELAY)
        session(HOST, PORT, "Mia", PW["Mia"], hold=1)
        again = session(HOST, PORT, "Mia", PW["Mia"], hold=3)
        log("A sofort wieder (ohne Pause, erwartet Absturz):", again["result"],
            [e[2] for e in again.get("events", []) if e[1] == "kick"])
        time.sleep(2)
    except Exception as exc:  # noqa: BLE001
        log("Abbruch:", repr(exc))
    finally:
        c.reload()
        log("Containerstatus:", c.status)
        tail = c.logs(tail=60).decode("utf-8", "replace").splitlines()
        log("Log-Ende:", *("\n    " + line for line in tail if "ERROR" in line))
        prov.remove_world(WORLD, keep_volume=False)
        log("aufgeraeumt")


if __name__ == "__main__":
    main()

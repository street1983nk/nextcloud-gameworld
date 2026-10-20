"""Phase-4-Spike C: Ab welchem Abstand ist ein Wieder-Join nach dem Verlassen sicher?

Ohne Zeit-Mod (Stand Phase 3). Pro Abstand: Sitzung 3 s, Verlassen (DISCO), Pause, zweite Sitzung.
Stürzt der Server ab, wird die Welt neu gestartet und der nächste Abstand geprüft.
Aufruf: .venv/Scripts/python.exe -I .planning/phases/04-spielzeitlimits/spike/spike4c.py [mtg|voxelibre]
"""

from __future__ import annotations

import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from session_probe import session  # noqa: E402
from spike4 import HOST, PORT, PW, WORLD, log, wait_ready  # noqa: E402

import docker  # noqa: E402
from gameworld.provisioner.access_mod import render_access_file  # noqa: E402
from gameworld.provisioner.archive import build_world_payload  # noqa: E402
from gameworld.provisioner.client import DockerProvisioner  # noqa: E402
from gameworld.provisioner.luanti_auth import make_verifier  # noqa: E402
from gameworld.provisioner.luanti_conf import render_minetest_conf, render_world_mt  # noqa: E402
from gameworld.provisioner.presets import get_preset  # noqa: E402
from gameworld.provisioner.spec import resource_name  # noqa: E402

PRESET = {"mtg": "mtg_kreativ", "voxelibre": "voxelibre_sanft"}[sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else "mtg"]
DELAYS = (0.2, 0.5, 1.0, 2.0, 3.0, 5.0)
WITH_MOD = "--mit-zeitmod" in sys.argv


def main() -> None:
    preset = get_preset(PRESET)
    prov = DockerProvisioner("tcp://127.0.0.1:23750", "spike4")
    client = docker.DockerClient(base_url="tcp://127.0.0.1:23750", version="auto")
    access = render_access_file(1, {n: make_verifier(n, p) for n, p in PW.items()})
    payload = build_world_payload(preset, render_minetest_conf("Spike4c", "weltschluessel-geheim-xyz", preset),
                                  render_world_mt(preset), access)
    prov.create_world_container(WORLD, PORT, payload)
    payload.archive.close()
    c = client.containers.get(resource_name("spike4", WORLD))
    if WITH_MOD:
        from spike4 import WDIR, tar_of  # noqa: PLC0415

        conf_mod = b"name = gameworld_time\ndepends = gameworld_access\n"
        c.put_archive(WDIR, tar_of({"worldmods/gameworld_time/init.lua": ((HERE / "time_mod.lua").read_bytes(), 30000, 0o644),
                                    "worldmods/gameworld_time/mod.conf": (conf_mod, 30000, 0o644)}))
    try:
        prov.start_world(WORLD)
        log(PRESET, "bereit nach", round(wait_ready(120), 1), "s")
        session(HOST, PORT, "Mia", PW["Mia"], hold=8, timeout=60)  # Medien/Defs einmal "laden"
        for delay in DELAYS:
            first_session = session(HOST, PORT, "Mia", PW["Mia"], hold=3, timeout=30)
            first = first_session["result"] + str([e[2] for e in first_session.get("events", []) if e[1] == "kick"])
            time.sleep(delay)
            try:
                second = session(HOST, PORT, "Mia", PW["Mia"], hold=3, timeout=30)
                second_result = f"{second['result']} {second.get('reason', '')}"
                kick = [e[2] for e in second.get("events", []) if e[1] == "kick"]
            except (TimeoutError, OSError) as exc:
                second_result, kick = "fehler", [repr(exc)]
            time.sleep(1)
            c.reload()
            log(f"Abstand {delay} s: erste {first}, zweite {second_result} {kick}, Container {c.status}")
            if c.status != "running":
                prov.start_world(WORLD)
                wait_ready(120)
    finally:
        tail = c.logs(tail=200).decode("utf-8", "replace").splitlines()
        errors = [line for line in tail if "ERROR[Main]: ServerError" in line]
        log("Absturzmeldungen:", len(errors), *("\n    " + line[:220] for line in errors[:2]))
        prov.remove_world(WORLD, keep_volume=False)
        log("aufgeraeumt")


if __name__ == "__main__":
    main()

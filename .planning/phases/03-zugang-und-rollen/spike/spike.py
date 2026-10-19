"""Phase-3-Spike: Whitelist + Auth-Provisionierung ohne exec, Live gegen den Dev-Proxy."""

from __future__ import annotations

import io
import pathlib
import sys
import tarfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import docker  # noqa: E402

from gameworld.provisioner.archive import build_world_payload  # noqa: E402
from gameworld.provisioner.client import DockerProvisioner  # noqa: E402
from gameworld.provisioner.luanti_conf import render_minetest_conf, render_world_mt  # noqa: E402
from gameworld.provisioner.presets import MTG_KREATIV  # noqa: E402
from gameworld.provisioner.spec import DATA_DIR, resource_name  # noqa: E402
from luanti_probe import join  # noqa: E402
from luanti_srp import make_verifier  # noqa: E402

INSTANCE = "spike3"
WORLD = "w1"
PORT = 30091
WDIR = ".minetest/worlds/world"
PW = "Sonne-Baum-42"


def tar_of(files: dict[str, tuple[bytes, int, int]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, (data, uid, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.gid, info.mode = len(data), uid, 30000, mode
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def access_file(entries: dict[str, str]) -> bytes:
    lines = ["gameworld-access 1", *(f"{n} {h}" for n, h in sorted(entries.items())), "end"]
    return ("\n".join(lines) + "\n").encode()


def read_file(container, path: str) -> str:
    try:
        stream, _ = container.get_archive(path)
    except docker.errors.NotFound:
        return "<fehlt>"
    raw = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        return tar.extractfile(tar.getmembers()[0]).read().decode()


def main() -> None:
    prov = DockerProvisioner("tcp://127.0.0.1:23750", INSTANCE)
    client = docker.DockerClient(base_url="tcp://127.0.0.1:23750", version="auto")
    conf = render_minetest_conf("Spike3", "weltschluessel-geheim-xyz", MTG_KREATIV)
    payload = build_world_payload(MTG_KREATIV, conf, render_world_mt(MTG_KREATIV))
    t = time.monotonic()
    prov.create_world_container(WORLD, PORT, payload)
    payload.archive.close()
    c = client.containers.get(resource_name(INSTANCE, WORLD))
    mod = (HERE / "access_mod.lua").read_bytes()
    ok = c.put_archive(
        DATA_DIR,
        tar_of({
            f"{WDIR}/worldmods/gameworld_access/init.lua": (mod, 30000, 0o644),
            f"{WDIR}/worldmods/gameworld_access/mod.conf": (b"name = gameworld_access\n", 30000, 0o644),
        }),
    )
    print("mod put_archive (vor Start):", ok)
    prov.start_world(WORLD)
    for _ in range(40):
        if read_file(c, f"{DATA_DIR}/{WDIR}/gameworld_players.txt") != "<fehlt>":
            break
        time.sleep(0.25)
    print(f"bereit nach {time.monotonic() - t:.1f} s")
    try:
        print("A0 ohne Access-Datei, Mia:", join("127.0.0.1", PORT, "Mia"))
        # Datei in LAUFENDEN Container schreiben (read_only rootfs, Ziel im Volume)
        v_mia = make_verifier("Mia", PW)
        t0 = time.monotonic()
        ok = c.put_archive(f"{DATA_DIR}/{WDIR}", tar_of({"gameworld_access.txt": (access_file({"Mia": v_mia}), 0, 0o444)}))
        print(f"access put_archive (laufend): {ok} in {time.monotonic() - t0:.2f} s")
        print("A1 nicht eingeladen, Fremder:", join("127.0.0.1", PORT, "Fremder"))
        print("A2 eingeladen, Mia, nur HELLO:", join("127.0.0.1", PORT, "Mia"))
        print("A3 eingeladen, Mia, richtiges PW:", join("127.0.0.1", PORT, "Mia", PW))
        print("A4 eingeladen, Mia, falsches PW:", join("127.0.0.1", PORT, "Mia", "falsch"))
        print("A5 Groß/klein, mia:", join("127.0.0.1", PORT, "mia", PW))
        # Unvollständige Datei: alter Stand muss bleiben
        c.put_archive(f"{DATA_DIR}/{WDIR}", tar_of({"gameworld_access.txt": (b"gameworld-access 1\nLeo #1#x#y\n", 0, 0o444)}))
        print("A6 nach kaputter Datei, Mia PW:", join("127.0.0.1", PORT, "Mia", PW))
        # Widerruf + neuer Spieler
        v_leo = make_verifier("Leo", "Wolke-Tiger-17")
        c.put_archive(f"{DATA_DIR}/{WDIR}", tar_of({"gameworld_access.txt": (access_file({"Leo": v_leo}), 0, 0o444)}))
        print("A7 nach Widerruf, Mia PW:", join("127.0.0.1", PORT, "Mia", PW))
        print("A8 Leo neu, PW:", join("127.0.0.1", PORT, "Leo", "Wolke-Tiger-17"))
        print("A9 Leo, Welt-Schluessel (default_password):", join("127.0.0.1", PORT, "Leo", "weltschluessel-geheim-xyz"))
        print("--- Mod-Log ---")
        print(read_file(c, f"{DATA_DIR}/{WDIR}/gameworld_spike.txt"))
        print("--- docker logs (Ende) ---")
        print(c.logs(tail=25).decode("utf-8", "replace"))
        print("Inspect ReadonlyRootfs:", c.attrs["HostConfig"]["ReadonlyRootfs"])
    finally:
        prov.remove_world(WORLD, keep_volume=False)
        print("aufgeraeumt")


if __name__ == "__main__":
    main()

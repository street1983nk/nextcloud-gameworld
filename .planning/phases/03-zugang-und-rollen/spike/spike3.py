from __future__ import annotations
import pathlib, sys, time
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import spike as s  # noqa: E402
from luanti_probe import join  # noqa: E402
GOLDEN = "#1#AAECAwQFBgcICQoLDA0ODw==#pCyNep+1Ug3he9xjpqMCK1MBx7OOe2SLVkX1lvyHmIf8bATbrA6zgiJ/+xEmx+MaV+IllHKn1rqJHViRuv9ysMGPSDxm5xWmTyhasxEQtfWJI1EiyABU/v15UncRaqWEr+OvrPXxcsb3QCsQrZ8cYd1vgRaJByW7QmW75Le8VriHfR+/xNSE2hHnmFd60n0eOlufj7UBtmfTmFOIO/uHbnvA74UHr3LnoeimBaOXvo4OR9NorNAjcVYraZ0i9HvO98VoRCKxvFsYXrbnfHJGE+3VWpsAPqmcGXzfFTkrzrfPY78b7lOjUMReiUf2zchmlwcNc12S46iQOEHkiFsdhw=="
prov = s.DockerProvisioner("tcp://127.0.0.1:23750", s.INSTANCE)
client = s.docker.DockerClient(base_url="tcp://127.0.0.1:23750", version="auto")
conf = s.render_minetest_conf("Spike3c", "weltschluessel-geheim-xyz", s.MTG_KREATIV)
payload = s.build_world_payload(s.MTG_KREATIV, conf, s.render_world_mt(s.MTG_KREATIV))
prov.create_world_container(s.WORLD, s.PORT, payload); payload.archive.close()
c = client.containers.get(s.resource_name(s.INSTANCE, s.WORLD))
try:
    files = {f"{s.WDIR}/worldmods/gameworld_access/init.lua": ((HERE / "access_mod_lock.lua").read_bytes(), 30000, 0o644),
             f"{s.WDIR}/worldmods/gameworld_access/mod.conf": (b"name = gameworld_access\n", 30000, 0o644),
             f"{s.WDIR}/gameworld_access.txt": (s.access_file({"Mia": GOLDEN, "Leo": GOLDEN}), 0, 0o444)}
    c.put_archive(s.DATA_DIR, s.tar_of(files)); prov.start_world(s.WORLD); time.sleep(4)
    print("Golden Mia richtig:", join("127.0.0.1", s.PORT, "Mia", s.PW)["result"])
    print("Golden Leo (Verifier fuer Mia):", join("127.0.0.1", s.PORT, "Leo", s.PW).get("code"))
    t = time.monotonic()
    res = [join("127.0.0.1", s.PORT, "Mia", f"falsch{i}").get("code") for i in range(5)]
    print(f"5 Fehlversuche in {time.monotonic()-t:.2f} s:", res)
    print("danach Mia richtig:", join("127.0.0.1", s.PORT, "Mia", s.PW))
finally:
    prov.remove_world(s.WORLD, keep_volume=False); print("aufgeraeumt")

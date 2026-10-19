"""Die gehärtete Container-Spec ist fest kodiert und ohne Docker prüfbar (WELT-05)."""

from gameworld.provisioner.spec import LUANTI_IMAGE, LUANTI_VERSION, resource_name, world_spec

INSTANCE = "ab12cd34"
WORLD = "0123456789ab"
NAME = "gameworld-ab12cd34-0123456789ab"


def _spec() -> dict[str, object]:
    return world_spec(INSTANCE, WORLD, 30015)


def test_image_is_pinned_by_digest() -> None:
    spec = _spec()
    assert spec["image"] == LUANTI_IMAGE
    assert "@sha256:db682cae" in LUANTI_IMAGE
    assert LUANTI_VERSION == "5.17.0"


def test_name_carries_instance_and_world() -> None:
    assert resource_name(INSTANCE, WORLD) == NAME
    assert _spec()["name"] == NAME


def test_limits_and_hardening() -> None:
    spec = _spec()
    assert spec["user"] == "30000:30000"
    assert spec["mem_limit"] == "512m"
    assert spec["memswap_limit"] == "512m"
    assert spec["pids_limit"] == 128
    assert spec["nano_cpus"] == 1_000_000_000
    assert spec["cap_drop"] == ["ALL"]
    assert spec["security_opt"] == ["no-new-privileges:true"]
    assert spec["read_only"] is True
    assert spec["restart_policy"] == {"Name": "no"}


def test_ports_and_storage() -> None:
    spec = _spec()
    assert spec["ports"] == {"30000/udp": ("0.0.0.0", 30015)}  # noqa: S104
    mounts = spec["mounts"]
    assert isinstance(mounts, list)
    assert len(mounts) == 1
    mount = mounts[0]
    assert mount["Type"] == "volume"
    assert mount["Source"] == NAME
    assert mount["Target"] == "/var/lib/minetest"
    tmpfs = spec["tmpfs"]
    assert isinstance(tmpfs, dict)
    assert "/etc/minetest" in tmpfs
    assert "/tmp" in tmpfs  # noqa: S108


def test_dangerous_keys_are_absent() -> None:
    spec = _spec()
    for key in ("privileged", "volumes", "network_mode", "pid_mode", "devices", "cap_add", "environment"):
        assert key not in spec, key


def test_labels() -> None:
    assert _spec()["labels"] == {
        "gameworld.managed": "true",
        "gameworld.instance": INSTANCE,
        "gameworld.world_id": WORLD,
        "gameworld.schema": "1",
        "gameworld.engine": "luanti",
        "gameworld.engine_version": "5.17.0",
        "gameworld.port": "30015",
    }

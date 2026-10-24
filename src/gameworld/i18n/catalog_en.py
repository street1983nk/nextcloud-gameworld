"""English server texts (D-25). Keys are the imported German constants, never copied literals.

Terms follow the glossary of 06-17 (manager, world, player, backup, playtime, time
window, holidays, break, world data, container, Talk room). Values inserted into
templates (hosts, ports, Docker explanations, type names) are never translated.
"""

from __future__ import annotations

from gameworld import config, nc
from gameworld.access import accounts, directory, roles, secret
from gameworld.access import service as access_service
from gameworld.api import admin, alerts, backups, csrf, invites, me, pause, talk, talk_bot
from gameworld.api import playtime as playtime_api
from gameworld.backup import archive, files
from gameworld.backup import service as backup_service
from gameworld.notify import links
from gameworld.play import ticket_api
from gameworld.playtime import pause as playtime_pause
from gameworld.playtime import plan
from gameworld.playtime import service as playtime_service
from gameworld.provisioner import archive as game_archive
from gameworld.provisioner import client, presets, setup_check
from gameworld.talk import rooms
from gameworld.worlds import ports, status
from gameworld.worlds import service as world_service

_GUIDE = f"Guide: {setup_check.DOCS_URL}"
_UNAVAILABLE = "Nextcloud is not responding right now. Please try again in a moment."
_NOT_FOUND = "This world does not exist (anymore)."
_OOM = "The world ran out of memory and was stopped."
_GAMEKEY_DOWN = "The game secret cannot be read from Nextcloud right now."

MESSAGES: dict[str, str] = {
    # access/roles.py
    roles.MSG_NOT_LOGGED_IN: "Not logged in.",
    roles.MSG_UNAVAILABLE: _UNAVAILABLE,
    roles.MSG_FORBIDDEN: "Only parents can manage worlds.",
    roles.MSG_NC_ADMIN_ONLY: "Only Nextcloud admins can change this.",
    # access/accounts.py, directory.py, secret.py, service.py
    accounts.MSG_INVALID_NAME: "The player name can have 1 to 20 characters: letters without accents, digits, _ and -.",
    directory.MSG_UNAVAILABLE: _UNAVAILABLE,
    secret.MSG_UNAVAILABLE: _GAMEKEY_DOWN,
    secret.MSG_UNREADABLE: "The stored game secret is unreadable and will not be overwritten.",
    access_service.MSG_UNKNOWN_ACCOUNT: "This Nextcloud account does not exist or is disabled.",
    access_service.MSG_UNKNOWN_GROUP: "This Nextcloud group does not exist.",
    access_service.MSG_NO_PLAYER: "There is no player for this Nextcloud account yet.",
    access_service.MSG_NAME_TAKEN: "Someone else already has this player name.",
    access_service.MSG_REPROVISION_PENDING: "The login details are being renewed; please fetch them again in a moment.",
    access_service.MSG_ACCOUNT_OUT_OF_SCOPE: "This account is not in any of your groups.",
    access_service.MSG_GROUP_OUT_OF_SCOPE: "This group is not one of your groups.",
    # api/admin.py
    admin.MSG_ADMIN_FIXED: "The admin group always manages Gameworld.",
    admin.MSG_UNKNOWN_GROUP: "This group does not exist in Nextcloud.",
    admin.MSG_CONFLICT: "The manager groups were just changed. Please reload.",
    admin.MSG_SEARCH_UNAVAILABLE: "Group search in Nextcloud is not possible right now.",
    admin.MSG_ORPHAN_REFUSED: "This belongs to this installation or not to Gameworld.",
    admin.MSG_ORPHAN_IN_USE: "The world data is still used by a container.",
    admin.MSG_DOCKER_UNAVAILABLE: "Gameworld cannot reach Docker right now. Please try again later.",
    admin.MSG_ORPHAN_FAILED: "Docker refused the removal. Details are in the ExApp log.",
    # api/alerts.py, backups.py, csrf.py, invites.py, me.py, pause.py, playtime.py, talk.py, talk_bot.py
    alerts.MSG_UNAVAILABLE: "The data cannot be read right now. Please try again in a moment.",
    alerts.DELETED_WORLD: "deleted world",
    backups.MSG_BAD_FILE_ID: "file_id must be a positive whole number.",
    csrf.MSG_NOT_JSON: "Gameworld only accepts changes as JSON from its own page.",
    csrf.MSG_FOREIGN: "Gameworld only accepts changes from its own page.",
    invites.MSG_UNAVAILABLE: _UNAVAILABLE,
    invites.MSG_INVALID_TARGET: "Invalid account or group ID.",
    invites.MSG_INVALID_HOST: "Please enter only a host name or an IP address, without http:// and without a port.",
    me.TEXT_WELT_PROBLEM: "This world has a problem right now. Tell your parents.",
    me.TEXT_WELT_PAUSE: "The world is taking a short break",
    pause.MSG_UNAVAILABLE: "The break could not be saved right now. Please try again in a moment.",
    playtime_api.MSG_UNAVAILABLE: _UNAVAILABLE,
    talk.MSG_NO_ROOM: "This world does not have a Talk room yet. It is created at the next sync once Talk is ready.",
    talk.MSG_TALK_DOWN: "Talk is not responding right now. Please try again in a moment.",
    talk_bot.MSG_ONLY_APPAPI: "This address is only for Talk via AppAPI.",
    # backup/archive.py
    archive.MSG_BAD_ENTRY: "The backup contains invalid or unsafe entries.",
    archive.MSG_NO_MAP: "Without a world map (map.sqlite) there is no valid backup.",
    archive.MSG_FOREIGN_WORLD: "This backup belongs to a different world.",
    archive.MSG_TOO_BIG: "The backup is too large or suspiciously highly compressed.",
    archive.MSG_NO_MANIFEST: "The backup was not made by Gameworld or is damaged.",
    archive.MSG_NO_SPACE: "Not enough free disk space on the server.",
    archive.MSG_BROKEN_STREAM: "The world data could not be read completely.",
    # backup/files.py
    files.MSG_QUOTA: "Not enough storage space in your Nextcloud files.",
    files.MSG_UPLOAD_INCOMPLETE: "The backup was not completely saved to Nextcloud.",
    files.MSG_FILE_GONE: "This backup is no longer in your Nextcloud files.",
    files.MSG_FILES_FAILED: "Nextcloud Files cannot be reached right now.",
    files.MSG_NAME_EXHAUSTED: "Too many backups with the same name. Please try again in a minute.",
    # backup/service.py (job messages are stored and translated on delivery)
    backup_service.BACKUP_NOT_FOUND: "This backup does not exist (anymore).",
    backup_service.JOB_FAILED: "The backup failed. The world keeps running.",
    backup_service.JOB_UNUSABLE: "The backup was incomplete and was discarded. The world keeps running.",
    backup_service.PLAYERS_ONLINE_ONE: "1 child is playing in the world right now and will be disconnected briefly.",
    backup_service.JOB_INTERRUPTED: "The backup was interrupted by a server restart.",
    backup_service.RESTORE_JOB_INTERRUPTED: "The restore was interrupted by a server restart.",
    backup_service.RESTORE_NOT_CONFIRMED: "Please confirm the restore.",
    backup_service.RESTORE_TAMPERED: "The backup was modified and will not be restored.",
    backup_service.RESTORE_FAILED: "The restore failed. The world keeps running.",
    backup_service.RESTORE_FALLBACK: "The restore failed. The previous world was brought back.",
    backup_service.RESTORE_SWAP_FAILED: "The restore failed. Please restore again.",
    # nc.py, notify/links.py
    nc.MSG_NO_USER: "A Nextcloud client acting for an account needs an account ID.",
    links.MSG_INVALID_ORIGIN: "The address must look like https://cloud.example or https://example.org/nextcloud.",
    # play/ticket_api.py (seen by kids)
    ticket_api.TEXT_NICHT_EINGELADEN: "You don't have an invitation for this world.",
    ticket_api.TEXT_WELT_AUS: "This world is not running right now. Tell your parents.",
    ticket_api.TEXT_TICKET: "The game start has expired. Please start the game again from Gameworld.",
    ticket_api.TEXT_FREMD: "Gameworld only starts the game from its own page.",
    ticket_api.TEXT_NAME_NEU: "Your player name has changed. Please start the game again from Gameworld.",
    ticket_api.MSG_NOT_LOGGED_IN: "Not logged in.",
    # playtime/pause.py, playtime/service.py
    playtime_pause.MSG_BAD_MINUTES: "A break lasts 15, 30 or 60 minutes.",
    playtime_service.MSG_TOO_MANY_HOLIDAYS: f"At most {playtime_service.MAX_HOLIDAYS} holiday periods are possible.",
    playtime_service.MSG_NO_HOLIDAY: "This holiday period does not exist.",
    playtime_service.MSG_ADMIN_NO_RULES: "Managers have no playtime rules.",
    playtime_service.MSG_ADULT_IS_VERWALTER: "This account manages Gameworld and plays without rules anyway.",
    playtime_service.MSG_WINDOW_NEEDS_OPEN_DAY: "A world with a time window needs at least one open day.",
    # provisioner/client.py
    client.NOT_FOUND_MESSAGE: _NOT_FOUND,
    client.SNAPSHOT_RUNNING: "The world is still running; a backup needs a stopped world.",
    # provisioner/presets.py
    presets.MTG_KREATIV.title: "Build (creative)",
    presets.MTG_KREATIV.description: "Minetest Game: unlimited blocks, no damage, flying allowed.",
    presets.VOXELIBRE_SANFT.title: "Adventure (gentle)",
    presets.VOXELIBRE_SANFT.description: "VoxeLibre: survival with peaceful animals, inventory is kept on death.",
    # provisioner/setup_check.py
    setup_check.MSG_CONTAINERS_OK: "Access to containers is allowed.",
    setup_check.MSG_CONTAINERS_DENIED: (
        f"The Docker proxy does not allow access to containers. Please set CONTAINERS=1. {_GUIDE}"
    ),
    setup_check.MSG_POST_OK: "Write requests are allowed.",
    setup_check.MSG_POST_DENIED: (
        "The Docker proxy does not allow write requests, so worlds can neither be created "
        f"nor started. Please set POST=1. {_GUIDE}"
    ),
    setup_check.MSG_IMAGES_OK: "Access to images is allowed.",
    setup_check.MSG_IMAGES_DENIED: f"The Docker proxy does not allow access to images. Please set IMAGES=1. {_GUIDE}",
    setup_check.MSG_VOLUMES_OK: "Access to volumes is allowed.",
    setup_check.MSG_VOLUMES_DENIED: (
        "The Docker proxy does not allow access to volumes, so worlds cannot be deleted. "
        f"Please set VOLUMES=1. {_GUIDE}"
    ),
    setup_check.MSG_EXEC_OK: "Commands in containers are blocked.",
    setup_check.MSG_EXEC_OPEN: (
        f"The Docker proxy is too open: commands in containers are allowed. Please set EXEC=0. {_GUIDE}"
    ),
    setup_check.MSG_INFO_OK: "System information is blocked.",
    setup_check.MSG_INFO_OPEN: f"The Docker proxy reveals system information. Please set INFO=0. {_GUIDE}",
    setup_check.MSG_NOT_CHECKED: f"Not checked: set POST=1 first, then run the setup check again. {_GUIDE}",
    setup_check.MSG_DOCKER_SOCKET: (
        "Gameworld should never talk to the Docker socket directly. Enter the address of the scoped "
        f"Docker proxy, default tcp://gameworld-docker-proxy:2375. {_GUIDE}"
    ),
    setup_check.MSG_PROXY_EXPOSED: (
        "The Docker proxy is on an address outside the private network. It must only be reachable "
        f"in Gameworld's Docker network. {_GUIDE}"
    ),
    setup_check.MSG_REACHABLE: "The Docker proxy is reachable.",
    # talk/rooms.py
    rooms.MSG_UNAVAILABLE: "Talk is not responding right now. Please try again later.",
    # worlds/service.py (stored as last_error, translated on delivery)
    world_service.PORTS_EXHAUSTED: "No free UDP port found. Please check the port range GAMEWORLD_PORT_RANGE.",
    world_service.NOT_FOUND: _NOT_FOUND,
    world_service.JOB_RUNNING: "A backup or restore is already running. Please wait a moment.",
    world_service.TEXT_UNKNOWN_PRESET: (
        "Gameworld does not know this world's game type. Please update Gameworld or delete the world."
    ),
    world_service.PAYLOAD_FAILED: (
        "The world data could not be prepared. Please check the free disk space on the server and try again."
    ),
    world_service.CREATE_FAILED: "The world could not be created. Please try again later.",
    world_service.RECONCILE_OOM: _OOM,
    world_service.RECONCILE_DATA_MISSING: "The world data is missing. The world can only be deleted.",
    world_service.RECONCILE_INTERRUPTED: (
        "Creating the world was interrupted. Please delete the world and create it again."
    ),
    world_service.RESTORE_INTERRUPTED: (
        "The restore was interrupted. Please restore again; the backup made before the restore is in Files."
    ),
    world_service.WORLD_BUSY: "The world is being backed up or restored right now.",
    world_service.OFFLINE_RESTART_FAILED: "The world could not be started again afterwards. Please start the world.",
    world_service.RECONCILE_FAILED: "The world could not be brought back after the server restart.",
    world_service.UNKNOWN_PRESET_TITLE: "Unknown game type",
    # worlds/status.py
    status.TEXT_UNREACHABLE: "Docker unreachable",
    status.TEXT_CREATING: "Being created",
    status.TEXT_BACKING_UP: "Backing up ...",
    status.TEXT_RESTORING: "Restoring ...",
    status.TEXT_UNKNOWN_ERROR: "Unknown error",
    status.TEXT_MISSING: "The world's server is missing. Starting it brings it back if the world data is still there.",
    status.TEXT_RESTARTING: "Keeps restarting",
    status.TEXT_RUNNING: "Running",
    status.TEXT_STARTING: "Starting",
    status.TEXT_STOPPED: "Stopped",
    status.TEXT_OOM: _OOM,
}

TEMPLATES: dict[str, str] = {
    # access/secret.py
    secret.TEXT_UNAVAILABLE_TYPE: _GAMEKEY_DOWN + " ({type_name})",
    # backup/service.py
    backup_service.PLAYERS_ONLINE_MANY: (
        "{count} children are playing in the world right now and will be disconnected briefly."
    ),
    # config.py
    config.TEXT_PORT_RANGE_INVALID: (
        "GAMEWORLD_PORT_RANGE is invalid: '{raw}'. Expected '<from>-<to>' with "
        "1024 <= from <= to <= 65535 and at most {max_width} ports."
    ),
    config.TEXT_STORAGE_UNUSABLE: (
        "APP_PERSISTENT_STORAGE is not usable: '{storage}' cannot be created as a directory ({error})."
    ),
    # provisioner/client.py
    client.TEXT_DOCKER_NOT_FOUND: "Docker does not know the object: {explanation}",
    client.TEXT_DOCKER_REJECTED: "Docker rejected the request: {explanation}",
    client.TEXT_DOCKER_UNREACHABLE: (
        "Gameworld cannot reach the Docker proxy at {docker_url}. "
        "Please check that the gameworld-docker-proxy service is running."
    ),
    client.TEXT_START_REJECTED: "Docker rejected starting the world: {explanation}",
    client.TEXT_PORT_IN_USE: "UDP port {port} is already in use on the server.",
    # provisioner/presets.py (the exact message with translated titles is in MESSAGES below)
    presets.TEXT_UNKNOWN_PRESET_ID: "Unknown game type. Allowed: {titles}.",
    # provisioner/setup_check.py
    setup_check.TEXT_PROXY_DNS: (
        "Gameworld cannot find the service {host}. It must run in the same Docker network as "
        "Gameworld (the network of the deploy daemon, nextcloud-aio for AIO). Guide: {docs_url}"
    ),
    setup_check.TEXT_PROXY_TIMEOUT: (
        "The Docker proxy at {host}:{port} is not responding. Usually it is in a different "
        "Docker network, or a firewall blocks port {port}. Guide: {docs_url}"
    ),
    setup_check.TEXT_PROXY_REFUSED: (
        "The Docker proxy at {host}:{port} does not accept connections. Is the "
        "gameworld-docker-proxy container running? Guide: {docs_url}"
    ),
    setup_check.TEXT_PROXY_UNREACHABLE: (
        "Gameworld cannot reach the Docker proxy at {docker_url}. Please start the "
        "gameworld-docker-proxy service and check GAMEWORLD_DOCKER_URL. Guide: {docs_url}"
    ),
    setup_check.TEXT_ENGINE_TOO_OLD: (
        "Docker Engine too old, API 1.44 or newer required (reported: {shown}). Please update Docker. Guide: {docs_url}"
    ),
    setup_check.TEXT_API_SUPPORTED: "Docker API {version} is supported.",
    setup_check.TEXT_UNEXPECTED_ANSWER: (
        "Unexpected answer from the Docker proxy to {method} {path}: HTTP {code}. Guide: {docs_url}"
    ),
    setup_check.TEXT_REQUEST_FAILED: "The request to the Docker proxy ({path}) failed: {error_type}. Guide: {docs_url}",
    # worlds/ports.py
    ports.TEXT_PORTS_TAKEN: "All UDP ports in the range {low}-{high} are in use.",
    # worlds/status.py
    status.TEXT_CRASHED: "The world stopped unexpectedly (code {code}).",
    status.TEXT_ODD_STATE: "Unexpected server state ({state}).",
}

# Task 3: raise texts of validators, rules, Docker refusals and the bundled game file.
MESSAGES.update(
    {
        # api/playtime.py (validators, 422)
        playtime_api.MSG_PLAYTIME_LABEL_CONTROL: "The label must not contain control characters or line breaks.",
        playtime_api.MSG_PLAYTIME_UNKNOWN_ZONE: "Unknown time zone.",
        playtime_api.MSG_WINDOW_SEVEN_DAYS: "A time window needs exactly the seven weekdays 1 to 7.",
        playtime_api.MSG_WEEKDAY_TWICE: "Each weekday may only appear once.",
        playtime_api.MSG_CLOSED_DAY_WINDOW: "A closed day has no time window.",
        playtime_api.MSG_OPEN_DAY_NEEDS_TIMES: "An open day needs the start and end of its time window.",
        # playtime/plan.py (rules, 422 via str(exc))
        plan.MSG_LIMIT_RANGE: "The daily limit is between 1 and 1440 minutes or None.",
        plan.MSG_WINDOW_BOTH_OR_NONE: "A time window needs both start and end, or neither.",
        plan.MSG_WINDOW_START_RANGE: "The window start is between 0 and 1439 minutes.",
        plan.MSG_WINDOW_END_RANGE: "The window end is between 1 and 1440 minutes.",
        plan.MSG_WINDOW_START_BEFORE_END: "The window start must be before the window end.",
        plan.MSG_WEEK_SEVEN_DAYS: "A weekly plan needs exactly the seven weekdays 1 to 7.",
        plan.MSG_HOLIDAY_ENDS_BEFORE_START: "A holiday period cannot end before it starts.",
        # provisioner/client.py
        client.MSG_PAYLOAD_REJECTED: "Docker did not accept the world data.",
        client.MSG_ACCESS_LIST_REJECTED: "Docker did not accept the world's access list.",
        client.MSG_BACKUP_REJECTED: "Docker did not accept the backup.",
        client.MSG_ORPHAN_BAD_ID: "Invalid container ID.",
        client.MSG_ORPHAN_CONTAINER_REFUSED: "The container belongs to this installation or not to Gameworld.",
        client.MSG_ORPHAN_VOLUME_REFUSED: "The volume belongs to this installation or not to Gameworld.",
        client.MSG_VOLUME_IN_USE: "The volume is still in use.",
        client.MSG_STATUS_FILE_UNREADABLE: "The world's status file cannot be read.",
        client.MSG_ACCESS_STATE_UNREADABLE: "The world's access state cannot be read.",
        client.MSG_LEDGER_UNREADABLE: "The world's playtime ledger cannot be read.",
        client.MSG_EVENTS_UNREADABLE: "The world's event file cannot be read.",
        # provisioner/archive.py
        game_archive.MSG_NO_GAME_CONF: "The bundled game file contains no game.conf.",
    }
)
TEMPLATES.update(
    {
        playtime_api.TEXT_HOLIDAY_MAX_DAYS: "A holiday period lasts at most {days} days.",
        game_archive.TEXT_GAME_ZIP_MISSING: (
            "The bundled game file is missing: {game_zip}. Please run sh scripts/fetch-games.sh."
        ),
        game_archive.TEXT_GAME_ZIP_TAMPERED: (
            "The bundled game file is damaged or modified ({game_zip}). Please reinstall Gameworld."
        ),
    }
)

# Messages whose inserted value is itself a German text: complete messages instead of templates.
MESSAGES[presets.unknown_preset_message([preset.title for preset in presets.PRESETS.values()])] = TEMPLATES[
    presets.TEXT_UNKNOWN_PRESET_ID
].format(titles=", ".join(MESSAGES[preset.title] for preset in presets.PRESETS.values()))
MESSAGES[setup_check.MSG_ENGINE_VERSION_UNKNOWN] = TEMPLATES[setup_check.TEXT_ENGINE_TOO_OLD].format(
    shown="unknown", docs_url=setup_check.DOCS_URL
)

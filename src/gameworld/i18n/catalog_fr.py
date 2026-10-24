"""French server texts (D-25). Keys are the imported German constants, never copied literals.

Terms follow the glossary of 06-17 (gestionnaire, monde, joueur, sauvegarde, temps de
jeu, plage horaire, vacances, pause, données de monde, conteneur, salon Talk); tu form.
Typography: non-breaking space before ? ! ; : and the apostrophe as escapes (RUF001).
Values inserted into templates are never translated.
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

_GUIDE = f"Guide\u00a0: {setup_check.DOCS_URL}"
_UNAVAILABLE = "Nextcloud ne répond pas pour le moment. Réessaie dans un instant."
_NOT_FOUND = "Ce monde n\u2019existe pas (ou plus)."
_OOM = "Le monde a manqué de mémoire et a été arrêté."
_GAMEKEY_DOWN = "Le secret de jeu n\u2019est pas lisible dans Nextcloud pour le moment."

MESSAGES: dict[str, str] = {
    # access/roles.py
    roles.MSG_NOT_LOGGED_IN: "Non connecté.",
    roles.MSG_UNAVAILABLE: _UNAVAILABLE,
    roles.MSG_FORBIDDEN: "Seuls les parents peuvent gérer les mondes.",
    roles.MSG_NC_ADMIN_ONLY: "Seuls les administrateurs Nextcloud peuvent modifier ceci.",
    # access/accounts.py, directory.py, secret.py, service.py
    accounts.MSG_INVALID_NAME: (
        "Le nom de joueur peut avoir 1 à 20 caractères\u00a0: lettres sans accents, chiffres, _ et -."
    ),
    directory.MSG_UNAVAILABLE: _UNAVAILABLE,
    secret.MSG_UNAVAILABLE: _GAMEKEY_DOWN,
    secret.MSG_UNREADABLE: "Le secret de jeu enregistré est illisible et ne sera pas écrasé.",
    access_service.MSG_UNKNOWN_ACCOUNT: "Ce compte Nextcloud n\u2019existe pas ou est désactivé.",
    access_service.MSG_UNKNOWN_GROUP: "Ce groupe Nextcloud n\u2019existe pas.",
    access_service.MSG_NO_PLAYER: "Il n\u2019y a pas encore de joueur pour ce compte Nextcloud.",
    access_service.MSG_NAME_TAKEN: "Quelqu\u2019un d\u2019autre a déjà ce nom de joueur.",
    access_service.MSG_REPROVISION_PENDING: (
        "Les identifiants sont en cours de renouvellement\u00a0; récupère-les à nouveau dans un instant."
    ),
    access_service.MSG_ACCOUNT_OUT_OF_SCOPE: "Ce compte n\u2019est dans aucun de tes groupes.",
    access_service.MSG_GROUP_OUT_OF_SCOPE: "Ce groupe ne fait pas partie de tes groupes.",
    # api/admin.py
    admin.MSG_ADMIN_FIXED: "Le groupe admin gère toujours Gameworld.",
    admin.MSG_UNKNOWN_GROUP: "Ce groupe n\u2019existe pas dans Nextcloud.",
    admin.MSG_CONFLICT: "Les groupes de gestionnaires viennent d\u2019être modifiés. Recharge la page.",
    admin.MSG_SEARCH_UNAVAILABLE: "La recherche de groupes dans Nextcloud n\u2019est pas possible pour le moment.",
    admin.MSG_ORPHAN_REFUSED: "Cet élément appartient à cette installation ou n\u2019appartient pas à Gameworld.",
    admin.MSG_ORPHAN_IN_USE: "Les données de monde sont encore utilisées par un conteneur.",
    admin.MSG_DOCKER_UNAVAILABLE: "Gameworld ne parvient pas à joindre Docker pour le moment. Réessaie plus tard.",
    admin.MSG_ORPHAN_FAILED: "Docker a refusé la suppression. Les détails figurent dans le journal de l\u2019ExApp.",
    # api/alerts.py, backups.py, csrf.py, invites.py, me.py, pause.py, playtime.py, talk.py, talk_bot.py
    alerts.MSG_UNAVAILABLE: "Les données ne sont pas lisibles pour le moment. Réessaie dans un instant.",
    alerts.DELETED_WORLD: "monde supprimé",
    backups.MSG_BAD_FILE_ID: "file_id doit être un nombre entier positif.",
    csrf.MSG_NOT_JSON: "Gameworld n\u2019accepte les modifications qu\u2019en JSON depuis sa propre page.",
    csrf.MSG_FOREIGN: "Gameworld n\u2019accepte les modifications que depuis sa propre page.",
    invites.MSG_UNAVAILABLE: _UNAVAILABLE,
    invites.MSG_INVALID_TARGET: "Identifiant de compte ou de groupe invalide.",
    invites.MSG_INVALID_HOST: "Saisis uniquement un nom d\u2019hôte ou une adresse IP, sans http:// et sans port.",
    me.TEXT_WELT_PROBLEM: "Ce monde a un problème en ce moment. Préviens tes parents.",
    me.TEXT_WELT_PAUSE: "Le monde fait une petite pause",
    pause.MSG_UNAVAILABLE: "La pause n\u2019a pas pu être enregistrée pour le moment. Réessaie dans un instant.",
    playtime_api.MSG_UNAVAILABLE: _UNAVAILABLE,
    talk.MSG_NO_ROOM: (
        "Ce monde n\u2019a pas encore de salon Talk. Il sera créé à la prochaine synchronisation, "
        "dès que Talk sera prêt."
    ),
    talk.MSG_TALK_DOWN: "Talk ne répond pas pour le moment. Réessaie dans un instant.",
    talk_bot.MSG_ONLY_APPAPI: "Cette adresse est réservée à Talk via AppAPI.",
    # backup/archive.py
    archive.MSG_BAD_ENTRY: "La sauvegarde contient des entrées invalides ou dangereuses.",
    archive.MSG_NO_MAP: "Sans carte du monde (map.sqlite), il n\u2019y a pas de sauvegarde valide.",
    archive.MSG_FOREIGN_WORLD: "Cette sauvegarde appartient à un autre monde.",
    archive.MSG_TOO_BIG: "La sauvegarde est trop grande ou anormalement compressée.",
    archive.MSG_NO_MANIFEST: "La sauvegarde ne provient pas de Gameworld ou est endommagée.",
    archive.MSG_NO_SPACE: "Pas assez d\u2019espace libre sur le serveur.",
    archive.MSG_BROKEN_STREAM: "Les données de monde n\u2019ont pas pu être lues entièrement.",
    # backup/files.py
    files.MSG_QUOTA: "Pas assez d\u2019espace de stockage dans tes fichiers Nextcloud.",
    files.MSG_UPLOAD_INCOMPLETE: "La sauvegarde n\u2019a pas été entièrement enregistrée dans Nextcloud.",
    files.MSG_FILE_GONE: "Cette sauvegarde ne se trouve plus dans tes fichiers Nextcloud.",
    files.MSG_FILES_FAILED: "Les fichiers Nextcloud sont injoignables pour le moment.",
    files.MSG_NAME_EXHAUSTED: "Trop de sauvegardes portent le même nom. Réessaie dans une minute.",
    # backup/service.py (job messages are stored and translated on delivery)
    backup_service.BACKUP_NOT_FOUND: "Cette sauvegarde n\u2019existe pas (ou plus).",
    backup_service.JOB_FAILED: "La sauvegarde a échoué. Le monde continue de tourner.",
    backup_service.JOB_UNUSABLE: "La sauvegarde était incomplète et a été supprimée. Le monde continue de tourner.",
    backup_service.PLAYERS_ONLINE_ONE: "1 enfant joue en ce moment dans le monde, il sera brièvement déconnecté.",
    backup_service.JOB_INTERRUPTED: "La sauvegarde a été interrompue par un redémarrage du serveur.",
    backup_service.RESTORE_JOB_INTERRUPTED: "La restauration a été interrompue par un redémarrage du serveur.",
    backup_service.RESTORE_NOT_CONFIRMED: "Confirme la restauration.",
    backup_service.RESTORE_TAMPERED: "La sauvegarde a été modifiée et ne sera pas restaurée.",
    backup_service.RESTORE_FAILED: "La restauration a échoué. Le monde continue de tourner.",
    backup_service.RESTORE_FALLBACK: "La restauration a échoué. L\u2019ancien monde a été rétabli.",
    backup_service.RESTORE_SWAP_FAILED: "La restauration a échoué. Relance la restauration.",
    # nc.py, notify/links.py
    nc.MSG_NO_USER: "Un client Nextcloud agissant pour un compte a besoin d\u2019un identifiant de compte.",
    links.MSG_INVALID_ORIGIN: (
        "L\u2019adresse doit ressembler à https://cloud.example ou https://example.org/nextcloud."
    ),
    # play/ticket_api.py (seen by kids)
    ticket_api.TEXT_NICHT_EINGELADEN: "Tu n\u2019as pas d\u2019invitation pour ce monde.",
    ticket_api.TEXT_WELT_AUS: "Ce monde ne tourne pas en ce moment. Préviens tes parents.",
    ticket_api.TEXT_TICKET: "Le lancement du jeu a expiré. Relance le jeu depuis Gameworld.",
    ticket_api.TEXT_FREMD: "Gameworld ne lance le jeu que depuis sa propre page.",
    ticket_api.TEXT_NAME_NEU: "Ton nom de joueur a changé. Relance le jeu depuis Gameworld.",
    ticket_api.MSG_NOT_LOGGED_IN: "Non connecté.",
    # playtime/pause.py, playtime/service.py
    playtime_pause.MSG_BAD_MINUTES: "Une pause dure 15, 30 ou 60 minutes.",
    playtime_service.MSG_TOO_MANY_HOLIDAYS: (
        f"Au maximum {playtime_service.MAX_HOLIDAYS} périodes de vacances sont possibles."
    ),
    playtime_service.MSG_NO_HOLIDAY: "Cette période de vacances n\u2019existe pas.",
    playtime_service.MSG_ADMIN_NO_RULES: "Les gestionnaires n\u2019ont pas de règles de temps de jeu.",
    playtime_service.MSG_ADULT_IS_VERWALTER: "Ce compte gère Gameworld et joue de toute façon sans règles.",
    playtime_service.MSG_WINDOW_NEEDS_OPEN_DAY: (
        "Un monde avec une plage horaire a besoin d\u2019au moins un jour ouvert."
    ),
    # provisioner/client.py
    client.NOT_FOUND_MESSAGE: _NOT_FOUND,
    client.SNAPSHOT_RUNNING: "Le monde tourne encore\u00a0; une sauvegarde nécessite un monde arrêté.",
    # provisioner/presets.py
    presets.MTG_KREATIV.title: "Construire (créatif)",
    presets.MTG_KREATIV.description: "Minetest Game\u00a0: blocs illimités, pas de dégâts, vol autorisé.",
    presets.VOXELIBRE_SANFT.title: "Aventure (douce)",
    presets.VOXELIBRE_SANFT.description: (
        "VoxeLibre\u00a0: survie avec des animaux pacifiques, l\u2019inventaire est conservé à la mort."
    ),
    # provisioner/setup_check.py
    setup_check.MSG_CONTAINERS_OK: "L\u2019accès aux conteneurs est autorisé.",
    setup_check.MSG_CONTAINERS_DENIED: (
        f"Le proxy Docker n\u2019autorise pas l\u2019accès aux conteneurs. Définis CONTAINERS=1. {_GUIDE}"
    ),
    setup_check.MSG_POST_OK: "Les requêtes d\u2019écriture sont autorisées.",
    setup_check.MSG_POST_DENIED: (
        "Le proxy Docker n\u2019autorise pas les requêtes d\u2019écriture, les mondes ne peuvent donc être "
        f"ni créés ni démarrés. Définis POST=1. {_GUIDE}"
    ),
    setup_check.MSG_IMAGES_OK: "L\u2019accès aux images est autorisé.",
    setup_check.MSG_IMAGES_DENIED: (
        f"Le proxy Docker n\u2019autorise pas l\u2019accès aux images. Définis IMAGES=1. {_GUIDE}"
    ),
    setup_check.MSG_VOLUMES_OK: "L\u2019accès aux volumes est autorisé.",
    setup_check.MSG_VOLUMES_DENIED: (
        "Le proxy Docker n\u2019autorise pas l\u2019accès aux volumes, les mondes ne peuvent donc pas être "
        f"supprimés. Définis VOLUMES=1. {_GUIDE}"
    ),
    setup_check.MSG_EXEC_OK: "Les commandes dans les conteneurs sont bloquées.",
    setup_check.MSG_EXEC_OPEN: (
        "Le proxy Docker est trop ouvert\u00a0: les commandes dans les conteneurs sont autorisées. "
        f"Définis EXEC=0. {_GUIDE}"
    ),
    setup_check.MSG_INFO_OK: "Les informations système sont bloquées.",
    setup_check.MSG_INFO_OPEN: f"Le proxy Docker divulgue des informations système. Définis INFO=0. {_GUIDE}",
    setup_check.MSG_NOT_CHECKED: (
        f"Non vérifié\u00a0: définis d\u2019abord POST=1, puis relance la vérification de l\u2019installation. {_GUIDE}"
    ),
    setup_check.MSG_DOCKER_SOCKET: (
        "Gameworld ne doit jamais parler directement au socket Docker. Indique l\u2019adresse du proxy "
        f"Docker restreint, par défaut tcp://gameworld-docker-proxy:2375. {_GUIDE}"
    ),
    setup_check.MSG_PROXY_EXPOSED: (
        "Le proxy Docker se trouve sur une adresse hors du réseau privé. Il ne doit être joignable "
        f"que dans le réseau Docker de Gameworld. {_GUIDE}"
    ),
    setup_check.MSG_REACHABLE: "Le proxy Docker est joignable.",
    # talk/rooms.py
    rooms.MSG_UNAVAILABLE: "Talk ne répond pas pour le moment. Réessaie plus tard.",
    # worlds/service.py (stored as last_error, translated on delivery)
    world_service.PORTS_EXHAUSTED: "Aucun port UDP libre trouvé. Vérifie la plage de ports GAMEWORLD_PORT_RANGE.",
    world_service.NOT_FOUND: _NOT_FOUND,
    world_service.JOB_RUNNING: "Une sauvegarde ou une restauration est déjà en cours. Patiente un instant.",
    world_service.TEXT_UNKNOWN_PRESET: (
        "Gameworld ne connaît pas le type de jeu de ce monde. Mets Gameworld à jour ou supprime le monde."
    ),
    world_service.PAYLOAD_FAILED: (
        "Les données de monde n\u2019ont pas pu être préparées. Vérifie l\u2019espace libre sur le serveur et réessaie."
    ),
    world_service.CREATE_FAILED: "Le monde n\u2019a pas pu être créé. Réessaie plus tard.",
    world_service.RECONCILE_OOM: _OOM,
    world_service.RECONCILE_DATA_MISSING: (
        "Les données de monde sont manquantes. Le monde peut seulement être supprimé."
    ),
    world_service.RECONCILE_INTERRUPTED: "La création a été interrompue. Supprime le monde et crée-le à nouveau.",
    world_service.RESTORE_INTERRUPTED: (
        "La restauration a été interrompue. Relance la restauration\u00a0; la sauvegarde faite avant "
        "la restauration se trouve dans Fichiers."
    ),
    world_service.WORLD_BUSY: "Le monde est en cours de sauvegarde ou de restauration.",
    world_service.MSG_WORLD_LANGUAGE_UNSUPPORTED: "Cette langue n\u2019est pas disponible pour les textes du jeu.",
    world_service.OFFLINE_RESTART_FAILED: "Le monde n\u2019a pas pu redémarrer ensuite. Démarre le monde.",
    world_service.RECONCILE_FAILED: "Le monde n\u2019a pas pu être rétabli après le redémarrage du serveur.",
    world_service.UNKNOWN_PRESET_TITLE: "Type de jeu inconnu",
    # worlds/status.py
    status.TEXT_UNREACHABLE: "Docker injoignable",
    status.TEXT_CREATING: "Création en cours",
    status.TEXT_BACKING_UP: "Sauvegarde en cours ...",
    status.TEXT_RESTORING: "Restauration en cours ...",
    status.TEXT_UNKNOWN_ERROR: "Erreur inconnue",
    status.TEXT_MISSING: (
        "Le serveur du monde est manquant. Le démarrage le rétablit si les données de monde existent encore."
    ),
    status.TEXT_RESTARTING: "Redémarre sans cesse",
    status.TEXT_RUNNING: "En marche",
    status.TEXT_STARTING: "Démarrage en cours",
    status.TEXT_STOPPED: "Arrêté",
    status.TEXT_OOM: _OOM,
}

TEMPLATES: dict[str, str] = {
    # access/secret.py
    secret.TEXT_UNAVAILABLE_TYPE: _GAMEKEY_DOWN + " ({type_name})",
    # backup/service.py
    backup_service.PLAYERS_ONLINE_MANY: (
        "{count} enfants jouent en ce moment dans le monde, ils seront brièvement déconnectés."
    ),
    # config.py
    config.TEXT_PORT_RANGE_INVALID: (
        "GAMEWORLD_PORT_RANGE est invalide\u00a0: '{raw}'. Attendu\u00a0: '<début>-<fin>' avec "
        "1024 <= début <= fin <= 65535 et au plus {max_width} ports."
    ),
    config.TEXT_STORAGE_UNUSABLE: (
        "APP_PERSISTENT_STORAGE n\u2019est pas utilisable\u00a0: '{storage}' ne peut pas être créé "
        "comme dossier ({error})."
    ),
    # provisioner/client.py
    client.TEXT_DOCKER_NOT_FOUND: "Docker ne connaît pas l\u2019objet\u00a0: {explanation}",
    client.TEXT_DOCKER_REJECTED: "Docker a refusé la requête\u00a0: {explanation}",
    client.TEXT_DOCKER_UNREACHABLE: (
        "Gameworld ne parvient pas à joindre le proxy Docker à l\u2019adresse {docker_url}. "
        "Vérifie que le service gameworld-docker-proxy tourne."
    ),
    client.TEXT_START_REJECTED: "Docker a refusé le démarrage du monde\u00a0: {explanation}",
    client.TEXT_PORT_IN_USE: "Le port UDP {port} est déjà utilisé sur le serveur.",
    # provisioner/presets.py (the exact message with translated titles is in MESSAGES below)
    presets.TEXT_UNKNOWN_PRESET_ID: "Type de jeu inconnu. Types autorisés\u00a0: {titles}.",
    # provisioner/setup_check.py
    setup_check.TEXT_PROXY_DNS: (
        "Gameworld ne trouve pas le service {host}. Il doit tourner dans le même réseau Docker que "
        "Gameworld (le réseau du démon de déploiement, nextcloud-aio pour AIO). Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_PROXY_TIMEOUT: (
        "Le proxy Docker à l\u2019adresse {host}:{port} ne répond pas. Le plus souvent, il se trouve dans un "
        "autre réseau Docker, ou un pare-feu bloque le port {port}. Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_PROXY_REFUSED: (
        "Le proxy Docker à l\u2019adresse {host}:{port} n\u2019accepte pas de connexion. Le conteneur "
        "gameworld-docker-proxy tourne-t-il\u00a0? Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_PROXY_UNREACHABLE: (
        "Gameworld ne parvient pas à joindre le proxy Docker à l\u2019adresse {docker_url}. Démarre le service "
        "gameworld-docker-proxy et vérifie GAMEWORLD_DOCKER_URL. Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_ENGINE_TOO_OLD: (
        "Docker Engine trop ancien, API 1.44 ou plus récente requise (signalée\u00a0: {shown}). "
        "Mets Docker à jour. Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_API_SUPPORTED: "L\u2019API Docker {version} est prise en charge.",
    setup_check.TEXT_UNEXPECTED_ANSWER: (
        "Réponse inattendue du proxy Docker à {method} {path}\u00a0: HTTP {code}. Guide\u00a0: {docs_url}"
    ),
    setup_check.TEXT_REQUEST_FAILED: (
        "La requête au proxy Docker ({path}) a échoué\u00a0: {error_type}. Guide\u00a0: {docs_url}"
    ),
    # worlds/ports.py
    ports.TEXT_PORTS_TAKEN: "Tous les ports UDP de la plage {low}-{high} sont occupés.",
    # worlds/status.py
    status.TEXT_CRASHED: "Le monde s\u2019est arrêté de façon inattendue (code {code}).",
    status.TEXT_ODD_STATE: "État inattendu du serveur ({state}).",
}

# Task 3: raise texts of validators, rules, Docker refusals and the bundled game file.
MESSAGES.update(
    {
        # api/playtime.py (validators, 422)
        playtime_api.MSG_PLAYTIME_LABEL_CONTROL: (
            "Le libellé ne doit contenir ni caractères de contrôle ni sauts de ligne."
        ),
        playtime_api.MSG_PLAYTIME_UNKNOWN_ZONE: "Fuseau horaire inconnu.",
        playtime_api.MSG_WINDOW_SEVEN_DAYS: "Une plage horaire a besoin exactement des sept jours de la semaine 1 à 7.",
        playtime_api.MSG_WEEKDAY_TWICE: "Chaque jour de la semaine ne peut apparaître qu\u2019une fois.",
        playtime_api.MSG_CLOSED_DAY_WINDOW: "Un jour fermé n\u2019a pas de plage horaire.",
        playtime_api.MSG_OPEN_DAY_NEEDS_TIMES: "Un jour ouvert a besoin du début et de la fin de sa plage horaire.",
        # playtime/plan.py (rules, 422 via str(exc))
        plan.MSG_LIMIT_RANGE: "La limite quotidienne est comprise entre 1 et 1440 minutes ou vaut None.",
        plan.MSG_WINDOW_BOTH_OR_NONE: (
            "Une plage horaire a besoin d\u2019un début et d\u2019une fin, ou d\u2019aucun des deux."
        ),
        plan.MSG_WINDOW_START_RANGE: "Le début de la plage est compris entre 0 et 1439 minutes.",
        plan.MSG_WINDOW_END_RANGE: "La fin de la plage est comprise entre 1 et 1440 minutes.",
        plan.MSG_WINDOW_START_BEFORE_END: "Le début de la plage doit précéder sa fin.",
        plan.MSG_WEEK_SEVEN_DAYS: "Un planning hebdomadaire a besoin exactement des sept jours de la semaine 1 à 7.",
        plan.MSG_HOLIDAY_ENDS_BEFORE_START: "Une période de vacances ne peut pas se terminer avant de commencer.",
        # provisioner/client.py
        client.MSG_PAYLOAD_REJECTED: "Docker n\u2019a pas accepté les données de monde.",
        client.MSG_ACCESS_LIST_REJECTED: "Docker n\u2019a pas accepté la liste d\u2019accès du monde.",
        client.MSG_BACKUP_REJECTED: "Docker n\u2019a pas accepté la sauvegarde.",
        client.MSG_ORPHAN_BAD_ID: "Identifiant de conteneur invalide.",
        client.MSG_ORPHAN_CONTAINER_REFUSED: (
            "Le conteneur appartient à cette installation ou n\u2019appartient pas à Gameworld."
        ),
        client.MSG_ORPHAN_VOLUME_REFUSED: (
            "Le volume appartient à cette installation ou n\u2019appartient pas à Gameworld."
        ),
        client.MSG_VOLUME_IN_USE: "Le volume est encore utilisé.",
        client.MSG_STATUS_FILE_UNREADABLE: "Le fichier d\u2019état du monde est illisible.",
        client.MSG_ACCESS_STATE_UNREADABLE: "L\u2019état d\u2019accès du monde est illisible.",
        client.MSG_LEDGER_UNREADABLE: "Le registre du temps de jeu du monde est illisible.",
        client.MSG_EVENTS_UNREADABLE: "Le fichier d\u2019événements du monde est illisible.",
        # provisioner/archive.py
        game_archive.MSG_NO_GAME_CONF: "Le fichier de jeu fourni ne contient pas de game.conf.",
    }
)
TEMPLATES.update(
    {
        playtime_api.TEXT_HOLIDAY_MAX_DAYS: "Une période de vacances dure au maximum {days} jours.",
        game_archive.TEXT_GAME_ZIP_MISSING: (
            "Le fichier de jeu fourni est manquant\u00a0: {game_zip}. Exécute sh scripts/fetch-games.sh."
        ),
        game_archive.TEXT_GAME_ZIP_TAMPERED: (
            "Le fichier de jeu fourni est endommagé ou modifié ({game_zip}). Réinstalle Gameworld."
        ),
    }
)

# Messages whose inserted value is itself a German text: complete messages instead of templates.
MESSAGES[presets.unknown_preset_message([preset.title for preset in presets.PRESETS.values()])] = TEMPLATES[
    presets.TEXT_UNKNOWN_PRESET_ID
].format(titles=", ".join(MESSAGES[preset.title] for preset in presets.PRESETS.values()))
MESSAGES[setup_check.MSG_ENGINE_VERSION_UNKNOWN] = TEMPLATES[setup_check.TEXT_ENGINE_TOO_OLD].format(
    shown="inconnue", docs_url=setup_check.DOCS_URL
)

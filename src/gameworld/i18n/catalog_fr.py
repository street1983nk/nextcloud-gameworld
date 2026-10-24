"""French server texts (D-25). Keys are the imported German constants, never copied literals.

Typography: non-breaking space before ? ! ; : written as an escape (RUF001).
"""

from __future__ import annotations

from gameworld.access import roles
from gameworld.worlds import status

MESSAGES: dict[str, str] = {
    # access/roles.py
    roles.MSG_NOT_LOGGED_IN: "Non connecté.",
    roles.MSG_UNAVAILABLE: "Nextcloud ne répond pas pour le moment. Réessaie dans un instant.",
    roles.MSG_FORBIDDEN: "Seuls les parents peuvent gérer les mondes.",
    roles.MSG_NC_ADMIN_ONLY: "Seuls les administrateurs Nextcloud peuvent modifier ceci.",
}

TEMPLATES: dict[str, str] = {
    # worlds/status.py
    status.TEXT_CRASHED: "Le monde s\u2019est arrêté de façon inattendue (code {code}).",
}

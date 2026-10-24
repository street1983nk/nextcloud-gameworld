"""English server texts (D-25). Keys are the imported German constants, never copied literals."""

from __future__ import annotations

from gameworld.access import roles
from gameworld.worlds import status

MESSAGES: dict[str, str] = {
    # access/roles.py
    roles.MSG_NOT_LOGGED_IN: "Not logged in.",
    roles.MSG_UNAVAILABLE: "Nextcloud is not responding right now. Please try again in a moment.",
    roles.MSG_FORBIDDEN: "Only parents can manage worlds.",
    roles.MSG_NC_ADMIN_ONLY: "Only Nextcloud admins can change this.",
}

TEMPLATES: dict[str, str] = {
    # worlds/status.py
    status.TEXT_CRASHED: "The world stopped unexpectedly (code {code}).",
}

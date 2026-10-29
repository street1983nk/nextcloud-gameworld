"""Nextcloud as the directory of accounts (ROLLE-02: no user management of its own).

Every check runs on behalf of the inviting manager: Gameworld only invites
accounts that Nextcloud confirms as existing to this manager (T-03-17).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from nc_py_api import NextcloudException

from gameworld.nc import nc_app, nc_as

LOG = logging.getLogger(__name__)

# Key of the cross-check; only whether it exists is read, its value does not matter.
PROBE_KEY = "gameworld_probe"

# 998 is the OCS code "not found" of the provisioning API.
_NOT_FOUND_CODES = frozenset({404, 998})
# Explicit refusal of the acting account: 401 (AppAPI does not know the account,
# OCS 997) and 403 (not an admin, "must be at least a sub admin"), proven on the dev stack.
_REJECTED_CODES = frozenset({401, 403, 997})

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
_GROUPS_EP = "/ocs/v1.php/cloud/groups"


@dataclass(frozen=True)
class DirectoryUser:
    uid: str
    display_name: str
    enabled: bool


class DirectoryUnavailableError(Exception):
    """Nextcloud did not answer the account check."""


class DirectoryRejectedError(DirectoryUnavailableError):
    """Nextcloud refuses the acting account (401/403): it is no longer an admin or does not exist.

    Subclass of DirectoryUnavailableError: whoever only handles outages keeps
    the previous behavior (never an empty group, never permissions). Only the
    background check of the manager snapshot distinguishes both cases.
    """


class Directory(Protocol):
    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        """Account as Nextcloud shows it to the manager; None if it does not exist."""
        ...

    async def group_members(self, acting_uid: str, gid: str) -> list[str] | None:
        """Account IDs of the group, read as manager; None if the group does not exist."""
        ...

    async def group_exists(self, acting_uid: str, gid: str) -> bool:
        """Does the group exist? Same check as group_members."""
        ...

    async def search_groups(self, acting_uid: str, query: str, limit: int = 20) -> list[tuple[str, str]]:
        """Groups (ID, display name) whose ID or name contains ``query``, read as admin; at most limit."""
        ...

    async def app_accepted(self) -> bool:
        """Does Nextcloud currently accept the ExApp itself (request without account)? False on any error."""
        ...


class NcDirectory:
    """Account check via OCS as the acting manager (``users.get_user(uid)``).

    Nextcloud only resolves groups for admins, subadmins and members of the group
    (``/cloud/groups/{gid}/users``); to everyone else it answers 403 (pitfall 6).
    Therefore group queries only run in the manager context; a 403 counts as
    refusal or outage (503), never as an empty group, so that no reconciliation removes access
    because of missing permissions.
    """

    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        try:
            async with nc_as(acting_uid) as nc:
                # nc_py_api puts the ID into the path unchecked: encode it so that "/" or ".." redirect nothing.
                info = await nc.users.get_user(quote(uid, safe=""))
        except NextcloudException as exc:
            if exc.status_code in _NOT_FOUND_CODES:
                return None
            LOG.warning("Account check at Nextcloud failed: status %s", exc.status_code)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        except Exception as exc:
            LOG.warning("Account check at Nextcloud failed: %s", type(exc).__name__)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        canonical = info.user_id or uid
        return DirectoryUser(uid=canonical, display_name=info.display_name or canonical, enabled=bool(info.enabled))

    async def group_members(self, acting_uid: str, gid: str) -> list[str] | None:
        try:
            async with nc_as(acting_uid) as nc:
                # /users instead of /cloud/groups/{gid} (nc_py_api get_members): the old
                # endpoint demands subadmin rights, /users also lets members of the
                # group read (D-01), non-members still get 403 (06-12).
                # The group ID is encoded so that "/" or ".." redirect nothing.
                data = await nc.ocs("GET", f"{_GROUPS_EP}/{quote(gid, safe='')}/users")
                members = data.get("users") if isinstance(data, dict) else None
        except NextcloudException as exc:
            if exc.status_code in _NOT_FOUND_CODES:
                return None
            LOG.warning("Group query at Nextcloud failed: status %s", exc.status_code)
            if exc.status_code in _REJECTED_CODES:
                raise DirectoryRejectedError(MSG_UNAVAILABLE) from None
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        except Exception as exc:
            LOG.warning("Group query at Nextcloud failed: %s", type(exc).__name__)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        # Empty group: nc_py_api then returns {} instead of [].
        return [str(member) for member in members or []]

    async def group_exists(self, acting_uid: str, gid: str) -> bool:
        return await self.group_members(acting_uid, gid) is not None

    async def search_groups(self, acting_uid: str, query: str, limit: int = 20) -> list[tuple[str, str]]:
        """Group search for the admin section (D-02) via ``users_groups.get_details`` (with display names).

        nc_py_api passes ``query`` through as the parameter ``search`` (no path). Any
        outage or refusal means DirectoryUnavailableError (503 at the caller).
        """
        try:
            async with nc_as(acting_uid) as nc:
                details = await nc.users_groups.get_details(mask=query or None, limit=limit)
        except NextcloudException as exc:
            LOG.warning("Group search at Nextcloud failed: status %s", exc.status_code)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        except Exception as exc:
            LOG.warning("Group search at Nextcloud failed: %s", type(exc).__name__)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        return [(str(item.group_id), str(item.display_name or item.group_id)) for item in details[:limit]]

    async def app_accepted(self) -> bool:
        """Cross-check for a refusal: an app request without account (appconfig_ex).

        Proven on the dev stack: as long as Nextcloud does not accept the ExApp (start,
        re-registration), it answers every request with 401, including this one.
        If it succeeds, a 401/403 of the group query was a refusal of the account.
        """
        try:
            async with nc_app() as nc:
                await nc.appconfig_ex.get_value(PROBE_KEY)
        except Exception as exc:
            LOG.warning("Nextcloud currently does not accept Gameworld: %s", type(exc).__name__)
            return False
        return True


_directory: Directory | None = None


def get_directory() -> Directory:
    """Module-wide singleton; tests inject a fake."""
    global _directory
    if _directory is None:
        _directory = NcDirectory()
    return _directory

"""Spielzeit-Regeln je Kind setzen, entfernen und auflisten (ZEIT-01, Verwalter).

Nur die ExApp kann ein Kontingent über alle Welten rechnen (O-03): Dieser Dienst
schreibt den Wochenplan eines Kindes in die Datenbank und schiebt die Regeldatei
sofort in jede Welt des Kindes (``WorldService.push_time``), ohne Welt-Neustart.

Sperr-Regel (wie access/service.py): Nextcloud-Aufrufe (Anzeigename) laufen immer
außerhalb von ``worlds.mutation()``; unter der Sperre nur Store und das Schreiben
der Regeldatei. Der Anzeigename ist Beiwerk: Fällt Nextcloud aus, steht der
Konto-Name statt des Anzeigenamens, die Regel selbst hängt nicht daran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError
from gameworld.access.service import MSG_NO_PLAYER, PlayerNotFoundError
from gameworld.playtime.plan import DEFAULT_TIME_ZONE, ChildState, WeekPlan, load_zone, local_day
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore


@dataclass(frozen=True)
class ChildView:
    """Spielzeit-Sicht auf ein Kind: Regeln, heutiger Verbrauch und aktuelle Auswertung."""

    nc_user: str
    display_name: str
    player_name: str
    has_rules: bool
    normal: WeekPlan | None
    used_today_s: int
    state: ChildState | None


@dataclass(frozen=True)
class PlaytimeView:
    """Alle Kinder (Konten mit Spielerzeile) samt Zeitzone des Haushalts."""

    time_zone: str
    children: list[ChildView]


@dataclass(frozen=True)
class ChildResult:
    """Ergebnis von set_child/clear_child: die neue Sicht und ob die Welten sie schon tragen."""

    child: ChildView
    applied: bool


@dataclass(frozen=True)
class _Snapshot:
    time_zone: str
    rows: list[ChildView]


class TimeService:
    def __init__(self, worlds: WorldService, directory: Directory) -> None:
        self._worlds = worlds
        self._store: WorldStore = worlds.store
        self._directory = directory

    async def list_children(self, acting_uid: str) -> PlaytimeView:
        """Alle Konten mit Spielerzeile, je mit Regeln, heutigem Verbrauch und Auswertung."""
        snapshot = await anyio.to_thread.run_sync(self._snapshot)
        children: list[ChildView] = []
        for row in snapshot.rows:
            display = await self._display_name(acting_uid, row.nc_user)
            children.append(_with_display(row, display))
        return PlaytimeView(time_zone=snapshot.time_zone, children=children)

    async def set_child(self, acting_uid: str, nc_user: str, normal: WeekPlan) -> ChildResult:
        """Setzt den Wochenplan eines Kindes und schreibt die Regeldatei in alle seine Welten."""
        await self._require_player(nc_user)
        applied = await anyio.to_thread.run_sync(self._set_sync, nc_user, normal, acting_uid)
        return await self._result(acting_uid, nc_user, applied)

    async def clear_child(self, acting_uid: str, nc_user: str) -> ChildResult:
        """Entfernt Regeln und Verbrauch eines Kindes (zurück auf keine Begrenzung, O-10)."""
        await self._require_player(nc_user)
        applied = await anyio.to_thread.run_sync(self._clear_sync, nc_user)
        return await self._result(acting_uid, nc_user, applied)

    # Unter der Sperre (Worker-Thread)

    def _set_sync(self, nc_user: str, normal: WeekPlan, acting_uid: str) -> bool:
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._worlds.mutation():
            self._store.set_child_plan(nc_user, normal, None, acting_uid, updated_at)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _clear_sync(self, nc_user: str) -> bool:
        with self._worlds.mutation():
            self._store.clear_child(nc_user)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _snapshot(self) -> _Snapshot:
        tz_name = self._store.get_meta("time_zone") or DEFAULT_TIME_ZONE
        tz = load_zone(tz_name)
        today = local_day(int(time.time()), tz)
        plans = self._store.child_plans()
        rows: list[ChildView] = []
        for player in self._store.list_players():
            has_rules = player.nc_user in plans
            normal = plans[player.nc_user][0] if has_rules else None
            rows.append(
                ChildView(
                    nc_user=player.nc_user,
                    display_name=player.nc_user,
                    player_name=player.player_name,
                    has_rules=has_rules,
                    normal=normal,
                    used_today_s=self._store.usage(player.nc_user, today),
                    state=self._worlds.time.child_state(player.nc_user),
                )
            )
        return _Snapshot(time_zone=tz_name, rows=rows)

    def _child_snapshot(self, nc_user: str) -> ChildView:
        for row in self._snapshot().rows:
            if row.nc_user == nc_user:
                return row
        raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _result(self, acting_uid: str, nc_user: str, applied: bool) -> ChildResult:
        row = await anyio.to_thread.run_sync(self._child_snapshot, nc_user)
        display = await self._display_name(acting_uid, nc_user)
        return ChildResult(child=_with_display(row, display), applied=applied)

    async def _require_player(self, nc_user: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_player, nc_user) is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name


def _with_display(row: ChildView, display_name: str) -> ChildView:
    return ChildView(
        nc_user=row.nc_user,
        display_name=display_name,
        player_name=row.player_name,
        has_rules=row.has_rules,
        normal=row.normal,
        used_today_s=row.used_today_s,
        state=row.state,
    )

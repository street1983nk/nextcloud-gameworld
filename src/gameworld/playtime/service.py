"""Spielzeit-Regeln je Kind, Ferien und Zeitzone pflegen (ZEIT-01, ZEIT-03, ZEIT-04, Verwalter).

Nur die ExApp kann ein Kontingent über alle Welten rechnen (O-03): Dieser Dienst
schreibt den Wochenplan (und den Ferienplan) eines Kindes in die Datenbank und
schiebt die Regeldatei sofort in jede Welt des Kindes (``WorldService.push_time``),
ohne Welt-Neustart. Ferienzeiträume und Zeitzone gelten für den ganzen Haushalt
(O-08, O-02): Jede Änderung schreibt die Regeldatei aller Welten, damit keine
Welt mit dem alten Plan oder alten Tagesgrenzen weiterläuft.

Sperr-Regel (wie access/service.py): Nextcloud-Aufrufe (Anzeigename) laufen immer
außerhalb von ``worlds.mutation()``; unter der Sperre nur Store und das Schreiben
der Regeldatei. Der Anzeigename ist Beiwerk: Fällt Nextcloud aus, steht der
Konto-Name statt des Anzeigenamens, die Regel selbst hängt nicht daran.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError
from gameworld.access.service import MSG_NO_PLAYER, PlayerNotFoundError
from gameworld.playtime.plan import DEFAULT_TIME_ZONE, ChildState, Holiday, WeekPlan, load_zone, local_day
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore

# Datensparsamkeit: höchstens so viele Ferienzeiträume (T-04-23).
MAX_HOLIDAYS = 50
MSG_TOO_MANY_HOLIDAYS = f"Es sind höchstens {MAX_HOLIDAYS} Ferienzeiträume möglich."
MSG_NO_HOLIDAY = "Diesen Ferienzeitraum gibt es nicht."


class HolidayNotFoundError(LookupError):
    """Unbekannte Ferien-id (404)."""


@dataclass(frozen=True)
class ChildView:
    """Spielzeit-Sicht auf ein Kind: Regeln, heutiger Verbrauch und aktuelle Auswertung."""

    nc_user: str
    display_name: str
    player_name: str
    has_rules: bool
    normal: WeekPlan | None
    holiday: WeekPlan | None
    used_today_s: int
    state: ChildState | None


@dataclass(frozen=True)
class HolidayView:
    """Ferienzeitraum mit id; active heißt: das heutige lokale Datum liegt darin."""

    id: int
    label: str
    start_date: date
    end_date: date
    active: bool


@dataclass(frozen=True)
class PlaytimeView:
    """Alle Kinder (Konten mit Spielerzeile), Ferienzeiträume und Zeitzone des Haushalts."""

    time_zone: str
    holidays: list[HolidayView]
    children: list[ChildView]


@dataclass(frozen=True)
class ChildResult:
    """Ergebnis von set_child/clear_child: die neue Sicht und ob die Welten sie schon tragen."""

    child: ChildView
    applied: bool


@dataclass(frozen=True)
class HolidayResult:
    """Ergebnis von add_holiday/remove_holiday: der Zeitraum und ob alle Welten ihn tragen."""

    holiday: HolidayView
    applied: bool


@dataclass(frozen=True)
class _Snapshot:
    time_zone: str
    holidays: list[HolidayView]
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
            children.append(replace(row, display_name=display))
        return PlaytimeView(time_zone=snapshot.time_zone, holidays=snapshot.holidays, children=children)

    async def set_child(
        self, acting_uid: str, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None = None
    ) -> ChildResult:
        """Setzt Wochen- und Ferienplan eines Kindes und schreibt die Regeldatei in alle seine Welten.

        ``holiday`` None heißt: In den Ferien gilt der Normalplan.
        """
        await self._require_player(nc_user)
        applied = await anyio.to_thread.run_sync(self._set_sync, nc_user, normal, holiday, acting_uid)
        return await self._result(acting_uid, nc_user, applied)

    async def clear_child(self, acting_uid: str, nc_user: str) -> ChildResult:
        """Entfernt Regeln und Verbrauch eines Kindes (zurück auf keine Begrenzung, O-10)."""
        await self._require_player(nc_user)
        applied = await anyio.to_thread.run_sync(self._clear_sync, nc_user)
        return await self._result(acting_uid, nc_user, applied)

    async def add_holiday(self, holiday: Holiday) -> HolidayResult:
        """Legt einen Ferienzeitraum für den Haushalt an und schreibt alle Welten neu (O-08)."""
        return await anyio.to_thread.run_sync(self._add_holiday_sync, holiday)

    async def remove_holiday(self, holiday_id: int) -> HolidayResult:
        """Entfernt einen Ferienzeitraum; ab sofort gilt wieder der Normalplan, wo er griff."""
        return await anyio.to_thread.run_sync(self._remove_holiday_sync, holiday_id)

    async def set_time_zone(self, time_zone: str) -> bool:
        """Setzt die Zeitzone (der Aufrufer prüft gegen ``available_timezones``) und schreibt alle Welten neu."""
        return await anyio.to_thread.run_sync(self._set_time_zone_sync, time_zone)

    # Unter der Sperre (Worker-Thread)

    def _set_sync(self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, acting_uid: str) -> bool:
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._worlds.mutation():
            self._store.set_child_plan(nc_user, normal, holiday, acting_uid, updated_at)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _clear_sync(self, nc_user: str) -> bool:
        with self._worlds.mutation():
            self._store.clear_child(nc_user)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _add_holiday_sync(self, holiday: Holiday) -> HolidayResult:
        with self._worlds.mutation():
            # Zählen und Anlegen unter derselben Sperre: zwei parallele Anfragen
            # können die Obergrenze nicht gemeinsam überschreiten.
            if len(self._store.holiday_rows()) >= MAX_HOLIDAYS:
                raise ValueError(MSG_TOO_MANY_HOLIDAYS)
            holiday_id = self._store.add_holiday(holiday.start, holiday.end, holiday.label)
            applied = self._refresh_all_worlds()
            view = self._holiday_view(holiday_id, holiday)
        return HolidayResult(holiday=view, applied=applied)

    def _remove_holiday_sync(self, holiday_id: int) -> HolidayResult:
        with self._worlds.mutation():
            found = next((item for hid, item in self._store.holiday_rows() if hid == holiday_id), None)
            if found is None or not self._store.remove_holiday(holiday_id):
                raise HolidayNotFoundError(MSG_NO_HOLIDAY)
            applied = self._refresh_all_worlds()
            view = self._holiday_view(holiday_id, found)
        return HolidayResult(holiday=view, applied=applied)

    def _set_time_zone_sync(self, time_zone: str) -> bool:
        with self._worlds.mutation():
            self._store.set_meta("time_zone", time_zone)
            return self._refresh_all_worlds()

    def _refresh_all_worlds(self) -> bool:
        """Regeldatei aller Welten der Datenbank neu schreiben; nur unter mutation().

        Ohne Container schreibt der nächste Start (push_time liefert dann False).
        Ergebnis: Tragen alle Welten den neuen Stand schon?
        """
        results = [self._worlds.push_time(row.id) for row in self._store.list_worlds()]
        return all(results)

    def _today(self) -> date:
        return local_day(int(time.time()), load_zone(self._store.get_meta("time_zone") or ""))

    def _holiday_view(self, holiday_id: int, holiday: Holiday, today: date | None = None) -> HolidayView:
        day = self._today() if today is None else today
        return HolidayView(
            id=holiday_id,
            label=holiday.label,
            start_date=holiday.start,
            end_date=holiday.end,
            active=holiday.start <= day <= holiday.end,
        )

    def _snapshot(self) -> _Snapshot:
        tz_name = self._store.get_meta("time_zone") or DEFAULT_TIME_ZONE
        today = local_day(int(time.time()), load_zone(tz_name))
        plans = self._store.child_plans()
        holidays = [self._holiday_view(hid, item, today) for hid, item in self._store.holiday_rows()]
        rows: list[ChildView] = []
        for player in self._store.list_players():
            has_rules = player.nc_user in plans
            normal, holiday = plans[player.nc_user] if has_rules else (None, None)
            rows.append(
                ChildView(
                    nc_user=player.nc_user,
                    display_name=player.nc_user,
                    player_name=player.player_name,
                    has_rules=has_rules,
                    normal=normal,
                    holiday=holiday,
                    used_today_s=self._store.usage(player.nc_user, today),
                    state=self._worlds.time.child_state(player.nc_user),
                )
            )
        return _Snapshot(time_zone=tz_name, holidays=holidays, rows=rows)

    def _child_snapshot(self, nc_user: str) -> ChildView:
        for row in self._snapshot().rows:
            if row.nc_user == nc_user:
                return row
        raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _result(self, acting_uid: str, nc_user: str, applied: bool) -> ChildResult:
        row = await anyio.to_thread.run_sync(self._child_snapshot, nc_user)
        display = await self._display_name(acting_uid, nc_user)
        return ChildResult(child=replace(row, display_name=display), applied=applied)

    async def _require_player(self, nc_user: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_player, nc_user) is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name

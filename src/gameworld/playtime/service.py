"""Spielzeit-Regeln je Kind, Ferien und Zeitzone pflegen (ZEIT-01, ZEIT-03, ZEIT-04, Verwalter).

Nur die ExApp kann ein Kontingent über alle Welten rechnen (O-03): Dieser Dienst
schreibt den Wochenplan (und den Ferienplan) eines Kindes in die Datenbank und
schiebt die Regeldatei sofort in jede Welt des Kindes (``WorldService.push_time``),
ohne Welt-Neustart. Ferienzeiträume und Zeitzone gelten für den ganzen Haushalt
(O-08, O-02): Jede Änderung schreibt die Regeldatei aller Welten, damit keine
Welt mit dem alten Plan oder alten Tagesgrenzen weiterläuft.

Welt-Zeitfenster (ZEIT-05) setzt nur die Welt-Zeile der Regeldatei: Kinder kommen
außerhalb nicht hinein und werden am Fensterende getrennt, die Welt selbst läuft
weiter (O-05, kein Stopp, kein Eingriff ins Eltern-Soll).

Verwalter-Schnappschuss (O-11/A4): Der Zeittakt hat keinen handelnden Nutzer,
Gruppen löst aber nur ein Verwalter auf. Darum holt ``refresh_admins`` im Kontext
eines geprüften Verwalters die Mitglieder der Gruppe admin (gedrosselt) und legt
sie als meta ``time_admins`` ab (JSON, sortiert, der handelnde Verwalter immer
darin). Bei einer Nextcloud-Störung bleibt der letzte Stand; ohne jeden Stand gibt
es keine Freistellung (fail closed).

Sperr-Regel (wie access/service.py, _LOCK ist nicht reentrant): Nextcloud-Aufrufe
(Anzeigename, Gruppe admin) laufen immer außerhalb von ``worlds.mutation()`` und
immer VOR dem Betreten; unter der Sperre nur Store und das Schreiben der
Regeldatei. Dashboard-Pfade nehmen die Sperre nur per ``try_mutation()``. Der
Anzeigename ist Beiwerk: Fällt Nextcloud aus, steht der Konto-Name statt des
Anzeigenamens, die Regel selbst hängt nicht daran.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError
from gameworld.access.roles import ADMIN_GROUP
from gameworld.access.service import MSG_NO_PLAYER, PlayerNotFoundError
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.plan import (
    DEFAULT_TIME_ZONE,
    WEEKDAY_TOKENS,
    ChildState,
    Holiday,
    WeekPlan,
    WindowDay,
    evaluate_world,
    load_zone,
    local_day,
    window_days,
)
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND, WorldService
from gameworld.worlds.store import WorldStore

LOG = logging.getLogger(__name__)

# Datensparsamkeit: höchstens so viele Ferienzeiträume (T-04-23).
MAX_HOLIDAYS = 50
MSG_TOO_MANY_HOLIDAYS = f"Es sind höchstens {MAX_HOLIDAYS} Ferienzeiträume möglich."
MSG_NO_HOLIDAY = "Diesen Ferienzeitraum gibt es nicht."
MSG_ADMIN_NO_RULES = "Verwalter haben keine Spielzeitregeln."
MSG_WINDOW_NEEDS_OPEN_DAY = "Eine Welt mit Zeitfenster braucht mindestens einen offenen Tag."
# Verwalter-Schnappschuss höchstens so oft aus Nextcloud holen (wie SYNC_INTERVAL_SECONDS).
ADMINS_INTERVAL_SECONDS = 60
# Kind-Ansicht: weniger Rest gilt als aufgebraucht, gleiche Schwelle wie MIN_LEFT im Welt-Mod (Pitfall 8).
MIN_LEFT_SECONDS = 60
# Lesefehler der Zeitregeln (Datenbank, Zeitzone, kaputte Zeilen) werden 503.
_READ_ERRORS = (sqlite3.Error, ValueError, KeyError)


@dataclass
class AdminsState:
    """Zeitpunkt (monotonic) der letzten Abfrage der Gruppe admin."""

    last: float | None = None


ADMINS_STATE = AdminsState()


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
class WorldWindowResult:
    """Ergebnis von set_world_window/clear_world_window: Fenster (None = immer offen) und applied."""

    world_id: str
    time_window: list[WindowDay] | None
    applied: bool


@dataclass(frozen=True)
class NextTime:
    """Nächste Spielzeit für die Kind-Ansicht: ISO-Wochentag 1..7 und lokale Minute 0..1439."""

    weekday: int
    minute: int


@dataclass(frozen=True)
class MyPlaytime:
    """Eigene Restzeit eines Kindes (Kind-Ansicht, 04-07); bewusst ohne Pläne und Verbrauch.

    ``state``: ok | aufgebraucht | fenster | tag (None ohne Regeln). ``remaining_minutes``
    abgerundet und nie über das Fensterende hinaus, None ohne Limit. ``until_minute``
    lokal ab 00:00, None heißt Tagesende. ``next`` nur, wenn gerade nicht gespielt werden darf.
    """

    limited: bool
    state: str | None
    remaining_minutes: int | None
    until_minute: int | None
    next: NextTime | None


UNLIMITED = MyPlaytime(limited=False, state=None, remaining_minutes=None, until_minute=None, next=None)


@dataclass(frozen=True)
class WindowSlot:
    """Ein Öffnungsfenster einer Welt: Wochentag und Minuten (Ende 1440 = Mitternacht)."""

    weekday: int
    start: int
    end: int


@dataclass(frozen=True)
class MyWorldWindow:
    """Fensterstatus einer Welt für die Kind-Ansicht: offen (None = kein Fenster) und das aktuelle oder nächste."""

    open: bool | None
    next: WindowSlot | None


NO_WINDOW = MyWorldWindow(open=None, next=None)


class PlaytimeUnavailableError(RuntimeError):
    """Die Zeitregeln ließen sich nicht lesen (503, nie Daten anderer)."""


def parse_hint(token: str) -> NextTime | None:
    """Token wie ``Sa-10:00`` (plan.next_hint) in Wochentag und Minute; ``-`` oder Unsinn ergibt None."""
    day, _, clock = token.partition("-")
    hours, _, minutes = clock.partition(":")
    if day not in WEEKDAY_TOKENS or not hours.isdigit() or not minutes.isdigit():
        return None
    return NextTime(weekday=WEEKDAY_TOKENS.index(day) + 1, minute=int(hours) * 60 + int(minutes))


def _until_minute(until: int, day: date, tz: ZoneInfo) -> int | None:
    """Lokale Minute des Fensterendes; None, wenn es das Tagesende (Folgetag 00:00) ist."""
    local = datetime.fromtimestamp(until, tz)
    if local.date() != day:
        return None
    return local.hour * 60 + local.minute


def kid_playtime(state: ChildState, now: int, tz: ZoneInfo) -> MyPlaytime:
    """Auswertung eines Kindes in die Struktur der Kind-Ansicht (rein).

    Unter MIN_LEFT_SECONDS Rest gilt die Zeit als aufgebraucht bzw. das Fenster
    als zu (Pitfall 8, dieselbe Schwelle wie MIN_LEFT im Welt-Mod). Die Minuten
    reichen nie über das Fensterende hinaus.
    """
    next_time = parse_hint(state.next_hint)
    if state.reason == "tag":
        return MyPlaytime(limited=True, state="tag", remaining_minutes=0, until_minute=None, next=next_time)
    blocked = "aufgebraucht" if state.reason == "limit" else None
    if state.reason == "fenster" or (blocked is None and state.until - now < MIN_LEFT_SECONDS):
        blocked = "fenster"
    elif blocked is None and state.rest_s is not None and state.rest_s < MIN_LEFT_SECONDS:
        blocked = "aufgebraucht"
    if blocked is not None:
        return MyPlaytime(limited=True, state=blocked, remaining_minutes=0, until_minute=None, next=next_time)
    remaining = None if state.rest_s is None else min(state.rest_s, state.until - now) // 60
    return MyPlaytime(
        limited=True,
        state="ok",
        remaining_minutes=remaining,
        until_minute=_until_minute(state.until, state.day, tz),
        next=None,
    )


def world_window_status(now: int, tz: ZoneInfo, windows: dict[int, tuple[int, int]] | None) -> MyWorldWindow:
    """Welt-Fenster für die Kind-Ansicht: offen jetzt plus heutiges, sonst nächstes Fenster (kein Wochenplan)."""
    state = evaluate_world(now, tz, windows)
    if state is None or windows is None:
        return NO_WINDOW
    if state.reason == "ok":
        today = local_day(now, tz).isoweekday()
        start, end = windows[today]
        return MyWorldWindow(open=True, next=WindowSlot(weekday=today, start=start, end=end))
    upcoming = parse_hint(state.next_hint)
    slot = None if upcoming is None else windows.get(upcoming.weekday)
    if upcoming is None or slot is None:
        return MyWorldWindow(open=False, next=None)
    return MyWorldWindow(open=False, next=WindowSlot(weekday=upcoming.weekday, start=slot[0], end=slot[1]))


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

    async def refresh_admins(self, acting_uid: str, *, force: bool = False, blocking: bool = True) -> bool:
        """Verwalter-Schnappschuss (meta time_admins) aus der Gruppe admin; True, wenn er sich änderte.

        Nur im Kontext eines geprüften Verwalters aufrufen und nie unter
        ``mutation()`` (die Gruppenabfrage läuft vorher, außerhalb der Sperre).
        Gedrosselt auf ADMINS_INTERVAL_SECONDS, außer mit ``force``. Bei einer
        Nextcloud-Störung bleibt der letzte Stand. Ändert sich die Liste, bekommen
        alle Welten die neue Regeldatei: ``blocking`` unter ``mutation()``, sonst
        (Dashboard) per ``try_mutation()``; bei belegter Sperre holt der nächste
        Aufruf nach.
        """
        now = monotonic()
        if not force and ADMINS_STATE.last is not None and now - ADMINS_STATE.last < ADMINS_INTERVAL_SECONDS:
            return False
        ADMINS_STATE.last = now
        try:
            members = await self._directory.group_members(acting_uid, ADMIN_GROUP)
        except DirectoryUnavailableError:
            LOG.warning("Gruppe admin nicht abrufbar, der letzte Verwalter-Stand bleibt")
            ADMINS_STATE.last = None
            return False
        value = json.dumps(sorted(set(members or ()) | {acting_uid}))
        current = await anyio.to_thread.run_sync(self._store.get_meta, META_TIME_ADMINS)
        if current == value:
            return False
        if blocking:
            return await anyio.to_thread.run_sync(self._store_admins_sync, value)
        return await anyio.to_thread.run_sync(self._try_store_admins_sync, value)

    async def list_children(self, acting_uid: str) -> PlaytimeView:
        """Alle Konten mit Spielerzeile (ohne Verwalter), je mit Regeln, Verbrauch und Auswertung."""
        await self.refresh_admins(acting_uid)
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

        ``holiday`` None heißt: In den Ferien gilt der Normalplan. Verwalter-Konten
        lehnt er ab (ValueError, 422): Sie sind freigestellt (A4).
        """
        await self._require_player(nc_user)
        await self.refresh_admins(acting_uid, force=True)
        applied = await anyio.to_thread.run_sync(self._set_sync, nc_user, normal, holiday, acting_uid)
        return await self._result(acting_uid, nc_user, applied)

    async def clear_child(self, acting_uid: str, nc_user: str) -> ChildResult:
        """Entfernt Regeln und Verbrauch eines Kindes (zurück auf keine Begrenzung, O-10)."""
        await self._require_player(nc_user)
        await self.refresh_admins(acting_uid, force=True)
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

    async def set_world_window(
        self, acting_uid: str, world_id: str, windows: dict[int, tuple[int, int]]
    ) -> WorldWindowResult:
        """Setzt das Wochen-Zeitfenster einer Welt (fehlender Wochentag = geschlossen) und schreibt die Regeldatei.

        Die Welt läuft weiter (O-05); außerhalb des Fensters sperrt der Mod Kinder
        beim Beitritt und trennt verbundene am Fensterende.
        """
        if not windows:
            raise ValueError(MSG_WINDOW_NEEDS_OPEN_DAY)
        await self._require_world(world_id)
        await self.refresh_admins(acting_uid, force=True)
        return await anyio.to_thread.run_sync(self._window_sync, world_id, windows)

    async def clear_world_window(self, acting_uid: str, world_id: str) -> WorldWindowResult:
        """Entfernt das Zeitfenster: Die Welt ist ab sofort immer offen, ohne Neustart."""
        await self._require_world(world_id)
        await self.refresh_admins(acting_uid, force=True)
        return await anyio.to_thread.run_sync(self._window_sync, world_id, None)

    async def my_playtime(self, nc_user: str, *, exempt: bool) -> MyPlaytime:
        """Eigene Restzeit für die Kind-Ansicht; ``nc_user`` kommt aus der signierten Anfrage.

        ``exempt`` (Verwalter laut Selbstauskunft) und Konten im Verwalter-Schnappschuss
        sind frei wie im Welt-Mod (A4); ohne Regeln keine Begrenzung (O-10). Liest
        nur, ohne Sperre. Lesefehler: PlaytimeUnavailableError.
        """
        if exempt:
            return UNLIMITED
        return await anyio.to_thread.run_sync(self._my_playtime_sync, nc_user)

    async def my_world_windows(self, world_ids: list[str]) -> dict[str, MyWorldWindow]:
        """Fensterstatus je eigener Welt (offen jetzt, aktuelles oder nächstes Fenster); Lesefehler: 503."""
        return await anyio.to_thread.run_sync(self._my_world_windows_sync, world_ids)

    def _my_playtime_sync(self, nc_user: str) -> MyPlaytime:
        try:
            if nc_user in self._admins():
                return UNLIMITED
            engine = self._worlds.time
            state = engine.child_state(nc_user)
            if state is None:
                return UNLIMITED
            return kid_playtime(state, engine.now(), self._zone())
        except _READ_ERRORS as exc:
            LOG.warning("Spielzeit für die Kind-Ansicht nicht lesbar: %s", type(exc).__name__)
            raise PlaytimeUnavailableError from exc

    def _my_world_windows_sync(self, world_ids: list[str]) -> dict[str, MyWorldWindow]:
        try:
            now = self._worlds.time.now()
            tz = self._zone()
            return {
                world_id: world_window_status(now, tz, self._store.world_window(world_id)) for world_id in world_ids
            }
        except _READ_ERRORS as exc:
            LOG.warning("Welt-Zeitfenster für die Kind-Ansicht nicht lesbar: %s", type(exc).__name__)
            raise PlaytimeUnavailableError from exc

    def _zone(self) -> ZoneInfo:
        return load_zone(self._store.get_meta("time_zone") or "")

    # Unter der Sperre (Worker-Thread)

    def _store_admins_sync(self, value: str) -> bool:
        with self._worlds.mutation():
            return self._apply_admins(value)

    def _try_store_admins_sync(self, value: str) -> bool:
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                # Belegte Sperre: Der nächste Verwalter-Aufruf versucht es erneut.
                ADMINS_STATE.last = None
                return False
            return self._apply_admins(value)

    def _apply_admins(self, value: str) -> bool:
        """Nur unter der Sperre: neuen Schnappschuss ablegen und alle Welten neu rendern."""
        if self._store.get_meta(META_TIME_ADMINS) == value:
            return False
        self._store.set_meta(META_TIME_ADMINS, value)
        self._refresh_all_worlds()
        return True

    def _admins(self) -> frozenset[str]:
        return parse_admins(self._store.get_meta(META_TIME_ADMINS))

    def _window_sync(self, world_id: str, windows: dict[int, tuple[int, int]] | None) -> WorldWindowResult:
        with self._worlds.mutation():
            if self._store.get_world(world_id) is None:
                raise WorldNotFoundError(NOT_FOUND)
            if windows is None:
                self._store.clear_world_window(world_id)
            else:
                self._store.replace_world_window(world_id, windows)
            applied = self._worlds.push_time(world_id)
            current = window_days(self._store.world_window(world_id))
        return WorldWindowResult(world_id=world_id, time_window=current, applied=applied)

    def _set_sync(self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, acting_uid: str) -> bool:
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._worlds.mutation():
            if nc_user in self._admins():
                raise ValueError(MSG_ADMIN_NO_RULES)
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
        return local_day(int(time.time()), self._zone())

    def _holiday_view(self, holiday_id: int, holiday: Holiday, today: date | None = None) -> HolidayView:
        day = self._today() if today is None else today
        return HolidayView(
            id=holiday_id,
            label=holiday.label,
            start_date=holiday.start,
            end_date=holiday.end,
            active=holiday.start <= day <= holiday.end,
        )

    def _snapshot(self, *, without_admins: bool = True) -> _Snapshot:
        tz_name = self._store.get_meta("time_zone") or DEFAULT_TIME_ZONE
        today = local_day(int(time.time()), load_zone(tz_name))
        plans = self._store.child_plans()
        holidays = [self._holiday_view(hid, item, today) for hid, item in self._store.holiday_rows()]
        # Verwalter erscheinen nicht in der Kinderliste (A4); die Einzelsicht nach clear_child zeigt sie.
        admins = self._admins() if without_admins else frozenset[str]()
        rows: list[ChildView] = []
        for player in self._store.list_players():
            if player.nc_user in admins:
                continue
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
        for row in self._snapshot(without_admins=False).rows:
            if row.nc_user == nc_user:
                return row
        raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _result(self, acting_uid: str, nc_user: str, applied: bool) -> ChildResult:
        row = await anyio.to_thread.run_sync(self._child_snapshot, nc_user)
        display = await self._display_name(acting_uid, nc_user)
        return ChildResult(child=replace(row, display_name=display), applied=applied)

    async def _require_world(self, world_id: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_world, world_id) is None:
            raise WorldNotFoundError(NOT_FOUND)

    async def _require_player(self, nc_user: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_player, nc_user) is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name

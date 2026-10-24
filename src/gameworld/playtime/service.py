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

Verwalter-Schnappschuss (O-11/A4, ROLLE-03): Der Zeittakt hat keinen handelnden
Nutzer, Gruppen löst aber nur ein berechtigtes Konto auf. Darum holt
``refresh_admins`` im Kontext eines geprüften Verwalters die Mitglieder jeder
Verwalter-Gruppe (gedrosselt) und führt den Stand JE GRUPPE (Tabelle
verwalter_snapshot). Darf das Konto eine Gruppe nicht lesen (403, etwa ein Lehrer
die Gruppe admin) oder stört Nextcloud, bleibt genau der Stand dieser Gruppe
(P-03). Die Vereinigung aller Gruppenstände steht als meta ``time_admins`` (JSON,
sortiert, der handelnde Verwalter immer darin); alle bisherigen Leser sehen sie
unverändert. Getrennt davon führt meta ``nc_admins`` die bestätigten Mitglieder der
Gruppe admin: Nur sie dürfen den Kontenabgleich auslösen (404-Falle, F-04). Ohne
jeden Stand gibt es keine Freistellung (fail closed).

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
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryRejectedError, DirectoryUnavailableError
from gameworld.access.roles import ADMIN_GROUP, META_VERWALTER_GROUPS, parse_verwalter_groups
from gameworld.access.service import MSG_NO_PLAYER, PlayerNotFoundError
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.plan import (
    DEFAULT_TIME_ZONE,
    ChildState,
    Holiday,
    NextStart,
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
# Bestätigte Mitglieder der Gruppe admin (JSON, sortiert); nur sie lösen den Kontenabgleich aus.
# Bewusst hier und nicht in playtime/engine.py (der Erwachsen-Plan ändert engine.py).
META_NC_ADMINS = "nc_admins"
# Kind-Ansicht: weniger Rest gilt als aufgebraucht, gleiche Schwelle wie MIN_LEFT im Welt-Mod (Pitfall 8).
MIN_LEFT_SECONDS = 60
# Lesefehler der Zeitregeln (Datenbank, Zeitzone, kaputte Zeilen) werden 503.
_READ_ERRORS = (sqlite3.Error, ValueError, KeyError)


@dataclass
class AdminsState:
    """Zeitpunkt (monotonic) der letzten Abfrage der Verwalter-Gruppen."""

    last: float | None = None


ADMINS_STATE = AdminsState()


class HolidayNotFoundError(LookupError):
    """Unbekannte Ferien-id (404)."""


@dataclass
class _GroupRead:
    """Ergebnis der Abfragen einer Verwalter-Gruppe in einem Lauf.

    ``answer``: letzte erfolgreiche Mitgliederliste (Nextclouds Antwort), None ohne
    Erfolg. ``confirmed``: Konten, die die Gruppe selbst lesen konnten UND darin
    stehen (CR-01). ``rejected``: Konten, denen Nextcloud die Gruppe verweigert hat.
    """

    answer: frozenset[str] | None = None
    confirmed: set[str] = field(default_factory=set[str])
    rejected: set[str] = field(default_factory=set[str])
    outage: bool = False


@dataclass(frozen=True)
class _AdminsUpdate:
    """Neuer Verwalter-Stand: je Gruppe, Vereinigung (JSON), NC-Admins (JSON, None = unverändert)."""

    stands: dict[str, frozenset[str]]
    union: str
    nc_admins: str | None
    seen_at: str | None = None


def _next_stands(
    groups: list[str], previous: dict[str, set[str]], reads: dict[str, _GroupRead]
) -> dict[str, frozenset[str]]:
    """Stand je Gruppe: Nextclouds Antwort, sonst der letzte Stand ohne die abgelehnten Konten.

    Ein Konto, das im Stand einer Gruppe steht und sie trotzdem nicht lesen darf,
    gehört ihr nicht mehr an (Mitglieder lesen die eigene Gruppe). Wer nur keine
    Rechte auf die Gruppe hat und nicht darin steht, ändert nichts (P-03).
    """
    stands: dict[str, frozenset[str]] = {}
    for gid in groups:
        read = reads[gid]
        if read.answer is not None:
            stands[gid] = read.answer
        else:
            stands[gid] = frozenset(previous.get(gid, set[str]()) - read.rejected)
    return stands


def _json_list(uids: Iterable[str]) -> str:
    return json.dumps(sorted(set(uids)))


def _union(groups: Iterable[Iterable[str]]) -> set[str]:
    result: set[str] = set()
    for uids in groups:
        result.update(uids)
    return result


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
    """Nächster Start für die Kind-Ansicht: ISO-Wochentag 1..7, lokale Minute 0..1439, Tage ab heute.

    ``days_ahead`` 0 heißt heute, 7 heißt derselbe Wochentag in einer Woche: Nur so
    kann die Anzeige "heute" sagen, ohne die Zeitzone des Haushalts zu kennen.
    """

    weekday: int
    minute: int
    days_ahead: int


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
    """Ein Öffnungsfenster einer Welt: Wochentag, Minuten (Ende 1440 = Tagesende) und Tage ab heute.

    ``days_ahead`` 0 heißt heute (auch beim offenen Fenster), 7 derselbe Wochentag
    in einer Woche; damit sagt die Kind-Ansicht "Heute", "Morgen" oder "Am Samstag".
    """

    weekday: int
    start: int
    end: int
    days_ahead: int


@dataclass(frozen=True)
class MyWorldWindow:
    """Fensterstatus einer Welt für die Kind-Ansicht: offen (None = kein Fenster) und das aktuelle oder nächste."""

    open: bool | None
    next: WindowSlot | None


NO_WINDOW = MyWorldWindow(open=None, next=None)


class PlaytimeUnavailableError(RuntimeError):
    """Die Zeitregeln ließen sich nicht lesen (503, nie Daten anderer)."""


def next_time(start: NextStart | None, now: int, tz: ZoneInfo) -> NextTime | None:
    """Nächster Start (plan.NextStart) in Wochentag, Minute und Tage ab heute; None ergibt None.

    Die Tage kommen aus dem absoluten Epoch des Starts, nicht aus dem Token
    ``Sa-10:00``: Liegt der Start eine Woche später am selben Wochentag, aber zu
    einer späteren Uhrzeit als jetzt, heißt das 7 und nicht "heute" (WR-01).
    """
    if start is None:
        return None
    days_ahead = (local_day(start.at, tz) - local_day(now, tz)).days
    return NextTime(weekday=start.weekday, minute=start.minute, days_ahead=days_ahead)


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
    if state.reason == "tag":
        blocked: str | None = "tag"
    elif state.reason == "limit":
        blocked = "aufgebraucht"
    elif state.reason == "fenster" or state.until - now < MIN_LEFT_SECONDS:
        blocked = "fenster"
    elif state.rest_s is not None and state.rest_s < MIN_LEFT_SECONDS:
        blocked = "aufgebraucht"
    else:
        blocked = None
    if blocked is not None:
        upcoming = next_time(state.next_start, now, tz)
        return MyPlaytime(limited=True, state=blocked, remaining_minutes=0, until_minute=None, next=upcoming)
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
        return MyWorldWindow(open=True, next=WindowSlot(weekday=today, start=start, end=end, days_ahead=0))
    upcoming = next_time(state.next_start, now, tz)
    slot = None if upcoming is None else windows.get(upcoming.weekday)
    if upcoming is None or slot is None:
        return MyWorldWindow(open=False, next=None)
    return MyWorldWindow(
        open=False,
        next=WindowSlot(weekday=upcoming.weekday, start=slot[0], end=slot[1], days_ahead=upcoming.days_ahead),
    )


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
        """Verwalter-Schnappschuss je Verwalter-Gruppe auffrischen; True, wenn sich time_admins änderte.

        Nur im Kontext eines geprüften Verwalters aufrufen und nie unter
        ``mutation()`` (die Gruppenabfragen laufen vorher, außerhalb der Sperre).
        Gedrosselt auf ADMINS_INTERVAL_SECONDS, außer mit ``force``. Jede Gruppe
        einzeln: Ablehnung (403, etwa ein Lehrer auf der Gruppe admin) oder Störung
        lassen genau den Stand dieser Gruppe stehen (P-03). Ändert sich die
        Vereinigung, bekommen alle Welten die neue Regeldatei: ``blocking`` unter
        ``mutation()``, sonst (Dashboard) per ``try_mutation()``; bei belegter Sperre
        holt der nächste Aufruf nach.
        """
        now = monotonic()
        if not force and ADMINS_STATE.last is not None and now - ADMINS_STATE.last < ADMINS_INTERVAL_SECONDS:
            return False
        ADMINS_STATE.last = now
        groups = await self._verwalter_groups()
        reads = await self._read_groups(groups, [acting_uid])
        if any(read.outage for read in reads.values()):
            LOG.warning("Eine Verwalter-Gruppe ist nicht abrufbar, ihr letzter Stand bleibt")
            ADMINS_STATE.last = None
        if all(read.answer is None and not read.rejected for read in reads.values()):
            # Reine Störung: Nichts Neues zu wissen, der letzte Stand bleibt unverändert.
            return False
        update = await anyio.to_thread.run_sync(self._plan_refresh, groups, reads, acting_uid)
        if update is None:
            return False
        if blocking:
            return await anyio.to_thread.run_sync(self._store_admins_sync, update)
        return await anyio.to_thread.run_sync(self._try_store_admins_sync, update)

    async def verify_admins(self, candidates: Iterable[str]) -> str | None:
        """Hintergrund-Prüfung des Schnappschusses ohne geprüften Verwalter (CR-01); bestätigtes Konto oder None.

        Fragt jede Verwalter-Gruppe der Reihe nach als die Konten aus ``candidates``.
        Bestätigt ist ein Konto nur, wenn es eine Gruppe selbst lesen kann UND darin
        steht; ungeprüft wird nie ein Konto eingefügt. Eine erfolgreiche Antwort
        ersetzt den Stand dieser Gruppe. Ohne Antwort bleibt er (ein Lehrer ohne
        Recht auf die Gruppe admin leert sie nie, P-03); nur Konten, die darin
        standen und abgelehnt wurden, fallen heraus. Lehnt Nextcloud jedes Konto
        ausdrücklich ab (401/403), wird der Schnappschuss leer (fail closed, keine
        Empfänger, keine Freistellung). meta ``nc_admins`` bekommt die eben
        gelesenen Mitglieder der Gruppe admin; ohne Antwort auf admin ist sie leer,
        dann läuft kein Kontenabgleich (F-04). Vorher muss Nextcloud die ExApp selbst
        annehmen (Directory.app_accepted), sonst fragt die Prüfung gar nicht erst
        und der Stand bleibt. Bei einer reinen Störung bleibt der letzte Stand, es
        gilt aber kein Konto als bestätigt. Belegte Sperre: None, der nächste Lauf
        versucht es erneut.
        """
        # Gegenprobe zuerst: Solange Nextcloud die ExApp selbst ablehnt (Start,
        # Neuregistrierung), bekommt jedes Konto 401. Das ist eine Störung, keine
        # Ablehnung der Konten; ohne Gegenprobe leerte jeder Neustart den
        # Schnappschuss. Danach, nicht davor: eine spätere Probe könnte schon gelingen,
        # während die Abfragen noch abgelehnt wurden (am Dev-Stack beobachtet).
        if not await self._directory.app_accepted():
            LOG.warning("Verwalter-Schnappschuss nicht bestätigt, Nextcloud nimmt Gameworld gerade nicht an")
            return None
        order = list(dict.fromkeys(candidates))
        if not order:
            return None
        groups = await self._verwalter_groups()
        reads = await self._read_groups(groups, order)
        if all(read.answer is None and not read.rejected for read in reads.values()):
            LOG.warning("Verwalter-Schnappschuss nicht bestätigt, der letzte Stand bleibt")
            return None
        confirmed = _union(read.confirmed for read in reads.values())
        acting = next((uid for uid in order if uid in confirmed), None)
        seen_at = datetime.now(UTC).isoformat(timespec="seconds")
        update = await anyio.to_thread.run_sync(self._plan_verify, groups, reads, seen_at)
        if not await anyio.to_thread.run_sync(self._store_admins_background_sync, update):
            return None
        if acting is None:
            LOG.warning("Kein Konto des Verwalter-Schnappschusses ist bestätigt, der Stand folgt den Antworten")
            return None
        ADMINS_STATE.last = monotonic()
        return acting

    async def _verwalter_groups(self) -> list[str]:
        """Konfigurierte Verwalter-Gruppen, admin zuerst; kaputte Konfiguration heißt nur admin (fail closed)."""
        raw = await anyio.to_thread.run_sync(self._store.get_meta, META_VERWALTER_GROUPS)
        return sorted(parse_verwalter_groups(raw), key=lambda gid: (gid != ADMIN_GROUP, gid))

    async def _read_groups(self, groups: list[str], candidates: list[str]) -> dict[str, _GroupRead]:
        """Jede Gruppe als die Kandidaten der Reihe nach, bis einer sie liest und darin steht.

        Außerhalb jeder Sperre (Sperr-Regel); ein Fehler betrifft nur die eine Gruppe.
        """
        reads: dict[str, _GroupRead] = {}
        for gid in groups:
            read = _GroupRead()
            for uid in candidates:
                try:
                    members = await self._directory.group_members(uid, gid)
                except DirectoryRejectedError:
                    read.rejected.add(uid)
                    continue
                except DirectoryUnavailableError:
                    read.outage = True
                    continue
                read.answer = frozenset(members or ())
                if uid in read.answer:
                    read.confirmed.add(uid)
                    break
            reads[gid] = read
        return reads

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
        """Entfernt die Regeln eines Kindes (zurück auf keine Begrenzung, O-10); der heutige Verbrauch bleibt."""
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

    def _previous_stands(self) -> dict[str, set[str]]:
        """Letzter Stand je Gruppe; vor dem ersten Lauf mit Schema 8 gilt der alte Schnappschuss als Gruppe admin."""
        stands = self._store.group_snapshot()
        if not stands:
            legacy = self._admins()
            if legacy:
                stands = {ADMIN_GROUP: set(legacy)}
        return stands

    def _plan_refresh(self, groups: list[str], reads: dict[str, _GroupRead], acting_uid: str) -> _AdminsUpdate | None:
        """Neuer Stand nach einem Verwalter-Besuch; None, wenn sich nichts ändert (dann keine Sperre)."""
        stands = _next_stands(groups, self._previous_stands(), reads)
        union = _json_list(_union(stands.values()) | {acting_uid})
        admin_read = reads[ADMIN_GROUP]
        if admin_read.answer is not None:
            nc_admins: str | None = _json_list(admin_read.answer)
        elif admin_read.rejected:
            current = parse_admins(self._store.get_meta(META_NC_ADMINS))
            nc_admins = _json_list(current - admin_read.rejected)
        else:
            nc_admins = None
        update = _AdminsUpdate(stands=stands, union=union, nc_admins=nc_admins)
        return update if self._differs(update) else None

    def _plan_verify(self, groups: list[str], reads: dict[str, _GroupRead], seen_at: str) -> _AdminsUpdate:
        """Neuer Stand nach der Hintergrund-Prüfung; nc_admins nur aus einer frischen Antwort der Gruppe admin."""
        stands = _next_stands(groups, self._previous_stands(), reads)
        answered = any(read.answer is not None for read in reads.values())
        outage = any(read.outage for read in reads.values())
        if not answered and not outage:
            # Jede Abfrage jedes Kontos abgelehnt: Niemand ist mehr bestätigt (fail closed).
            stands = {gid: frozenset[str]() for gid in groups}
        admin_answer = reads[ADMIN_GROUP].answer
        return _AdminsUpdate(
            stands=stands,
            union=_json_list(_union(stands.values())),
            nc_admins=_json_list(admin_answer or ()),
            seen_at=seen_at,
        )

    def _differs(self, update: _AdminsUpdate) -> bool:
        current = {gid: frozenset(uids) for gid, uids in self._store.group_snapshot().items()}
        wanted = {gid: uids for gid, uids in update.stands.items() if uids}
        if current != wanted or self._store.get_meta(META_TIME_ADMINS) != update.union:
            return True
        return update.nc_admins is not None and self._store.get_meta(META_NC_ADMINS) != update.nc_admins

    def _store_admins_sync(self, update: _AdminsUpdate) -> bool:
        with self._worlds.mutation():
            return self._apply_admins(update)

    def _try_store_admins_sync(self, update: _AdminsUpdate) -> bool:
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                # Belegte Sperre: Der nächste Verwalter-Aufruf versucht es erneut.
                ADMINS_STATE.last = None
                return False
            return self._apply_admins(update)

    def _store_admins_background_sync(self, update: _AdminsUpdate) -> bool:
        """Hintergrund: Stand ohne Warten ablegen; True, wenn er jetzt gilt."""
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                return False
            self._apply_admins(update)
            return True

    def _apply_admins(self, update: _AdminsUpdate) -> bool:
        """Nur unter der Sperre: Stand je Gruppe, NC-Admins, Dienstalter und Vereinigung ablegen.

        True, wenn time_admins neu ist; dann bekommen alle Welten die neue Regeldatei.
        """
        for gid, uids in sorted(update.stands.items()):
            self._store.replace_group_snapshot(gid, set(uids))
        self._store.drop_group_snapshots(keep=set(update.stands))
        if update.nc_admins is not None:
            self._store.set_meta(META_NC_ADMINS, update.nc_admins)
        if update.seen_at is not None:
            self._store.sync_verwalter_seen(set(parse_admins(update.union)), update.seen_at)
        if self._store.get_meta(META_TIME_ADMINS) == update.union:
            return False
        self._store.set_meta(META_TIME_ADMINS, update.union)
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
            # Heutigen Verbrauch behalten: erneutes Setzen gibt kein frisches Kontingent (WR-04).
            today = local_day(self._worlds.time.now(), self._zone())
            self._store.clear_child(nc_user, keep_from=today)
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

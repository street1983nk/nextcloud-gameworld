"""Die Spielzeit-Rechnung der ExApp: verbuchen, rendern, Verbrauch pflegen.

Nur diese Schicht verbindet die reinen Module (``playtime.plan``,
``playtime.ledger``, ``provisioner.time_mod``) mit der Datenbank (Schema 4). Sie
ist synchron und kennt kein Docker: Sie liest und schreibt ausschließlich den
Store und reine Funktionen. Der Aufrufer (``WorldService``) liest das Zählbuch
aus der Welt und schreibt die Regeldatei; der 15-s-Takt und der Einladungspfad
rufen diese Methoden unter der Welt-Sperre bzw. ``try_mutation`` auf.

``book`` verbucht die Zählbuch-Zuwächse einer Welt auf den lokalen Tag jedes
Kindes mit Regeln (ein Kontingent über alle Welten, O-03) und verankert den
gesehenen Stand neu. ``render`` rechnet je Welt die Regeldatei aus der Datenbank:
für jedes eingeladene Kind mit Regeln eine Zeile mit absolutem Fenster und
Deckel im Zählbuch-Maß (gesehener Stand plus Restsekunden), für jedes eingeladene
Verwalter-Konto aus dem Schnappschuss ``time_admins`` die Zeile ``frei`` (O-11/A4),
dazu die Welt-Zeile aus dem Welt-Fenster. Der Regelteil wird je Welt zwischengespeichert; nur bei
einer Änderung zählt die Generation hoch und der Kopf bekommt einen neuen
Zeitpunkt, damit die Bytes nicht in jedem Takt wechseln (Pitfall 6).

Für den Kindertext schreibt ``render`` keinen fertigen Tagesbezug ("morgen"),
sondern absolute Epochs (Quick 261021-481): je Zeile den nächsten Start
(``@start``) und einmal die Tagesanfänge heute bis heute+8 (``@tage``). Der Mod
rechnet "Heute", "Morgen" oder "Am Samstag" gegen die eigene Uhr; so bleibt der
Text auch nach Mitternacht richtig, wenn die Regeldatei noch nicht neu ist. Die
Epochs ändern sich nicht mit der Uhr, ``@tage`` nur einmal je Tag.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import astuple, dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from gameworld.playtime.ledger import attribution_day, increments
from gameworld.playtime.plan import (
    ChildState,
    NextStart,
    day_starts,
    evaluate_child,
    evaluate_world,
    load_zone,
    local_day,
)
from gameworld.provisioner.time_mod import DayGrid, Ledger, TimeLine, render_time_file
from gameworld.worlds.store import WorldStore

# Verbrauch höchstens einmal pro Stunde aufräumen (A8/Pitfall 9).
_PRUNE_INTERVAL_SECONDS = 3600
# Aufbewahrung: heute und 7 Tage zurück.
_RETENTION_DAYS = 7
# meta-Schlüssel des Verwalter-Schnappschusses (JSON-Liste, sortiert; playtime/service.py).
META_TIME_ADMINS = "time_admins"
# Verwalter sind freigestellt (O-11/A4): Welt-Fenster und eigene Grenzen gelten nicht.
_FREI = TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-")


def _next_fields(start: NextStart | None) -> tuple[int, int]:
    """Felder next_at und next_minute einer TimeLine; -1 -1 heißt: kein nächster Start."""
    return (-1, -1) if start is None else (start.at, start.minute)


def parse_admins(raw: str | None) -> frozenset[str]:
    """Verwalter-Schnappschuss aus meta; fehlt er oder ist er kaputt, gibt es keine Freistellung (fail closed)."""
    if not raw:
        return frozenset()
    try:
        value: object = json.loads(raw)
    except ValueError:
        return frozenset()
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))  # pyright: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class _Rendered:
    """Zwischenspeicher je Welt: Regelteil, Generation, Zeitpunkt und fertige Bytes."""

    key: tuple[object, ...]
    generation: int
    issued_at: int
    data: bytes


class TimeEngine:
    """Rechnet Regeldateien aus Schema 4 und verbucht Zählbuch-Zuwächse (rein bis auf den Store)."""

    def __init__(self, store: WorldStore, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        # Zuletzt gerenderter Stand je Welt (Speicher): verhindert, dass sich die
        # Bytes in jedem Takt ändern (nur bei echter Änderung neue Generation).
        self._cache: dict[str, _Rendered] = {}
        self._last_prune: int | None = None

    def _now(self) -> int:
        return int(self._clock())

    def now(self) -> int:
        """Jetzt (Epoch) nach der Uhr dieser Rechnung; die Kind-Ansicht rechnet mit derselben Uhr."""
        return self._now()

    def _zone(self) -> ZoneInfo:
        return load_zone(self._store.get_meta("time_zone") or "")

    def book(self, world_id: str, ledger: Ledger | None) -> None:
        """Verbucht die Zuwächse des Zählbuchs; verankert den gesehenen Stand neu.

        Nur Kinder mit Regeln werden verbucht (Opt-in, O-10); für alle anderen
        Namen wird der Stand nur verankert (Schutz gegen Doppelzählung). Ein
        fehlendes Zählbuch (None) ändert nichts.
        """
        if ledger is None:
            return
        seen = self._store.ledger_seen(world_id)
        delta, new_seen = increments(seen, ledger.seconds)
        usage: dict[str, int] = {}
        tz = self._zone()
        day = attribution_day(ledger.written_at, tz)
        if delta:
            plans = self._store.child_plans()
            for name, seconds in delta.items():
                nc_user = self._store.player_name_owner(name)
                if nc_user is not None and nc_user in plans:
                    usage[nc_user] = usage.get(nc_user, 0) + seconds
        # Verbrauch und neuer Stand in einer Transaktion: nie doppelt verbucht (WR-05).
        self._store.book_usage(world_id, day, usage, new_seen)

    def render(self, world_id: str) -> tuple[bytes, bool]:
        """Regeldatei der Welt aus der Datenbank; (Bytes, geändert).

        ``geändert`` False heißt: Der Regelteil ist gleich geblieben, die Bytes
        und die Generation sind unverändert (Anti-Pattern "Regeldatei in jedem
        Takt neu schreiben").
        """
        tz = self._zone()
        now = self._now()
        plans = self._store.child_plans()
        holidays = self._store.list_holidays()
        seen = self._store.ledger_seen(world_id)
        admins = parse_admins(self._store.get_meta(META_TIME_ADMINS))
        today = local_day(now, tz)
        players: dict[str, TimeLine] = {}
        for name in self._store.access_entries(world_id):
            nc_user = self._store.player_name_owner(name)
            if nc_user is None:
                continue
            if nc_user in admins:
                # Eingeladene Verwalter: Zeile frei, auch ohne Welt-Fenster (A4).
                players[name] = _FREI
                continue
            if nc_user not in plans:
                continue
            normal, holiday = plans[nc_user]
            used = self._store.usage(nc_user, today)
            state = evaluate_child(now, tz, normal, holiday, holidays, used)
            # cap_rest_s statt rest_s: Vor dem Fenster öffnet der Mod ab "from" selbst (WR-02).
            cap = -1 if state.cap_rest_s is None else seen.get(name, 0) + state.cap_rest_s
            next_at, next_minute = _next_fields(state.next_start)
            players[name] = TimeLine(
                cap=cap,
                start=state.start,
                until=state.until,
                reason=state.reason,
                next_hint=state.next_hint,
                next_at=next_at,
                next_minute=next_minute,
            )
        world_line = self._world_line(world_id, now, tz)
        lines = [*players.values(), *([] if world_line is None else [world_line])]
        days = None
        if any(line.next_at >= 0 for line in lines):
            # Tagesgrenzen nur, wenn eine Zeile einen nächsten Start trägt (sonst Bytes wie bisher).
            days = DayGrid(weekday=today.isoweekday(), starts=day_starts(now, tz))
        rendered = self._render_cached(world_id, world_line, players, now, days)
        self._maybe_prune(now, tz)
        return rendered

    def forget(self, world_id: str) -> None:
        """Verwirft den gerenderten Stand der Welt (CR-01).

        Nach einem gescheiterten Schreiben der Regeldatei: Der nächste ``render``
        liefert ``geändert`` True (mit neuer Generation), damit der Takt die Datei
        erneut schreibt, statt den nie angekommenen Stand für geschrieben zu halten.
        """
        self._cache.pop(world_id, None)

    def child_state(self, nc_user: str) -> ChildState | None:
        """Auswertung für ein Kind (API und Kind-Ansicht); None heißt: keine Regeln (Opt-in)."""
        plans = self._store.child_plans()
        if nc_user not in plans:
            return None
        tz = self._zone()
        now = self._now()
        normal, holiday = plans[nc_user]
        holidays = self._store.list_holidays()
        used = self._store.usage(nc_user, local_day(now, tz))
        return evaluate_child(now, tz, normal, holiday, holidays, used)

    def _world_line(self, world_id: str, now: int, tz: ZoneInfo) -> TimeLine | None:
        state = evaluate_world(now, tz, self._store.world_window(world_id))
        if state is None:
            return None
        next_at, next_minute = _next_fields(state.next_start)
        return TimeLine(
            cap=0,
            start=state.start,
            until=state.until,
            reason=state.reason,
            next_hint=state.next_hint,
            next_at=next_at,
            next_minute=next_minute,
        )

    def _render_cached(
        self,
        world_id: str,
        world_line: TimeLine | None,
        players: dict[str, TimeLine],
        now: int,
        days: DayGrid | None,
    ) -> tuple[bytes, bool]:
        key = self._body_key(world_line, players, days)
        cached = self._cache.get(world_id)
        if cached is not None and cached.key == key:
            return cached.data, False
        generation = self._store.bump_time_generation(world_id)
        data = render_time_file(generation, now, world_line, players, days=days)
        self._cache[world_id] = _Rendered(key=key, generation=generation, issued_at=now, data=data)
        return data, True

    @staticmethod
    def _body_key(
        world_line: TimeLine | None, players: dict[str, TimeLine], days: DayGrid | None
    ) -> tuple[object, ...]:
        world = None if world_line is None else astuple(world_line)
        grid = None if days is None else astuple(days)
        return (world, tuple(sorted((name, astuple(line)) for name, line in players.items())), grid)

    def _maybe_prune(self, now: int, tz: ZoneInfo) -> None:
        if self._last_prune is not None and now - self._last_prune < _PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune = now
        self._store.prune_usage(local_day(now, tz) - timedelta(days=_RETENTION_DAYS))

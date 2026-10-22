"""Pause für alle Welten des Haushalts (ELTERN-01): Zeitfenster, Morgen-Minuten, Zustand.

Regeln (04.1-CONTEXT):

- D-01: Eine Pause gilt für alle Welten des Haushalts, nie für eine einzelne Welt.
- D-02: Dauer 15, 30 oder 60 Minuten, danach endet sie von selbst. "Weiter" beendet
  sofort, "Für heute Schluss" sperrt bis zum Beginn des nächsten lokalen Tages.
  Das Tageskontingent (``time_usage``) bleibt in beiden Fällen unverändert.
- D-03/D-04: Der Welt-Mod warnt 30 s vorher im Chat und trennt dann mit dem
  Pausentext; darum liegt ``ab`` immer 30 s nach dem Auslösen.
- D-05: Die Pause wirkt serverseitig über die Zeile ``@pause`` der Regeldatei.
  Getrennte Kinder verbrauchen nichts; Verwalter (``frei``) sind ausgenommen.
- D-06: Erneutes Auslösen während einer Pause behält ``ab`` und verlängert ``bis``
  höchstens, nie kürzer (WR-01); ein laufendes "Für heute Schluss" bleibt.
- D-25: Welten mit altem Welt-Mod (ohne Ereignisdatei) werden beim Auslösen neu
  gestartet, damit die Pause sicher greift (``WorldService.apply_pause_sync``).
- D-29: Zeitfenster laufen während der Pause weiter, nichts wird verlängert.

Der Zustand liegt in SQLite (``pause_state``, genau eine Zeile) und übersteht
einen Neustart der ExApp; ``TimeEngine.render`` liest ihn bei jedem Rendern und
räumt eine abgelaufene Pause weg.

Sperr-Regel (wie playtime/service.py): ``PauseService`` ruft kein Nextcloud auf;
alles Schreiben läuft in einem Worker-Thread unter ``worlds.mutation()``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.playtime.plan import Holiday, WeekPlan, day_starts, local_day, plan_for

if TYPE_CHECKING:
    from gameworld.worlds.service import WorldService

# Vorlauf zwischen Auslösen und Trennen: so lange gilt die Chat-Vorwarnung (D-04).
PAUSE_LEAD_SECONDS = 30
# Erlaubte Dauern in Minuten (D-02).
PAUSE_MINUTES = (15, 30, 60)
ART_PAUSE = "pause"
ART_SCHLUSS = "schluss"
# Morgen laut Plan kein Spieltag (wie time_mod.NO_TOMORROW).
_NO_TOMORROW = -1
# Arten der Outbox-Zeilen je Welt (versendet vom Bot in 04.1-06).
OUTBOX_PAUSE_START = "pause_start"
OUTBOX_PAUSE_SCHLUSS = "pause_schluss"
OUTBOX_PAUSE_END = "pause_end"
MSG_BAD_MINUTES = "Eine Pause dauert 15, 30 oder 60 Minuten."


@dataclass(frozen=True)
class PauseState:
    """Pause des Haushalts: wer sie ausgelöst hat, Trennen (``ab``), Ende (``bis``), Art.

    ``started_by`` dient nur der Nachvollziehbarkeit (T-04.1-15) und geht nie an Kinder.
    """

    started_by: str
    ab: int
    bis: int
    art: str


def is_active(state: PauseState | None, now: int) -> bool:
    """Gilt die Pause noch? Auch während der 30-s-Vorlaufzeit; ab ``bis`` nicht mehr."""
    return state is not None and now < state.bis


def start_window(now: int, minutes: int, current: PauseState | None) -> tuple[int, int]:
    """(ab, bis) einer Pause: ab = jetzt + 30 s, bis = ab + Dauer (D-02, D-04).

    Läuft schon eine Pause (``current`` aktiv), bleibt deren ``ab`` (kein neuer
    Vorlauf) und ``bis`` wird nie verkürzt (WR-01): Ein zweiter Elternteil, dessen
    Seite die laufende Pause noch nicht zeigt, kann sie so weder beenden noch in
    die Vergangenheit legen. Das neue Ende ist das spätere von altem Ende und
    jetzt plus Dauer.
    """
    if minutes not in PAUSE_MINUTES:
        raise ValueError(MSG_BAD_MINUTES)
    if current is not None and is_active(current, now):
        return current.ab, max(current.bis, now + minutes * 60)
    ab = now + PAUSE_LEAD_SECONDS
    return ab, ab + minutes * 60


def schluss_window(now: int, tz: ZoneInfo, current: PauseState | None) -> tuple[int, int]:
    """(ab, bis) für "Für heute Schluss": bis = Beginn des nächsten lokalen Tages.

    Ohne laufende Pause ab = jetzt + 30 s, sonst bleibt ``ab`` der laufenden Pause.
    Kurz vor Mitternacht bleibt ``ab`` vor ``bis``, damit die Zeile gültig bleibt.
    """
    bis = day_starts(now, tz)[1]
    ab = current.ab if current is not None and is_active(current, now) else now + PAUSE_LEAD_SECONDS
    return min(ab, bis - 1), bis


def morgen_minutes(
    now: int,
    tz: ZoneInfo,
    plans: Mapping[str, tuple[WeekPlan, WeekPlan | None]],
    holidays: list[Holiday],
    names_by_user: Mapping[str, str],
) -> dict[str, int]:
    """Spielername auf die Startminute des nächsten lokalen Tages (Zeile ``@morgen``).

    -1: morgen laut Plan kein Spieltag; 0: ganzer Tag ohne Startzeit; sonst der
    Fensteranfang. Ferien morgen nehmen den Ferienplan. Konten ohne Plan fehlen
    (der Mod nimmt dann den Grundtext).
    """
    tomorrow = local_day(now, tz) + timedelta(days=1)
    result: dict[str, int] = {}
    for nc_user, name in names_by_user.items():
        if nc_user not in plans:
            continue
        normal, holiday = plans[nc_user]
        rule = plan_for(tomorrow, normal, holiday, holidays).days[tomorrow.isoweekday()]
        if not rule.allowed:
            result[name] = _NO_TOMORROW
        else:
            result[name] = 0 if rule.window_start is None else rule.window_start
    return result


def clock_text(epoch: int, tz: ZoneInfo) -> str:
    """Uhrzeit H:MM in der Haushalts-Zeitzone (für Seite und Bot, nie für Kindertexte)."""
    local = datetime.fromtimestamp(epoch, tz)
    return f"{local.hour}:{local.minute:02d}"


@dataclass(frozen=True)
class PauseWorldResult:
    """Ergebnis je Welt: Regeldatei angekommen (``applied``) und ob neu gestartet wurde (D-25)."""

    world_id: str
    name: str
    applied: bool
    restarted: bool


@dataclass(frozen=True)
class PauseResult:
    """Neuer Zustand (None = keine Pause) und das Ergebnis je Welt."""

    state: PauseState | None
    worlds: list[PauseWorldResult]


# Entscheidet unter der Sperre aus (laufender Pause oder None, jetzt) den neuen Zustand.
PauseDecision = Callable[[PauseState | None, int], PauseState | None]


class PauseService:
    """Pause starten, beenden, für heute Schluss und lesen (Verwalter-API)."""

    def __init__(self, worlds: WorldService) -> None:
        self._worlds = worlds

    def zone(self) -> ZoneInfo:
        """Haushalts-Zeitzone für die Uhrzeit des Endes (Seite und Bot)."""
        return self._worlds.time.zone()

    async def get(self) -> PauseResult:
        """Aktuelle Pause oder None; eine abgelaufene Pause zählt nicht mehr."""
        return await anyio.to_thread.run_sync(self._get_sync)

    async def start(self, acting_uid: str, minutes: int) -> PauseResult:
        """Pause starten oder verlängern; ein laufendes "Für heute Schluss" bleibt unverändert (WR-01)."""
        if minutes not in PAUSE_MINUTES:
            raise ValueError(MSG_BAD_MINUTES)

        def decide(current: PauseState | None, now: int) -> PauseState:
            if current is not None and current.art == ART_SCHLUSS:
                # Nie herabstufen: Die Elternentscheidung "Schluss" gilt bis morgen.
                return current
            ab, bis = start_window(now, minutes, current)
            return PauseState(started_by=acting_uid, ab=ab, bis=bis, art=ART_PAUSE)

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_START)

    async def schluss(self, acting_uid: str) -> PauseResult:
        zone = self._worlds.time.zone()

        def decide(current: PauseState | None, now: int) -> PauseState:
            ab, bis = schluss_window(now, zone, current)
            return PauseState(started_by=acting_uid, ab=ab, bis=bis, art=ART_SCHLUSS)

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_SCHLUSS)

    async def end(self, acting_uid: str) -> PauseResult:
        """Beendet die Pause sofort; ohne laufende Pause ändert sich nichts (idempotent)."""
        del acting_uid  # Wer beendet, wird nicht gespeichert (es gibt danach keinen Zustand).

        def decide(current: PauseState | None, now: int) -> None:
            del current, now

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_END)

    def _get_sync(self) -> PauseResult:
        state = self._worlds.store.get_pause()
        if not is_active(state, self._worlds.time.now()):
            state = None
        return PauseResult(state=state, worlds=[])

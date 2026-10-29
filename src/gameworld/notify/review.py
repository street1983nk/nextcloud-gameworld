"""Daily review (pure, D-12 to D-15).

``review_line`` builds "Lena 45 Min., Tom 60 Min. (Limit erreicht)" from
(display name, seconds, limit reached); without playtime there is no line and
thus no message (D-14). ``review_due`` checks whether the local minute is in the
short window from the manager's configured minute (WR-03).
"""

from __future__ import annotations

from collections.abc import Iterable

from gameworld.notify.texts import notify_strings

ReviewEntry = tuple[str, int, bool]
# For this long after the configured minute the review may still come (restart, tick).
REVIEW_GRACE_MINUTES = 30


def minutes(seconds: int) -> int:
    """Rounded minutes, but at least 1 for playtime > 0."""
    if seconds <= 0:
        return 0
    return max(1, round(seconds / 60))


def review_line(entries: Iterable[ReviewEntry], *, language: str = "de") -> str | None:
    """One part per child, sorted by display name; None without playtime.

    Minute unit and limit suffix follow ``language`` (the recipient's account
    language); German stays "Min." and " (Limit erreicht)".
    """
    strings = notify_strings(language)
    parts = [
        f"{name} {minutes(seconds)} {strings.review_minutes}{strings.review_limit_suffix if limit_reached else ''}"
        for name, seconds, limit_reached in sorted(entries, key=lambda entry: entry[0].casefold())
        if seconds > 0
    ]
    return ", ".join(parts) if parts else None


def review_due(local_minute: int, pref_minute: int, *, enabled: bool) -> bool:
    """Due only in the window REVIEW_GRACE_MINUTES from the configured minute; never when switched off (WR-03).

    Later in the day no review comes any more: otherwise it would come at the first play
    after the time with partial data, with an early time even in the morning.
    """
    return enabled and pref_minute <= local_minute < pref_minute + REVIEW_GRACE_MINUTES

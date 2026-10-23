---
phase: quick-261023-kq1
plan: 01
subsystem: play (Browser-Spike 04.2)
tags: [security, dos, logging, report]
requires: []
provides:
  - "_read_body ohne Vollpufferung (Content-Length-Vorprüfung + request.stream()-Abbruch)"
  - "RedactWsQueryFilter + install_ws_query_redaction() auf uvicorn.access und uvicorn.error"
  - "korrigiertes sicher-Kriterium in 04.2-REPORT.md"
affects: [src/gameworld/play/ticket_api.py, src/gameworld/main.py]
tech-stack:
  added: []
  patterns: ["Logger-Filter statt Handler-Filter, überlebt uvicorns dictConfig"]
key-files:
  created:
    - src/gameworld/play/log_redact.py
    - tests/play/test_log_redact.py
  modified:
    - src/gameworld/play/ticket_api.py
    - tests/play/test_play_ticket_api.py
    - src/gameworld/main.py
    - .planning/phases/04.2-browser-spike-luanti-wasm/04.2-REPORT.md
decisions:
  - "Content-Length zählt nur als reine ASCII-Ziffern; mehr als 9 Ziffern sind ohne int() sofort 413, unsinniger Wert führt in den Stream-Weg"
  - "Log-Schwärzung als Logger-Filter auf uvicorn.access UND uvicorn.error (WebSocket-Zeilen laufen über uvicorn.error)"
metrics:
  completed: 2026-10-23
  tasks: 3
  files: 6
---

# Quick 261023-kq1: Phase-04.2-Sicherheitsfixes Summary

CR-01 (Memory-DoS durch volles Puffern vor der MAX_BODY-Prüfung) per Content-Length-Vorprüfung und Stream-Abbruch behoben, T-04.2-36 (WebSocket-Ticket in uvicorn-Logzeilen) per Logger-Filter geschwärzt, REPORT-Kriterium "sicher" wahrheitsgemäß korrigiert (T-04.2-52).

## Tasks

| Task | Inhalt | Commit |
|------|--------|--------|
| 1 | CR-01: `_declared_too_large` + `_read_body` mit `async for chunk in request.stream()`, kein `request.body()` mehr; 9 neue Tests (Content-Length 1025 und 100000000 mit Zähler 0; chunked, "10", "abc", Byte 0xB2 = "²" mit Zähler <= 3; play-ticket-Stream; Grenze MAX_BODY = 200, MAX_BODY + 1 = 413 bei unverbrauchtem Ticket) | 9adbe2f |
| 2 | T-04.2-36: `log_redact.py` (Args- und msg-Schwärzung), Aufruf in main.py nach `_setup_logging()`; 23 Tests über uvicorns DefaultFormatter/AccessFormatter, inkl. dictConfig(LOGGING_CONFIG) und Idempotenz | c4b3e0a |
| 3 | T-04.2-52: nur Absatz "sicher:" in 04.2-REPORT.md ersetzt | 6e68d3a |

TDD: RED belegt (Task 1: 7 von 9 neuen Tests rot gegen den alten Code, die beiden Grenz-Positivtests waren schon grün; Task 2: Sammelfehler, Modul fehlte), danach GREEN.

## Prüfung Rückbau T-04.2-14 (per Befehl, 23.10.2026)

- `tailscale serve status`: "No serve config"
- `curl http://127.0.0.1:10040/play/`: Verbindung abgelehnt (exit 7), netstat ohne Eintrag für :10040
- Prozess 16404 existiert nicht mehr, kein python-Prozess mit "gameworld" in der Befehlszeile
- `gameworld-devfront-devfront-1`: Exited (0)

Ergebnis: Rückbau erfolgt, im REPORT als erledigt geführt.

## Gates

ruff check (Vollsatz) grün, ruff format --check grün (163 Dateien), pyright latest 0 Fehler, vulture grün, `pytest tests/play -m "not docker"` 490 passed (1 vorbestehende StarletteDeprecationWarning aus test_play_ws.py).

## Deviations from Plan

- [Rule 3 - Blocking] Der Unicode-Ziffern-Fall wird als rohes Header-Byte `b"\xb2"` gesendet (httpx kodiert str-Header nur ASCII); Starlette dekodiert latin-1 und sieht "²". Dafür übergibt der Test die Header als Liste von Byte-Tupeln (pyright-sauber).
- [Rule 3 - Blocking] Testkonstante heißt `TICKET_VALUE` statt `SECRET` (ruff S105).
- Zusätzlicher Test `test_neg_bereits_formatierte_zeile` deckt die msg-Regex-Schwärzung ab; Idempotenz als eigener Test `test_pos_install_idempotent`.
- Der Plan-Verify-Befehl `grep -nP "\x{2014}|\x{2013}"` scheitert lokal am Locale ("character value too large"); Gegenprobe per Python: 0 Em-/En-Dashes im REPORT und in allen geänderten Dateien.

## Known Stubs

Keine.

## Self-Check: PASSED

- Dateien vorhanden: src/gameworld/play/log_redact.py, tests/play/test_log_redact.py
- Commits vorhanden: 9adbe2f, c4b3e0a, 6e68d3a (lokal, nicht gepusht, Autor street1983nk, ohne Trailer)

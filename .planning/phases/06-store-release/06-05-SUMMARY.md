---
phase: 06-store-release
plan: 05
subsystem: frontend
tags: [frontend, ui-spec-b2, adult-flag]
requires: ["06-03", "06-04"]
provides:
  - "frontend/src/adult.js: confirmLead, CONFIRM_SCOPE, CONFIRM_WARNING, rulesKeptText, adultOnText, adultOffText, nowVerwalterText, adultInviteWarning, invitedLabel, SWITCH_META, INVITE_SWITCH_META, PLAYTIME_RESTING_TEXT"
  - "api.js setAdult(ncUser, adult) -> POST /api/players/adult"
  - "Spielerliste: Chips Erwachsen/Verwalter, Schalter Erwachsen nur für Nicht-Verwalter, Bestätigung ersetzt den Spieler-Dialog"
  - "Einladen-Dialog: Schalter Als erwachsen einladen (nur Einzelkonten), Bestätigung, Warnung je nicht markiertem Konto"
  - "Spielzeit-Abschnitt: Chip Erwachsen: Regel ruht, Verbrauch zählt nicht, Hinweis im PlaytimeDialog"
affects: [06-13]
tech-stack:
  added: []
  patterns:
    - "Bestätigung ersetzt den offenen Dialog (v-if=\"!confirmAdult\" / v-else), Muster BackupSection"
    - "Eigene Schalter-Anzeige (adultShown) folgt der Serverantwort und springt bei Fehler zurück, Muster TalkRoomStatus"
    - "Meta-Text über die description-Prop von NcCheckboxRadioSwitch (setzt aria-describedby selbst)"
key_files:
  created:
    - frontend/src/adult.js
    - frontend/tests/adult.check.mjs
  modified:
    - frontend/src/api.js
    - frontend/src/components/PlayerManager.vue
    - frontend/src/components/InviteDialog.vue
    - frontend/src/components/PlaytimeSection.vue
    - frontend/src/components/PlaytimeDialog.vue
decisions:
  - "Absatz 4 (Regel bleibt gespeichert) nur in der Spielerliste: die Kontosuche im Einladen-Dialog liefert kein has_rules"
  - "adultInviteWarning entfernt den Schlusspunkt der Backend-Meldung, sonst stünde 'Regeln..' im Text"
  - "Verwalter-Chip hat Vorrang vor Erwachsen-Chip, falls ein markiertes Konto später Verwalter wird"
metrics:
  duration: "ca. 35 min"
  completed: 2026-10-24
  tasks: 3
  files: 7
requirements: [ROLLE-04]
---

# Phase 6 Plan 05: Erwachsen-Schalter in der UI (B2) Summary

Verwalter markieren Konten jetzt in der Spielerliste oder direkt beim Einladen als erwachsen, nach einem Bestätigungsdialog mit den Folgen im Klartext; Ausschalten wirkt ohne Dialog, der Spielzeit-Abschnitt zeigt ruhende Regeln.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 (RED) | Prüfskript für die B2-Texte | 3a92af8 |
| 1 (GREEN) | adult.js und setAdult | a9386c2 |
| 2 | Schalter, Marken und Bestätigung in PlayerManager.vue | 937da86 |
| 3 | Als erwachsen einladen und Spielzeit-Kennzeichnung | f033189 |

## Umsetzung

- **Spielerliste:** Chip "Verwalter" (tertiary) bzw. "Erwachsen" (secondary) neben dem Namen, `.players__head` mit `flex-wrap`. Zeile `.players__adult` nur für Nicht-Verwalter mit Schalter "Erwachsen" und Meta-Text als `description` (aria-describedby). Einschalten öffnet den Dialog "Als erwachsen markieren" anstelle des Spieler-Dialogs (Absätze 1 bis 4, Knopf `variant="warning"`, Lade-Icon, X/Escape = Abbrechen, Fehler bleibt im Dialog). Erfolg: Spieler-Dialog mit adultOnText, Liste aus der Serverantwort neu. Ausschalten: sofort `setAdult(false)`, adultOffText; bei Fehler springt der Schalter zurück. `applied: false` zeigt NOT_APPLIED_TEXT, 409 zeigt nowVerwalterText und lädt neu. Fokus nach Schließen auf den Schalter der Person.
- **Einladen-Dialog:** Schalter "Als erwachsen einladen" mit INVITE_SWITCH_META, gesperrt ohne Einzelkonto oder während des Einladens, springt auf aus, wenn alle Einzelkonten abgewählt werden. "Einladen" mit Schalter an öffnet zuerst die Bestätigung mit den Namen der Einzelkonten; Abbrechen führt zurück, Auswahl bleibt. Danach Einladungen wie bisher, je erfolgreich eingeladenem Einzelkonto `setAdult(true)`; Erfolgszeile über invitedLabel mit "(erwachsen)", Teil-Fehler als Warn-NoteCard adultInviteWarning. Nach erfolgreichem Absenden Schalter aus.
- **Spielzeit:** Für `adult` Chip "Erwachsen: Regel ruht", Verbrauch "zählt nicht", Bearbeiten bleibt; PlaytimeDialog zeigt oben PLAYTIME_RESTING_TEXT.

## Gates

- `npm run build`: grün (nur die bekannte Chunk-Größen-Warnung). Bundle `js/` ist gitignored, kein Commit nötig.
- Alle `frontend/tests/*.check.mjs` grün (adult, api, backup, origin, playtime, roles, route).
- `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed.
- `uv run pytest -q -m "not docker"`: 2486 passed, 44 deselected.
- Kein `v-html`, keine Gedankenstriche, kein "public"/"visibility" in den geänderten Dateien.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Doppelter Punkt in der Einladen-Warnung**
- **Found during:** Task 3
- **Issue:** Backend-Meldungen (z. B. 409 "Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln.") enden mit Punkt, die UI-SPEC-Vorlage "{detail}. Du kannst ..." ergäbe "Regeln.. Du".
- **Fix:** adultInviteWarning entfernt Schlusspunkte am Detail; zusätzlicher Fall im Prüfskript.
- **Files modified:** frontend/src/adult.js, frontend/tests/adult.check.mjs
- **Commit:** f033189

**2. [Rule 3] Gedankenstrich-Regex im Prüfskript als Escape**
- Das Werkzeug hatte `–—` als echte Zeichen geschrieben; ersetzt durch Escape-Sequenzen, damit die Datei selbst keine Gedankenstriche enthält. Commit f033189.

Sonst Plan wie geschrieben. Absatz 4 entfällt im Einladen-Dialog, weil dort kein has_rules vorliegt (siehe decisions).

## Threat Flags

Keine neue Angriffsfläche: einzige neue Route-Nutzung ist das in 06-04 abgesicherte `POST /api/players/adult` (require_verwalter). T-06-21 (Bestätigung mit Warnung, variant warning), T-06-22 (nur Textinterpolation) und T-06-23 (Warn-NoteCard je Konto) sind umgesetzt.

## Known Stubs

Keine.

## Self-Check: PASSED

- FOUND: frontend/src/adult.js, frontend/tests/adult.check.mjs
- FOUND commits: 3a92af8, a9386c2, 937da86, f033189

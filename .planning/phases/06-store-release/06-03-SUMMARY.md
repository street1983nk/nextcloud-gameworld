---
phase: 06-store-release
plan: 03
subsystem: frontend
tags: [frontend, ui-spec-b1, roles]
requires: ["06-02"]
provides:
  - "frontend/src/roles.js: scopeHint, groupAddedText, groupRemovedText, groupUnknownText, loadErrorText, SECTION_HINT, CHILDREN_WARNING, BOUNDARY_TEXT, ONLY_ADMIN_TEXT, NC_ADMIN_ONLY_TEXT, SEARCH_DOWN_TEXT, NO_SCOPE_TEXT"
  - "frontend/src/api.js: getVerwalterGroups, addVerwalterGroup, removeVerwalterGroup, searchGroups"
  - "VerwalterGroupsSection.vue (B1-Abschnitt, nur bei me.nc_admin === true)"
  - "ParentView und AttemptsView mit Prop me; ParentView emittiert reload-me, App.vue lädt /api/me neu"
  - "InviteDialog mit Prop me und Einladungsgrenze (.invite__scope) für Gruppen-Verwalter"
affects: [06-04, 06-05, 06-13]
tech-stack:
  added: []
  patterns:
    - "Reine Textfunktionen in roles.js, Prüfskript mit eigenen Soll-Literalen (unabhängige Gegenprobe)"
    - "Admin-Abschnitt per v-if auf me.nc_admin; 403 meldet forbidden, App lädt /api/me neu, Hinweis bleibt in ParentView stehen"
key_files:
  created:
    - frontend/src/roles.js
    - frontend/tests/roles.check.mjs
    - frontend/src/components/VerwalterGroupsSection.vue
  modified:
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
    - frontend/src/views/AttemptsView.vue
    - frontend/src/App.vue
    - frontend/src/components/InviteDialog.vue
decisions:
  - "403 im Verwalter-Gruppen-Abschnitt: ParentView merkt sich das, zeigt NC_ADMIN_ONLY_TEXT als error-NoteCard an der Stelle des Abschnitts und lässt App.vue /api/me neu laden (Event reload-me); so verschwindet der Abschnitt, die Meldung bleibt lesbar"
  - "Anzeigenamen der Verwalter-Gruppen kommen nur aus der Gruppensuche (die Listen-API liefert IDs); unbekannt = nur ID, keine Zusatzabfrage"
  - "Fokus nach Hinzufügen/Entfernen: Fehler-NoteCard (tabindex -1), sonst Knopf Gruppe hinzufügen"
metrics:
  duration: "ca. 25 min"
  completed: 2026-10-24
  tasks: 3
  files: 8
---

# Phase 06 Plan 03: Verwalter-Gruppen-Abschnitt und Einladungsgrenze Summary

UI-Baustein B1: NC-Admins pflegen die Verwalter-Gruppen per Suche und Sofort-Speichern (admin fest mit Marke "immer dabei", Warnung "keine Gruppe mit Kindern"), Gruppen-Verwalter sehen im Einladen-Dialog, aus welchen Gruppen sie einladen dürfen; alle Texte wörtlich aus 06-UI-SPEC B1 in roles.js.

## Tasks

| Task | Name | Commit | Dateien |
|------|------|--------|---------|
| 1 (RED) | Prüfskript B1-Texte | e719bf8 | frontend/tests/roles.check.mjs |
| 1 (GREEN) | roles.js und API-Aufrufe | 68bad36 | frontend/src/roles.js, frontend/src/api.js |
| 2 | VerwalterGroupsSection.vue, me an ParentView | 7ded3b4 | VerwalterGroupsSection.vue, ParentView.vue, App.vue |
| 3 | Einladungsgrenze im Einladen-Dialog | c25f115 | InviteDialog.vue, ParentView.vue, AttemptsView.vue, App.vue |

## Umsetzung

- Abschnitt nach `<ReviewSetting />`: `<VerwalterGroupsSection v-if="me?.nc_admin === true" @forbidden=... />`, `margin-top: 32px`, h3, Hinweis, Warn-NoteCard, Liste (admin plus NcChip tertiary "immer dabei" ohne Knopf; weitere Gruppen bold mit Anzeigename in 0.9em maxcontrast, falls bekannt und abweichend; "Entfernen" variant error mit aria-label "Gruppe {gid} entfernen", ohne Bestätigung), Leerzustand, Hinzufügen-Zeile (NcSelect mit Serversuche, 300 ms Verzögerung, seq-Zähler, admin und gewählte ausgeblendet; "Gruppe hinzufügen" primary, gesperrt ohne Auswahl/beim Speichern, NcLoadingIcon 20), Grenz-Erklärung immer sichtbar, Erfolg in aria-live polite.
- Zustände: Laden (NcLoadingIcon statt Liste und Zeile), Ladefehler warning, 422 "gibt es in Nextcloud nicht" -> groupUnknownText, 403 -> NC_ADMIN_ONLY_TEXT plus forbidden, sonstiger Fehler errorText (Liste bleibt Serverstand), Suche gestört warning SEARCH_DOWN_TEXT. Liste nach jeder Aktion aus der Serverantwort.
- 390 px: ID `overflow-wrap: anywhere`, Entfernen `margin-inline-start: auto`, unter 480 px NcSelect `flex: 1 1 100%` und Knopf volle Breite.
- InviteDialog: nur bei `me?.nc_admin === false` `<p class="invite__scope">` mit scopeHint(invite_groups) (alphabetisch per localeCompare de), sonst info-NoteCard NO_SCOPE_TEXT. 403-Texte des Backends laufen unverändert im bestehenden Muster `{label}: {detail}`. Fehlender Anzeigename: Option zeigt die Konto-ID.

## Gates

- `npm run build` grün (nur bestehende Chunk-Größen-Warnung)
- `node frontend/tests/*.check.mjs`: api, backup, origin, playtime, roles, route grün
- `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed
- `uv run pytest -m "not docker" -q`: 2392 passed, 44 deselected (vor dem kleinen AttemptsView-Nachtrag; danach Build, roles.check und test_frontend_privacy erneut grün)
- `grep -c v-html VerwalterGroupsSection.vue` = 0; keine neuen Vorkommen von public/visibility unter frontend/src (bestehende `document.visibilityState` sind vom Strukturtest erlaubt)
- Python nicht angefasst, daher keine ruff/pyright/vulture-Läufe nötig

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] Einladungsgrenze auch im Einladen-Dialog der Versuchsseite**
- **Found during:** Task 3
- **Issue:** InviteDialog wird auch in AttemptsView geöffnet; ohne me hätten Gruppen-Verwalter dort keinen Grenz-Hinweis gesehen.
- **Fix:** AttemptsView bekommt Prop me (App.vue reicht `:me="me"` durch) und gibt sie an InviteDialog weiter.
- **Files modified:** frontend/src/views/AttemptsView.vue, frontend/src/App.vue
- **Commit:** c25f115

**2. [Rule 1 - Plan-Annahme] Akzeptanzkriterium ":me=\"me\" mindestens zwei Zeilen (PlayerView und ParentView)"**
- PlayerView bekommt me als `:user="me"`, nicht als `:me`. PlayerView blieb unverändert; die zwei Treffer kommen jetzt aus ParentView und AttemptsView.

**3. [Rule 2] 403-Meldung bleibt sichtbar**
- Würde nur /api/me neu geladen, verschwände der Abschnitt samt Meldung sofort. ParentView zeigt deshalb nach forbidden NC_ADMIN_ONLY_TEXT als error-NoteCard an derselben Stelle (Commit 7ded3b4).

**4. TDD-Reihenfolge**
- roles.js und Prüfskript entstanden im selben Schritt; das Prüfskript ist trotzdem als eigener test-Commit vor dem feat-Commit eingecheckt. Ein echter roter Lauf wurde nicht protokolliert.

## TDD Gate Compliance

test-Commit e719bf8 vor feat-Commit 68bad36 vorhanden (siehe Abweichung 4).

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus. T-06-13: Gruppen-IDs, Anzeigenamen und invite_groups nur per Textinterpolation, kein v-html (grep 0). T-06-14: UI-Weiche ist reine Komfortfunktion, Sperre bleibt require_nc_admin. T-06-15: test_frontend_privacy grün.

## Self-Check: PASSED

- FOUND: frontend/src/roles.js, frontend/tests/roles.check.mjs, frontend/src/components/VerwalterGroupsSection.vue
- FOUND: Commits e719bf8, 68bad36, 7ded3b4, c25f115

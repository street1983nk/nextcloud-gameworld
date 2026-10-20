---
phase: 03-zugang-und-rollen
verified: 2026-10-20T00:00:00Z
status: passed
score: 5/5 Erfolgskriterien verifiziert
overrides_applied: 0
---

# Phase 3: Zugang und Rollen, Verifikationsbericht

**Phasenziel:** Nur Eingeladene können spielen; Kinder spielen, Eltern verwalten, und jeder Spieler findet selbst in seine Welt.
**Verifiziert:** 2026-10-20
**Status:** passed
**Re-Verifikation:** Nein, Erstverifikation

## Zielerreichung

| # | Erfolgskriterium | Status | Beleg im Code und im Lauf |
|---|------------------|--------|---------------------------|
| 1 | Eltern laden NC-Benutzer und -Gruppen ein; Luanti-Accounts werden automatisch provisioniert | VERIFIZIERT | `api/invites.py`: POST `/worlds/{id}/invites` (kind user/group), validiert gegen das Nextcloud-Verzeichnis (422 bei unbekanntem Ziel). `provisioner/luanti_auth.py`: SRP-6a-Verifier, nur Verifier im Volume. `access_mod.py` setzt ihn per `core.set_player_password`. Gruppen-Mitglieder lazy über `AccessService.my_worlds`. Live: acceptance K1 grün |
| 2 | Nicht eingeladener Name scheitert serverseitig am Join | VERIFIZIERT | Welt-Mod `gameworld_access`: `register_on_prejoinplayer` lehnt Namen ohne Eintrag in `gameworld_access.txt` ab (vor Auth), Datei root/0444, Kick im 5-s-Takt nach Widerruf, Sperre nach 5 Fehlversuchen. Live: UDP-Prober, Fremder abgewiesen mit "nicht eingeladen", Eingeladener `auth_accept`, falsches Passwort `WRONG_PASSWORD`, nach Entfernen abgelehnt (K2) |
| 3 | Jeder Eingeladene sieht Verbindungsinfo | VERIFIZIERT | `api/me.py` `/my/worlds` liefert host, port, player_name, password, Status. `PlayerView.vue` rendert das. Live K3: Port gleich `docker port`, Daten gleich Verwalter-Ansicht, Join mit genau diesen Daten gelingt |
| 4 | Kind-Ansicht nur eigene Welten; Verwaltung serverseitig gesperrt | VERIFIZIERT | `/my/worlds` filtert auf `profile.user_id` aus signierter AppAPI-Anfrage (nie aus dem Browser). Alle Router `invites`, `worlds`, `setup_check` tragen `Depends(require_verwalter)` (403 bzw. 503 bei NC-Ausfall, nie Verwalterrecht). Zusätzlich info.xml: USER nur `^/js/.*`, `^/img/.*`, `^/api/me$`, `^/api/my/.*`, Rest `^/api/.*` ADMIN; Reihenfolge korrekt (spezifische vor Auffangmuster). Live K4: fünf Verwaltungsaufrufe als Kind nicht 200, keine fremden Zugänge in der Antwort (mit Positivkontrolle) |
| 5 | Rollen aus NC-Gruppen, keine eigene Benutzerverwaltung | VERIFIZIERT | `access/roles.py`: Verwalter genau bei Gruppe `admin`, 30-s-Cache nur für Erfolge. Frontend-Weiche in `App.vue` nach `/api/me`. SQLite-Tabelle `players` nur nc_user, player_name, rotation; Passwörter abgeleitet, nicht gespeichert. Live K5: Rollenwechsel über Gruppe hin und zurück, Passwort nicht in der DB (Positivkontrolle), statisch keine Kontenverwaltung |

**Score:** 5/5

## Eigene Läufe des Verifiers

| Prüfung | Befehl | Ergebnis |
|---------|--------|----------|
| Testsuite | `uv run pytest -q -m "not docker"` | 573 passed, 21 deselected (Docker-e2e) |
| Live-Abnahme | `sh scripts/dev/acceptance-phase3.sh` | Exit 0, 75 von 75 Prüfungen, darin Regression Phase 1 84/84 und Phase 2 104/104, Aufräumen ohne Reste |

Vermerk zum Testlauf: Die Docker-e2e-Marker wurden nicht ausgeführt, weil `games/mineclone2-39534.zip` fehlt (Ordner `games` nicht vorhanden). Die Docker-nahen Pfade sind durch die Live-Abnahme abgedeckt, die auf dem echten Dev-Stack läuft. Die SUMMARY nennt 590 passed inklusive der 17 bis 21 Docker-Tests; die Differenz ist durch die Deselektion erklärt.

## Anforderungen

| Anforderung | Status | Begründung |
|-------------|--------|------------|
| ZUGANG-02 | ERFÜLLT | Einladung und automatische Provisionierung, K1 |
| ZUGANG-03 | ERFÜLLT | Whitelist-Durchsetzung im Spielserver-Mod, K2 per UDP-Prober |
| ZUGANG-04 | ERFÜLLT | Verbindungsinfo in Kind-Ansicht, K3 |
| ROLLE-01 | ERFÜLLT | Doppelte Sperre ADMIN-Route plus `require_verwalter`, K4 |
| ROLLE-02 | ERFÜLLT | Rollen nur aus NC-Gruppe admin, K5 |

Keine verwaisten Anforderungen. Die Markierung Complete in REQUIREMENTS.md ist gerechtfertigt.

## Anti-Pattern-Prüfung

Keine TBD/FIXME/XXX-Marker als Blocker gefunden, keine Stub-Routen. 03-REVIEW.md: 0 Critical; die zwei Warnings (WR-01, WR-02) sind in 7126f94 und 0760c7f behoben und im Code nachvollziehbar (WR-02: `my_worlds` wirft `SecretUnavailableError` statt ein ungültiges Passwort zu zeigen). Info-Findings IN-01 bis IN-07 bleiben offen und sind laut Auftrag keine Gaps.

## Bekannt offen, nicht als Gap gewertet

- Live-Join mit echtem Luanti-Client (kein Client installiert, Owner-deferred). Ersatzbeleg: UDP-Prober mit echtem SRP-Handshake gegen den echten Luanti-Server, Golden Vector gegen Luanti 5.17.0.
- Kick laufender Spieler nach Widerruf mit echtem Client (A7, Owner-offen); der Mod-Code kickt im 5-s-Takt.
- Neuinstallations-Randfall Geheimnisverlust (in docs/install.md dokumentiert).

## Menschliche Prüfung

Keine neuen Punkte. Owner-Abnahme per Playwright am 20.10.2026 ("Abgenommen"), Entscheide A6, A8, A9 im 03-07-SUMMARY.

## Zusammenfassung

Das Phasenziel ist im Code erreicht: Durchsetzung sitzt im Spielserver, Rollen kommen allein aus Nextcloud, Verwaltung ist doppelt gesperrt, und der Spieler findet über `/api/my/worlds` selbst zu seiner Welt. Keine Gaps.

---

_Verifiziert: 2026-10-20_
_Verifier: Claude (gsd-verifier)_

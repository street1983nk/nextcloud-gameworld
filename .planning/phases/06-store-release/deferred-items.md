# Phase 06: zurückgestellte Befunde

## Aus 06-12 (Abnahme über HaRP, 24.10.2026)

### Talk-Raum eines frisch (wieder) ernannten Verwalters bleibt bis zum Schnappschuss allein

- Beobachtet in der HaRP-Abnahme K7 (zweiter Lauf): gw-alt wird per `occ group:adduser lehrkraefte` wieder Verwalter und legt sofort eine Welt an. `ensure_room` legt den Raum als gw-alt an, `_sync_locked` nimmt aber nur Konten aus dem Verwalter-Schnappschuss (`_admins()`, höchstens alle 60 s aufgefrischt) als handelnde Kandidaten. gw-alt steht dort noch nicht, admin ist noch kein Teilnehmer, der Abgleich bricht ohne Änderung ab. Bis zum nächsten Schnappschuss plus Talk-Abgleich (5 min) ist gw-alt allein im Raum.
- Wird gw-alt in diesem Fenster gelöscht, greift der Sperrfall richtig (Log "hat keinen Moderator mehr, neuer Raum wird angelegt", neuer Raum für admin erreichbar, `orphaned_token` gemeldet). Kein Datenleck, kein Kind im Raum ohne Verwalter; nur der alte Raum bleibt als verwaist stehen.
- Möglicher Fix: In `ensure_room` den eben per `require_verwalter` frisch bestätigten Anleger als ersten Kandidaten für den ersten Abgleich zulassen oder vor dem Anlegen `refresh_admins(acting, force=True)` aufrufen. Sicherheitsrelevant (CR-01, nur bestätigte Konten handeln), darum nicht nebenbei in 06-12, sondern mit deep Review (Owner-Regel Gameworld).
- Die Abnahme wartet in K7 jetzt, bis admin Moderator ist, und prüft damit den regulären Übernahmeweg (Token bleibt gleich).

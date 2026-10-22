# Deferred Items Phase 4.1

## Aus 04.1-06

- **Webhook-Ankunft im Dev-Stack nicht belegbar:** AppAPI trägt die Bot-URL mit der Adresse des registrierenden Requests ein (`http://localhost:8091/ocs/v2.php/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot`). Im Nextcloud-Container lauscht auf `localhost:8091` niemand (`curl` im Container: 000, `http://localhost` 200). Talk zählt keinen Fehler hoch (`error_count` 0, `postAsync`). Eine echte Kindernachricht erreicht `/talk/bot` darum im Dev nie. Belegt sind: Route und Verwerfen (Unit-Tests), AppAPI weist eine gefälschte Signatur mit 404 ab, der Inhalt steht nie im ExApp-Log. Prüfpunkt Phase 6 (HaRP, Instanz mit erreichbarer eigener URL), zusammen mit Annahme A4.
- **Timing-Test unter Last:** `tests/test_notify_loop.py::test_notify_forever_survives_errors` (aus 04.1-04, schläft 0,1 s und erwartet zwei Durchläufe) schlug einmal fehl, als zwei Suiten parallel liefen. Allein und im seriellen Gesamtlauf grün. Nicht durch 04.1-06 verursacht, nicht angefasst.
- **A3 visuell offen:** Ob Talk `\_` und `\(` in Bot-Nachrichten als Markdown-Maskierung rendert (statt Backslash zu zeigen), ist per API nicht prüfbar. Gehört in die gemeinsame Playwright-Abnahme 04.1-09.

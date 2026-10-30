# 06-13 Task 2: Zwischenstand (30.10.2026)

Task 2 ist ausgeführt; Task 3 und Task 4 (Owner-Checkpoints) sind offen. Kein SUMMARY.

## Commits

- fd91e66 fix(06-13): world table no longer grows past the page
- a230442 fix(06-13): world name rule in English and French
- 95ea205 feat(06-13): screenshot demo data and capture per language
- 2084df0 docs(06-13): screenshots in German, English and French
- 088beee docs(06-13): language lines, cross-promotion and forum thread draft

## Bilder (PNG-Kopf, Breite x Höhe)

| Motiv | DE (-v1) | EN (-v1-en) | FR (-v1-fr) |
|---|---|---|---|
| worlds | 1280x800 | 1280x800 | 1280x800 |
| invite | 1280x800 | 1280x800 | 1280x800 |
| kids-view | 1280x800 | 1280x800 | 1280x800 |
| backups | 1280x800 | 1280x800 | 1280x800 |
| playtime | 1280x800 | 1280x800 | 1280x800 |
| mobile | 390x844 | 390x844 | 390x844 |

Sichtprüfung je Bild (Read): nur Demo-Konten und Demo-Welten, Passwörter maskiert, keine Tokens,
keine IP, keine Adressleiste (Spieleradresse nextcloud.example.org). Einziger deutscher Rest in
EN/FR: der Ordnerpfad "Gameworld/Sicherungen" im Sicherungen-Dialog. Das ist der echte
Ordnername (backup/naming.py BACKUPS_ROOT), kein Wörterbuchfehler; Entscheid für den Owner in
Task 3 (Ordner je Sprache wäre eine Produktänderung).

DE-Satz neu aufgenommen: die Weltzeile zeigt seit 06-24 die Sprachauswahl, und der Tabellen-Fix
(fd91e66) ändert das Layout. Namen bleiben -v1.

## Abweichungen

- [Rule 1] Welttabelle lief bei 1280 px über den Seitenrand (Zellen erben nowrap; Hinweis unter
  der Sprachauswahl und Fehlerkarten blieben einzeilig). Fix fd91e66, Bundle neu gebaut.
- [Rule 1] NAME_ERROR (Weltname-Regel) kam für en/fr-Konten deutsch zurück; fehlte in beiden
  Katalogen und in der Abdeckungsprüfung. Fix a230442, gefunden beim FR-Lauf.
- FR-Weltname "L'île aux aventures" ist nach der Namensregel unzulässig (kein Apostroph);
  stattdessen "Île aux aventures".
- Gruppen- und Konten-IDs sind in der Oberfläche sichtbar (Einladen-Hinweis, Spielernamen). Darum
  Erwachsene, Gruppen und Welten je Sprache: mama/oma, mom/grandma, maman/mamie;
  familie/eltern, family/parents, famille/parents. mia und leo gemeinsam.
- Cross-Promo-Sätze im Französischen mit normalem Leerzeichen vor ":" wie der Bestand in
  info.xml und store-listing.md (dort kein geschütztes Leerzeichen).
- Playwright lief über scripts/dev/screenshot-capture.mjs (Node-Playwright 1.63 aus dem
  npx-Cache), wie in Task 1.

## Cross-Promo (D-28), wörtlich

- EN: From the same developer: Findling Search (full text search in the Nextcloud search bar) and MCP Connector (connects MCP assistants to Nextcloud).
- DE: Vom selben Entwickler: Findling Search (Volltextsuche über die Nextcloud-Suchleiste) und MCP Connector (verbindet MCP-Assistenten mit Nextcloud).
- FR: Du même développeur : Findling Search (recherche plein texte dans la barre de recherche de Nextcloud) et MCP Connector (connecte les assistants MCP à Nextcloud).

Quelle: apps.nextcloud.com/apps/findling und /apps/mcp_connector (Beschreibung, erster Punkt), nur gelesen.

## Kontosprache admin

Vorher de_DE, nach jedem Lauf de_DE (vom Skript gelesen und wiederhergestellt).

## Tests und Gates

- tests/test_info_xml.py + tests/test_docs.py: 63 passed
- pytest -m "not docker": 2872 passed, 52 deselected
- ruff check, ruff format --check, pyright (latest, venv), vulture: grün

## Für Task 3 offen

- Dev-Stack läuft: http://localhost:8091, Gameworld registriert (manual_install, Port 10040).
- Konten: admin, gw-lehrer (lehrkraefte, klasse; Kontosprache nicht gesetzt), gw-kind, Demo-Konten.
  lehrkraefte ist bereits Verwalter-Gruppe (Schritt 1 erst entfernen oder mit anderer Gruppe zeigen).
- Demo-Welten DE laufen, EN/FR gestoppt; zwei fremde Dev-Welten (Browser Minetest/VoxeLibre) laufen.
- Fehlt: Test-Orphan für "Reste früherer Installationen" (Schritt 5) und ein Ex-Verwalter-Talk-Raum
  (Schritt 6).

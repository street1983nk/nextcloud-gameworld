# 06-13 Task 3: gemeinsame Playwright-Abnahme (30.10.2026)

Owner-Antwort wörtlich: "Abgenommen"

Für das SUMMARY übernehmen.

## Schritte

| Schritt | Ergebnis |
|---|---|
| 1 Verwalter-Gruppen | lehrkraefte entfernt und wieder hinzugefügt, Erfolgstexte |
| 2 gw-lehrer | kein Verwalter-Gruppen- und kein Reste-Abschnitt; Einladen-Hinweis "Du kannst Konten aus deinen Gruppen einladen: klasse, lehrkraefte. ..." |
| 3 Erwachsen-Schalter | Marken Erwachsen, Bestätigungsdialog mit Folgen-Text beim Einschalten, Ausschalten ohne Dialog |
| 4 Als erwachsen einladen | Bestätigung vor dem Einladen; abgebrochen, nichts eingeladen |
| 5 Reste | Test-Orphan (Container + Volume, Instanz abnahme13-orphan) mit je eigenem Dialog entfernt; fremde a60510fd-Volumes nicht angefasst |
| 6 Talk Ex-Verwalter | Testwelt Talktest von gw-lehrer, lehrkraefte entfernt, Hinweis + "Raum neu anlegen" mit Bestätigung, neuer Raum; Welt danach gelöscht, lehrkraefte wieder Verwalter-Gruppe |
| 7 Sprachen | Prüflauf aller Ansichten und Dialoge als admin, gw-lehrer, mia in de/en/fr (71 Punkte, Wortdetektor aus den Wörterbüchern mit Positivkontrolle) plus Stichproben gelesen |
| 8 Sprache je Welt | Hinweis "Die neue Sprache gilt ab dem nächsten Start der Welt." bei laufender Welt |
| 9 390 px | Weltentabelle scrollte waagerecht (seit Phase 3); Owner-Entscheid Kartenansicht |
| 10 Bilder | alle 18 neu aufgenommen und gesichtet |

## Fixes während der Abnahme (alle lokal, Owner-Entscheide in Klammern)

- ee503ec Sprachauswahl in der Weltentabelle abgeschnitten (Spalte breiter)
- 8eb994c Servertexte nach Sprachwechsel 30 s in alter Sprache (Header X-Gameworld-Language)
- 460f8b0 pydantic- und Starlette-Meldungen englisch bei de/fr ("Sprachfehler sind no go")
- a324c21 Spielzeitliste 12 s als gw-lehrer (Anzeigenamen parallel)
- 8007712 Weltenliste 7 s (Besuchs-Abgleich im Hintergrund)
- 09a26aa Kartenansicht unter 480 px (Kartenansicht)
- a8a8d64 Sicherungsordner und Zusatz je Kontosprache ("Sollen übersetzt werden")
- 3ef6a1b Größen unter 1 MB in KB (KB unter 1 MB)
- de2eaf1 18 Bilder neu

## Für den Volltest vor dem Release (Owner 30.10.)

- Luanti-Client-Begriffe der Kinderanleitung in de/fr mit echtem Client prüfen
- Erwachsen-Marke hinkt 1 bis 2 s nach dem Umschalten
- Talk-Hinweis Ex-Verwalter erscheint erst nach Neuladen (Talk-Stand wird nicht gepollt)
- Luanti 5.18.0 seit 29.10. stabil: Wechsel später, nicht Teil von v1

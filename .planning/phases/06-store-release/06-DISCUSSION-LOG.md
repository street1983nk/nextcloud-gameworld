# Phase 6: Store-Release - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md , this log preserves the alternatives considered.

**Date:** 2026-10-24
**Phase:** 6-store-release
**Areas discussed:** Verwalter-Gruppen (ROLLE-03), Erwachsen-Schalter (ROLLE-04), Store-Auftritt, Release-Mechanik

---

## Verwalter-Gruppen (ROLLE-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Mitglieds-/Subadmin-Gruppen | NC-Rechte wie vorgesehen, Grenze in der UI erklärt | ✓ |
| App-Konto-Lookup (volle Sicht) | ExApp-Systemrechte, umgeht NC-Sichtbarkeitsmodell | |
| Du entscheidest | | |

**User's choice:** Mitglieds-/Subadmin-Gruppen

| Option | Description | Selected |
|--------|-------------|----------|
| Gameworld-UI, Admin-Abschnitt | nur für echte NC-Admins sichtbar | ✓ |
| Nur occ/app-config | | |
| Beides | | |

**User's choice:** Gameworld-UI, Admin-Abschnitt

| Option | Description | Selected |
|--------|-------------|----------|
| Alle sehen alles | Familienmodell bleibt, Besitzer-Modell erst v2 | ✓ |
| Besitzer-Modell jetzt | worlds.owner_uid, größerer Umbau | |

**User's choice:** Alle sehen alles (v1)

| Option | Description | Selected |
|--------|-------------|----------|
| Alle Verwalter | dürfen globale Einstellungen bedienen | ✓ |
| Nur NC-Admins | | |

**User's choice:** Alle Verwalter

---

## Erwachsen-Schalter (ROLLE-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Global je Konto | ein Zustand pro Person | ✓ |
| Je Welt-Einladung | | |

**User's choice:** Global je Konto

| Option | Description | Selected |
|--------|-------------|----------|
| Einladen-Dialog + Spielerliste | | ✓ |
| Nur Spielerliste | | |

**User's choice:** Einladen-Dialog + Spielerliste

| Option | Description | Selected |
|--------|-------------|----------|
| Bestätigungsdialog | Folgen in Klartext, nur beim Einschalten | ✓ |
| Nur Hinweistext | | |

**User's choice:** Bestätigungsdialog

| Option | Description | Selected |
|--------|-------------|----------|
| Sofort | wirkt auch mitten im Spiel | ✓ |
| Ab nächstem Beitritt | | |

**User's choice:** Sofort

---

## Store-Auftritt

| Option | Description | Selected |
|--------|-------------|----------|
| Englisch + Deutsch | | |
| 8-sprachig wie Findling | | |
| Nur Englisch | | |
| Other: Englisch, Deutsch, Französisch | Owner-Freitext | ✓ |

**User's choice:** EN + DE + FR (Freitext)

| Option | Description | Selected |
|--------|-------------|----------|
| Voller Satz 5-6 | Weltliste, Einladen, Kinder-Ansicht, Sicherungen, Spielzeit, Handy | ✓ |
| Kleiner Satz 3 | | |

**User's choice:** Voller Satz 5-6

| Option | Description | Selected |
|--------|-------------|----------|
| Eigener Abschnitt oben | "Was diese App darf und warum" + privacy.md | ✓ |
| Abschnitt unten + privacy.md | | |

**User's choice:** Eigener Abschnitt oben

| Option | Description | Selected |
|--------|-------------|----------|
| Englisch, DE-Fassung verlinkt | | ✓ |
| Nur Englisch | | |
| Deutsch zuerst | | |

**User's choice:** Englisch, DE-Fassung verlinkt

---

## Release-Mechanik

| Option | Description | Selected |
|--------|-------------|----------|
| 1.0.0 | v1 feature-komplett | ✓ |
| 0.9.0 Beta zuerst | | |

**User's choice:** 1.0.0

| Option | Description | Selected |
|--------|-------------|----------|
| ghcr.io | am Repo, Build per GitHub Actions | ✓ |
| Docker Hub | | |

**User's choice:** ghcr.io

| Option | Description | Selected |
|--------|-------------|----------|
| Container weg, Volumes bleiben | Orphan-Kommando räumt gezielt | ✓ |
| Alles löschen nach Rückfrage | | |
| Du entscheidest | | |

**User's choice:** Container weg, Volumes bleiben

| Option | Description | Selected |
|--------|-------------|----------|
| Dienstältester Verwalter | deterministisch, Reconciler prüft | ✓ |
| Nächster aktiver Verwalter | | |
| Du entscheidest | | |

**User's choice:** Dienstältester Verwalter

---

## Claude's Discretion

- Technik des Gruppen-Lookups (OCS, Caching), sofortige Wirkung des Erwachsen-Schalters
- Form des Orphan-Kommandos (occ vs. API+UI)
- Setup-Check-Texte, AIO-Testaufbau, Store-Kategorie/Schlagworte

## Deferred Ideas

- Besitzer-Modell je Welt (Lehrkraft sieht nur eigene) , Schul-Meilenstein v2
- Weitere Listing-Sprachen , nach Nachfrage

## Rahmen (Owner-Vorgaben während der Discussion)

- Zertifikats-PR #1364: warten, NICHT nachhaken (Owner 24.10.2026)

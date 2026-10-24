# Phase 6: Store-Release - Pattern Map

**Erstellt:** 24.10.2026
**Analysierte Dateien (neu/geändert):** 46
**Analoge gefunden:** 42 / 46 (Image/CI/Store-Analoge aus den Schwester-Repos `nextcloud-mcp-connector` und `nextcloud-search` (Findling), beide ExApps desselben Owners)

Hinweis zur Lesart: Zeilenangaben beziehen sich auf den Stand vom 24.10.2026. "Analog" heißt: Muster übernehmen, nicht die Datei kopieren. Wo ein Muster aus einem Schwester-Repo kommt, ist der absolute Pfad angegeben.

---

## File Classification

### A. Rollen-Kern ROLLE-03 (höchste Sorgfalt, Negativtests Pflicht)

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `src/gameworld/access/roles.py` (M) | middleware/guard | request-response | sich selbst (`require_verwalter`, `RoleService`) | exact |
| `src/gameworld/api/admin.py` (NEU: Verwalter-Gruppen, Gruppensuche, Orphans) | controller | request-response CRUD | `src/gameworld/api/talk.py` + `src/gameworld/api/invites.py` (`/settings`) | role-match |
| `src/gameworld/api/me.py` (M: `nc_admin`, `invite_groups`) | controller | request-response | sich selbst (`MeOut`, `me()`) | exact |
| `src/gameworld/access/service.py` (M: Einladungs-Umfang, `_resolve`, purge nur NC-Admin) | service | CRUD | sich selbst (`invite_user`, `_resolve`, `purge_missing_accounts`) | exact |
| `src/gameworld/access/directory.py` (M: ggf. Gruppensuche, Subadmin) | service/adapter | request-response | sich selbst (`NcDirectory.group_members`) | exact |
| `src/gameworld/playtime/service.py` (M: Schnappschuss je Gruppe) | service | batch | sich selbst (`refresh_admins`, `verify_admins`) | exact |
| `src/gameworld/notify/loop.py` (M: acting nur NC-Admin für purge) | service (Hintergrund) | event-driven | sich selbst (`verify_once`, `run_hooks`, `MAINTENANCE`) | exact |
| `src/gameworld/main.py` (M: `admin.router`) | config | - | sich selbst Z. 119-129 | exact |
| `appinfo/info.xml` (M: `^/api/.*` USER, 1.0.0, max 35, EN/DE/FR) | config | - | sich selbst + `C:\Users\Student\nextcloud-mcp-connector\appinfo\info.xml` | exact |
| `pyproject.toml` (M: `version = "1.0.0"`) | config | - | Lockstep-Test `tests/test_info_xml.py` | exact |
| `tests/test_info_xml.py` (M) | test | - | sich selbst | exact |
| `tests/test_route_guards.py` (NEU, Strukturtest aller `/api/`-Routen) | test | - | `tests/test_roles.py` (parametrisierte 403-Prüfung) | role-match |
| `tests/test_verwalter_groups.py` (NEU) | test | request-response | `tests/test_roles.py`, `tests/conftest.py` FakeDirectory | role-match |
| `tests/conftest.py` (M: FakeDirectory je Gruppe/Subadmin, FAKE_PROFILES Lehrer) | test fixture | - | sich selbst Z. 433-534 | exact |

### B. Erwachsen-Schalter ROLLE-04

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `src/gameworld/worlds/store.py` (M: Schema 8 `adults`, `verwalter_seen`, ggf. `verwalter_snapshot`, `ACCOUNT_TABLES`) | model/migration | CRUD | sich selbst (`SCHEMA`, `migrate`, `ACCOUNT_TABLES`, `set_meta`) | exact |
| `src/gameworld/playtime/engine.py` (M: `frei = admins | adults`) | service (rein) | transform | sich selbst (`render` Z. 187-224, `book` Z. 153-185) | exact |
| `src/gameworld/playtime/service.py` (M: `set_adult`, `_snapshot` mit `adult`) | service | CRUD | `set_child` / `_set_sync` Z. 383-394, 522-528 | exact |
| `src/gameworld/api/invites.py` (M: `POST /api/players/adult`, `PlayerOut.adult/verwalter/has_rules`) | controller | request-response | `reset_password` Z. 257-263 | exact |
| `src/gameworld/api/playtime.py` (M: `ChildOut.adult`) | controller | request-response | `_child_out` Z. 269-280 | exact |
| `src/gameworld/api/me.py` (M: `/api/my/playtime` frei für Erwachsene) | controller | request-response | `my_playtime` Z. 183-191 | exact |
| `tests/test_adult_flag.py` (NEU) | test | - | `tests/test_forget_account.py` (Fixtures Z. 57-83) | role-match |
| `tests/test_forget_account.py` (M: `adults` wird vergessen) | test | - | sich selbst (`ACCOUNT_TABLES`-Import Z. 29) | exact |

### C. Talk-Übernahme D-16/D-19

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `src/gameworld/talk/service.py` (M: Übernahme im Abgleich, "Raum neu anlegen", Sperrfall) | service | event-driven/batch | sich selbst (`_candidates`, `_acting_members`, `reconcile_all`, `status`) | exact |
| `src/gameworld/api/talk.py` (M: `orphaned_token`, Route Neuanlage) | controller | request-response | sich selbst (`_read_only`, Z. 75-92) | exact |
| `tests/test_talk_service.py` (M) | test | - | sich selbst + `FakeTalkRooms` (conftest Z. 303) | exact |

### D. Lebenszyklus, Orphans, Setup-Check, AR-23

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `src/gameworld/lifecycle.py` (M: Deaktivieren stoppt+entfernt Welt-Container) | lifecycle hook | event-driven | sich selbst (zweiter try-Block Talk-Bot Z. 51-61) | exact |
| `src/gameworld/worlds/service.py` (M: `teardown_all` für Deaktivieren) | service | batch | `_boot_reconcile_sync` Z. 1308-1326, `_delete_world_sync` Z. 1404-1416 | exact |
| `src/gameworld/provisioner/client.py` (M: `list_orphans`, `remove_orphan_container`, `remove_orphan_volume`) | adapter (Docker) | request-response | `_list_managed` Z. 449-472, `remove_world` Z. 399-414, `_used_host_ports` Z. 431-438 | exact |
| `src/gameworld/provisioner/setup_check.py` (M: Namensauflösung/Abgelehnt/Timeout getrennt, feste Doku-URL) | utility | request-response | sich selbst (`_Checker.ping`, `unreachable`, `DOCS`) | exact |
| `src/gameworld/provisioner/archive.py` (M, AR-23 nach Spike: Weltordner root:30000 1775, worldmods root 0755) | utility | file-I/O | sich selbst (`_add_dir` Z. 116-122, `_add_access_file` Z. 146-148) | exact |
| `scripts/gameworld-orphans.sh` (NEU, Host-Skript) | utility (CLI) | batch | `scripts/fetch-games.sh` (Aufbau) + `acceptance-phase5.sh` `new_containers` Z. 345-354 | role-match |
| `tests/test_lifecycle.py` (M) | test | - | sich selbst | exact |
| `tests/test_setup_check.py` (M) | test | - | sich selbst | exact |
| `tests/test_orphans.py` (NEU) | test | - | `tests/test_service_lifecycle.py` FakeProvisioner | role-match |

### E. Frontend B1 bis B4 (UI-SPEC verbindlich)

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `frontend/src/components/VerwalterGroupsSection.vue` (NEU, B1) | component | request-response | `ReviewSetting.vue` (Abschnitt) + `BackupSection.vue` (Listeneintrag) + `InviteDialog.vue` (Suche, `searchSeq`) | role-match |
| `frontend/src/components/OrphanSection.vue` (NEU, B3) | component | request-response | `BackupSection.vue` (Liste) + `ParentView.vue` "Welt löschen" (NcDialog `message`/`buttons`) | role-match |
| `frontend/src/components/InviteDialog.vue` (M: Grenz-Hinweis, Schalter "Als erwachsen einladen", Bestätigung) | component | request-response | sich selbst + `BackupSection.vue` `v-if="!confirm"`/`v-else` | exact |
| `frontend/src/components/PlayerManager.vue` (M: Chips, `.players__adult`-Schalter, Bestätigung) | component | request-response | sich selbst + `TalkRoomStatus.vue` (Schalter springt zurück) | exact |
| `frontend/src/components/TalkRoomStatus.vue` (M, B4: Warn-Hinweis + "Raum neu anlegen", Sperrfall) | component | request-response | sich selbst + `ParentView.vue` Löschdialog | exact |
| `frontend/src/components/PlaytimeSection.vue` / `PlaytimeDialog.vue` (M: "Erwachsen: Regel ruht") | component | - | `PlaytimeSection.vue` Z. 27-29 (NcChip-Variante) | exact |
| `frontend/src/views/ParentView.vue` (M: `me`-Prop, B1/B3 einhängen nach `<ReviewSetting />` Z. 251) | view | - | sich selbst | exact |
| `frontend/src/App.vue` (M: `:me="me"` an ParentView) | view | - | sich selbst Z. 33, 35 (`PlayerView :user="me"`) | exact |
| `frontend/src/api.js` (M: neue Aufrufe) | utility | request-response | `setTalkReadOnly` Z. 312-316, `rotatePassword` Z. 192-195 | exact |
| `frontend/src/playtime.js` (M: `talkHint` ohne "Besitz übertragen", Erwachsen-Texte) | utility | transform | `talkHint` Z. 444-458, `NOT_APPLIED_TEXT` Z. 462-469 | exact |

### F. Image, CI, Store-Paket (PLATT-01)

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `Dockerfile` (NEU) | config/build | - | `C:\Users\Student\nextcloud-mcp-connector\Dockerfile` | exact (anderes Projekt) |
| `scripts/image/start.sh` (NEU, HaRP verbatim) | config | - | `C:\Users\Student\nextcloud-mcp-connector\start.sh` | exact |
| `scripts/image/entrypoint.sh` (NEU, Wächter + ggf. chown/gosu) | config | - | `C:\Users\Student\nextcloud-mcp-connector\entrypoint.sh` | exact |
| `scripts/image/healthcheck.sh` (NEU) | config | - | `C:\Users\Student\nextcloud-mcp-connector\healthcheck.sh` | exact |
| `.dockerignore` (NEU) | config | - | keins im Repo | none |
| `.github/workflows/image.yml` (NEU) | CI | batch | `C:\Users\Student\nextcloud-mcp-connector\.github\workflows\release.yml` | exact |
| `scripts/build-store-release.sh` (NEU) | utility | file-I/O | `C:\Users\Student\nextcloud-mcp-connector\scripts\build_store_release.sh` | exact |
| Store-Submit (letzter Plan, nicht autonom) | CI/manuell | request-response | `C:\Users\Student\nextcloud-search\.github\workflows\store-submit.yml` (Direktmodus Z. 111-134) | exact |

### G. Doku, Listing, Abnahme

| Neu/Geändert | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `docs/privacy.md` (NEU, EN) + `docs/privacy.de.md` (NEU) | docs | - | `C:\Users\Student\nextcloud-mcp-connector\docs\privacy.md` | role-match |
| `docs/install.md` (M, EN-Hauptfassung) + `docs/install.de.md` | docs | - | `docs/install.md` selbst (Abschnitte 1 bis 11) | exact |
| `docs/store-listing.md` (NEU, Entwurf zur Owner-Abnahme) | docs | - | `C:\Users\Student\nextcloud-search\docs\store-listing.md` | exact |
| `README.md` / `README.de.md` (NEU, Repo hat noch keine README) | docs | - | Connector `README.md`/`README.de.md`/`README.fr.md` | role-match |
| `docs/screenshots/*-v1.png` (NEU, Playwright gemeinsam) | asset | - | Connector `docs/screenshots/*-v2.png` | exact |
| `scripts/dev/harp.compose.yaml` (NEU, Dev-HaRP mit Docker-Engine) | config | - | `scripts/dev/spike-04.2/harp-probe.compose.yaml` | role-match |
| `scripts/dev/acceptance-phase6.sh` (NEU) | test (Abnahme) | batch | `scripts/dev/acceptance-phase5.sh` | exact |

---

## Pattern Assignments

### `src/gameworld/access/roles.py` (guard, request-response)

**Analog:** sich selbst. Heute hart `ADMIN_GROUP`, Z. 22 und Z. 46-47:

```python
ADMIN_GROUP = "admin"
...
def role_of(profile: Profile) -> str:
    return ROLE_VERWALTER if ADMIN_GROUP in profile.groups else ROLE_SPIELER
```

**Profil aus der Selbstauskunft** (Z. 32-36, 50-54); `subadmin` ergänzen (nc_py_api `UserInfo.subadmin` laut RESEARCH 1.1):

```python
@dataclass(frozen=True)
class Profile:
    user_id: str
    display_name: str
    groups: tuple[str, ...]

async def nc_profile(uid: str) -> Profile:
    """Selbstauskunft im Namen des Nutzers (/ocs/v1.php/cloud/user); der Client schließt danach (WR-05)."""
    async with nc_as(uid) as nc:
        info = await nc.users.get_user()
    return Profile(user_id=uid, display_name=info.display_name or uid, groups=tuple(info.groups))
```

**Cache-Muster 30 s, nur Erfolge** (Z. 57-78). `require_nc_admin` darf diesen Cache NICHT nutzen (RESEARCH 1.2 Punkt 2), also direkt `self._lookup(uid)` aufrufen. Beim Ändern der Verwalter-Gruppen `self._cache.clear()`.

**Guard-Muster, 403/503 fail closed** (Z. 104-112), Vorlage für `require_nc_admin`:

```python
async def require_verwalter(uid: UserDep, roles: RolesDep) -> str:
    """Zweite Sperre jeder Verwaltungsroute: 403 für Nicht-Admins, 503 bei Störung."""
    try:
        role = await roles.role(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if role != ROLE_VERWALTER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_FORBIDDEN)
    return uid
```

- Konfig lesen: `meta`-Schlüssel `verwalter_groups` über `WorldStore.get_meta` (Muster `parse_admins` in `playtime/engine.py` Z. 86-96: kaputt/fehlend = nur `admin`, fail closed).
- `RoleService` bekommt heute nur `Lookup`; für die Gruppenliste einen zweiten Callable (Store-Leser) injizieren, damit `tests/test_roles.py` Z. 101-138 weiter ohne Store läuft.
- Docstring Z. 1-9 ("doppelt gesperrt: AppAPI-Route ADMIN") muss umgeschrieben werden: nach Phase 6 ist `require_verwalter` die einzige Sperre.
- `ADMIN_GROUP` bleibt als Konstante (echter NC-Admin = `"admin" in profile.groups`), Importeure: `playtime/service.py` Z. 44.

---

### `src/gameworld/api/admin.py` (NEU, controller, request-response)

**Analog:** `src/gameworld/api/talk.py` (kleiner Router, Out-Modelle, 404/409) und `api/invites.py` `/settings` (meta lesen/schreiben).

**Router-Kopf mit routerweiter Sperre** (`api/talk.py` Z. 15-25), hier mit `require_nc_admin` statt `require_verwalter`:

```python
from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, WorldId
...
# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-04.1-28).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])
...
VerwalterDep = Annotated[str, Depends(require_verwalter)]
```

**meta lesen/schreiben über Worker-Thread** (`api/invites.py` Z. 266-275):

```python
@router.get("/settings")
async def get_settings(service: ServiceDep) -> SettingsOut:
    value = await anyio.to_thread.run_sync(service.store.get_meta, JOIN_HOST_KEY)
    return SettingsOut(join_host=value or "")

@router.post("/settings")
async def save_settings(body: SettingsIn, service: ServiceDep) -> SettingsOut:
    await anyio.to_thread.run_sync(service.store.set_meta, JOIN_HOST_KEY, body.join_host)
    return SettingsOut(join_host=body.join_host)
```

**Eingabe-Validierung** (`api/invites.py` Z. 53-57, 93-104): Gruppen-ID mit `Field(max_length=64)` + `AfterValidator(_clean_target)`, `ConfigDict(extra="forbid")`. Entfernen als POST mit Body (Z. 3-6 Docstring: IDs dürfen Sonderzeichen enthalten; info.xml kennt nur GET, POST, DELETE).

**Feste deutsche Fehlermeldungen, nie Nextcloud-Texte** (`api/invites.py` Z. 177-188): 422 bei unbekannter Gruppe (`group_exists` als handelnder NC-Admin, `access/directory.py` Z. 113-114), 503 bei `DirectoryUnavailableError`.

**Orphan-Routen** in demselben Router (alle `require_nc_admin`): `GET /api/admin/orphans`, `POST /api/admin/orphans/container/remove`, `POST /api/admin/orphans/volume/remove` (Body mit Namen, 409 wenn Volume noch benutzt). Docker-Aufrufe über `anyio.to_thread.run_sync` wie `api/setup_check.py` Z. 42.

- In `main.py` Z. 119-128 einreihen: `APP.include_router(admin.router)`.

---

### `src/gameworld/api/me.py` (controller, request-response)

**Analog:** sich selbst, `MeOut` Z. 47-50 und `me()` Z. 126-132:

```python
class MeOut(BaseModel):
    user_id: str
    display_name: str
    role: str

@router.get("/me")
async def me(uid: UserDep, roles: RolesDep) -> MeOut:
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return MeOut(user_id=profile.user_id, display_name=profile.display_name, role=role_of(profile))
```

- Ergänzen: `nc_admin: bool` (`ADMIN_GROUP in profile.groups`) und `invite_groups: list[str]` (sortiert, `groups ∪ subadmin`), nur für Verwalter befüllen, Spieler bekommen `[]` (kein Leck der Gruppen an Kinder).
- `tests/test_roles.py` Z. 72-81 prüfen `response.json() == {...}` exakt: dort die neuen Felder nachziehen.
- `/api/my/playtime` Z. 183-191: `exempt=role_of(profile) == ROLE_VERWALTER` bleibt; Erwachsene löst `TimeService._my_playtime_sync` Z. 450-461 über die erweiterte Frei-Menge auf (`if nc_user in self._admins()` auf `frei`-Menge umstellen).

---

### `src/gameworld/access/service.py` (service, CRUD) - 404-Falle

**Analog:** sich selbst. Diese drei Stellen sind die Angriffsfläche von F-04/P-01:

**Einzelkonto prüft heute per `user()`** (Z. 149-163); für Mitglied-Verwalter gibt `user()` 404, deshalb Existenz über die Mitgliederliste der eigenen Gruppen belegen:

```python
async def invite_user(self, world_id: str, acting_uid: str, uid: str) -> AccessResult:
    await self._require_world(world_id)
    user = await self._directory.user(acting_uid, uid)
    if user is None or not user.enabled:
        raise InviteTargetError(MSG_UNKNOWN_ACCOUNT)
```

**Auflösung ruft `user()` je Gruppenmitglied** (Z. 389-410), der eigentliche Schaden-Pfad:

```python
for kind, target in sorted(invites):
    members = None if kind == KIND_USER else await self._directory.group_members(acting_uid, target)
    uids = [target] if kind == KIND_USER else (members or [])
    for uid in uids:
        if uid not in cache:
            cache[uid] = await self._directory.user(acting_uid, uid)
        user = cache[uid]
        if user is not None and user.enabled:
            resolution.effective[user.uid] = user
```

Regel für den Umbau: "404 heißt gelöscht" nur, wenn `acting_uid` bestätigter NC-Admin ist; sonst `DirectoryUser(uid, display_name=uid, enabled=True)` aus der Gruppenliste und direkte Einladungen nie entfernen.

**purge mit Positivkontrolle** (Z. 345-370) bleibt, darf aber nur mit NC-Admin-`acting` gerufen werden (Aufrufer `notify/loop.py` Z. 342-350).

**Neue Fehlerklasse** für "außerhalb deiner Gruppen": Muster `InviteTargetError` Z. 69-70; API mappt auf 403 mit festen Texten aus UI-SPEC B1 ("Dieses Konto ist in keiner deiner Gruppen." / "Diese Gruppe gehört nicht zu deinen Gruppen.").

**Sperr-Regel** (Z. 237-243, 273-279): Nextcloud-Aufrufe nie unter `worlds.mutation()`, Store-Schreiben in `run()` per `anyio.to_thread.run_sync`. FakeDirectory prüft das (`lock_held`, conftest Z. 451-476).

---

### `src/gameworld/playtime/service.py` (service, batch) - Schnappschuss je Gruppe

**Analog:** sich selbst. `refresh_admins` Z. 296-323 (gedrosselt, Störung = letzter Stand) und `verify_admins` Z. 325-371 (Gegenprobe `app_accepted`, Kandidat muss selbst in der Antwort stehen, alle abgelehnt = leeren):

```python
try:
    members = await self._directory.group_members(acting_uid, ADMIN_GROUP)
except DirectoryUnavailableError:
    LOG.warning("Gruppe admin nicht abrufbar, der letzte Verwalter-Stand bleibt")
    ADMINS_STATE.last = None
    return False
value = json.dumps(sorted(set(members or ()) | {acting_uid}))
```

```python
for uid in candidates:
    tried += 1
    try:
        members = await self._directory.group_members(uid, ADMIN_GROUP)
    except DirectoryRejectedError:
        rejected += 1
        continue
    except DirectoryUnavailableError:
        continue
    found = set(members or ())
    if uid not in found:
        rejected += 1
        continue
```

- Umbau: Schleife über `verwalter_groups`, je Gruppe eigener Stand (P-03: Lehrer bekommt auf `admin` 403, darf nur diese Gruppe nicht leeren). Union aller Gruppen ergibt die Frei-/Moderatoren-/Empfänger-Menge; `nc_admins` separat für purge.
- Schreiben unter der Sperre und alle Welten neu rendern: `_apply_admins` Z. 499-505 + `_refresh_all_worlds` Z. 562-569.
- Erwachsen setzen: Muster `_set_sync` Z. 522-528 (unter `mutation()`, dann `push_time` je Welt des Kontos, Ergebnis `applied`):

```python
def _set_sync(self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, acting_uid: str) -> bool:
    updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    with self._worlds.mutation():
        if nc_user in self._admins():
            raise ValueError(MSG_ADMIN_NO_RULES)
        self._store.set_child_plan(nc_user, normal, holiday, acting_uid, updated_at)
        return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))
```

- `_snapshot` Z. 584-609 liefert `ChildView`; um `adult: bool` erweitern (UI braucht es im Spielzeit-Abschnitt).

---

### `src/gameworld/worlds/store.py` (model/migration, CRUD) - Schema 8

**Analog:** sich selbst.

**Versionsnummer und Tabellen im SCHEMA-String** (Z. 29-31, Tabellenmuster `talk_rooms` Z. 171-178):

```python
SCHEMA_VERSION = "7"
...
CREATE TABLE IF NOT EXISTS talk_rooms (
  world_id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  owner_uid TEXT NOT NULL,
  read_only INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'ok'
);
```

Neue Tabellen anhängen (`CREATE TABLE IF NOT EXISTS adults (nc_user TEXT PRIMARY KEY, set_by TEXT NOT NULL, set_at TEXT NOT NULL)`, `verwalter_seen (uid TEXT PRIMARY KEY, first_seen TEXT NOT NULL)`), Gruppen-Frozenset wie `BACKUP_TABLES` Z. 222-223 ergänzen (Migrationstest).

**Spalte nachrüsten, idempotent nach Spaltenliste** (Z. 237-245, 409-418), falls `talk_rooms` eine Spalte `orphaned_token` bekommt:

```python
ADD_PLAYER_SALT = "ALTER TABLE players ADD COLUMN salt TEXT NOT NULL DEFAULT ''"
...
player_columns = {str(info[1]) for info in connection.execute("PRAGMA table_info(players)").fetchall()}
if "salt" not in player_columns:
    connection.execute(ADD_PLAYER_SALT)
```

**ACCOUNT_TABLES** (Z. 246-260) um `"adults"` erweitern (P-08), Kommentar Z. 246-249 nachführen; `forget_account` Z. 650-676 löscht dann automatisch. `verwalter_seen` gehört NICHT hinein (Verwalter, kein Kinderkonto, wie `talk_rooms.owner_uid`), wird über den Schnappschuss gepflegt.

**Atomares meta-Schreiben**: `compare_and_set_meta` Z. 594-606 für `verwalter_groups`, falls zwei NC-Admins gleichzeitig ändern.

---

### `src/gameworld/playtime/engine.py` (service, transform)

**Analog:** sich selbst. Einzige Stellen, an denen die Frei-Zeile entsteht:

`render` Z. 199 und 206-213:

```python
admins = parse_admins(self._store.get_meta(META_TIME_ADMINS))
...
for name in self._store.access_entries(world_id):
    nc_user = self._store.player_name_owner(name)
    if nc_user is None:
        continue
    if nc_user in admins:
        # Eingeladene Verwalter: Zeile frei, auch ohne Welt-Fenster (A4).
        players[name] = _FREI
        continue
```

`book` Z. 174-183 (Rückblick-Ausschluss über `play`):

```python
admins = parse_admins(self._store.get_meta(META_TIME_ADMINS))
for name, seconds in delta.items():
    ...
    usage[nc_user] = usage.get(nc_user, 0) + seconds
    if nc_user not in admins:
        play[nc_user] = play.get(nc_user, 0) + seconds
```

- Umbau: `frei = admins | adults` an beiden Stellen. In `book` zusätzlich `usage` für Erwachsene NICHT verbuchen (RESEARCH 2.2: "was als Erwachsener gespielt wurde, wurde nicht verbucht").
- Cache-Schlüssel `_Rendered.key` (Z. 99-108): die Frei-Menge muss in den Regelteil-Schlüssel, sonst ändert ein Umschalten die Bytes nicht (Anti-Pattern Z. 189-193). Prüfen, wie `key` heute gebildet wird (hinter Z. 224).
- Mod (`provisioner/time_mod.py`) bleibt unverändert (RESEARCH 2.2).

---

### `src/gameworld/api/invites.py` (controller, request-response) - Erwachsen-Route

**Analog:** `reset_password` Z. 257-263 (kontoweite Änderung in allen Welten, `applied`):

```python
@router.post("/players/password")
async def reset_password(body: PlayerRef, access: AccessDep, uid: VerwalterDep) -> PlayerChangeOut:
    """Passwort neu (T-03-29): Das alte gilt sofort nicht mehr, in allen Welten, ohne Neustart."""
    try:
        return _change_out(await access.rotate_password(uid, body.nc_user))
    except _PLAYER_ERRORS as exc:
        raise _http_error(exc) from None
```

- Body-Modell: `class AdultIn(PlayerRef): adult: bool` (Muster `RenameRequest` Z. 106-108).
- Antwort `{nc_user, adult, applied}`; Konto ist Verwalter = 409 (UI-SPEC B2 "verwaltet Gameworld inzwischen"), unbekannter Spieler = 404 (`PlayerNotFoundError`).
- `PlayerOut` Z. 111-116 um `adult`, `verwalter`, `has_rules` erweitern; befüllt in `_players` Z. 155-174.
- Router ist schon `require_verwalter` routerweit (Z. 43): Kind-Negativtest gibt 403 ohne weiteren Code.

---

### `src/gameworld/talk/service.py` (service, event-driven) - Übernahme

**Analog:** sich selbst.

**Handelndes Konto** (Z. 128-133), Grundlage der Übernahme (neuer Besitzer = dienstältester bestätigter Verwalter aus `verwalter_seen`, Gleichstand nach Konto-ID):

```python
@staticmethod
def _candidates(row: TalkRoomRow, admins: list[str]) -> list[str]:
    """Handelndes Konto: Owner, falls noch Verwalter, sonst die Verwalter der Reihe nach."""
    if row.owner_uid in admins:
        return [row.owner_uid, *(uid for uid in admins if uid != row.owner_uid)]
    return list(admins)
```

**Sperrfall-Erkennung** (Z. 175-186): niemand sieht den Raum mehr. Heute wird die Zeile nur gelöscht, wenn der Owner Kandidat war; für den Sperrfall das alte Token merken (`orphaned_token`) und neu anlegen lassen:

```python
for acting in candidates:
    try:
        return acting, await self._rooms.participants(acting, row.token)
    except RoomGoneError:
        continue
if row.owner_uid in candidates:
    LOG.warning("Talk-Raum der Welt %s fehlt in Talk, wird neu angelegt", row.world_id)
    await anyio.to_thread.run_sync(self.store.delete_talk_room, row.world_id)
return None
```

**Abgleich-Schleife mit isolierten Fehlern** (Z. 279-313, `_isolated` Z. 327-332): Übernahmeprüfung als zusätzlicher Schritt in `_reconcile_room` Z. 315-325, nur mit bestätigtem `acting` (CR-01, Z. 289 und 311-313).

**Status** (Z. 336-357) um `orphaned_token` ergänzen; `owner_display` ist heute die Konto-ID (Z. 354).

**"Raum neu anlegen" (D-19)**: Kombination aus `delete_room` Z. 257-275 und `ensure_room` Z. 137-156 unter `self._lock(world_id)`; nie unter `worlds.mutation()` (Docstring Z. 9-10).

**`_admins()`** Z. 108-110 liest `META_TIME_ADMINS`; auf die neue Verwalter-Union umstellen (alle Lesestellen: `grep META_TIME_ADMINS` = engine.py, playtime/service.py, talk/service.py, notify/loop.py, api/alerts.py Z. 155).

---

### `src/gameworld/api/talk.py` (controller, request-response)

**Analog:** `_read_only` Z. 75-82 (404 ohne Welt, 409 ohne Raum, Ergebnis mit `applied`):

```python
async def _read_only(world_id: str, service: ServiceDep, *, on: bool) -> TalkReadOnlyOut:
    store = service.store
    if await anyio.to_thread.run_sync(store.get_world, world_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if await anyio.to_thread.run_sync(store.talk_room, world_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_NO_ROOM)
    applied = await get_talk_service(store).set_read_only(world_id, on=on)
```

- Neue Route `POST /api/worlds/{world_id}/talk/recreate` (POST, weil info.xml nur GET/POST/DELETE).
- `TalkWorldOut` Z. 28-38 um `orphaned_token: str | None` erweitern.

---

### `src/gameworld/lifecycle.py` (lifecycle hook, event-driven) - D-17 Option A

**Analog:** sich selbst. Isolierter zweiter try-Block (Z. 51-61), nur Typname ins Log, nie Fehlertext an AppAPI:

```python
try:
    if enabled:
        await talk_bot.register(nc)
    else:
        await talk_bot.unregister(nc)
except Exception as exc:
    LOG.warning("Talk-Bot nicht %s: %s", "registriert" if enabled else "abgemeldet", type(exc).__name__)
return ""
```

- Dritter Block bei `enabled is False`: alle eigenen Welt-Container parallel stoppen und entfernen, Volumes behalten, `desired_state` NICHT ändern (P-07: 60-s-Timeout von AppAPI). Fehler loggen, immer `""` zurück.
- `api_base()` Z. 20-28 bleibt (F-06: unter AIO ohne `HP_SHARED_KEY` PHP-Proxy, gewollt).
- Kommentar Z. 41-42 ("durch die ADMIN-Routen und require_verwalter gesperrt") anpassen.

### `src/gameworld/worlds/service.py` (service, batch)

**Analog:** `_boot_reconcile_sync` Z. 1308-1326 (nicht blockierender Lock, `list_managed`, Fehler je Welt isoliert) und `remove_world(..., keep_volume=True)`:

```python
def _boot_reconcile_sync(self) -> bool:
    # Nicht blockierend (Pitfall 6): Läuft eine Elternaktion, kommt der Abgleich später wieder.
    if not _LOCK.acquire(blocking=False):
        LOG.info("Boot-Abgleich verschoben: Eine Elternaktion läuft")
        return False
    try:
        managed = self._provisioner.list_managed()
        ...
    finally:
        _LOCK.release()
        self._invalidate_cache()
```

- Wiederaufbau nach Aktivieren/Update ist schon da: `decide_boot` liefert `RECREATE`, wenn Container fehlt und Volume da ist (`worlds/reconciler.py` Z. 95-98). Kein neuer Reconciler-Code nötig, nur ein Test, dass `desired running` + fehlender Container + Volume = RECREATE beim Boot.
- Async-Wrapper wie `boot_reconcile` Z. 316-318 mit `abandon_on_cancel=True`.

### `src/gameworld/provisioner/client.py` (adapter Docker) - Orphans

**Analog:** `_list_managed` Z. 449-472 (Label-Filter plus zweite Prüfung am Ergebnis) und `remove_world` Z. 399-414:

```python
containers = self._docker().containers.list(
    all=True,
    filters={"label": ["gameworld.managed=true", f"gameworld.instance={self._instance_id}"]},
)
```

```python
with self._guarded():
    api = self._docker()
    try:
        self._owned(world_id).remove(force=True, v=False)
    except (WorldNotFoundError, docker.errors.NotFound):
        LOG.info("Welt %s hat keinen eigenen Container mehr", world_id)
    if not keep_volume:
        with contextlib.suppress(docker.errors.NotFound):
            api.volumes.get(resource_name(self._instance_id, world_id)).remove()
```

- `list_orphans`: Container mit `gameworld.managed=true` und `gameworld.instance != self._instance_id` (Filter nur auf managed, Instanz im Ergebnis prüfen wie `_is_owned` Z. 260-267), plus Volumes mit Präfix `gameworld-` (Namensschema `spec.py` Z. 24-26 `gameworld-{instance}-{world}`), die keiner eigenen Weltzeile gehören.
- Entfernen nur nach erneuter Prüfung am Objekt (Label bzw. Präfix), nie über einen Namen ohne Prüfung (Docstring `_owned` Z. 270-275). Volume in Benutzung: Docker 409 -> eigene Fehlerklasse -> API 409.
- Lesen über `self._read(...)` (Retry-Muster Z. 245-258), Schreiben über `self._guarded()`.

### `src/gameworld/provisioner/setup_check.py` (utility, request-response)

**Analog:** sich selbst. `DOCS`-Konstante Z. 18 durch feste GitHub-URL ersetzen; `ping` Z. 165-172 und `unreachable` Z. 154-163 nach Ursache aufteilen:

```python
def ping(self) -> CheckItem:
    try:
        response = self.request("GET", "/_ping")
    except requests.RequestException:
        return self.unreachable()
```

- `requests.exceptions.ConnectionError` mit `socket.gaierror` in der `__cause__`/`__context__`-Kette = Name nicht auflösbar; `ConnectTimeout` = falsches Netz; sonst abgelehnt. Eigene `CheckItem`-IDs (Muster `_Probe` Z. 37-48), Texte aus RESEARCH Abschnitt 7.
- `run_setup_check` Z. 249-260 fängt jede Ausnahme, Vertrag bleibt.

### `src/gameworld/provisioner/archive.py` (utility, file-I/O) - AR-23 nur nach Spike

**Analog:** sich selbst, `_add_dir` Z. 116-122 setzt heute jedes Verzeichnis auf Luanti-UID 0o755:

```python
def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.uid = info.gid = LUANTI_UID
    info.mode = 0o755
    info.mtime = FIXED_MTIME
    tar.addfile(info)
```

- Härtung: `_add_dir` um `uid`/`gid`/`mode`-Parameter erweitern (Muster `_file_info` Z. 125-131); Weltordner `root:30000 0o1775`, `worldmods` `root 0o755`. Betroffen: `build_world_files` Z. 159-179 und `build_world_payload` Z. 216-233.
- Spike zuerst (D-21): echte Welt per E2E (`tests/e2e/test_create_world_e2e.py`-Muster), Luanti schreibt `map.sqlite`, `env_meta.txt`, Zählbuch.

---

### `frontend/src/components/VerwalterGroupsSection.vue` (NEU, B1)

**Analog 1, Abschnitt mit Laden/Speichern/NoteCards:** `ReviewSetting.vue` Z. 1-41 (Template), Z. 86-115 (load/save mit `errorText`), Z. 120-135 (Styles):

```vue
<section class="review-setting">
	<h4>Tagesrückblick am Abend</h4>
	<p class="review-setting__hint">
		Gilt nur für dich. Ohne Spielzeit an dem Tag kommt keine Nachricht.
	</p>
	<NcLoadingIcon v-if="loading" :size="20" />
	<div v-else class="review-setting__form">
```

```js
async function load() {
	loading.value = true
	error.value = ''
	try {
		apply(await getReviewPrefs())
	} catch (err) {
		error.value = `Die Einstellung konnte nicht geladen werden: ${errorText(err)}`
	} finally {
		loading.value = false
	}
}
```

UI-SPEC weicht ab: `h3` statt `h4`, `margin-top: 32px` (Muster `.gameworld__mine`, ParentView Z. 766), `gap: 12px`, `align-items: flex-end`.

**Analog 2, Gruppensuche mit Verzögerung und `seq`:** `InviteDialog.vue` Z. 99-129 (SEARCH_DELAY_MS, `searchSeq`, Fehlertext "gerade nicht möglich"). Für Gruppen entweder Backend-Gruppensuche oder `searchAccounts` (`api.js` Z. 329-349) auf `shareTypes: [1]` filtern.

**Analog 3, Listeneintrag:** `BackupSection.vue` Z. 29-45 und Styles Z. 278-297 (`flex-wrap`, `overflow-wrap: anywhere`, Trennlinie `var(--color-border)`).

- Nur gerendert bei `me.nc_admin === true` (v-if in ParentView), aria-label "Gruppe {gid} entfernen".

### `frontend/src/components/OrphanSection.vue` (NEU, B3)

**Analog 1, Liste:** `BackupSection.vue` Z. 23-46 (Laden, Leerzustand als `<p>`, `NcChip ... no-close` als Art-Marke Z. 35-40).

**Analog 2, destruktive Bestätigung per NcDialog-`message`/`buttons`:** `ParentView.vue` Z. 201-207 und Z. 385-414:

```js
const deleteButtons = [
	{ label: 'Abbrechen', variant: 'tertiary' },
	{
		label: 'Endgültig löschen',
		variant: 'error',
		callback: () => {
			const world = pendingDelete.value
			pendingDelete.value = null
			if (world) {
				run(world, deleteWorld)
			}
		},
	},
]
```

- Lädt einmal in `onMounted`, kein 5-s-Polling; "Erneut suchen" (secondary) startet `load()`.
- Link zur Doku mit `target="_blank" rel="noopener noreferrer"` wie `TalkRoomStatus.vue` Z. 6-13.

### `frontend/src/components/InviteDialog.vue` (M, B1-Grenze + B2)

**Analog:** sich selbst plus Bestätigungs-Ersatz aus `BackupSection.vue` Z. 2-8 und Z. 73-102 (`v-if="!confirm"` am ersten NcDialog, `v-else` am zweiten; Abbrechen setzt `confirm = null`, Auswahl bleibt):

```vue
<NcDialog
	v-if="!confirm"
	:open="true"
	...
<!-- Bestätigung (D-04/D-09): ersetzt den Bereich, solange sie offen ist. -->
<NcDialog
	v-else
	:open="true"
	:name="confirm.kind === 'restore' ? 'Welt wiederherstellen' : 'Welt sichern'"
	@update:open="onConfirmOpen">
```

- `submit()` Z. 132-158 lädt nacheinander ein und sammelt `failures`; danach je erfolgreichem Einzelkonto `setAdult(...)`; Teil-Fehler als Warn-NoteCard (UI-SPEC B2).
- Grenz-Hinweis unter `.invite__hint` Z. 8-10 nur bei `me.nc_admin === false`; Dialog braucht dafür eine `me`- oder `inviteGroups`-Prop (heute nur `world`, Z. 64-67).

### `frontend/src/components/PlayerManager.vue` (M, B2)

**Analog:** sich selbst. Kopfzeile Z. 33-36 bekommt die Chips; Schalter in neuer Zeile darunter; Fehler-/Erfolgsmuster `change()` Z. 245-261:

```js
async function change(action, success) {
	busy.value = true
	resetMessages()
	try {
		const result = await action()
		notice.value = success
		notApplied.value = result?.applied === false
		...
		apply(await listPlayers(props.world.id))
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		busy.value = false
	}
}
```

**Schalter mit eigener Anzeige, springt bei Fehler zurück:** `TalkRoomStatus.vue` Z. 54-61 und Z. 69-90:

```js
saving.value = true
...
readOnly.value = on
try {
	const result = await setTalkReadOnly(props.world.id, on)
	readOnly.value = result.read_only
	...
} catch (err) {
	readOnly.value = !on
	error.value = errorText(err)
} finally {
	saving.value = false
}
```

- Einschalten nur über den Bestätigungsdialog (Ersatz-Muster wie bei InviteDialog, PlayerManager hat heute nur Inline-NoteCards für Rotation Z. 70-80); Ausschalten direkt.
- `.players__head` (Styles Z. 315-319) braucht `flex-wrap: wrap` für 390 px.
- `notApplied` heute fester Text Z. 19-21; für Erwachsen `NOT_APPLIED_TEXT` aus `playtime.js` Z. 462-464 nehmen (UI-SPEC).

### `frontend/src/components/TalkRoomStatus.vue` (M, B4)

**Analog:** sich selbst (NoteCard-Stapel Z. 23-31) plus Löschdialog-Muster aus ParentView (oben). `talkHint` (`playtime.js` Z. 451-456) liefert heute den Satz "Den Besitz kannst du in Talk ... übertragen"; laut UI-SPEC B4 ersetzen und den Fall `owner_not_admin` als Warn-NoteCard mit Knopf hier rendern.

### `frontend/src/views/ParentView.vue` + `frontend/src/App.vue` (M)

- ParentView hat heute KEINE `me`-Prop; `App.vue` Z. 33 rendert `<ParentView v-else />`. Muster für die Weitergabe: `App.vue` Z. 35 `<PlayerView v-else :user="me" />`.
- Einhängen nach `<ReviewSetting />` (ParentView Z. 251): `<VerwalterGroupsSection v-if="me?.nc_admin" />`, `<OrphanSection v-if="me?.nc_admin" />`.
- Kommentar `App.vue` Z. 57-59 ("Gruppe admin") anpassen.

### `frontend/src/api.js` (M)

**Analog:** `setTalkReadOnly` Z. 311-316 und `rotatePassword` Z. 191-195 (immer `post()`/`del()` mit JSON-Pflicht Z. 31-43, IN-08; Pfadteile mit `encodeURIComponent`):

```js
export async function rotatePassword(ncUser) {
	const response = await post(`${apiBase}/api/players/password`, { nc_user: ncUser })
	return response.data
}
```

Neu: `getVerwalterGroups`, `addVerwalterGroup`, `removeVerwalterGroup`, `setAdult(ncUser, adult)`, `listOrphans`, `removeOrphanContainer`, `removeOrphanVolume`, `recreateTalkRoom(worldId)`.

---

### `Dockerfile` (NEU, build)

**Analog:** `C:\Users\Student\nextcloud-mcp-connector\Dockerfile` (gleiches Owner-Muster, im Store bewährt). Übernehmen:

- Basis per Index-Digest in beiden Stufen (Z. 16-20, 45-47), uv per Image-Tag `COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv` (Z. 25), `uv sync --frozen --no-dev --no-editable` (Z. 40).
- `LABEL org.opencontainers.image.source=...` (Z. 52-54), Pflicht für die ghcr-Verknüpfung (RESEARCH 4).
- frpc mit Konstanten statt ARGs und `sha256sum -c` je `TARGETARCH` (Z. 72-87); Version und Prüfsummen auf 0.71.1 aus RESEARCH 3.1 heben.
- Dienstnutzer und vorbereitete schreibbare Pfade (Z. 92-112):

```dockerfile
RUN groupadd --gid 10001 exapp \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin exapp

COPY entrypoint.sh start.sh healthcheck.sh /
RUN chmod 0755 /entrypoint.sh /start.sh /healthcheck.sh \
    && install -o 10001 -g 10001 -m 0600 /dev/null /frpc.toml \
    && install -d -o 10001 -g 10001 -m 0700 /nc_app_mcp_connector_data \
    && install -d -o 10001 -g 10001 -m 0700 /certs
```

  Für Gameworld: `/nc_app_gameworld_data`. Wichtig für D-22: Der Connector braucht KEIN gosu, weil ein frisches benanntes Volume Besitzer und Modus des vorbereiteten Verzeichnisses erbt (Kommentar Z. 101-104) und HaRP die Zertifikate als Container-Nutzer kopiert (Z. 106-111). Der Planer entscheidet: Connector-Muster (`USER 10001`, kein chown) oder D-22 wörtlich (root-Entrypoint, chown, gosu). Das Connector-Muster ist im Store gemessen; RESEARCH 3.1 nimmt dagegen `docker cp` als root an.
- Code nicht dem Dienstnutzer gehören lassen (Z. 114-121, WR-13).
- `HEALTHCHECK` und `ENTRYPOINT ["/entrypoint.sh", ...]` (Z. 132-136).
- Gameworld-Zusatz: Node-Stufe (`npm ci --ignore-scripts && npm run build`), Spiele-Stufe (`scripts/fetch-games.sh` prüft gegen `vendor/games/SHA256SUMS`), WORKDIR = App-Root, weil `set_handlers` `js/` und `img/` relativ zum cwd mountet (`main.py` Z. 60-61). Startbefehl `python -m gameworld.main` (`main.py` Z. 147-148, `run_app` wählt Socket/TCP selbst).

### `scripts/image/start.sh`, `entrypoint.sh`, `healthcheck.sh` (NEU)

**Analog:** Connector-Dateien gleichen Namens.
- `start.sh` unverändert aus HaRP (Connector-Kopie `C:\Users\Student\nextcloud-mcp-connector\start.sh`, 69 Zeilen; Herkunft im Kopf vermerken). Nicht zur Bauzeit laden (RESEARCH Package Audit).
- `entrypoint.sh`: Zertifikats-Wächter Z. 27-68 übernehmen (verweigert Klartext-FRP), die DNS-Rebinding-Zeile Z. 70 ist Connector-spezifisch und entfällt. Bei gosu-Variante: chown auf `$APP_PERSISTENT_STORAGE` vor `exec gosu`.
- `healthcheck.sh`: unverändert übernehmbar (Z. 20-46: frpc über `/proc`, Socket `HP_EXAPP_SOCK` oder `127.0.0.1:${APP_PORT}`, `/heartbeat`); setzt `curl` im Image voraus (Connector Z. 56-61).

### `.github/workflows/image.yml` (NEU, CI)

**Analog:** `C:\Users\Student\nextcloud-mcp-connector\.github\workflows\release.yml`. Übernehmen:
- Auslöser Tag `v*` + `workflow_dispatch` mit `dry_run` (Z. 20-29), `permissions: contents: read` oben, Schreibrechte nur am Job (Z. 31-43).
- Lockstep-Prüfung Tag gegen info.xml `<version>` (Z. 47-66); für Gameworld zusätzlich `<image-tag>` und pyproject `version`.
- Actions per SHA (Z. 45, 68-85). Achtung: `docker/login-action` steht im Connector auf v4.6.0 `dbcb8138...`, RESEARCH nennt v4.7.0 `81c6f93d...`; RESEARCH-Pins nehmen, `docker/metadata-action` optional.
- `platforms: linux/amd64,linux/arm64`, Tag `ghcr.io/street1983nk/gameworld:<version>` (info.xml Z. 60-62).
- Store-Archiv bauen und an den Release hängen (Z. 87-94).
- Kommentarstil des Repos ist Deutsch (`luanti-wasm.yml` Z. 1-5); SHA-Pins mit `# vX.Y.Z` (dort Z. 60, 151).

### `scripts/build-store-release.sh` (NEU)

**Analog:** `C:\Users\Student\nextcloud-mcp-connector\scripts\build_store_release.sh` Z. 24-66 (Top-Ordner `<app_id>/appinfo/info.xml`, LICENSE, `tar --numeric-owner --owner=0 --group=0 -czf`, Signatur nur zur Diagnose, weil tar.gz nicht byte-reproduzierbar ist; die Store-Signatur kommt über das HERUNTERGELADENE Asset). Gameworld zusätzlich `img/app.svg` (RESEARCH 5.1 Punkt 4). Repo-Konvention ist POSIX `sh` (alle `scripts/dev/*.sh`, `fetch-games.sh`); der Connector nutzt bash (`grep -oP`), daher für Gameworld portabel umschreiben.

### Store-Upload (letzter Plan, nicht autonom, R-01)

**Analog:** `C:\Users\Student\nextcloud-search\.github\workflows\store-submit.yml`. Der "Direktmodus" Z. 111-134 ist ausdrücklich für Schwester-Apps desselben Kontos gebaut (Token liegt nur im Findling-Repo, Signatur am Owner-Rechner). Registrierung `POST /api/v1/apps` Z. 85-107 (Zertifikat aus `app-certificate-requests/master/<app>/<app>.crt`, Signatur über die App-ID). Entweder diesen Workflow mit Direktmodus nutzen (dann braucht er einen Registrierungsschalter für eine fremde App-ID) oder die beiden curl-Aufrufe aus RESEARCH "Release signieren und hochladen" manuell; erwartet 2x HTTP 201.

---

### `scripts/gameworld-orphans.sh` (NEU, Host-CLI)

**Analog:** `scripts/fetch-games.sh` (Kopfkommentar mit Zweck, `set -eu`, `fail()`, POSIX sh, Z. 1-32) und das Container-Zählmuster aus `scripts/dev/acceptance-phase5.sh` Z. 345-354:

```sh
for cid in $(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null); do
```

- Standard nur auflisten; `--remove-containers` entfernt, `--remove-volumes` zusätzlich mit zweiter Rückfrage. Volumes: `docker volume ls --filter name=gameworld-` (Volumes tragen kein Label, `spec.py` Z. 61). Nie Container ohne `gameworld.managed=true`.

### `scripts/dev/harp.compose.yaml` (NEU, Dev-HaRP)

**Analog:** `scripts/dev/spike-04.2/harp-probe.compose.yaml`: Secrets nur aus `.dev/` per `${VAR:?...}` (Z. 13-16, 27), externes Netz `gameworld-dev_default` (Z. 103-106), `extra_hosts host-gateway` (Z. 37-38), Loopback-Ports (Z. 39-41). Unterschied: Docker-Socket für HaRP (Deploy), `--harp`-Daemon-Registrierung per occ aus RESEARCH 9, TLS für FRP an lassen (der Spike schaltete `HP_FRP_DISABLE_TLS` nur mangels Zertifikaten ab, Z. 33-35).

### `scripts/dev/acceptance-phase6.sh` (NEU)

**Analog:** `scripts/dev/acceptance-phase5.sh`:
- Kopfkommentar mit Kriterien K1..Kn und "Bewusst unabhängig vom Implementierungsmuster" (Z. 1-44).
- Zähler und Helfer `pass`/`fail`/`abort`/`check` (Z. 82-115), `occ` (Z. 117-119), `add_user` mit 3 Versuchen (Z. 121-137), `call AUTH METHODE URL AUSGABE [JSON]` (Z. 143-151) für Lehrer-Konto mit eigenem Passwort.
- `trap cleanup EXIT` mit Wegwerfkonten-Rückbau (Z. 356-374), Voraussetzungs-Prüfung (Z. 376-390), Grundlinie fremder Container (Z. 390, 399).
- Negativ- und Positivkontrollen paarweise (Z. 405, 446-454, 662).
- Regressionsblock mit `GAMEWORLD_SKIP_REGRESSION` und exakten "N von N"-Zeilen (Z. 665-693); Phase 6 ruft `acceptance-phase5.sh` und ergänzt dessen Summenzeile.
- Neue Fixtures: Gruppe `lehrkraefte` (Verwalter-Gruppe), Gruppe `klasse` (Lehrer Mitglied, Kind Mitglied), Kind außerhalb.

### `docs/privacy.md` (NEU, EN) und `docs/privacy.de.md`

**Analog:** `C:\Users\Student\nextcloud-mcp-connector\docs\privacy.md`: SPDX-Kopf als HTML-Kommentar (Z. 1-4), "Scope"-Absatz (Z. 8-12), Gliederung "The short version / What the app stores / What the app never does / What leaves your control / Deletion and user control / Retention" (Überschriften Z. 14, 27, 94, 107, 210, 247). Inhalte für Gameworld: Docker-Proxy root-gleich, UDP-Ports nur LAN, Netz-Restrisiko (AIO `nextcloud-aio`), Erwachsen-Flag, Talk, Sicherungen in Files, Deinstallation lässt Volumes und Sicherungen (D-15).

### `docs/install.md` (M)

**Analog:** sich selbst. Tonlage Faktenliste mit Tabellen (Abschnitt 6 Setup-Check Z. 77-95 als Tabelle "Meldung | Abhilfe" für die neuen Setup-Check-Texte). Zu ändern: Z. 3 ("Store-Installation folgt"), Z. 75 ("weitere Härtung ist für das Store-Release geplant"), Z. 104 (Updates übernehmen Container: gilt nach D-17 nicht mehr), Z. 108-110 (Rollen nur Gruppe `admin`). Neuer Abschnitt "Aufräumen" mit festem Anker für den Link aus B3.

### `docs/store-listing.md` (NEU)

**Analog:** `C:\Users\Student\nextcloud-search\docs\store-listing.md`: eine Quelle aller Store-Texte, je Feld `<name>`, `<summary>`, `<description>` (EN ohne `lang`), `lang="de"`, `lang="fr"` als eigener Abschnitt (Überschriften Z. 120-253), "Was bewusst nicht drinsteht" (Z. 374), datierter Abnahme-Vermerk (Z. 397). Form im info.xml: Connector `appinfo/info.xml` Z. 39-41 (summary je Sprache), Z. 65/84/103 (description CDATA je Sprache), Z. 131 `<documentation>`, Z. 140-142 mehrere `<category>`, Z. 152-153 `<screenshot>` mit `-v2`-Namen auf raw.githubusercontent.

---

## Shared Patterns

### Zugriffskontrolle (gilt für jede neue oder geänderte Route)
**Quelle:** `src/gameworld/access/roles.py` Z. 104-112; routerweit wie `api/playtime.py` Z. 56, `api/invites.py` Z. 43, `api/talk.py` Z. 21, `api/setup_check.py` Z. 20.
```python
router = APIRouter(prefix="/api/playtime", dependencies=[Depends(require_verwalter)])
```
Nach dem Routenwechsel auf USER ist das die einzige Sperre. Strukturtest über `APP.routes`: jede Route unter `/api/` außer `/api/me` und `/api/my/...` trägt `require_verwalter` oder `require_nc_admin` in den Abhängigkeiten. `/api/admin/*` nur `require_nc_admin` ohne Rollen-Cache. Der Negativtest-Stil steht in `tests/test_roles.py` Z. 16-57 (parametrisierte Routenliste, Dienst darf nie aufgerufen werden, `no_service == []`).

### Fehlerabbildung
**Quelle:** `api/invites.py` Z. 177-191, `api/playtime.py` Z. 298-315.
```python
def _http_error(exc: Exception) -> HTTPException:
    """Feste deutsche Meldungen; nie Ausnahmetexte mit Daten aus Nextcloud."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    ...
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)
```
Gilt für `api/admin.py`, Erwachsen-Route, Talk-Neuanlage.

### Sperr-Regel und sofortige Wirkung
**Quelle:** `worlds/service.py` `mutation()` Z. 394-399, `try_mutation()` Z. 401-416, `push_time` Z. 438-445; `playtime/service.py` `_set_sync` Z. 522-528.
Nextcloud- und Talk-Aufrufe nie unter `mutation()`; Store und `push_time` nur im Worker-Thread unter `mutation()`; Ergebnis `applied` an die UI (UI zeigt `NOT_APPLIED_TEXT`). Gilt für Erwachsen-Schalter, Verwalter-Gruppen-Änderung (alle Welten neu rendern), Teardown beim Deaktivieren (nicht blockierend).

### Hintergrund nur mit bestätigtem Konto (CR-01)
**Quelle:** `notify/loop.py` `verify_once` Z. 436-459, `run_hooks` Z. 462-468, `MAINTENANCE` Z. 353.
Neu: zwei bestätigte Mengen. `purge_accounts` bekommt nur ein bestätigtes NC-Admin-Konto, sonst läuft er nicht (fail safe, in Doku nennen). Talk-Pflege darf ein bestätigter Verwalter aus jeder Verwalter-Gruppe sein.

### Logging
**Quelle:** `lifecycle.py` Z. 59-60, `talk/service.py` Z. 327-332, `access/service.py` Z. 225.
Nur Welt-ID und `type(exc).__name__`, nie Fehlertexte mit Nextcloud-Daten, Tokens oder Geheimnissen.

### Frontend-Grundmuster
**Quelle:** `api.js` `errorText` Z. 45-57, `post`/`del` Z. 31-43; Ausgabe nur per Textinterpolation (kein `v-html`, UI-SPEC); NoteCard-Typen success/info/warning/error; `NcLoadingIcon :size="20"` im Icon-Slot (InviteDialog Z. 46-48).

### Fail closed bei kaputter Konfig
**Quelle:** `playtime/engine.py` `parse_admins` Z. 86-96: fehlend/kaputt = leere Menge, nie Rechte. Für `verwalter_groups`: kaputt = nur `admin`; für `adults`: Tabelle, kein JSON.

---

## Fallen, die der Planer kennen muss (aus dem Code, nicht aus RESEARCH)

1. **`tests/test_info_xml.py` Z. 101-104** verbietet die Zeichenfolgen `announce` und `public` irgendwo in `appinfo/info.xml`. Ein ehrliches Listing ("no public server list", "ghcr package is public") fällt damit durch. Store-Texte ohne diese Wörter schreiben oder den Test bewusst auf Einstellungen (nicht Prosa) einschränken.
2. **`tests/test_frontend_privacy.py` Z. 10** verbietet `announce`, `serverlist`, `public`, `visibility`, `öffentlich machen`, `sichtbar machen` in ALLEN Dateien unter `frontend/src/`. Gilt für die neuen Texte in B1 bis B4 (z. B. kein "öffentlich" in Kombination "öffentlich machen", kein `visibility` in CSS).
3. **`tests/test_info_xml.py` Z. 38, 79-82, 94-98**: `EXPECTED_ROUTES` mit ADMIN, `test_admin_catch_all_is_last` (genau ein ADMIN) und `max-version == "34"` müssen gezielt mitgeändert werden, nicht gelöscht.
4. **`ParentView` hat keine `me`-Prop** (App.vue Z. 33). Ohne diese Änderung kann B1/B3 nicht nach `nc_admin` weichen.
5. **`talkHint`** (`playtime.js` Z. 455) verspricht "Besitz in Talk übertragen"; Talk erlaubt das Gameworld nicht (F-09). Text muss weg.
6. **`docs/install.md` Z. 104** sagt "Gameworld übernimmt die vorhandenen Container wieder" nach Updates; mit D-17 falsch.
7. **Boot-Abgleich meldet eigene verwaiste Container nur** (`worlds/service.py` Z. 1317-1320, "Nie anfassen"). Die In-App-Orphan-Liste ist dafür die Aktion; Container fremder Instanzen sieht `list_managed` gar nicht (Instanz-Filter Z. 452), also braucht `list_orphans` einen eigenen Filter.
8. **Repo hat keine README** und keinen `.dockerignore`; `.gitignore` schließt `js/` und `vendor/games/mineclone2-*.zip` aus, das Image muss beides selbst bauen bzw. holen.

---

## No Analog Found

| Datei | Rolle | Datenfluss | Grund |
|---|---|---|---|
| `.dockerignore` | config | - | Weder Gameworld noch die Schwester-Repos liefern ein direkt passendes Gegenstück im gelesenen Umfang; Inhalt aus `.gitignore` plus `.planning/`, `tests/`, `webplay/`, `.venv/`, `node_modules/` ableiten |
| Gruppensuche für B1 (Backend oder Autocomplete mit `shareTypes: [1]`) | service | request-response | Kein Gruppen-Suchendpunkt im Backend; nächstes Muster ist die Browser-Autocomplete in `api.js` Z. 329-349 |
| AR-23-Spike (Luanti-Schreibrechte unter root:30000/1775) | test (Spike) | file-I/O | Kein bestehender Rechte-Spike; E2E-Rahmen aus `tests/e2e/` nutzen, Ergebnis vor der Härtung belegen |
| AIO-VM-Testaufbau (D-20) | Abnahme | - | Kein AIO-Setup im Repo; RESEARCH Abschnitt 9 und `harp_aio`-Befund F-06 sind die einzige Grundlage |

## Metadata

**Analog-Suchbereich:** `src/gameworld/**`, `frontend/src/**`, `tests/**`, `scripts/**`, `appinfo/`, `docs/`, `.github/workflows/`; Schwester-Repos `C:\Users\Student\nextcloud-mcp-connector` (Dockerfile, entrypoint/start/healthcheck, release.yml, build_store_release.sh, privacy.md, info.xml) und `C:\Users\Student\nextcloud-search` (store-submit.yml, store-listing.md)
**Gelesene Dateien:** 41
**Datum der Musterextraktion:** 24.10.2026

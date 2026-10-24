---
phase: 05
slug: backup-und-restore
status: verified
threats_open: 0
asvs_level: 1
created: 2026-10-24
---

# Phase 05 , Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register stammt aus den `<threat_model>`-Blöcken der 9 Pläne 05-01 bis 05-09 (plan-time, 53 Threats:
> 51 mitigate, 2 accept). Audit 2026-10-24 durch gsd-security-auditor gegen den Stand nach den
> Review-Fixes WR-01 `fc9747e`, WR-02 `3f7305a`, WR-03 `7d154ba` (HEAD `4fa57c5`).
> Testläufe in diesem Audit (seriell, ohne docker-Marker): 498 passed
> (`tests/test_backup_*.py tests/test_backups_api.py tests/test_restore_*.py tests/test_time_mod.py tests/test_reconciler.py`),
> 71 passed (`tests/test_service_lifecycle.py tests/test_my_worlds.py tests/test_provisioner_errors.py tests/test_players_memory.py`
> mit `-k "busy or offline or players_online or halt or snapshot or swap or restore or job or backup or pause_writes or tick_reports"`),
> `node frontend/tests/backup.check.mjs`: alle Prüfungen bestanden.
> Unabhängige Gegenproben (eigenes Skript, nicht das Testmuster der Umsetzung): selbst gebaute tar.gz mit
> absolutem Pfad, `..`, Backslash, Doppelpunkt, fremdem Präfix, Symlink in `worldmods/`, Hardlink, FIFO,
> Zeichengerät, ohne map.sqlite und mit fremder world_id werden alle mit RestoreRejected abgelehnt;
> `world/./world.mt`, `worldmods/`, `mods/`, `game/`, `*.lua`, `gameworld_*` (auch in Unterordnern) fehlen
> im Restore-Tar, übrig bleiben nur `keep.txt` und `map.sqlite` mit uid 30000 und Modus 0644.
> `folder_name` ergibt für `..`, `.`, ` . `, `...`, `-/-`, `CON`, `nul.txt`, `Com1 ` den Ersatz `Welt-<id6>`,
> nie einen Schrägstrich. Docker-e2e und Abnahmeskript wurden hier bewusst nicht gestartet; deren Belege
> sind statisch geprüft plus die Läufe aus 05-08-SUMMARY (7 passed) und 05-09-SUMMARY (Phase-5-Teil 96/96).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Nextcloud Files -> ExApp | Sicherungsdateien sind für Verwalter und Freigabeempfänger beschreibbar; nur der DB-Nachweis ist Autorität | tar.gz aus Files, nicht vertrauenswürdig |
| ExApp -> Welt-Volume (put_archive) | eingespielte Dateien landen im Spielserver eines Kindes | gefiltertes Restore-Tar, Zählbuch |
| Docker-Proxy -> ExApp (get_archive) | Strom kann mitten drin abbrechen | Tar-Strom des Weltordners |
| ExApp -> Nextcloud WebDAV | Zugriff im Namen des auslösenden Verwalters über AppAPI | Sicherungsdateien, Ordnerlisten |
| ExApp -> Regeldatei (Welt-Volume) | Halt-Wert fließt in eine vom Lua-Mod geparste Datei | `@halt <epoch>` |
| Browser (Verwalter) -> /api/worlds/{id}/backups, /restore | AppAPI-ADMIN-Route, Körper nicht vertrauenswürdig | confirm-Flags, file_id |
| Browser (Kind) -> /api/my/worlds | darf keine Verwalterdaten sehen | Status, fester Text |
| Prozessneustart -> Boot-Abgleich | persistierter op_state ist einzige Wahrheit | op_state, backup_jobs |
| Backend -> Browser (Verwalter) | Dateinamen und Fehlertexte werden angezeigt | Namen aus Files |
| Testcode / Abnahmeskript -> Dev-Docker, Dev-Nextcloud | erzeugt und zerstört echte Welten, Dev-Zugangsdaten einer Loopback-Instanz | Dev-Konten, Abnahme-Dateien |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-05-01 | Tampering | prepare_restore Pfade | mitigate | `world_relative` -> `safe_relative` je Eintrag (backup/archive.py:181-186, provisioner/archive.py:73-85: `/`, `\`, `:`, `..` abgelehnt); Typprüfung vor allem anderen, nur isfile/isdir, sonst RestoreRejected (archive.py:350-357); Tests `test_restore_rejects_unsafe_entry` (parametrisiert), Gegenprobe Symlink/Hardlink/FIFO/Gerät/abs/`..`/Backslash abgelehnt | closed |
| T-05-02 | Elevation of Privilege | Lua-Code aus Sicherung | mitigate | `RESTORE_DROP_*` und `_restore_dropped` (archive.py:82-85, 298-302): world.mt, worldmods/, mods/, game/, `*.lua`, `gameworld_*` in jedem Pfadteil verworfen; world.mt aus Preset mit sqlite3-Backends (worlds/service.py:856 `render_world_mt`, provisioner/luanti_conf.py:67-70); Tests `test_restore_drops_code_and_runtime_files`, `test_code_from_backup_never_reaches_the_world` | closed |
| T-05-03 | Denial of Service | Tar-/gzip-Bombe | mitigate | `MAX_RESTORE_BYTES` 8 GiB, `MAX_RESTORE_ENTRIES` 200 000, `MAX_RATIO` 50 (archive.py:61-66), `_Limits.add` je Eintrag vor dem Entpacken (archive.py:312-326, 340); ENOSPC -> `MSG_NO_SPACE` (archive.py:223-224, 393-397); Tests `test_restore_rejects_too_many_bytes/_entries/_compression_bomb`, `test_restore_enospc_has_fixed_text` | closed |
| T-05-04 | Tampering | Snapshot aus laufender Welt | mitigate | `snapshot_to`: `container.reload()` und `status in SNAPSHOT_SAFE_STATES` (created/exited/dead) vor `get_archive` (provisioner/client.py:57, 371-376); Test `test_snapshot_of_running_world_is_refused` (tests/test_provisioner_errors.py:593) | closed |
| T-05-05 | Tampering | Ordnername aus Weltnamen | mitigate | `_clean`/`folder_name` mit Ersatz `Welt-<id6>`, `_DISALLOWED` ersetzt `/`, Rand-Punkte und reservierte Namen (backup/naming.py:24-47); Tests `test_dot_and_empty_names_fall_back`, `test_reserved_names_fall_back`, `test_never_a_separator`; Gegenprobe s. oben | closed |
| T-05-06 | Information Disclosure | Logs mit Dateinamen aus Archiven | mitigate | nur Zählwerte und Fehlertypen bzw. feste Texte im Log (archive.py:275, 282, 388, 391, 398); Test `test_restore_never_logs_entry_names` | closed |
| T-05-07 | Information Disclosure | Files-Zugriff | mitigate | jede Methode von `NcBackupFiles` öffnet `_client(uid)` = `nc_as(uid, ...)` (backup/files.py:151-152, 162, 204, 216, 224, 238), Konto im Konstruktor, Sessions im `finally` geschlossen (nc.py:51-65); Tests `test_upload_uses_backup_client_options_and_proves_size`, `test_client_closed_when_mkdir_fails` | closed |
| T-05-08 | Tampering | Fremde Datei überschrieben | mitigate | nach WR-03: Upload auf eindeutigen Temp-Namen `.{name}.{uuid}.gwtmp`, dann `nc.files.move` (nc_py_api Default `Overwrite: F`, files_async.py:210-223), 412 -> nächster Suffix (files.py:166-200); Aufräumen löscht nur `created` (files.py:178-182); Tests `test_upload_picks_free_suffix_and_never_deletes_existing`, `test_race_file_at_target_survives_upload`, `test_race_file_at_move_target_is_not_overwritten` | closed |
| T-05-09 | Repudiation | Halbe Datei gilt als Sicherung | mitigate | Erfolg nur bei `by_path`-Größe == lokal (files.py:170-172), Nachweis erst danach in `_finish_ok`/`_add_proof` (backup/service.py:319-320, 378-404); unvollständige Datei gelöscht (files.py:178-182); Test `test_size_mismatch_deletes_only_own_target` | closed |
| T-05-10 | Spoofing | Sicherung eines anderen Verwalters | mitigate | `PRIMARY KEY (owner_uid, file_id)` (worlds/store.py:190), `backup_by_file` filtert `owner_uid` (store.py:1278-1285); Tests `test_file_of_other_admin_is_404`, `test_foreign_or_unknown_file_is_not_found_without_io` | closed |
| T-05-11 | Denial of Service | Kontingent voll (507) | mitigate | `STATUS_QUOTA` -> `FilesError(MSG_QUOTA)` (files.py:118-119), Temp-/Zieldatei im Fehlerpfad gelöscht (files.py:178-182); Test `test_quota_507_is_fixed_text_and_cleans_target` | closed |
| T-05-12 | Information Disclosure | Pfade/Namen in Logs | mitigate | `_map_error` loggt nur Aktion, Statuscode bzw. Typname (files.py:112-122); Test-Assert in `test_quota_507_is_fixed_text_and_cleans_target` (tests/test_backup_files.py:250) | closed |
| T-05-13 | Tampering | @halt-Zeile | mitigate | `_halt_line` nur `_is_int` (ohne bool) und `>= 0` (provisioner/time_mod.py:209-210, 780-784); Lua `line:match("^@halt (%d+)$")` (time_mod.py:393); Regeldatei root 0444 über `_add_access_file` (provisioner/archive.py:146-148, 178, 194); Tests `test_invalid_halt_raises`, `test_lua_parses_halt_line` | closed |
| T-05-14 | Denial of Service | Halt bleibt hängen | mitigate | Halt nur in `self._halts` im Speicher (playtime/engine.py:120-123, 249-260); `clear_halt` in `end_offline` und `abort_offline` vor dem Wiederanlauf (worlds/service.py:737, 750); Tests `test_end_offline_restarts_running_world_and_clears_halt`, `test_abort_offline_writes_rules_without_halt` | closed |
| T-05-15 | Tampering | Start/Löschen während Tausch | mitigate | `_refuse_busy` unter `_mutating()` in `_start_world_sync`, `_stop_world_sync`, `_restart_world_sync`, `_delete_world_sync` (worlds/service.py:1174-1177, 1258, 1272, 1293, 1407); `BUSY_OP_STATES` inkl. `restoring_swap` (worlds/reconciler.py:58); Tests `test_busy_world_refuses_parent_actions`, `test_api_busy_world_answers_409` | closed |
| T-05-16 | Denial of Service | Pause/Takt blockiert | mitigate | Busy-Zustand in der DB, Offline-Abschnitte je eigener kurzer `_mutating()`-Block (worlds/service.py:641-822); `_pause_world` schreibt bei Busy nur die Regeldatei (service.py:616-639); Tests `test_offline_sections_hold_lock_only_briefly`, `test_pause_writes_rules_but_never_restarts_busy_world`, `test_pause_answers_during_long_upload` | closed |
| T-05-17 | Information Disclosure | backup_job an Kinder | mitigate | `MyWorldOut` ohne `backup_job` (api/me.py:63-80), Busy-Status -> `TEXT_WELT_PAUSE` (me.py:43-44, 161-162); Test `test_busy_world_shows_pause_text_without_job_data` (tests/test_my_worlds.py:295) | closed |
| T-05-18 | Denial of Service | Unterbrochener Restore wird delete-only | mitigate | `decide_boot`: `restoring_swap` -> `MARK_RESTORE_INTERRUPTED` vor jeder Volume-Logik (worlds/reconciler.py:87-88); `RESTORE_INTERRUPTED` nicht in `DELETE_ONLY_ERRORS` (worlds/service.py:101-106, 125); Tests in tests/test_reconciler.py, `test_interrupted_world_can_be_restored_again` | closed |
| T-05-19 | Repudiation | Talk meldet Welt aus/an bei Backup | mitigate | `_track_run_state` überspringt `BUSY_OP_STATES` (worlds/service.py:508-511); Test `test_tick_reports_no_stop_or_start_for_busy_world` | closed |
| T-05-20 | Elevation of Privilege | api/backups.py | mitigate | `APIRouter(..., dependencies=[Depends(require_verwalter)])` (api/backups.py:40), uid nur aus `VerwalterDep` (backups.py:94, 99, 113, 141), Router eingebunden (main.py:121), `require_verwalter` 403 (access/roles.py:104-112); Tests `test_child_gets_403` (Backup und Restore) | closed |
| T-05-21 | Tampering | Request-Body | mitigate | `ConfigDict(extra="forbid", strict=True)` für `BackupRequest` und `RestoreRequest`, `file_id` nur echte Ganzzahl 1..2^63-1 (api/backups.py:43-70); Tests `test_strict_body_is_422` (beide APIs) | closed |
| T-05-22 | Information Disclosure | Liste fremder Sicherungen | mitigate | `list_backups`: `backups_for(uid, world_id)` plus `listdir(uid, ...)` als uid (backup/service.py:714-745, store.py:1268-1276); Tests `test_list_backups_only_own_files`, `test_list_shows_own_backup_after_upload_only_for_owner` | closed |
| T-05-23 | Tampering | inkonsistenter Snapshot | mitigate | `stop_for_snapshot` vor `_snapshot` (backup/service.py:340-342, 575-576), `snapshot_to` prüft Status (client.py:373-375); Tests `test_backup_runs_in_order_and_uploads_after_restart`, `test_fake_snapshot_streams_chunks_and_refuses_running` | closed |
| T-05-24 | Denial of Service | Welt bleibt nach Fehler aus / Sperre minutenlang | mitigate | `end_offline` bzw. `abort_offline` im `finally`, abgeschirmt (backup/service.py:343-349, 351-358); Sperre nur in kurzen Abschnitten (s. T-05-16); Tests `test_snapshot_error_restarts_world_and_fails_job`, `test_upload_error_keeps_world_running_and_fails_job` | closed |
| T-05-25 | Denial of Service | Platte voll durch Spool / parallele Jobs | mitigate | ein Job global (`begin_offline`: andere Busy-Welt oder `running_backup_jobs()` -> `JOB_RUNNING`, worlds/service.py:665-667); anonymer Spool `tempfile.TemporaryFile(dir=storage_dir/tmp)` (backup/service.py:124, 324-329, 792); Platzprüfung `SPACE_FACTOR * letzte Größe` (service.py:360-365); ENOSPC fester Text; Tests `test_second_backup_while_running_is_refused`, `test_spool_lives_in_tmp_and_is_closed`, `test_too_little_space_fails_before_stop` | closed |
| T-05-26 | Information Disclosure | Logs und Benachrichtigungen | mitigate | Logs nur Welt-ID und Typname (backup/service.py:217-235, 669, 682, 757); `_finish_failed` benachrichtigt nur `uid` (service.py:406-424), Weltname und Grund per `clean_value` (notify/texts.py:47-53, 72-79); Tests `test_upload_error_notifies_triggering_admin`, `test_every_failed_exit_notifies_once` | closed |
| T-05-27 | Repudiation | halbe/nicht wiederherstellbare Datei als Sicherung | mitigate | `write_snapshot` verlangt map.sqlite (archive.py:264, 272-273); `_verify` = `verify_snapshot` vor Upload (backup/service.py:314, 618); Nachweis erst nach Größenprüfung (T-05-09); Liste nur Schnittmenge `(file_id, size)` (service.py:726-731); Tests `test_failed_dry_run_is_unusable`, `test_list_backups_is_intersection_of_files_and_proofs` | closed |
| T-05-28 | Spoofing | file_id eines anderen Verwalters | mitigate | `_prepare_restore`: `backup_by_file(uid, file_id)` und `proof.world_id != world_id` -> `BackupNotFound` vor Spielerzählung, `begin_offline` und jedem I/O (backup/service.py:461-470); 404 (api/backups.py:125-126); Tests `test_foreign_or_unknown_file_is_not_found_without_io`, `test_file_of_other_world_is_404` | closed |
| T-05-29 | Tampering | in Files veränderte Sicherung | mitigate | `_check_integrity` Größe und SHA-256 gegen Nachweis in Phase A vor `_offline_safety` (backup/service.py:499-505, 548-554); WR-02: Pfad per file_id aus dem Listing (service.py:528-541); Tests `test_tampered_file_is_rejected_before_stop`, `test_restore_of_tampered_file_keeps_world`, `test_deleted_backup_with_decoy_at_old_name_is_file_gone` | closed |
| T-05-30 | Elevation of Privilege | Lua/world.mt aus Sicherung | mitigate | `_restore_tar` -> `prepare_restore` (backup/service.py:556-562) mit Verwurf (T-05-02); world.mt und Mods aus `_payload` (worlds/service.py:794-795, 844-866); Test `test_code_from_backup_never_reaches_the_world`, e2e `test_lua_in_backup_is_dropped_not_installed` | closed |
| T-05-31 | Elevation of Privilege | alte Zugangsdaten aus Sicherung | mitigate | `gameworld_*` in jedem Pfadteil verworfen (archive.py:85, 302); `restore_swap` legt Zugangs- und Regeldatei frisch über `_payload` (`_access_file(row)`, `_time_file(row)`) an (worlds/service.py:794-795, 857-858); Gegenprobe: `gameworld_access.txt` und `sub/gameworld_time.txt` fehlen im Restore-Tar | closed |
| T-05-32 | Tampering | heißes SQLite-Journal | mitigate | `restore_swap`: `remove_world(keep_volume=False)` und `create_world_container(..., reuse_volume=False)` (worlds/service.py:790, 795; client.py:399-414); Test `test_restore_swap_rebuilds_on_fresh_volume_in_order` | closed |
| T-05-33 | Denial of Service | Absturz mitten im Tausch | mitigate | `mark_swap` persistiert `restoring_swap` vor `restore_swap` (worlds/service.py:766-774; backup/service.py:641-645); Boot-Regel (T-05-18); `begin_offline(..., allow_failed=True)` (backup/service.py:474); Tests `test_mark_swap_persists_before_remove`, `test_delete_only_world_can_be_restored`, e2e `test_crash_during_swap_recovers_as_restore_interrupted` | closed |
| T-05-34 | Repudiation | Restore nicht umkehrbar | mitigate | `_safety_backup` mit `verify_snapshot` und eigenem Nachweis vor `mark_swap` (backup/service.py:604-625); lokaler Rückfall `_fallback` mit dem Safety-Spool (service.py:652-655, 674-684); Tests `test_two_swap_failures_fall_back_to_safety_snapshot`, `test_failed_safety_upload_restarts_old_world` | closed |
| T-05-35 | Denial of Service | Platte voll beim Restore | mitigate | `_check_restore_space` 3 x `proof.size` vor dem Download (backup/service.py:109, 543-546); WR-01: `_CappedWriter` deckelt den Download auf `proof.size`, sonst `RestoreTampered` (service.py:165-186, 521-522; files.py:226-228); anonyme Spools (service.py:509-512); ENOSPC in `prepare_restore` -> `MSG_NO_SPACE`; Tests `test_not_enough_space_fails_before_download`, `test_oversized_swapped_file_aborts_download_early`, `test_all_spools_are_closed` | closed |
| T-05-36 | Tampering | XSS über Dateinamen | mitigate | nur Mustache-Interpolation (`{{ entry.name }}`, `{{ restoreQuestion(...) }}`) in frontend/src/components/BackupSection.vue:31, 81; Grep `v-html|innerHTML` über frontend/src: kein Treffer | closed |
| T-05-37 | Tampering | versehentliches Überschreiben | mitigate | `askRestore` öffnet immer die Abfrage `restoreQuestion` (BackupSection.vue:184-191, 80-82; frontend/src/backup.js:25-27); `confirm: true` nur aus dem Bestätigungsweg (frontend/src/api.js:164-169); Backend ohne confirm 409 (backup/service.py:447-448); Tests `test_missing_confirmation_is_409`, `test_restore_requires_confirmation` | closed |
| T-05-38 | Denial of Service | Doppelklick startet zwei Jobs | mitigate | `locked` = saving oder Job running oder Busy-Status, Knöpfe `:disabled="locked"` und Früh-Return in `askBackup`/`askRestore`/`run` (BackupSection.vue:132-137, 42, 63, 95, 172-202); Backend 409 (T-05-25); Test `test_second_backup_while_running_is_refused` | closed |
| T-05-52 | Repudiation | veraltete Liste nach Jobende | mitigate | Prop `backupJob` als computed aus dem Polling (frontend/src/views/ParentView.vue:232, 375), `watch` + `jobFinished` lädt neu (BackupSection.vue:162-170; backup.js:60-69); Prüfskript frontend/tests/backup.check.mjs:49-61 (in diesem Audit grün) | closed |
| T-05-39 | Repudiation | Selbstbestätigung im e2e | mitigate | Gegenprobe über eigenen `docker.DockerClient`, `api.api.get_archive`/`put_archive` und sqlite3 `?mode=ro` (tests/e2e/backup_helpers.py:26, 135-164; tests/e2e/test_backup_restore_e2e.py:35, 83-84); Grep `DockerProvisioner` in den e2e-Prüfhelfern: nur Docstring-Hinweis "nie über den DockerProvisioner" (test_backup_restore_e2e.py:8) | closed |
| T-05-40 | Tampering | Negativfälle nur im Unit-Test | mitigate | `NEGATIVE_CASES = ("traversal", "symlink", "foreign_preset", "swapped")` plus `test_lua_in_backup_is_dropped_not_installed` gegen echten Proxy, Container-ID, Volume und StartedAt unverändert (tests/e2e/test_backup_restore_e2e.py:75, 351-394, 397); deckt exakt die geplante Liste aus 05-08-PLAN ab; Lauf 7 passed laut 05-08-SUMMARY | closed |
| T-05-41 | Denial of Service | Testreste blockieren Dev-Stack | accept | `docker_cleanup`-Fixture entfernt Container und Volumes der Test-Instanz (tests/conftest.py:592-609), per `pytestmark usefixtures` aktiv (test_backup_restore_e2e.py:62, test_halt_e2e.py:31); siehe AR-05-01 | closed |
| T-05-51 | Repudiation | @halt nur per Lua-String belegt | mitigate | tests/e2e/test_halt_e2e.py:89-135 `test_halt_notice_and_kick` mit Prober gegen echtes Luanti: Chat `TEXT_HALT_SOON` vor Kick `TEXT_HALT`, Prejoin-Ablehnung, Positivkontrolle nach `clear_halt` | closed |
| T-05-42 | Information Disclosure | Zugangsdaten im Skript | accept | Dev-Konten einer Loopback-Instanz (scripts/dev/acceptance-phase5.sh:51-57, 62), Spielpasswörter nur als Länge ausgegeben (acceptance-phase5.sh:26-27, 433, 553); siehe AR-05-02 | closed |
| T-05-43 | Tampering | trap löscht fremde Dateien | mitigate | `OWN_FILE_RE` (acceptance-phase5.sh:69), `dav_delete_own` löscht nur passende Namen (acceptance-phase5.sh:198-201), Ordner nur wenn danach leer (acceptance-phase5.sh:204-213), `DAV_FOLDER` fest auf den Abnahme-Ordner (acceptance-phase5.sh:65), `trap cleanup EXIT` (acceptance-phase5.sh:373) | closed |
| T-05-53 | Information Disclosure | D-13 nur bedingt geprüft | mitigate | Positivkontrolle `gw-admin2` GET /api/worlds 200 und sieht die Welt, dann GET backups leer und Restore 404 (acceptance-phase5.sh:534-545); `reset_fixtures` löscht das Konto im trap (acceptance-phase5.sh:359-363, 370) | closed |
| T-05-44 | Repudiation | Abnahme bestätigt eigene Annahmen | mitigate | Belege über `docker ps/inspect/cp`, WebDAV PROPFIND und sqlite3 `mode=ro` (acceptance-phase5.sh:223, 240-251, 565-620); Negativkontrollen 409 ohne Bestätigung, 409 zweiter Auftrag, 404 fremde/unbekannte file_id (acceptance-phase5.sh:446-463, 545, 585-587); Lauf 96/96 laut 05-09-SUMMARY | closed |
| T-05-45 | Tampering | Welt löschen während Upload-Phase | mitigate | `_refuse_job_running` in `_delete_world_sync` (worlds/service.py:1179-1188, 1408); Tests `test_delete_refused_while_job_runs_in_upload_phase`, `test_api_delete_with_running_job_answers_409` | closed |
| T-05-46 | Repudiation | Kinder ohne Chat-Hinweis getrennt | mitigate | `players_online` liest `read_status_file` + `parse_players` direkt, unabhängig von op_state (worlds/service.py:678-701); Test `test_players_online_reads_status_file_while_busy` | closed |
| T-05-47 | Repudiation | Kinder ohne Chat-Hinweis getrennt (Integration) | mitigate | `announce_halt` vor `stop_for_snapshot` (backup/service.py:337-341, 572-576); Tests `test_backup_with_player_halts_before_stop` (tests/test_backup_service.py:208), `test_restore_with_player_halts_before_stop_while_restoring` | closed |
| T-05-48 | Tampering | Löschen während Upload hinterlässt verwaisten Job | mitigate | `_refuse_job_running` (T-05-45); Integrationstest `test_delete_during_upload_is_refused` (tests/test_backup_service.py:494) mit blockiertem Upload | closed |
| T-05-49 | Repudiation | Snapshot ohne map.sqlite gilt als gültig | mitigate | `write_snapshot` -> `BackupError(MSG_NO_MAP)` (archive.py:241-273); `verify_snapshot` als Probelauf mit `prepare_restore` (archive.py:402-411), aufgerufen in backup/service.py:314 und 618; Tests `test_snapshot_without_map_is_rejected`, `test_snapshot_with_map_as_directory_is_rejected`, `test_snapshot_without_map_is_unusable` | closed |
| T-05-50 | Denial of Service | @halt bleibt nach Restore hängen | mitigate | `clear_halt` in `restore_swap` vor `_payload` (worlds/service.py:786-787), `finish_swap` (812), `abort_offline` (750), `mark_restore_interrupted` (818); Tests `test_restore_swap_renders_rules_without_halt`, `test_finish_swap_keeps_stopped_world_stopped_and_without_halt`, `test_mark_restore_interrupted_is_repeatable_failed_without_halt`, `test_abort_offline_restores_failed_world_without_halt` | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

### Unregistered Flags

Keine. Threat-Flags-Abschnitte in 05-01, 05-03, 05-07 und 05-09-SUMMARY melden ausdrücklich keine neue Angriffsfläche
und verweisen nur auf registrierte IDs; 05-02, 05-04, 05-05, 05-06 und 05-08-SUMMARY haben keinen Threat-Flags-Abschnitt.

### Hinweise ohne Blocker (Qualität, kein offener Threat)

- H-01 (zu T-05-35): ENOSPC beim Schreiben des Restore-Downloads kommt über `download_to` -> `_map_error` als
  `MSG_FILES_FAILED` ("Nextcloud-Dateien sind gerade nicht erreichbar.") statt `MSG_NO_SPACE` an
  (backup/files.py:233-234). Fester Text bleibt, nichts leakt, die Welt ist in Phase A unberührt
  (`abort_offline`); nur die Meldung ist irreführend. Die 3x-Vorabprüfung macht den Fall selten.
- H-02 (zu T-05-25): Die erste Sicherung einer Welt hat keine Platzprüfung (`_check_space` kehrt ohne
  Vorgänger zurück, backup/service.py:361-363); ENOSPC wird dann im Snapshot auf `MSG_NO_SPACE` abgebildet.
- H-03 (zu T-05-03): `MAX_RATIO` greift erst ab `RATIO_FLOOR` 256 MiB entpackt (archive.py:64-66, 324),
  bewusst für kleine SQLite-Welten; die harten Grenzen 8 GiB und 200 000 Einträge gelten immer.
- Offene Review-Infos IN-01 bis IN-07 (05-REVIEW.md) bleiben unverändert; IN-03 (D-09-Race der Spielerprüfung
  vor der Sperre) ist dort als bewusste Abschwächung eingeordnet, Chat-Hinweis und Gnadenfrist greifen weiter.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-05-01 | T-05-41 | Testreste im Dev-Stack: Die `docker_cleanup`-Fixture räumt wie in allen übrigen e2e-Tests Container und Volumes der Test-Instanz ab; betrifft nur den lokalen Dev-Stack, keine Nutzerdaten | Owner (Plan-Disposition 05-08) | 2026-10-24 |
| AR-05-02 | T-05-42 | Dev-Zugangsdaten im Abnahmeskript: reine Dev-Konten einer Loopback-Nextcloud (localhost/127.0.0.1), gleiches Muster wie alle bisherigen Abnahmeskripte; Spielpasswörter werden nie ausgegeben, nur ihre Länge | Owner (Plan-Disposition 05-09) | 2026-10-24 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-24 | 53 | 53 | 0 | gsd-security-auditor (Stand nach WR-01..03, 498 + 71 Tests grün, backup.check.mjs grün, unabhängige Archiv- und Namens-Gegenproben) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-24

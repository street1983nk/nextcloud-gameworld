---
status: resolved
trigger: "Dev-ExApp-Backend (uvicorn Windows-Host, Py 3.13.13, ProactorEventLoop) stirbt sporadisch in Abnahmeläufen: WinError 995 -> ConnectionResetError -> _OverlappedFuture.set_exception -> InvalidStateError in IocpProactor._poll, danach CancelledError im Lifespan."
created: 2026-10-22T08:00:00+02:00
updated: 2026-10-22T13:00:00+02:00
---

## Current Focus

reasoning_checkpoint:
  hypothesis: "Nicht geschlossene niquests-Keep-Alive-Verbindungen (AsyncNextcloudApp pro Aufruf) werden vom GC auch in anyio-Worker-Threads eingesammelt; StreamWriter.__del__ ruft dort transport.close() -> _read_fut.cancel() auf eine laufende overlapped Recv-Future des ProactorEventLoop. CancelIoEx stellt sofort ein 995-Paket zu, _poll sieht die Future noch PENDING, der Worker setzt sie danach auf CANCELLED, set_exception wirft InvalidStateError, die run_forever und damit den Prozess beendet."
  confirming_evidence:
    - "Minimal-Reproduktion (nur stdlib): Off-Thread-Freigabe auf Proactor 10/10 Absturz mit zeilengleichem Traceback (3.13.13 und 3.12.13); gleiche Last im Loop-Thread, mit sauberem close oder auf Selector 0/22"
    - "Instrumentiertes echtes Backend: StreamWriter.__del__ und _OverlappedFuture.cancel (pending, cb=_ProactorReadPipeTransport._loop_reading) im AnyIO worker thread, Gegenstelle 127.0.0.1:8091"
    - "Traceback der beiden Absturz-Logs: Callback finish_socket_func (Recv), nicht connect; CancelledError in sock_connect und Lifespan sind Folge des Loop-Abbruchs"
  falsification_test: "Mit Selector-Loop (keine overlapped Futures) tritt der Absturz unter derselben Last weiter auf, oder im instrumentierten Backend gibt es weiter _OverlappedFuture.cancel-Einträge"
  fix_rationale: "Selector-Loop auf win32 entfernt die overlapped Futures, an denen die Race entsteht; der Off-Thread-Finalizer ruft dort nur _SelectorTransport.close (Reader abmelden, call_soon), das keine Future in einen Endzustand setzt. Linux-Produkt bleibt bei uvicorn loop=auto."
  blind_spots: "Die Leckstelle selbst (nie geschlossene AsyncNextcloudApp-Sessions, teils in nc_py_api intern) bleibt; Off-Thread-close auf Selector/uvloop ist formal nicht threadsicher, unter Linux (3.13.15, selector und uvloop) aber 6/6 ohne Absturz. Eine Positivkontrolle am echten Backend ohne Fix gelang in 15 min Last nicht (63 Off-Thread-Cancels, kein Treffer), das Rennen ist im Backend selten (2 Abstürze in rund 6 Abnahmeläufen)."

hypothesis: bestätigt, siehe Resolution
test: erledigt (Reproduktion, Instrumentierung, Lasttest, Abnahme)
expecting: -
next_action: keine; offene Reste in Resolution

## Symptoms

expected: Backend überlebt komplette Abnahmeläufe (acceptance-phase4_1.sh) ohne Absturz
actual: Backend-Prozess stirbt sporadisch; Requests danach 500 bzw. Verbindung weg
errors: OSError [WinError 995] in finish_socket_func -> ConnectionResetError -> _OverlappedFuture.set_exception -> asyncio.exceptions.InvalidStateError: invalid state (windows_events.py:806 _poll); danach CancelledError im Lifespan
reproduction: sporadisch während acceptance-phase4_1.sh; Logs .dev/logs/exapp-20261022-063636-3004.log, .dev/logs/exapp-20261022-072400-10550.log
started: mindestens seit Phase 4 ("backend vanish run 3")

## Eliminated

- hypothesis: Abgebrochene Client-Verbindungen (curl-Timeouts, AppAPI) lösen den Absturz direkt aus
  evidence: Solche Abbrüche laufen im Loop-Thread; Cancel/Close im Loop-Thread stürzt in der Reproduktion nie ab (drop=loop 7/7, drop=close 5/5). Die betroffene Future ist eine Recv-Future einer ausgehenden Verbindung zu Nextcloud (peer 8091), gecancelt im Worker-Thread.
  timestamp: 2026-10-22T08:50

- hypothesis: Python-Patch-Update behebt es
  evidence: 3.12.13 stürzt in der Reproduktion genauso ab (5/5); CPython main/3.14/3.13 haben dieselbe _poll-Logik; StreamWriter.__del__ schließt in allen den Transport.
  timestamp: 2026-10-22T08:55

- hypothesis: docker-py oder eine Bibliothek startet asyncio-Socket-E/A aus einem Worker-Thread
  evidence: docker-py nutzt eigene Sync-Sockets; im Trace ist es nur der Code, in dem der GC zufällig anspringt. Die Off-Thread-Operation ist der GC-Finalizer StreamWriter.__del__, nicht E/A einer Bibliothek.
  timestamp: 2026-10-22T09:05

## Evidence

- timestamp: 2026-10-22T08:00
  checked: Traceback beider Logs
  found: Die InvalidStateError entsteht in IocpProactor._poll (windows_events.py:806) bei einer Future mit Callback finish_socket_func (recv/send, nicht connect). Die CancelledError am sock_connect (niquests) und im Lifespan tragen die InvalidStateError als Kontext.
  implication: Der Cancel von sock_connect/Lifespan ist Folge (asyncio.run bricht nach Loop-Absturz alle Tasks ab), nicht Ursache. Die Exception tötet den Loop selbst.
  excerpt: |
    (beide Logs gleich; die Logs selbst rotieren aus .dev/logs heraus, Kopie nur im Session-Scratchpad)
    windows_events.py:463 finish_socket_func  return ov.getresult()
    OSError: [WinError 995] Der E/A-Vorgang wurde wegen eines Threadendes oder einer Anwendungsanforderung abgebrochen
    windows_events.py:804 _poll  value = callback(transferred, key, ov)
    windows_events.py:467 finish_socket_func  raise ConnectionResetError(*exc.args)
    base_events.py:2023 _run_once -> windows_events.py:446 select -> :806 _poll  f.set_exception(e)
    windows_events.py:89 set_exception  super().set_exception(exception)
    asyncio.exceptions.InvalidStateError: invalid state
    danach: CancelledError in proactor_events.py:728 sock_connect (niquests, laufender Request -> 500) und in starlette lifespan receive()

- timestamp: 2026-10-22T08:05
  checked: CPython 3.13.13 windows_events.py _poll und _OverlappedFuture
  found: `elif not f.done(): try: value = callback(...) except OSError as e: f.set_exception(e)`. Zwischen done-Prüfung und set_exception läuft nur der Callback (ov.getresult(), Exception-Erzeugung). InvalidStateError dort ist nicht abgefangen.
  implication: Future muss während des Callbacks den Zustand wechseln; nur möglich durch Code, der dazwischen läuft (GC-Finalizer, Signal-Handler, anderer Thread).

- timestamp: 2026-10-22T08:20
  checked: Websuche CPython-Issues (bpo-33834, bpo-35682, bpo-39010, bpo-23095), Wingman-AI PR #483
  found: Kein CPython-Issue mit genau diesem Pfad (_poll -> _OverlappedFuture.set_exception -> InvalidStateError) gefunden. Wingman-AI PR #483 beschreibt denselben Traceback als Folge eines Socket-Close/Read-Cancel aus einem anderen Thread, Workaround dort per eigener Loop-Policy.
  implication: Thread-übergreifender Cancel ist Kandidat Nr. 1.

- timestamp: 2026-10-22T08:25
  checked: CPython 3.13.13 streams.py / proactor_events.py
  found: StreamWriter.__del__ ruft self.close() -> _ProactorBasePipeTransport.close() -> self._read_fut.cancel() synchron. Proactor-Transporte haben im Leerlauf immer eine laufende overlapped Recv-Future. Der Transport referenziert den StreamWriter nicht (Client-Pfad open_connection), der Writer kann also eingesammelt werden, während der Transport über den IOCP-Cache lebt.
  implication: Ein nicht geschlossener StreamWriter, der in einem Worker-Thread freigegeben wird (Refcount oder zyklischer GC laufen im gerade allozierenden Thread), cancelt die Recv-Future am Loop vorbei. CancelIoEx erzeugt sofort ein 995-Paket; _poll im Loop-Thread sieht die Future noch PENDING, der Worker setzt sie danach auf CANCELLED -> InvalidStateError.

- timestamp: 2026-10-22T08:30
  checked: src/gameworld (grep) und nc_py_api 0.30.3 _session.py
  found: AsyncNextcloudApp() wird pro Aufruf neu gebaut und nie geschlossen (access/directory.py:60,77, access/roles.py:51, talk/rooms.py:113, talk/bot.py:88,104, notify/service.py:32; nc_py_api integration_fastapi.py:368 pro Request). Jede Instanz hat eine niquests AsyncSession mit Keep-Alive-Pool (urllib3-future AsyncSocket -> asyncio.open_connection). Gleichzeitig laufen viele anyio.to_thread-Worker (Store, Docker). Keine asyncio-Subprozesse im Code.
  implication: Verwaiste Keep-Alive-Verbindungen werden regelmäßig per GC eingesammelt, oft in Worker-Threads.

- timestamp: 2026-10-22T08:45
  checked: Minimal-Reproduktion .planning/debug/repro_proactor_offthread_cancel.py (nur stdlib), Matrix per run_repro_matrix.sh, je 5 Läufe à 500 Verbindungen
  found: |
    py 3.13.13 proactor, Writer im Worker-Thread freigegeben: 5/5 CRASH InvalidStateError (nach 0.0 bis 0.2 s), Traceback zeilengleich mit den Backend-Logs (windows_events.py 463 -> 804/467 -> 806 -> 89)
    py 3.13.13 proactor, Writer im Loop-Thread freigegeben: 5/5 OK (zusätzlich 2/2 in erster Serie)
    py 3.13.13 proactor, Writer vorher sauber geschlossen: 5/5 OK
    py 3.13.13 selector, Writer im Worker-Thread freigegeben: 5/5 OK
    py 3.12.13 proactor, Worker-Thread: 5/5 CRASH; Loop-Thread: 5/5 OK
    (Erste Serie mit 5000 Verbindungen pro Lauf scheiterte teils an Port-Erschöpfung WinError 10048/52, kein Befund zum Bug; daher 500 pro Lauf und Warten auf TIME_WAIT)
  implication: Ursache-Mechanismus belegt. Off-Thread-Freigabe eines offenen StreamWriter auf Proactor ist hinreichend; gleiche Last auf Selector oder im Loop-Thread stürzt nicht ab. Kein Python-Patch-Unterschied (3.12.13 und 3.13.13 gleich).

- timestamp: 2026-10-22T08:50
  checked: --who-Instrumentierung der Reproduktion (Stack des ersten Off-Thread-Cancels)
  found: worker-Thread: streams.py StreamWriter.__del__ -> StreamWriter.close -> proactor_events.py:111 _read_fut.cancel() (3.12.13 Zeile 415, 3.13.13 Zeile 409)
  implication: Exakt der vermutete Pfad. Frühere Notiz "3.12 hat kein StreamWriter.__del__" war falsch (grep-Muster auf 3.13-Signatur), korrigiert.

- timestamp: 2026-10-22T08:55
  checked: CPython main, 3.14, 3.13 windows_events.py (raw.githubusercontent.com)
  found: main hat _poll in _process_completion_status ausgelagert (gh-154971), die Logik `elif not f.done(): ... f.set_exception(e)` ist unverändert; 3.13-Zweig = lokale 3.13.13 bis auf sendfile-Seek
  implication: Kein CPython-Fix verfügbar; Python-Patch-Update ist kein Fix. Aus CPython-Sicht ist ein Future-Cancel aus fremdem Thread ohnehin unzulässig (asyncio nicht threadsicher); der Auslöser ist der GC-Finalizer im fremden Thread.

- timestamp: 2026-10-22T08:20 bis 09:00
  checked: Absturz-Logs gesichert (Rotation hält nur 20) nach scratchpad/evidence-logs; nextcloud.log AppAPI "Failed to connect ... port 10040" pro Minute
  found: Bursts 2026-10-22 04:35 UTC und 05:22-05:23 UTC = die beiden heutigen Abstürze; 2026-10-21 14:29-14:37 UTC = Phase-4-Lauf 3 ("backend vanish") mit gleicher Burst-Form
  implication: Phase-4-Ausfall zeigt dieselbe AppAPI-Signatur; Traceback damals nicht erhalten.

- timestamp: 2026-10-22T09:05
  checked: instrumentierter Abnahmelauf vor dem Fix (sitecustomize, beobachtend), .dev/exapp.log
  found: "GWTRACE OFFTHREAD StreamWriter.__del__ thread=AnyIO worker thread transport_closing=False", Stack im Worker = docker-py (requests/sessions.py -> urllib3 sync read), GC löst dort den Finalizer aus; direkt danach "_OverlappedFuture.cancel thread=AnyIO worker thread future=<_OverlappedFuture pending cb=[_ProactorReadPipeTransport._loop_reading()]>" über streams.py:409 -> proactor_events.py:111
  implication: Der in der Minimal-Reproduktion belegte Mechanismus tritt im echten Backend während der Abnahme auf (Off-Thread-Cancel einer laufenden Proactor-Recv-Future).

- timestamp: 2026-10-22T08:47
  checked: Ende des instrumentierten Laufs (scratchpad/acc-prefix-instrumented.log, Backend-Logs 08:14 bis 08:43)
  found: 17x StreamWriter.__del__ und 14x _OverlappedFuture.cancel im AnyIO-Worker-Thread; jede protokollierte Gegenstelle peer=('127.0.0.1', 8091) = Dev-Nextcloud; kein Absturz in diesem Lauf. Lauf 126/128: Regression scheiterte an "ABBRUCH: Konto gw-abnahme2 ließ sich nicht anlegen" (occ user:add im NC-Container, nicht Backend); derselbe occ-Aufruf von Hand danach erfolgreich (angelegt und wieder gelöscht).
  implication: Die off-thread finalisierten Writer sind die Keep-Alive-Verbindungen der nie geschlossenen AsyncNextcloudApp-Sessions. Das Rennen trifft nur selten (GIL-Wechsel genau zwischen done-Prüfung und set_exception), passend zu 2 Abstürzen in rund 6 Läufen. Der occ-Fehlschlag ist ein separater, transienter Befund (vermutlich Altkonto aus einem abgebrochenen Lauf), im Lauf nach dem Fix beobachten.

- timestamp: 2026-10-22T09:00
  checked: Linux-Gegenprobe im Wegwerf-Container python:3.13-slim-trixie (Python 3.13.15, uvloop 0.23.0 wie uv.lock), Reproduktion mit Off-Thread-Freigabe, 2000 Verbindungen pro Lauf
  found: selector 3/3 OK, uvloop 3/3 OK
  implication: Im Produkt (Linux, uvicorn loop=auto = uvloop) tritt der Absturz unter derselben Last nicht auf. Die Leckstelle (nicht geschlossene Sessions, Finalizer im fremden Thread) bleibt formal unsauber, ist aber kein Absturzpfad.

- timestamp: 2026-10-22T09:35
  checked: Lasttest stress_invites.sh 900 s, 6 parallel (POST invites + GET worlds + GET players über AppAPI-Proxy), Stand ohne Fix (git stash), instrumentiert
  found: 1620x HTTP 200, kein Absturz; 329x StreamWriter.__del__ und 63x _OverlappedFuture.cancel im Worker-Thread
  implication: Positivkontrolle am echten Backend in 15 min nicht erreicht; das Rennen trifft selten. Mechanismus aber erneut beobachtet (63 riskante Off-Thread-Cancels).

- timestamp: 2026-10-22T09:40
  checked: Verstärker sys.setswitchinterval(1e-5) in der Reproduktion
  found: proactor/thread 0/3 Absturz (mit Standard 0.005 10/10), Kontrollen 9/9 OK
  implication: Kleines GIL-Intervall verhindert das Rennen eher; kein brauchbarer Verstärker. Die Race hängt am GIL-Wechsel zwischen Worker (nach CancelIoEx) und Loop-Thread.

- timestamp: 2026-10-22T11:20
  checked: Lasttest mit Fix (erster Versuch), Windows-Ereignisprotokoll (Power-Troubleshooter, Kernel-Power 42/506/507)
  found: Backend-Loop laut GWTRACE asyncio.windows_events._WindowsSelectorEventLoop; 170x StreamWriter.__del__ im Worker-Thread, 0x _OverlappedFuture.cancel; Backend lebt. Aber: Rechner im Standby 09:22:38 bis 11:16:27 mitten im Lauf; 14x HTTP 000 und NC-408 alle beim Aufwachen 11:16:26.
  implication: Struktureller Nachweis (keine overlapped Futures mehr, Finalizer laufen weiter harmlos) erbracht; Durchsatz-/Fehlervergleich dieses Laufs ungültig wegen Standby, Lauf wird wiederholt.

- timestamp: 2026-10-22T11:33
  checked: Lasttest mit Fix, zweiter Versuch 11:18:06 bis 11:33:16 (System per SetThreadExecutionState wach gehalten; Ereignisprotokoll ohne Kernel-Power 42/107/506/507 im Fenster)
  found: 1647x HTTP 200 (ohne Fix 1620), 0x 000, Backend lebt; 225x StreamWriter.__del__ im Worker-Thread, 0x _OverlappedFuture.cancel; im Log nur die bekannten periodischen "Talk-Bot nicht registriert" und ein Talk-408 für die Welt des Standby-Laufs
  implication: Gleiche Last ohne Absturz, ohne Fehler, ohne Durchsatzverlust. Die Off-Thread-Finalizer finden weiter statt, treffen aber keine overlapped Future mehr.

- timestamp: 2026-10-22T12:13
  checked: voller acceptance-phase4_1.sh mit Fix, ohne Instrumentierung, 11:34:45 bis 12:13:38 (scratchpad/acc-postfix.log)
  found: 126/128, Exit 1. Phase 4.1 komplett grün (122 bestanden); Regression: "K6 fünfmal Sitzung held und Join nach 0,2 s denied mit 'einen Moment warten' (ist 4 von 5)" in acceptance-phase4.sh; Phase 1 bis 3 grün. Backend-Logs des Laufs: 0 Traceback, 0 ERROR, 0 HTTP 500, kein InvalidStateError.
  implication: Kein Backend-Ausfall. K6-Rejoin-Sperre ist ein reiner Luanti/UDP-Timingtest (Prober direkt gegen den Welt-Container, sleep 0.2), Backend nicht im Pfad. Lauf wird wiederholt.

- timestamp: 2026-10-22T12:53
  checked: voller acceptance-phase4_1.sh mit Fix, zweiter Lauf, ohne Instrumentierung, 12:14:27 bis 12:52:52 (scratchpad/acc-postfix2.log)
  found: "128 von 128 Prüfungen bestanden", Exit 0; Regression acceptance-phase4.sh Exit 0 (109 von 109), darin 84/84, 104/104, 75/75. Alle acht Backend-Logs des Laufs ohne Traceback, ERROR oder HTTP 500. Kein Standby im Fenster.
  implication: Abnahme grün mit Fix.

- timestamp: 2026-10-22T12:58
  checked: Windows-Anwendungsprotokoll (1000/1001/1026) zu den heutigen, belegten Abstürzen 06:35 und 07:22
  found: kein Absturz-Event der ExApp (nur drei fremde LiveKernelEvent um 06:25)
  implication: Ein Python-Ende per unbehandelter InvalidStateError hinterlässt kein WER-Event. Genau das fand p4-regression-500 für den Phase-4-Ausfall ("kein Absturz-Event 1000/1001"). Zusammen mit "Backend antwortete selbst noch mit 500 und verschwand Sekunden danach" und derselben AppAPI-Burst-Form: gleiche Signatur.

## Resolution

root_cause: |
  Nicht geschlossene niquests-Keep-Alive-Verbindungen (AsyncNextcloudApp wird pro Aufruf neu gebaut und nie geschlossen: access/directory.py, access/roles.py, talk/rooms.py, talk/bot.py, notify/service.py, dazu nc_py_api intern) werden vom zyklischen GC eingesammelt, und zwar in dem Thread, der gerade alloziert, oft ein anyio-Worker (Store, docker-py). StreamWriter.__del__ (CPython 3.12/3.13/main) ruft dort transport.close(); beim ProactorEventLoop cancelt das die laufende overlapped Recv-Future am Loop vorbei (proactor_events.py:111). CancelIoEx liefert sofort ein Paket mit WinError 995; IocpProactor._poll im Loop-Thread sieht die Future noch PENDING, ruft finish_socket_func, und während des GIL-Wechsels setzt der Worker die Future auf CANCELLED. set_exception wirft InvalidStateError, die _poll nicht abfängt; run_forever bricht ab, asyncio.run cancelt alle Tasks (CancelledError in sock_connect und Lifespan), der Prozess endet. Kein CPython-Fix vorhanden (main unverändert); aus asyncio-Sicht ist ein Cancel aus fremdem Thread unzulässig, der Auslöser ist der Finalizer im fremden Thread.
fix: |
  src/gameworld/main.py: uvicorn startet über run_app(..., loop=_uvicorn_loop()) mit "asyncio:SelectorEventLoop", wenn sys.platform == "win32", sonst "auto" (Linux-Container unverändert, uvloop). Der Selector-Loop hat keine overlapped Futures, der Off-Thread-Finalizer meldet dort nur den Reader ab und plant connection_lost per call_soon. Der Code nutzt keine asyncio-Subprozesse (grep src: kein subprocess/create_subprocess), docker-py läuft synchron in Threads. Test tests/test_startup_loop.py (Plattformwahl, uvicorn lädt die Factory). Commit 0c448fc.
verification: |
  Minimal-Reproduktion .planning/debug/repro_proactor_offthread_cancel.py: Proactor + Worker-Thread 10/10 Absturz (3.13.13, 3.12.13), Selector + Worker-Thread 5/5 OK, Loop-Thread/close 12/12 OK; Linux 3.13.15 selector/uvloop 6/6 OK.
  Echtes Backend instrumentiert: vor dem Fix 63 Off-Thread-Cancels in 15 min Last (kein Treffer), mit Fix loop=_WindowsSelectorEventLoop, 225 Off-Thread-Finalizer, 0 overlapped Cancels, 1647x HTTP 200, Backend lebt.
  Gates: ruff check, ruff format --check, pyright src (0 Fehler), vulture, pytest -m "not docker" 1201 passed.
  Abnahme: acceptance-phase4_1.sh 128/128 Exit 0 (Lauf 12:14 bis 12:52, Log C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\acc-postfix2.log). Vorlauf 11:34 bis 12:13: 126/128, einzig Luanti-Timingtest K6 Rejoin-Sperre 4/5, Backend ohne Fehler.
  Phase 4 "backend vanish" (Lauf 3, 21.10.): gleiche Signatur (500 aus dem Backend selbst, dann weg; kein WER-Event; gleiche AppAPI-Burst-Form; gleiche Umgebung Windows-Host, Proactor, Python 3.13, AsyncNextcloudApp-Muster seit Phase 3). Traceback damals nicht erhalten, daher sehr wahrscheinlich dieselbe Ursache, nicht direkt belegt.
open_rest: |
  - Leck selbst: AsyncNextcloudApp-Sessions werden nie geschlossen (eigener Code und nc_py_api intern, z. B. integration_fastapi.py:59 Handler-Dependency, talk_bot.py:395). Kein Absturzpfad mehr (Windows Selector, Linux selector/uvloop ohne Absturz), aber Verbindungen bleiben bis zum GC offen und Finalizer laufen in fremden Threads. Kandidat für Phase-6-Härtung (Owner-Entscheid): Sessions schließen oder eine Session wiederverwenden; nc_py_api bietet kein öffentliches close.
  - Abnahme-Flakes ohne Backend-Bezug: K6 Rejoin-Sperre 4/5 (Luanti/UDP-Timing, sleep 0.2) und einmal "Konto gw-abnahme2 ließ sich nicht anlegen" (occ, danach von Hand ok).
  - Beobachtung: acceptance-phase4_1.sh prüft "Log enthält '84 von 84 ...'" per grep auf phase4.log; die Zeichenkette steht dort auch in der FEHLGESCHLAGEN-Zeile von Phase 4, die Prüfung kann daher falsch grün sein (im Lauf 08:13 sichtbar).
files_changed: [src/gameworld/main.py, tests/test_startup_loop.py]

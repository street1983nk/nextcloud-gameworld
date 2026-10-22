# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## backend-windows-invalidstate: ExApp-Host-Prozess stirbt unter Windows mit InvalidStateError im Proactor
- **Date:** 2026-10-22
- **Error patterns:** InvalidStateError, invalid state, WinError 995, ConnectionResetError, _OverlappedFuture, set_exception, IocpProactor, _poll, windows_events, CancelledError, lifespan, backend vanish, Port 10040, HTTP 500, AppAPI Failed to connect
- **Root cause:** Nie geschlossene niquests-Keep-Alive-Verbindungen (AsyncNextcloudApp pro Aufruf) werden vom GC in anyio-Worker-Threads eingesammelt; StreamWriter.__del__ ruft dort transport.close() und cancelt die laufende overlapped Recv-Future des ProactorEventLoop am Loop vorbei; IocpProactor._poll sieht sie noch PENDING und scheitert bei set_exception mit InvalidStateError, die run_forever beendet.
- **Fix:** uvicorn startet auf win32 mit asyncio:SelectorEventLoop (main.py _uvicorn_loop), Linux bleibt bei loop=auto; Commit 0c448fc.
- **Files changed:** src/gameworld/main.py, tests/test_startup_loop.py
---


"""Minimal-Reproduktion: InvalidStateError in IocpProactor._poll.

Mechanismus (Hypothese): Ein nicht geschlossener asyncio.StreamWriter wird in
einem fremden Thread freigegeben. StreamWriter.__del__ ruft transport.close(),
das cancelt die laufende overlapped Recv-Future am Event-Loop vorbei.
CancelIoEx stellt sofort ein Paket mit WinError 995 in den Completion-Port;
_poll im Loop-Thread sieht die Future noch als PENDING, ruft den Callback, und
bevor set_exception läuft, setzt der fremde Thread die Future auf CANCELLED.

Aufruf (nur stdlib):
  uv run --no-project --python 3.13 python -I repro_proactor_offthread_cancel.py \
      --loop proactor --drop thread

--loop  proactor | selector | uvloop (uvloop nur in der Linux-Gegenprobe)
--drop  thread  Writer im Worker-Thread freigeben (wie GC in anyio.to_thread)
        loop    Writer im Loop-Thread freigeben (Negativkontrolle)
        close   Writer vor dem Freigeben sauber im Loop schließen (Negativkontrolle)
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
import threading
import time
import traceback
import warnings

warnings.simplefilter("ignore", ResourceWarning)


async def _serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    # Hält die Verbindung offen wie ein Keep-Alive-Server, ohne zu senden.
    try:
        await reader.read()
    except OSError:
        pass
    finally:
        writer.close()


async def _busy(stop: asyncio.Event) -> None:
    # Hält den Loop beschäftigt, damit _poll oft mit Timeout 0 läuft und den
    # GIL zwischen den Paketen hält.
    while not stop.is_set():
        await asyncio.sleep(0)


async def run(drop: str, rounds: int, conns: int) -> int:
    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    stop = asyncio.Event()
    busy = asyncio.create_task(_busy(stop))
    for _ in range(rounds):
        holder: list[asyncio.StreamWriter] = []
        for _ in range(conns):
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
            holder.append(writer)
            del _reader, writer
        # Alle Transporte haben jetzt eine laufende overlapped Recv-Future.
        await asyncio.sleep(0.01)
        if drop == "thread":
            worker = threading.Thread(target=holder.clear, name="worker")
            worker.start()
            while worker.is_alive():
                await asyncio.sleep(0)
            worker.join()
        elif drop == "loop":
            holder.clear()
        else:
            for writer in holder:
                writer.close()
            holder.clear()
        await asyncio.sleep(0.01)
    stop.set()
    await busy
    server.close()
    await server.wait_closed()
    return rounds * conns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", choices=["proactor", "selector", "uvloop"], default="proactor")
    parser.add_argument("--drop", choices=["thread", "loop", "close"], default="thread")
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--conns", type=int, default=50)
    parser.add_argument("--switch", type=float, default=0.0, help="sys.setswitchinterval, 0 = Standard")
    parser.add_argument("--trace", action="store_true", help="Traceback des Absturzes ausgeben")
    parser.add_argument("--who", action="store_true", help="Stack des ersten Cancels aus fremdem Thread ausgeben")
    args = parser.parse_args()
    if args.who and sys.platform == "win32":
        from asyncio import windows_events

        original_cancel = windows_events._OverlappedFuture.cancel
        seen: list[bool] = []

        def traced_cancel(self, msg=None):  # type: ignore[no-untyped-def]
            if threading.current_thread() is not threading.main_thread() and not seen:
                seen.append(True)
                print(f"ERSTER CANCEL IM THREAD {threading.current_thread().name}:", file=sys.stderr)
                traceback.print_stack(limit=12)
            return original_cancel(self, msg=msg)

        windows_events._OverlappedFuture.cancel = traced_cancel  # type: ignore[method-assign]
    if args.switch:
        sys.setswitchinterval(args.switch)
    if args.loop == "uvloop":
        import uvloop  # nur in der Linux-Gegenprobe installiert

        factory = uvloop.new_event_loop
    elif args.loop == "proactor":
        factory = asyncio.ProactorEventLoop
    else:
        factory = asyncio.SelectorEventLoop
    label = (
        f"python={platform.python_version()} loop={args.loop} drop={args.drop} "
        f"rounds={args.rounds} conns={args.conns} switch={sys.getswitchinterval()}"
    )
    start = time.monotonic()
    try:
        with asyncio.Runner(loop_factory=factory) as runner:
            done = runner.run(run(args.drop, args.rounds, args.conns))
    except asyncio.InvalidStateError as exc:
        print(f"CRASH InvalidStateError {exc!r} nach {time.monotonic() - start:.1f}s | {label}")
        if args.trace:
            traceback.print_exc()
        return 1
    except BaseException as exc:  # noqa: BLE001 - jede andere Abbruchart ehrlich melden
        print(f"ANDERER FEHLER {type(exc).__name__}: {exc!r} | {label}")
        return 2
    print(f"OK {done} Verbindungen verworfen in {time.monotonic() - start:.1f}s | {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

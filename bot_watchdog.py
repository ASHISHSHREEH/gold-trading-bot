"""
Watchdog for main_mt5.py.

Start the bot via:
    python bot_watchdog.py

The watchdog:
- Launches main_mt5.py under the repo's venv python, streaming stdout.
- Checks data/restart_request.flag every 5 s.
  If found: deletes it, gracefully terminates the bot, waits 5 s, relaunches.
- If the bot crashes on its own: relaunches after 10 s.
- Ctrl+C: terminates bot cleanly and exits.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR    = Path(__file__).parent
SCRIPT      = BASE_DIR / "main_mt5.py"
FLAG_PATH   = BASE_DIR / "data" / "restart_request.flag"

POLL_INTERVAL         = 5   # seconds between flag checks
CRASH_RELAUNCH_WAIT   = 10  # seconds to wait after an unplanned exit
RESTART_RELAUNCH_WAIT = 5   # seconds to wait after a requested restart
GRACEFUL_TIMEOUT      = 15  # seconds before escalating terminate→kill


def _find_python() -> str:
    """Return the venv python if it exists, otherwise fall back to sys.executable."""
    candidates = [
        BASE_DIR / "venv"  / "Scripts" / "python.exe",  # Windows venv
        BASE_DIR / "venv"  / "bin"     / "python",       # Unix venv
        BASE_DIR / ".venv" / "Scripts" / "python.exe",
        BASE_DIR / ".venv" / "bin"     / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable


def _stream(proc: subprocess.Popen) -> None:
    """Daemon thread: copy proc stdout → our stdout line by line."""
    # sentinel is "" (str) because Popen runs in text mode (Fix D)
    # for raw in iter(proc.stdout.readline, b""):          # [pre-fix] binary mode
    #     sys.stdout.write(raw.decode(errors="replace"))   # [pre-fix]
    for line in iter(proc.stdout.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()


def _terminate(proc: subprocess.Popen) -> None:
    """Ask the process to exit; escalate to SIGKILL after GRACEFUL_TIMEOUT."""
    if proc.poll() is not None:
        return
    print("[watchdog] SIGTERM → bot ...", flush=True)
    proc.terminate()
    try:
        proc.wait(timeout=GRACEFUL_TIMEOUT)
        print("[watchdog] Bot exited cleanly.", flush=True)
    except subprocess.TimeoutExpired:
        print("[watchdog] Timeout — SIGKILL.", flush=True)
        proc.kill()
        proc.wait()


def _launch(python: str) -> subprocess.Popen:
    """Start main_mt5.py and wire up a stdout-streaming thread."""
    proc = subprocess.Popen(
        [python, str(SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",       # Fix D: text mode — arrows/dashes render correctly
        errors="replace",
        cwd=str(BASE_DIR),
    )
    threading.Thread(target=_stream, args=(proc,), daemon=True).start()
    return proc


def main() -> None:
    python = _find_python()
    print(f"[watchdog] Python : {python}", flush=True)
    print(f"[watchdog] Script : {SCRIPT}", flush=True)
    print(f"[watchdog] Flag   : {FLAG_PATH}", flush=True)
    print(f"[watchdog] Poll   : every {POLL_INTERVAL}s", flush=True)

    proc = _launch(python)
    print(f"[watchdog] Bot started  PID={proc.pid}", flush=True)

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            # ── Restart flag ───────────────────────────────────────────────────
            if FLAG_PATH.exists():
                print("[watchdog] Restart flag detected.", flush=True)
                try:
                    FLAG_PATH.unlink()
                except OSError:
                    pass
                _terminate(proc)
                print(
                    f"[watchdog] Waiting {RESTART_RELAUNCH_WAIT}s before relaunch …",
                    flush=True,
                )
                time.sleep(RESTART_RELAUNCH_WAIT)
                proc = _launch(python)
                print(f"[watchdog] Bot relaunched  PID={proc.pid}", flush=True)
                continue

            # ── Crash / unexpected exit ────────────────────────────────────────
            rc = proc.poll()
            if rc is not None:
                print(
                    f"[watchdog] Bot exited unexpectedly (code={rc}). "
                    f"Relaunching in {CRASH_RELAUNCH_WAIT}s …",
                    flush=True,
                )
                time.sleep(CRASH_RELAUNCH_WAIT)
                proc = _launch(python)
                print(f"[watchdog] Bot relaunched  PID={proc.pid}", flush=True)

    except KeyboardInterrupt:
        print("\n[watchdog] Ctrl+C — shutting down …", flush=True)
        _terminate(proc)
        print("[watchdog] Done.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()

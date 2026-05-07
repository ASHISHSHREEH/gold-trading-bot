"""
mt5_debug.py — diagnose MT5 connection issues.
Run: python mt5_debug.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    import MetaTrader5 as mt5
    print(f"[OK] MetaTrader5 package version : {mt5.__version__}")
except ImportError:
    print("[FAIL] MetaTrader5 not installed — run: pip install MetaTrader5")
    sys.exit(1)

login    = int(os.getenv("MT5_LOGIN", "0"))
password = os.getenv("MT5_PASSWORD", "")
server   = os.getenv("MT5_SERVER", "")
path     = os.getenv("MT5_PATH", "")

print(f"[INFO] Login    : {login}")
print(f"[INFO] Server   : {server}")
print(f"[INFO] Path     : {path or '(not set)'}")
print()

# ── Test 1: no path, no credentials (auto-connect to running terminal) ─────────
print("Test 1: auto-connect (no path, no credentials)...")
if mt5.initialize():
    a = mt5.account_info()
    print(f"  [OK] Connected! Account={a.login} Balance={a.balance} {a.currency}")
    mt5.shutdown()
    print("\nFix: remove MT5_PATH from your .env — auto-connect works fine.")
    sys.exit(0)
else:
    print(f"  [FAIL] {mt5.last_error()}")

# ── Test 2: credentials only, no path ──────────────────────────────────────────
print("Test 2: credentials only (no path)...")
if mt5.initialize(login=login, password=password, server=server):
    a = mt5.account_info()
    print(f"  [OK] Connected! Account={a.login} Balance={a.balance} {a.currency}")
    mt5.shutdown()
    print("\nFix: remove MT5_PATH from your .env.")
    sys.exit(0)
else:
    print(f"  [FAIL] {mt5.last_error()}")

# ── Test 3: full credentials + path ────────────────────────────────────────────
if path:
    print(f"Test 3: full init with path={path}...")
    # Check file exists first
    if not os.path.exists(path):
        print(f"  [FAIL] File not found: {path}")
        print("  The MT5_PATH in your .env is wrong.")
    else:
        print(f"  [OK] File exists.")
        if mt5.initialize(path=path, login=login, password=password, server=server):
            a = mt5.account_info()
            print(f"  [OK] Connected! Account={a.login} Balance={a.balance} {a.currency}")
            mt5.shutdown()
            sys.exit(0)
        else:
            print(f"  [FAIL] {mt5.last_error()}")

# ── Test 4: search common FxPro install locations ──────────────────────────────
print("\nTest 4: searching common install locations...")
candidates = [
    r"C:\Program Files\FxPro - MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\FxPro - MetaTrader 5\terminal64.exe",
    r"C:\Users\aashs\AppData\Local\FxPro - MetaTrader 5\terminal64.exe",
    r"C:\Users\aashs\AppData\Roaming\FxPro - MetaTrader 5\terminal64.exe",
    r"C:\Users\aashs\AppData\Local\Programs\FxPro - MetaTrader 5\terminal64.exe",
    r"C:\MetaTrader5\terminal64.exe",
]
found = False
for p in candidates:
    exists = os.path.exists(p)
    mark   = "[FOUND]" if exists else "[ --- ]"
    print(f"  {mark} {p}")
    if exists and not found:
        found = True
        print(f"  Trying to connect with this path...")
        if mt5.initialize(path=p, login=login, password=password, server=server):
            a = mt5.account_info()
            print(f"  [OK] Connected! Account={a.login} Balance={a.balance} {a.currency}")
            print(f"\nFix: set MT5_PATH={p} in your .env")
            mt5.shutdown()
            sys.exit(0)
        else:
            print(f"  [FAIL] {mt5.last_error()}")

print()
print("=" * 60)
print("All connection attempts failed.")
print()
print("Checklist:")
print("  1. Is MT5 fully loaded with live charts visible?")
print("  2. Is MT5 running as Administrator?")
print("     If yes: right-click MT5 shortcut → Properties →")
print("     Compatibility → UNCHECK 'Run as administrator'")
print("  3. Is Python also running as Administrator?")
print("     Both must run under the same privilege level.")
print("  4. In MT5: Tools → Options → Expert Advisors →")
print("     CHECK 'Allow automated trading'")
print("  5. Try: pip install --upgrade MetaTrader5")
print("=" * 60)

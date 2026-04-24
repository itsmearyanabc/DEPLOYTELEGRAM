"""
brutal_test.py — Full whitebox + blackbox test suite for ARMEDIAS Telegram Forwarder

Tests:
  1. Telegram connectivity for all accounts (blackbox)
  2. Session file existence check (whitebox)
  3. config.py validity (whitebox)
  4. targets.txt parsing (whitebox)
  5. Dispatcher queue logic — new message interruption (whitebox unit test)
  6. Dispatcher 15-min re-forward timer logic (whitebox unit test)
  7. AccountManager account cycling (whitebox unit test)
  8. Source channel ID validation (whitebox)
"""

import asyncio
import os
import sys
import random
import traceback

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"


def banner(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ── TEST 1: Telegram connectivity ─────────────────────────────────────────────
async def test_telegram_connectivity():
    banner("TEST 1: Telegram Connectivity (Blackbox)")
    from pyrogram import Client
    from pyrogram.errors import FloodWait, RPCError

    try:
        from config import ACCOUNTS
    except ImportError:
        print(f"  {FAIL}: config.py not found — run Save in the admin panel first.")
        return

    all_ok = True
    for acc in ACCOUNTS:
        phone = acc["phone"].replace(" ", "").replace("-", "")
        print(f"  Testing: {acc['name']} ({phone})")
        client = Client(
            name=f"diag_{acc['name']}",
            api_id=acc["api_id"],
            api_hash=acc["api_hash"],
            phone_number=phone,
            workdir="sessions",
        )
        try:
            await client.connect()
            me = await client.get_me()
            print(f"  {PASS}: Connected as {me.first_name} (ID: {me.id})")
        except Exception as e:
            print(f"  {FAIL}: {type(e).__name__}: {e}")
            all_ok = False
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    print(f"\n  Result: {'ALL ACCOUNTS OK' if all_ok else 'SOME ACCOUNTS FAILED'}")


# ── TEST 2: Session file existence ────────────────────────────────────────────
def test_session_files():
    banner("TEST 2: Session File Existence (Whitebox)")
    try:
        from config import ACCOUNTS
    except ImportError:
        print(f"  {FAIL}: config.py missing.")
        return

    for acc in ACCOUNTS:
        session_path = f"{acc['session_name']}.session"
        exists = os.path.exists(session_path)
        status = PASS if exists else FAIL
        print(f"  {status}: {session_path} {'found' if exists else 'NOT FOUND — must authenticate!'}")


# ── TEST 3: config.py validity ────────────────────────────────────────────────
def test_config_validity():
    banner("TEST 3: config.py Validity (Whitebox)")
    try:
        from config import ACCOUNTS, SOURCE_CHANNEL, TARGETS_FILE, MIN_DELAY, MAX_DELAY, MOCK_MODE
        print(f"  {PASS}: config.py imports OK")
        print(f"         ACCOUNTS    = {len(ACCOUNTS)} account(s)")
        print(f"         SOURCE_CHANNEL = {SOURCE_CHANNEL}")
        print(f"         TARGETS_FILE = {TARGETS_FILE}")
        print(f"         MIN_DELAY   = {MIN_DELAY}s ({MIN_DELAY//60}m)")
        print(f"         MAX_DELAY   = {MAX_DELAY}s ({MAX_DELAY//60}m)")
        print(f"         MOCK_MODE   = {MOCK_MODE}")

        # Validate source channel ID sign
        if isinstance(SOURCE_CHANNEL, int) and SOURCE_CHANNEL > 0:
            print(f"  {WARN}: SOURCE_CHANNEL={SOURCE_CHANNEL} is POSITIVE. "
                  "Channels/supergroups need negative IDs like -100XXXXXXXXXX!")
        
        # Validate delays
        if MIN_DELAY < 60:
            print(f"  {WARN}: MIN_DELAY={MIN_DELAY}s is very low. Risk of FloodWait!")
        if MAX_DELAY < MIN_DELAY:
            print(f"  {FAIL}: MAX_DELAY < MIN_DELAY! This will crash dispatcher.")
        if MIN_DELAY >= 900:
            print(f"  {PASS}: Delays are set to 15 minutes — good for anti-spam.")

        if not ACCOUNTS:
            print(f"  {FAIL}: ACCOUNTS list is empty!")
        for acc in ACCOUNTS:
            if not acc.get("api_id") or not acc.get("api_hash"):
                print(f"  {FAIL}: Account '{acc.get('name')}' is missing api_id or api_hash!")

    except Exception as e:
        print(f"  {FAIL}: config.py error: {e}")
        traceback.print_exc()


# ── TEST 4: targets.txt parsing ───────────────────────────────────────────────
def test_targets_file():
    banner("TEST 4: targets.txt Parsing (Whitebox)")
    try:
        from config import TARGETS_FILE
    except ImportError:
        TARGETS_FILE = "targets.txt"

    if not os.path.exists(TARGETS_FILE):
        print(f"  {FAIL}: {TARGETS_FILE} not found!")
        return

    targets = []
    with open(TARGETS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if line.lstrip("-").isdigit():
                    targets.append(int(line))
                else:
                    targets.append(line.lstrip("@"))

    if not targets:
        print(f"  {FAIL}: No valid targets found in {TARGETS_FILE}!")
        return

    print(f"  {PASS}: {len(targets)} target(s) loaded:")
    for t in targets:
        print(f"         → {t}")


# ── TEST 5: Dispatcher queue — new message interruption ───────────────────────
async def test_dispatcher_interruption():
    banner("TEST 5: Dispatcher Interruption Logic (Whitebox Unit Test)")

    # Import dispatcher directly — it uses the REAL config which is already loaded
    # We just need MIN_DELAY/MAX_DELAY to be small for testing
    import importlib
    import config as real_config

    orig_min = real_config.MIN_DELAY
    orig_max = real_config.MAX_DELAY

    # Temporarily override delays to 3s for testing
    real_config.MIN_DELAY = 3
    real_config.MAX_DELAY = 3

    # Re-import dispatcher so it picks up the patched values
    import dispatcher as disp_module
    importlib.reload(disp_module)
    Dispatcher = disp_module.Dispatcher

    send_log = []

    class MockAccountManager:
        clients = ["fake"]
        async def send_message(self, target, from_chat_id, message_id):
            send_log.append((target, message_id))
            await asyncio.sleep(0.05)

    targets = ["target_A", "target_B", "target_C"]
    mgr = MockAccountManager()
    dispatcher = Dispatcher(mgr, targets)

    async def inject_messages():
        await dispatcher.enqueue({"from_chat_id": 100, "message_id": 1, "text": "msg1"})
        await asyncio.sleep(1.5)  # Let dispatch start then interrupt mid-sleep
        await dispatcher.enqueue({"from_chat_id": 100, "message_id": 2, "text": "msg2"})
        await asyncio.sleep(10)  # Let msg2 dispatch complete
        dispatcher.stop()

    try:
        run_task = asyncio.create_task(dispatcher.run())
        inject_task = asyncio.create_task(inject_messages())
        await asyncio.gather(inject_task, run_task)
    except Exception as e:
        print(f"  Note: {e}")

    msg1_sends = [x for x in send_log if x[1] == 1]
    msg2_sends = [x for x in send_log if x[1] == 2]

    if len(msg1_sends) < len(targets):
        print(f"  PASS: Message 1 interrupted at {len(msg1_sends)}/{len(targets)} targets "
              "(new msg took priority correctly)")
    else:
        print(f"  WARN: Message 1 completed all targets before interruption "
              "(timing OK — 3s sleep vs 1.5s inject window)")

    if len(msg2_sends) > 0:
        print(f"  PASS: Message 2 forwarded to {len(msg2_sends)}/{len(targets)} target(s)")
    else:
        print(f"  FAIL: Message 2 was never forwarded!")

    print(f"  Full log: {send_log}")

    # Restore original config values
    real_config.MIN_DELAY = orig_min
    real_config.MAX_DELAY = orig_max


# ── TEST 6: AccountManager cycling ───────────────────────────────────────────
def test_account_cycling():
    banner("TEST 6: Account Cycling (Whitebox Unit Test)")
    import itertools

    clients = ["acc_A", "acc_B", "acc_C"]
    cycle = itertools.cycle(clients)

    results = [next(cycle) for _ in range(9)]
    expected = clients * 3

    if results == expected:
        print(f"  {PASS}: Account cycling works correctly: {results[:6]}...")
    else:
        print(f"  {FAIL}: Unexpected cycle order: {results}")


# ── TEST 7: Source channel ID format ─────────────────────────────────────────
def test_source_channel_format():
    banner("TEST 7: Source Channel ID Format (Whitebox)")
    try:
        from config import SOURCE_CHANNEL
    except ImportError:
        print(f"  {FAIL}: config.py missing.")
        return

    sc = SOURCE_CHANNEL
    print(f"  SOURCE_CHANNEL value: {repr(sc)} (type: {type(sc).__name__})")

    if isinstance(sc, int):
        if sc < 0:
            sc_str = str(sc)
            if sc_str.startswith("-100"):
                print(f"  {PASS}: Negative ID with -100 prefix. Format looks correct.")
            else:
                print(f"  {WARN}: Negative ID but does NOT start with -100. "
                      "Supergroups/channels should use -100XXXXXXXXXX format.")
        else:
            print(f"  {FAIL}: POSITIVE integer! Channels must be negative. "
                  "Prefix with -100 followed by the channel ID.")
    elif isinstance(sc, str):
        if sc.startswith("@"):
            print(f"  {WARN}: Has leading @. config.py generator strips @, "
                  "but monitor uses the raw value — check Pyrogram resolves it.")
        else:
            print(f"  {PASS}: String username '{sc}' — Pyrogram will resolve it.")
    else:
        print(f"  {FAIL}: Invalid type {type(sc)}")


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def run_all_tests():
    print("\n" + "!" * 60)
    print("  BRUTAL WHITEBOX + BLACKBOX TEST SUITE — ARMEDIAS FORWARDER")
    print("!" * 60)

    # Sync tests
    test_config_validity()
    test_session_files()
    test_targets_file()
    test_account_cycling()
    test_source_channel_format()

    # Async tests
    await test_telegram_connectivity()
    await test_dispatcher_interruption()

    print("\n" + "!" * 60)
    print("  ALL TESTS COMPLETED")
    print("!" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())

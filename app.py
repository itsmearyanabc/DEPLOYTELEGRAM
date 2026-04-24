import os
import json
import subprocess
import shutil
import time
import sys
import asyncio

from collections import defaultdict
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from pyrogram import Client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ARMEDIAS_PRODUCTION_KEY_2026_SECURE")
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Ensure required directories exist for Render
for folder in ["sessions", "logs"]:
    os.makedirs(folder, exist_ok=True)

print("ARMEDIAS App Loading...")

# --- AUTHENTICATION ---
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS_HASH = generate_password_hash(os.environ.get("ADMIN_PASS", "telegram2026"))

# --- BRUTE FORCE PROTECTION ---
_login_attempts = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 minutes

def _get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1')

def _is_locked_out(ip):
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < LOCKOUT_DURATION]
    return len(_login_attempts[ip]) >= MAX_LOGIN_ATTEMPTS

def _get_lockout_remaining(ip):
    if not _login_attempts[ip]:
        return 0
    oldest = _login_attempts[ip][0]
    return max(0, int(LOCKOUT_DURATION - (time.time() - oldest)))

def _record_failed_login(ip):
    _login_attempts[ip].append(time.time())

def _clear_login_attempts(ip):
    _login_attempts.pop(ip, None)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

CONFIG_FILE = "config.json"
BOT_PROCESS = None

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "api_id": "", "api_hash": "",
        "phones": "",
        "source_channel": "", "targets": "",
        "min_delay": 900, "max_delay": 900
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

    raw_targets = config["targets"]
    target_lines = [t.strip() for t in raw_targets.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    clean_targets = []
    for t in target_lines:
        if not t: continue
        if t.startswith("http"):
            t = t.split("/")[-1].split("?")[0]
        if t.startswith("@"):
            t = t[1:]
        clean_targets.append(t)

    with open("targets.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(clean_targets) + "\n")

    phone_list = [p.strip() for p in config['phones'].split('\n') if p.strip()]
    accounts_code = []
    for i, phone in enumerate(phone_list):
        p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
        accounts_code.append(f"""    {{
        "name": "Account_{i+1}",
        "api_id": {config['api_id'] or 0},
        "api_hash": "{config['api_hash']}",
        "phone": "{phone}",
        "session_name": "sessions/session_{p_clean}"
    }}""")

    accounts_str = ",\n".join(accounts_code)

    sc = config['source_channel'].strip()
    if sc.startswith("http"):
        sc = sc.split("/")[-1].split("?")[0]
    if sc.startswith("@"):
        sc = sc[1:]
    sc_val = sc if sc.lstrip('-').isdigit() else f"'{sc}'"

    # Clamp delays: minimum 60s each, max_delay >= min_delay
    min_d = max(60, int(config.get('min_delay', 900)))
    max_d = max(min_d, int(config.get('max_delay', 900)))

    with open("config.py", "w") as f:
        f.write(f"""# AUTO-GENERATED CONFIG - {time.ctime()}
MOCK_MODE = False
ACCOUNTS = [
{accounts_str}
]
SOURCE_CHANNEL = {sc_val}
MIN_DELAY = {min_d}
MAX_DELAY = {max_d}
TARGETS_FILE = "targets.txt"
LOG_FILE = "bot.log"
""")


# ---------------------------------------------------------------------------
# ASYNC HELPERS
# ---------------------------------------------------------------------------
# Gunicorn pre-forks workers. Threads do NOT survive a fork.
# Solution: NO global event loop. Every auth operation gets a FRESH loop
# created inside the worker process itself, which is guaranteed to work.
#
# For the auth flow (send_code → sign_in) the Pyrogram client MUST use the
# same event loop for both calls (it stores loop references internally).
# We keep a per-phone loop alive between the two HTTP requests.
# ---------------------------------------------------------------------------

# phone_clean -> asyncio.AbstractEventLoop  (kept alive across send_code/sign_in)
_auth_loops: dict = {}
# phone_clean -> pyrogram.Client  (kept alive for sign_in)
_pending_clients: dict = {}


def _get_or_create_auth_loop(p_clean: str) -> asyncio.AbstractEventLoop:
    """Return the persistent loop for this phone, creating one if needed."""
    loop = _auth_loops.get(p_clean)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _auth_loops[p_clean] = loop
    return loop


def _cleanup_auth_loop(p_clean: str):
    """Tear down the loop for this phone after auth completes or fails."""
    loop = _auth_loops.pop(p_clean, None)
    _pending_clients.pop(p_clean, None)
    if loop and not loop.is_closed():
        try:
            loop.close()
        except Exception:
            pass


def run_in_new_loop(coro):
    """One-shot async call — safe for any operation that doesn't need state."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ASYNC AUTH COROUTINES
# ---------------------------------------------------------------------------

async def async_send_code(api_id, api_hash, phone):
    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    session_name = f"sessions/session_{p_clean}"

    # Disconnect any previous pending client for this phone
    old_client = _pending_clients.pop(p_clean, None)
    if old_client:
        try:
            await old_client.disconnect()
        except Exception:
            pass

    # Remove stale session file so Pyrogram does a fresh auth
    session_file = f"sessions/session_{p_clean}.session"
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except Exception:
            pass

    client = Client(
        session_name,
        api_id=int(api_id),
        api_hash=api_hash,
        workdir=".",
        device_model="iPhone 15 Pro Max",
        system_version="iOS 17.5.1",
        app_version="10.14.1",
        lang_code="en",
        in_memory=False,
    )
    await client.connect()
    try:
        sent_code = await client.send_code(phone)
        _pending_clients[p_clean] = client  # Keep alive for sign_in
        return {"status": "success", "phone_code_hash": sent_code.phone_code_hash}
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return {"status": "error", "message": str(e)}


async def async_sign_in(api_id, api_hash, phone, phone_code_hash, code):
    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')

    client = _pending_clients.get(p_clean)
    if not client:
        return {"status": "error", "message": "Session expired. Click 'Request Code' again."}

    try:
        await client.sign_in(phone, phone_code_hash, code)
        me = await client.get_me()
        await client.disconnect()
        return {"status": "success", "message": f"Logged in as {me.first_name}"}
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        # Remove bad session file
        session_file = f"sessions/session_{p_clean}.session"
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
            except Exception:
                pass
        return {"status": "error", "message": str(e)}
    finally:
        # Always clean up the auth loop and client after sign_in attempt
        _cleanup_auth_loop(p_clean)


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = _get_client_ip()

        if _is_locked_out(ip):
            remaining = _get_lockout_remaining(ip)
            mins, secs = divmod(remaining, 60)
            return render_template("login.html", error=f"Too many failed attempts. Try again in {mins}m {secs}s.")

        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USER and check_password_hash(_ADMIN_PASS_HASH, password):
            session['logged_in'] = True
            _clear_login_attempts(ip)
            return redirect(url_for('index'))

        _record_failed_login(ip)
        attempts_left = MAX_LOGIN_ATTEMPTS - len(_login_attempts[ip])
        if attempts_left <= 0:
            remaining = _get_lockout_remaining(ip)
            mins = remaining // 60
            return render_template("login.html", error=f"Account locked for {mins} minutes.")
        return render_template("login.html", error=f"Invalid credentials. {attempts_left} attempts remaining.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route("/")
@login_required
def index():
    config = load_config()
    global BOT_PROCESS
    is_running = BOT_PROCESS and BOT_PROCESS.poll() is None

    phone_list = [p.strip() for p in config['phones'].split('\n') if p.strip()]
    auth_status = []
    os.makedirs("sessions", exist_ok=True)
    for p in phone_list:
        p_clean = p.replace('+', '').replace(' ', '').replace('-', '')
        session_file = f"sessions/session_{p_clean}.session"
        auth_status.append({
            "phone": p,
            "clean_phone": p_clean,
            "authenticated": os.path.exists(session_file)
        })

    return render_template("index.html", config=config, bot_running=is_running, auth_status=auth_status)


@app.route("/api/auth/send_code", methods=["POST"])
@login_required
def api_send_code():
    api_id = request.form.get("api_id")
    api_hash = request.form.get("api_hash")
    phone = request.form.get("phone")
    if not all([api_id, api_hash, phone]):
        return jsonify({"status": "error", "message": "Missing credentials"})

    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    loop = _get_or_create_auth_loop(p_clean)
    result = loop.run_until_complete(async_send_code(api_id, api_hash, phone))
    return jsonify(result)


@app.route("/api/auth/sign_in", methods=["POST"])
@login_required
def api_sign_in():
    api_id = request.form.get("api_id")
    api_hash = request.form.get("api_hash")
    phone = request.form.get("phone")
    phone_code_hash = request.form.get("phone_code_hash")
    code = request.form.get("code")

    if not all([api_id, api_hash, phone, phone_code_hash, code]):
        return jsonify({"status": "error", "message": "Missing required fields"})

    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    loop = _auth_loops.get(p_clean)
    if loop is None or loop.is_closed():
        return jsonify({"status": "error", "message": "Session expired. Click 'Request Code' again."})

    # async_sign_in calls _cleanup_auth_loop in its finally block
    result = loop.run_until_complete(async_sign_in(api_id, api_hash, phone, phone_code_hash, code))
    return jsonify(result)


@app.route("/save", methods=["POST"])
@login_required
def save():
    try:
        config = {
            "api_id": request.form.get("api_id", "").strip(),
            "api_hash": request.form.get("api_hash", "").strip(),
            "phones": request.form.get("phones", "").strip(),
            "source_channel": request.form.get("source_channel", "").strip(),
            "targets": request.form.get("targets", "").strip(),
            "min_delay": int(request.form.get("min_delay", 900)),
            "max_delay": int(request.form.get("max_delay", 900))
        }
        save_config(config)
        return jsonify({"status": "success", "message": "Configuration saved!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/start", methods=["POST"])
@login_required
def start_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.poll() is None:
        return jsonify({"status": "error", "message": "Bot is already running!"})

    # Disconnect any pending auth clients and clean up their loops
    for p_clean in list(_pending_clients.keys()):
        client = _pending_clients.get(p_clean)
        loop = _auth_loops.get(p_clean)
        if client and loop and not loop.is_closed():
            try:
                loop.run_until_complete(client.disconnect())
            except Exception:
                pass
        _cleanup_auth_loop(p_clean)

    try:
        if os.path.exists("__pycache__"):
            try: shutil.rmtree("__pycache__")
            except: pass

        if os.path.exists("logs/bot.log"):
            try: os.remove("logs/bot.log")
            except: pass

        if not os.path.exists("config.py"):
            save_config(load_config())

        log_file = open("logs/bot.log", "a")
        BOT_PROCESS = subprocess.Popen(
            [sys.executable, "main.py"],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
        return jsonify({"status": "success", "message": "Automation started in background!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Launch failed: {e}"})


@app.route("/stop", methods=["POST"])
@login_required
def stop_bot():
    global BOT_PROCESS
    if BOT_PROCESS:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(BOT_PROCESS.pid)], capture_output=True)
            else:
                BOT_PROCESS.terminate()
            BOT_PROCESS = None
            return jsonify({"status": "success", "message": "All automation stopped."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error", "message": "Bot is not running."})


@app.route("/clear_sessions", methods=["POST"])
@login_required
def clear_sessions():
    if os.path.exists("sessions"):
        shutil.rmtree("sessions")
        os.makedirs("sessions", exist_ok=True)
        return jsonify({"status": "success", "message": "All session files cleared!"})
    return jsonify({"status": "success", "message": "No sessions to clear."})


@app.route("/api/auth/logout_account", methods=["POST"])
@login_required
def logout_account():
    phone = request.form.get("phone")
    if not phone:
        return jsonify({"status": "error", "message": "No phone number provided"})

    p_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    session_file = f"sessions/session_{p_clean}.session"
    journal_file = f"sessions/session_{p_clean}.session-journal"

    removed = False
    for f in [session_file, journal_file]:
        if os.path.exists(f):
            try:
                os.remove(f)
                removed = True
            except Exception as e:
                return jsonify({"status": "error", "message": f"Failed: {e}"})

    if removed:
        return jsonify({"status": "success", "message": f"Logged out {phone} successfully"})
    return jsonify({"status": "success", "message": f"{phone} was not logged in"})


@app.route("/logs")
@login_required
def get_logs():
    log_path = "logs/bot.log"
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                return "".join(f.readlines()[-30:])
        except Exception:
            return "Initializing..."
    return "Ready. Waiting for first message..."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)

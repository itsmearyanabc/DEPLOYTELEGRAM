import json
import time
import os

with open("config.json") as f:
    config = json.load(f)

phones = [p.strip() for p in config["phones"].replace("\r\n", "\n").split("\n") if p.strip()]
accounts_code = []
for i, phone in enumerate(phones):
    p_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    accounts_code.append(f"""    {{
        "name": "Account_{i+1}",
        "api_id": {config['api_id'] or 0},
        "api_hash": "{config['api_hash']}",
        "phone": "{phone}",
        "session_name": "sessions/session_{p_clean}"
    }}""")

accounts_str = ",\n".join(accounts_code)

sc = config["source_channel"].strip()
if sc.startswith("http"):
    sc = sc.split("/")[-1].split("?")[0]
if sc.startswith("@"):
    sc = sc[1:]
sc_val = sc if sc.lstrip("-").isdigit() else f"'{sc}'"

min_d = max(60, int(config["min_delay"]))
max_d = max(min_d, int(config["max_delay"]))

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
print("config.py written OK.")

# targets.txt
raw = config["targets"].replace("\r\n", "\n").replace("\r", "\n")
targets = []
for t in raw.split("\n"):
    t = t.strip()
    if not t:
        continue
    if t.startswith("http"):
        t = t.split("/")[-1].split("?")[0]
    if t.startswith("@"):
        t = t[1:]
    targets.append(t)

with open("targets.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(targets) + "\n")
print(f"targets.txt written with {len(targets)} target(s).")

with open("config.py") as f:
    print(f.read())

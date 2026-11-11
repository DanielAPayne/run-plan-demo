#!/usr/bin/env python3
"""Create .env and secrets/credentials.json with random local test values.
Refuses to overwrite: the database volume is created with these passwords."""
import json, os, secrets, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(here, ".env")
if os.path.exists(env_path):
    sys.exit(".env exists; not overwriting")
v = {
    "PG_SUPER_PASSWORD": secrets.token_hex(16),
    "N8N_DB_PASSWORD": secrets.token_hex(16),
    "DEMO_DB_PASSWORD": secrets.token_hex(16),
    "N8N_ENCRYPTION_KEY": secrets.token_hex(24),
    "N8N_OWNER_EMAIL": "owner@rundemo.test",
    "N8N_OWNER_PASSWORD": "Rd" + secrets.token_hex(10) + "7",
}
with open(env_path, "w") as f:
    for k, val in v.items():
        f.write(f"{k}={val}\n")
os.chmod(env_path, 0o600)
os.makedirs(os.path.join(here, "secrets"), exist_ok=True)
creds = [
    {"id": "rdCredPostgres01", "name": "Demo Postgres", "type": "postgres",
     "data": {"host": "postgres", "database": "demo", "user": "demo", "password": v["DEMO_DB_PASSWORD"],
              "port": 5432, "ssl": "disable", "allowUnauthorizedCerts": False, "sshTunnel": False}},
    {"id": "rdCredSmtp000001", "name": "Mailpit SMTP", "type": "smtp",
     "data": {"user": "", "password": "", "host": "mailpit", "port": 1025, "secure": False, "disableStartTls": True}},
    {"id": "rdCredAlertSmtp1", "name": "Alert channel SMTP", "type": "smtp",
     "data": {"user": "", "password": "", "host": "alertbox", "port": 1025, "secure": False, "disableStartTls": True}},
]
p = os.path.join(here, "secrets", "credentials.json")
with open(p, "w") as f:
    json.dump(creds, f)
os.chmod(p, 0o600)
print("wrote .env and secrets/credentials.json (values not shown)")

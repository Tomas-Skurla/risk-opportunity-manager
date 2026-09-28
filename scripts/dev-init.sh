#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: Python 3 is required to generate local credentials." >&2
  exit 1
fi

exec python3 - <<'PY'
import os
import secrets
import string
import sys
from pathlib import Path

destination = Path(".env")
if destination.exists() or destination.is_symlink():
    print(".env already exists; left unchanged. Review it before starting Compose.")
    sys.exit(0)

# Use only characters that remain literal in both dotenv files and the shell.
# Require every character group to satisfy the API's default password policy.
groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "%+_-")
alphabet = "".join(groups)
while True:
    password = "".join(secrets.choice(alphabet) for _ in range(32))
    if all(any(character in group for character in password) for group in groups):
        break

values = {
    "SECRET_KEY": secrets.token_hex(32),
    "TOKEN_HASH_KEY": secrets.token_hex(32),
    "INITIAL_SUPERUSER_EMAIL": "admin@example.com",
    "INITIAL_SUPERUSER_PASSWORD": password,
}

lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
for name, value in values.items():
    placeholder = f"{name}="
    if lines.count(placeholder) != 1:
        sys.exit(f"ERROR: Expected exactly one blank {name} in .env.example.")
    lines[lines.index(placeholder)] = f"{name}={value}"

# Exclusive creation also prevents overwriting a file or following a symlink
# created by another invocation after the initial existence check.
os.umask(0o077)
try:
    with destination.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
except FileExistsError:
    sys.exit("ERROR: .env appeared during setup; left unchanged. Run setup again.")

print("Created private .env with fresh keys and a random administrator password.")
print("Login email: admin@example.com (editable in .env before the first start).")
print("Read INITIAL_SUPERUSER_PASSWORD in .env to log in; credentials are not printed.")
print("Existing database accounts are unchanged. Start with: docker compose up --build")
PY
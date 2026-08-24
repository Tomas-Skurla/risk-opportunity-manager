#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

YES=0

case "${1:-}" in
  --yes|-y)
    YES=1
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--yes]"
    exit 2
    ;;
esac

if [[ "$YES" -ne 1 ]]; then
  echo "This will remove:"
  echo "  server/riskapp.db"
  echo "  ~/.riskapp/client.sqlite3"
  echo
  read -r -p "Continue? [y/N] " ans

  case "$ans" in
    y|Y|yes|YES)
      ;;
    *)
      echo "Cancelled."
      exit 0
      ;;
  esac
fi

rm -f server/riskapp.db
rm -f "$HOME/.riskapp/client.sqlite3"

echo "Dev state reset."
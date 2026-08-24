"""Allow `python -m riskapp_client.app`."""

from riskapp_client.app.main_entrypoint import main

if __name__ == "__main__":
    raise SystemExit(main())

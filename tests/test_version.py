"""Release-version consistency checks."""

from pathlib import Path

from riskapp_client import __version__ as client_version
from riskapp_server import __version__ as server_version


def test_release_version_is_consistent_across_client_and_server() -> None:
    assert client_version == server_version == "0.1.0"


def test_api_schema_uses_the_release_version(
    isolated_app_factory, tmp_path: Path
) -> None:
    application = isolated_app_factory(f"sqlite+pysqlite:///{tmp_path / 'version.db'}")
    assert application.version == server_version

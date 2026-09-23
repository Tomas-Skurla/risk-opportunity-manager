"""Regression coverage for creating new Alembic revisions."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def test_revision_template_generates_valid_python(tmp_path: Path) -> None:
    script_location = tmp_path / "alembic"
    shutil.copytree(ROOT / "server" / "alembic", script_location)
    config = Config()
    config.set_main_option("script_location", str(script_location))

    command.revision(
        config,
        message="template smoke test",
        rev_id="template_smoke",
    )

    generated_paths = list(
        (script_location / "versions").glob("template_smoke_*.py")
    )
    assert len(generated_paths) == 1
    generated_path = generated_paths[0]
    source = generated_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(generated_path))
    assignments = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
    }
    assert assignments["revision"] == "template_smoke"
    assert assignments["down_revision"] == "0003"
    compile(source, str(generated_path), "exec")

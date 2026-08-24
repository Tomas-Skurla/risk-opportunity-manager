"""Apply one or more SQL files using DATABASE_URL."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from sqlalchemy import create_engine, text


def _resolve_database_url() -> str:
    try:
        from riskapp_server.core.config import DATABASE_URL  # type: ignore

        url = str(DATABASE_URL).strip()
        if url:
            return url
    except ImportError:
        pass
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Set it in the environment or make "
            "riskapp_server.core.config importable."
        )
    return url


def _iter_sql_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if not p.exists():
            raise SystemExit(f"SQL path not found: {p}")
        if p.is_dir():
            files.extend(sorted(p.glob("*.sql")))
        else:
            files.append(p)
    seen: set[Path] = set()
    out: list[Path] = []
    for f in files:
        rf = f.resolve()
        if rf not in seen:
            seen.add(rf)
            out.append(f)
    return out


def _split_sql(sql: str) -> Iterator[str]:
    """Split SQL on semicolons outside strings, comments, and dollar blocks."""

    buf: list[str] = []
    in_sq = False
    in_dq = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt2 = sql[i : i + 2]

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if nxt2 == "*/":
                buf.append(nxt2)
                i += 2
                in_block_comment = False
            else:
                buf.append(ch)
                i += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                buf.append(ch)
                i += 1
            continue

        if not in_sq and not in_dq:
            if nxt2 == "--":
                buf.append(nxt2)
                i += 2
                in_line_comment = True
                continue
            if nxt2 == "/*":
                buf.append(nxt2)
                i += 2
                in_block_comment = True
                continue

            if ch == "$":
                j = sql.find("$", i + 1)
                if j != -1:
                    tag = sql[i : j + 1]
                    inner = tag[1:-1]
                    if inner == "" or inner.replace("_", "").isalnum():
                        dollar_tag = tag
                        buf.append(tag)
                        i += len(tag)
                        continue

        if ch == "'" and not in_dq:
            if in_sq and sql[i : i + 2] == "''":
                buf.append("''")
                i += 2
                continue
            in_sq = not in_sq
            buf.append(ch)
            i += 1
            continue

        if ch == '"' and not in_sq:
            in_dq = not in_dq
            buf.append(ch)
            i += 1
            continue

        if ch == ";" and not in_sq and not in_dq:
            stmt = "".join(buf).strip()
            if stmt:
                yield stmt
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        yield tail


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m riskapp_server.ops.apply_sql",
        description="Apply one or more .sql files to the configured database.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more .sql files or directories containing .sql files.",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Execute each file as-is instead of splitting on semicolons.",
    )
    parser.add_argument(
        "--autocommit",
        action="store_true",
        help="Use AUTOCOMMIT for statements that require it.",
    )
    args = parser.parse_args(argv[1:])

    sql_paths = _iter_sql_files([Path(p) for p in args.paths])
    if not sql_paths:
        print("No .sql files found.", file=sys.stderr)
        return 2

    db_url = _resolve_database_url()
    engine = create_engine(db_url, pool_pre_ping=True)

    applied = 0
    for sql_path in sql_paths:
        sql = sql_path.read_text(encoding="utf-8")
        if args.autocommit:
            with engine.connect() as conn:
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                if args.no_split:
                    conn.execute(text(sql))
                else:
                    for stmt in _split_sql(sql):
                        conn.execute(text(stmt))
        else:
            with engine.begin() as conn:
                if args.no_split:
                    conn.execute(text(sql))
                else:
                    for stmt in _split_sql(sql):
                        conn.execute(text(stmt))
        applied += 1
        print(f"Applied: {sql_path}")

    print(f"Done. Applied {applied} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

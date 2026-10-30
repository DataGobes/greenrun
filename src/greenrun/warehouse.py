"""The DuckDB warehouse: where it lives and how to open it."""

import os
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/greenrun.duckdb")


def db_path() -> Path:
    """Path of the warehouse file: `$GREENRUN_DB`, default `data/greenrun.duckdb`."""
    value = os.environ.get("GREENRUN_DB")
    return Path(value) if value else DEFAULT_DB


def connect() -> duckdb.DuckDBPyConnection:
    """Open the warehouse, creating its parent directory if needed."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))

"""Reading and writing the four delivery formats the source contracts declare.

WHY not land everything as parquet: four of the eleven feeds declare csv, json or
jsonl, and those formats genuinely lose type information on the wire. A CSV feed
delivers ``"2026-03-08"`` and ``"12"`` as text, and the pipeline has to coerce them
back using the contract's declared types. Landing everything as parquet would hide
that entirely and make the bronze type-conformance step untestable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from insight_copilot.contracts.source_models import FileFormat
from insight_copilot.errors import IngestionError

EXTENSIONS: dict[str, str] = {
    "parquet": ".parquet",
    "csv": ".csv",
    "json": ".json",
    "jsonl": ".jsonl",
}


def extension_for(file_format: FileFormat) -> str:
    """The on-disk suffix a format lands with."""
    try:
        return EXTENSIONS[file_format]
    except KeyError as exc:  # pragma: no cover - Literal makes this unreachable
        raise IngestionError(f"unsupported delivery format {file_format!r}") from exc


def write_batch(frame: pd.DataFrame, path: Path, file_format: FileFormat) -> Path:
    """Write a batch in its declared format. Returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if file_format == "parquet":
        frame.to_parquet(path, index=False)
    elif file_format == "csv":
        frame.to_csv(path, index=False)
    elif file_format == "jsonl":
        path.write_text(frame.to_json(orient="records", lines=True, date_format="iso") or "")
    else:
        payload = json.loads(frame.to_json(orient="records", date_format="iso") or "[]")
        path.write_text(json.dumps({"records": payload}, indent=1))
    return path


def read_batch(path: Path, file_format: FileFormat) -> pd.DataFrame:
    """Read a landed batch back. Types are *not* restored here — bronze coerces them."""
    try:
        if file_format == "parquet":
            return pd.DataFrame(pd.read_parquet(path))
        if file_format == "csv":
            return pd.DataFrame(pd.read_csv(path, dtype=str, keep_default_na=False))
        if file_format == "jsonl":
            return pd.DataFrame(pd.read_json(path, lines=True, dtype=False, convert_dates=False))
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise IngestionError(f"unreadable batch file {path.name}", detail=str(exc)) from exc
    return pd.DataFrame(payload["records"])

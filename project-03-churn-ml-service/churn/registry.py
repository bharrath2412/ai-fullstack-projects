"""Tiny model registry: versioned directories + a JSON index + joblib artifacts.

Enough structure to make rollbacks and auditing real, without dragging in MLflow.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from .config import ARTIFACT_DIR


@dataclass
class RegisteredModel:
    version: str
    path: Path
    metadata: dict[str, Any]

    @property
    def pipeline(self):
        return joblib.load(self.path / "model.joblib")


class ModelRegistry:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or ARTIFACT_DIR / "models")
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    # ------------------------------------------------------------------ index
    def _read_index(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        return json.loads(self.index_path.read_text())

    def _write_index(self, entries: list[dict[str, Any]]) -> None:
        self.index_path.write_text(json.dumps(entries, indent=2))

    # ------------------------------------------------------------------- save
    def save(self, pipeline, metadata: dict[str, Any], version: str | None = None) -> RegisteredModel:
        version = version or metadata.get("version") or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        directory = self.root / version
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

        joblib.dump(pipeline, directory / "model.joblib", compress=3)
        payload = {**metadata, "version": version, "created_at": datetime.now(timezone.utc).isoformat()}
        (directory / "metadata.json").write_text(json.dumps(payload, indent=2, default=str))

        entries = [e for e in self._read_index() if e.get("version") != version]
        entries.append(
            {
                "version": version,
                "created_at": payload["created_at"],
                "roc_auc": payload.get("metrics", {}).get("roc_auc"),
                "f1": payload.get("metrics", {}).get("f1"),
                "threshold": payload.get("threshold"),
                "is_latest": True,
            }
        )
        for entry in entries[:-1]:
            entry["is_latest"] = False
        self._write_index(entries)
        return RegisteredModel(version=version, path=directory, metadata=payload)

    # ------------------------------------------------------------------- load
    def list_versions(self) -> list[dict[str, Any]]:
        return sorted(self._read_index(), key=lambda e: e["version"], reverse=True)

    def get(self, version: str) -> RegisteredModel:
        directory = self.root / version
        if not (directory / "model.joblib").exists():
            raise FileNotFoundError(f"No model version {version!r} in {self.root}")
        metadata = json.loads((directory / "metadata.json").read_text())
        return RegisteredModel(version=version, path=directory, metadata=metadata)

    def load_latest(self) -> RegisteredModel:
        entries = self._read_index()
        if not entries:
            raise FileNotFoundError(
                f"No models registered in {self.root}. Run `python -m churn.train` first."
            )
        version = next((e["version"] for e in entries if e.get("is_latest")), entries[-1]["version"])
        return self.get(version)

"""Shared fixtures: one trained model per test session (fast settings)."""

from __future__ import annotations

import pytest

from churn.train import train


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    """Train a small model into a temporary registry to keep the repo clean."""
    import churn.registry as registry_module

    model_dir = tmp_path_factory.mktemp("models")
    original_init = registry_module.ModelRegistry.__init__

    def patched_init(self, root=None):  # noqa: ANN001
        original_init(self, root or model_dir)

    registry_module.ModelRegistry.__init__ = patched_init  # type: ignore[method-assign]
    result = train(samples=1200, cv_folds=2, fast=True, write_report_file=False)
    yield result
    registry_module.ModelRegistry.__init__ = original_init  # type: ignore[method-assign]

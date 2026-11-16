"""Runtime configuration, read once from the environment.

Nothing here has a secret baked in: the JWT secret is generated per process if
`JWT_SECRET` is unset (which logs everyone out on restart — fine for a demo, and
deliberately annoying in production where you *should* set it).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .security import secret_from_env

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("BILLBOOK_DB", str(BASE_DIR / "billbook.db")))
    jwt_secret: str = field(default_factory=secret_from_env)
    token_ttl_seconds: int = field(default_factory=lambda: int(os.environ.get("TOKEN_TTL_SECONDS", 8 * 3600)))
    currency: str = "INR"
    razorpay_key_id: str = field(default_factory=lambda: os.environ.get("RAZORPAY_KEY_ID", "").strip())
    razorpay_key_secret: str = field(default_factory=lambda: os.environ.get("RAZORPAY_KEY_SECRET", "").strip())
    #: "auto" → call Razorpay when keys are present, otherwise use the local simulator.
    payment_mode: str = field(default_factory=lambda: os.environ.get("PAYMENT_MODE", "auto").strip().lower())
    razorpay_webhook_secret: str = field(default_factory=lambda: os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip())
    env: str = field(default_factory=lambda: os.environ.get("ENV", "dev"))
    slow_query_ms: int = 250

    @property
    def live_payments(self) -> bool:
        """True only when Razorpay keys are present and the mode allows them."""
        if self.payment_mode == "simulated":
            return False
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def payment_secret(self) -> str:
        """Secret used to sign/verify payment callbacks."""
        if self.live_payments:
            return self.razorpay_key_secret
        # Deterministic in dev so tests and the UI agree; never used with real money.
        return self.razorpay_key_secret or os.environ.get("SIMULATED_PAYMENT_SECRET", "billbook_test_secret")

    @property
    def payment_label(self) -> str:
        return "razorpay-test" if self.live_payments else "razorpay-simulated"

    def validate(self) -> None:
        if self.payment_mode not in {"auto", "simulated", "razorpay"}:
            raise RuntimeError("PAYMENT_MODE must be auto, simulated or razorpay")
        if self.payment_mode == "razorpay" and not self.live_payments:
            raise RuntimeError("PAYMENT_MODE=razorpay needs RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")
        if self.env == "prod" and self.jwt_secret in {"changeme", "secret", "dev"}:
            raise RuntimeError("refusing to start in prod with a placeholder JWT_SECRET")


def get_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings

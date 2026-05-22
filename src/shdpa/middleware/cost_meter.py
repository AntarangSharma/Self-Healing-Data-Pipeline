"""Tracks cumulative LLM spend per-incident and per-process.

Enforces:
 - per-incident hard cap (default $0.05)
 - process-wide hard cap (default $30)

Raises CostBudgetExceeded so the agent loop can circuit-break cleanly.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from shdpa.llm.provider import LLMResponse


class CostBudgetExceeded(RuntimeError):
    pass


@dataclass
class CostMeter:
    per_incident_cap: float = field(
        default_factory=lambda: float(os.getenv("SHDPA_MAX_COST_PER_INCIDENT", "0.05"))
    )
    total_cap: float = field(
        default_factory=lambda: float(os.getenv("SHDPA_MAX_TOTAL_COST", "30.00"))
    )
    incident_spend: float = 0.0
    total_spend: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset_incident(self) -> None:
        with self._lock:
            self.incident_spend = 0.0

    def record(self, resp: LLMResponse) -> None:
        with self._lock:
            self.incident_spend += resp.cost_usd
            self.total_spend += resp.cost_usd
        if self.incident_spend > self.per_incident_cap:
            raise CostBudgetExceeded(
                f"per-incident cap ${self.per_incident_cap:.4f} exceeded "
                f"(spent ${self.incident_spend:.4f})"
            )
        if self.total_spend > self.total_cap:
            raise CostBudgetExceeded(
                f"total cap ${self.total_cap:.2f} exceeded (spent ${self.total_spend:.4f})"
            )

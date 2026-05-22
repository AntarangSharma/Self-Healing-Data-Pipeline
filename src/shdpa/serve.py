"""FastAPI HTTP surface + Prometheus /metrics.

Run:
  pip install -e ".[serve]"
  shdpa serve --port 8080

Endpoints:
  GET  /healthz          -> {"ok": true}                 — liveness
  GET  /readyz           -> {"ok": true, "store": ...}   — readiness (DB ping)
  GET  /metrics          -> Prometheus text format
  POST /incidents        -> body=Incident JSON; runs the agent, returns result
  GET  /incidents        -> list recent incidents (requires SHDPA_STORAGE_PATH)
  GET  /incidents/{id}   -> get one incident
  GET  /stats            -> aggregate stats

The /metrics endpoint exposes 6 counters/gauges plus a histogram of
per-incident cost — enough for an SRE to alert on "agent stopped resolving"
or "cost per incident spiked > $0.05."

We import FastAPI lazily so `pip install -e .` (without the [serve] extra)
keeps working in CI.
"""

from __future__ import annotations

import contextlib
from typing import Any

import structlog

log = structlog.get_logger()


# --- Prometheus metrics (module-level singletons; created lazily) ----------

_METRICS: dict[str, Any] = {}


def _init_metrics() -> dict[str, Any]:
    from prometheus_client import Counter, Gauge, Histogram

    if _METRICS:
        return _METRICS
    _METRICS["incidents_total"] = Counter(
        "shdpa_incidents_total",
        "Total incidents processed",
        ["predicted_class", "resolved"],
    )
    _METRICS["llm_calls_total"] = Counter(
        "shdpa_llm_calls_total",
        "Total LLM calls",
        ["provider", "purpose"],
    )
    _METRICS["llm_cost_usd_total"] = Counter(
        "shdpa_llm_cost_usd_total",
        "Total LLM cost in USD",
        ["provider"],
    )
    _METRICS["guardrail_blocks_total"] = Counter(
        "shdpa_guardrail_blocks_total",
        "Guardrail blocks by rule",
        ["rule"],
    )
    _METRICS["escalations_total"] = Counter(
        "shdpa_escalations_total",
        "Total escalations sent",
        ["channel"],
    )
    _METRICS["incident_cost_usd"] = Histogram(
        "shdpa_incident_cost_usd",
        "Per-incident LLM cost",
        buckets=(0.0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 1.00),
    )
    _METRICS["incident_latency_seconds"] = Histogram(
        "shdpa_incident_latency_seconds",
        "Per-incident wallclock latency",
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    )
    _METRICS["last_resolution_rate"] = Gauge(
        "shdpa_last_resolution_rate",
        "Resolution rate from last /stats call (0..1)",
    )
    return _METRICS


def record_incident(incident: Any) -> None:
    """Update Prometheus counters from a finished incident.

    Called from the loop after run_agent finishes. Safe to call even
    if prometheus_client is not installed (we no-op).
    """
    try:
        m = _init_metrics()
    except ImportError:
        return
    m["incidents_total"].labels(
        predicted_class=str(incident.predicted_class or "unknown"),
        resolved=str(incident.resolved).lower(),
    ).inc()
    for c in incident.llm_calls:
        m["llm_calls_total"].labels(provider=c.provider, purpose=c.purpose).inc()
        m["llm_cost_usd_total"].labels(provider=c.provider).inc(c.cost_usd)
    for a in incident.actions:
        if a.blocked_by_guardrail:
            m["guardrail_blocks_total"].labels(rule=a.blocked_by_guardrail).inc()
    m["incident_cost_usd"].observe(incident.total_cost_usd)
    m["incident_latency_seconds"].observe(incident.total_latency_s)


def create_app():  # type: ignore[no-untyped-def]
    """Build the FastAPI app. Imported lazily."""
    try:
        from fastapi import FastAPI, HTTPException, Request, Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    except ImportError as e:
        raise RuntimeError(
            "shdpa[serve] extras not installed. Run: pip install -e '.[serve]'"
        ) from e

    from shdpa.agent.loop import run_agent
    from shdpa.models import Incident
    from shdpa.storage import get_default_store

    app = FastAPI(title="shdpa", version="0.1.0")
    _init_metrics()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        store = get_default_store()
        store_ok: bool | str = False
        if store is None:
            store_ok = "disabled"
        else:
            try:
                store.aggregate()
                store_ok = True
            except Exception as e:  # noqa: BLE001
                store_ok = repr(e)
        return {"ok": True, "store": store_ok}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/incidents")
    async def run_incident(req: Request) -> dict[str, Any]:
        body = await req.json()
        try:
            inc = Incident.model_validate(body)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"invalid incident: {e!r}") from e
        out = run_agent(inc)
        record_incident(out)
        return out.model_dump(mode="json")

    @app.get("/incidents")
    def list_incidents(limit: int = 50, predicted_class: str | None = None) -> Any:
        store = get_default_store()
        if store is None:
            raise HTTPException(503, "SHDPA_STORAGE_PATH not set; list disabled")
        return store.list_incidents(limit=limit, predicted_class=predicted_class)

    @app.get("/incidents/{incident_id}")
    def get_one(incident_id: str) -> Any:
        store = get_default_store()
        if store is None:
            raise HTTPException(503, "SHDPA_STORAGE_PATH not set")
        inc = store.get_incident(incident_id)
        if inc is None:
            raise HTTPException(404, f"no incident {incident_id}")
        return inc.model_dump(mode="json")

    @app.get("/stats")
    def stats() -> Any:
        store = get_default_store()
        if store is None:
            raise HTTPException(503, "SHDPA_STORAGE_PATH not set")
        agg = store.aggregate()
        with contextlib.suppress(Exception):
            _init_metrics()["last_resolution_rate"].set(agg["resolution_rate"])
        return agg

    return app


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Entry-point used by `shdpa serve`."""
    try:
        import uvicorn
    except ImportError as e:
        raise RuntimeError(
            "shdpa[serve] extras not installed. Run: pip install -e '.[serve]'"
        ) from e
    uvicorn.run(create_app(), host=host, port=port, log_level="info")

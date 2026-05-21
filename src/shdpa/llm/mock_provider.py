"""Deterministic mock LLM. Lets the entire pipeline run with zero API keys.

This is what makes the project demoable on a fresh machine without billing.
It pattern-matches the input log + schema diff to produce believable, structured output.

It is NOT an oracle: real LLMs (openai/anthropic/ollama) are expected to match or beat
these numbers, not be capped by them.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from shdpa.llm.provider import LLMResponse


class MockProvider:
    name = "mock"
    model = "mock-rules-v1"

    def _classify(self, user: str) -> tuple[str, float, str]:
        u = user.lower()
        if "undefinedcolumn" in u or ("column" in u and "does not exist" in u):
            return "schema_drift", 0.92, "psycopg UndefinedColumn → schema drift"
        if "memoryerror" in u or "exit code 137" in u or " sigkill" in u:
            return "oom", 0.88, "OOM signal in log"
        if "modulenotfounderror" in u or "no module named" in u:
            return "dep_conflict", 0.90, "ModuleNotFoundError"
        if "duplicate key" in u or "uniqueviolation" in u:
            return "idempotency", 0.87, "duplicate PK"
        if "refresherror" in u or " 401 " in u or " 403 " in u or "401 unauthorized" in u:
            return "auth_expiry", 0.86, "auth/token failure"
        if "no space left" in u or "xcom value exceeds" in u:
            return "disk_full", 0.84, "disk exhaustion"
        if "dagbag import errors" in u or ("importerror" in u and "dag" in u) \
                or ("nameerror" in u and "datetime" in u):
            return "dag_import", 0.90, "DAG import failure"
        if ("dbt test" in u and "not_null" in u) or "testfailure" in u:
            return "null_spike", 0.83, "null check failed"
        if "sensor" in u and "timeout" in u:
            return "late_partition", 0.78, "sensor timeout"
        if re.search(r"\b5\d\d\b", u) or "connectionerror" in u or "httperror" in u:
            return "upstream_5xx", 0.85, "5xx / timeout signature"
        return "unknown", 0.30, "no pattern matched"

    def _extract_first(self, pattern: str, text: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    def complete(
        self, system: str, user: str, *, max_tokens: int = 1024,
        temperature: float = 0.1, purpose: str = "",
    ) -> LLMResponse:
        t0 = time.time()
        cls, conf, rationale = self._classify(user)
        text = f"class={cls} confidence={conf:.2f}\nrationale: {rationale}"
        return LLMResponse(
            text=text, prompt_tokens=len(user) // 4, completion_tokens=len(text) // 4,
            cost_usd=0.0, latency_ms=max(int((time.time() - t0) * 1000), 1),
            model=self.model, provider=self.name,
        )

    def complete_json(
        self, system: str, user: str, *, schema_hint: str = "",
        max_tokens: int = 1024, temperature: float = 0.0, purpose: str = "",
    ) -> tuple[dict[str, Any], LLMResponse]:
        t0 = time.time()
        cls, conf, rationale = self._classify(user)

        out: dict[str, Any] = {
            "failure_class": cls,
            "confidence": conf,
            "rationale": rationale,
        }

        if purpose in ("diagnose", "plan"):
            patches: list[dict[str, str]] = []

            if cls == "schema_drift":
                # rely on schema-diff hint injected into the prompt
                missing = self._extract_first(r'"missing_column":\s*"([^"]+)"', user) \
                    or self._extract_first(r'column "([^"]+)" does not exist', user)
                suggested = self._extract_first(r'"suggested_column":\s*"([^"]+)"', user)
                if missing and suggested:
                    out["root_cause"] = (
                        f"upstream renamed {missing!r} → {suggested!r}; downstream still uses {missing!r}"
                    )
                    out["fix_kind"] = "code_patch"
                    out["must_include_strings"] = [missing, suggested]
                    out["sql_replace"] = {"find": missing, "replace": suggested}
                    out["patches"] = [{
                        "kind": "sql_replace",
                        "find": missing,
                        "replace": suggested,
                    }]
                elif missing:
                    out["root_cause"] = f"column {missing!r} dropped upstream; downstream still uses it"
                    out["fix_kind"] = "code_patch"
                    out["must_include_strings"] = [missing]
                    out["patches"] = [{
                        "kind": "sql_remove",
                        "find": missing,
                    }]
                else:
                    out["fix_kind"] = "noop"

            elif cls == "upstream_5xx":
                out["root_cause"] = "transient upstream HTTP failure"
                out["fix_kind"] = "retry"

            elif cls == "auth_expiry":
                out["root_cause"] = "credential rotation needed; never auto-rotate"
                out["fix_kind"] = "secret_rotate"

            elif cls == "disk_full":
                out["root_cause"] = "XCom / log volume exceeded; prune > 7d"
                out["fix_kind"] = "config_change"

            elif cls == "oom":
                out["root_cause"] = "worker OOM; chunk the read or bump memory"
                out["fix_kind"] = "config_change"
                out["must_include_strings"] = ["chunk"]
                # propose a comment-level patch to the model showing chunking intent
                model_file = self._extract_first(r"models/(\w+)\.sql", user)
                if model_file:
                    out["patches"] = [{
                        "kind": "prepend",
                        "file": f"models/{model_file}.sql",
                        "text": "-- TODO: chunk read; current query exceeds worker memory\n",
                    }]

            elif cls == "dep_conflict":
                pkg = self._extract_first(r"No module named '([^']+)'", user) \
                    or self._extract_first(r"No module named \"([^\"]+)\"", user)
                out["root_cause"] = f"missing dependency: {pkg or 'unknown'}"
                out["fix_kind"] = "config_change"
                if pkg:
                    out["must_include_strings"] = [pkg]
                    out["patches"] = [{
                        "kind": "create",
                        "file": "requirements.txt",
                        "text": f"{pkg}\n",
                    }]

            elif cls == "idempotency":
                out["root_cause"] = "duplicate PK on re-run; needs ON CONFLICT clause"
                out["fix_kind"] = "code_patch"
                out["must_include_strings"] = ["on conflict"]
                model_file = self._extract_first(r"models/(\w+)\.sql", user)
                if model_file:
                    out["patches"] = [{
                        "kind": "append",
                        "file": f"models/{model_file}.sql",
                        "text": "\non conflict (o_orderkey) do nothing\n",
                    }]

            elif cls == "null_spike":
                col = self._extract_first(r"not_null_(\w+)", user) \
                    or self._extract_first(r"Column (\w+) has", user)
                out["root_cause"] = f"sudden null rate on {col or 'column'}; filter as stopgap"
                out["fix_kind"] = "code_patch"
                if col:
                    out["must_include_strings"] = [col, "is not null"]
                    model_file = self._extract_first(r"models/(\w+)\.sql", user)
                    if model_file:
                        out["patches"] = [{
                            "kind": "append",
                            "file": f"models/{model_file}.sql",
                            "text": f"\n-- stopgap dq filter\nwhere {col} is not null\n",
                        }]

            elif cls == "dag_import":
                # detect specific NameError patterns
                missing_name = self._extract_first(r"name '(\w+)' is not defined", user)
                if missing_name == "datetime":
                    out["root_cause"] = "DAG references datetime but never imports it"
                    out["fix_kind"] = "code_patch"
                    out["must_include_strings"] = ["from datetime import datetime"]
                    out["patches"] = [{
                        "kind": "prepend",
                        "file": "dags/tpch.py",
                        "text": "from datetime import datetime\n",
                    }]
                else:
                    out["fix_kind"] = "code_patch"
                    out["root_cause"] = "DAG fails to import; manual fix needed"

            else:
                out["root_cause"] = rationale
                out["fix_kind"] = "noop"

        text = json.dumps(out, indent=2)
        resp = LLMResponse(
            text=text, prompt_tokens=len(user) // 4, completion_tokens=len(text) // 4,
            cost_usd=0.0, latency_ms=max(int((time.time() - t0) * 1000), 1),
            model=self.model, provider=self.name,
        )
        return out, resp

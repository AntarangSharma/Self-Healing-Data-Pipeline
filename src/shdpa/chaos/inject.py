"""Chaos injectors. Deterministic, seeded, no external dependencies.

Each injector:
  - takes (out_dir: Path, seed: int) -> Fixture
  - writes: fixture.yaml, log.txt, schema_before.json, schema_after.json,
            repo/ (a git repo with the model files)
"""
from __future__ import annotations

import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


# ----------- helpers -----------

def _init_repo(repo_path: Path, files: dict[str, str]) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo_path)], check=True)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "chaos@shdpa.local"],
                   check=True)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "chaos"], check=True)
    for rel, content in files.items():
        p = repo_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-q", "-m", "initial"], check=True)


def _write_fixture(out_dir: Path, fixture: dict, log: str,
                   schema_before: dict, schema_after: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "log.txt").write_text(log, encoding="utf-8")
    (out_dir / "schema_before.json").write_text(json.dumps(schema_before, indent=2))
    (out_dir / "schema_after.json").write_text(json.dumps(schema_after, indent=2))
    (out_dir / "fixture.yaml").write_text(yaml.safe_dump(fixture, sort_keys=False))


# ----------- TPC-H scaffolding -----------

TPCH_BASE_SCHEMA: dict[str, dict[str, str]] = {
    "orders": {
        "o_orderkey": "integer",
        "o_custkey": "integer",
        "o_orderstatus": "text",
        "o_totalprice": "numeric",
        "o_orderdate": "date",
        "o_priority": "text",
        "o_clerk": "text",
        "o_shippriority": "integer",
        "o_comment": "text",
    },
    "customer": {
        "c_custkey": "integer",
        "c_name": "text",
        "c_address": "text",
        "c_nationkey": "integer",
        "c_phone": "text",
        "c_acctbal": "numeric",
        "c_mktsegment": "text",
        "c_comment": "text",
    },
    "lineitem": {
        "l_orderkey": "integer",
        "l_partkey": "integer",
        "l_suppkey": "integer",
        "l_quantity": "numeric",
        "l_extendedprice": "numeric",
        "l_discount": "numeric",
        "l_tax": "numeric",
        "l_shipdate": "date",
    },
}


def _model_sql(model: str, sql: str) -> dict[str, str]:
    return {f"models/{model}.sql": sql, "README.md": f"# tpch warehouse\nmodel: {model}\n"}


# ----------- injectors -----------

@dataclass
class Fixture:
    id: str


def inject_schema_rename_column(out_dir: Path, seed: int = 0) -> Fixture:
    rng = random.Random(seed)
    rename_choices = [
        ("orders", "o_priority", "priority"),
        ("orders", "o_clerk", "clerk_name"),
        ("customer", "c_mktsegment", "market_segment"),
        ("lineitem", "l_quantity", "qty"),
    ]
    table, old_col, new_col = rng.choice(rename_choices)
    fid = f"schema_rename_{table}_{old_col}_{seed:03d}"

    schema_before = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    schema_after = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    schema_after[table][new_col] = schema_after[table].pop(old_col)

    model_sql = (
        f"-- stg_{table}.sql\n"
        f"select\n"
        f"    *,\n"
        f"    {old_col} as priority_label\n"
        f"from {{{{ source('raw', '{table}') }}}}\n"
    )
    repo_path = out_dir / "repo"
    _init_repo(repo_path, _model_sql(f"stg_{table}", model_sql))

    log = (
        "[2026-05-21 02:14:09] INFO  - airflow.task: running stg_{t}.sql\n"
        "[2026-05-21 02:14:10] ERROR - psycopg.errors.UndefinedColumn: "
        'column "{c}" does not exist\n'
        "LINE 3:     {c} as priority_label\n"
        "                ^\n"
        "HINT:  Perhaps you meant to reference \"{table}.{n}\".\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/airflow/dags/tpch.py", line 42, in run_model\n'
        "    cur.execute(sql)\n"
        "psycopg.errors.UndefinedColumn: column \"{c}\" does not exist\n"
    ).format(t=table, c=old_col, n=new_col, table=table)

    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": f"stg_{table}_dag",
            "task_id": f"stg_{table}",
            "run_id": f"scheduled__2026-05-21T02:00:00+seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": f'column "{old_col}" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": f"upstream renamed {table}.{old_col} to {table}.{new_col}",
            "fix": {
                "kind": "code_patch",
                "files_changed": [f"models/stg_{table}.sql"],
                "must_include_strings": [old_col, new_col],
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_schema_rename_column"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def inject_schema_drop_column(out_dir: Path, seed: int = 0) -> Fixture:
    rng = random.Random(seed + 1000)
    dropped = [
        ("orders", "o_shippriority"),
        ("customer", "c_comment"),
        ("lineitem", "l_tax"),
    ]
    table, col = rng.choice(dropped)
    fid = f"schema_drop_{table}_{col}_{seed:03d}"

    schema_before = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    schema_after = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    del schema_after[table][col]

    sql = f"select {col}, count(*) from {{{{ ref('stg_{table}') }}}} group by 1\n"
    _init_repo(out_dir / "repo", _model_sql(f"mart_{table}", sql))

    log = (
        f"ERROR - psycopg.errors.UndefinedColumn: column \"{col}\" does not exist\n"
        f"LINE 1: select {col}, count(*) from {table} group by 1\n"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": f"mart_{table}_dag",
            "task_id": f"mart_{table}",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": f'column "{col}" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": f"upstream dropped {table}.{col}",
            "fix": {
                "kind": "code_patch",
                "files_changed": [f"models/mart_{table}.sql"],
                "must_include_strings": [col],
            },
            "severity": "P2",
            "auto_fixable": False,  # drop is harder; PR-only
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_schema_drop_column"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def inject_upstream_5xx(out_dir: Path, seed: int = 0) -> Fixture:
    rng = random.Random(seed + 2000)
    code = rng.choice([500, 502, 503, 504])
    fid = f"upstream_5xx_{code}_{seed:03d}"
    log = (
        f"[2026-05-21 03:10:11] INFO  - calling https://api.vendor.com/extract\n"
        f"[2026-05-21 03:10:31] ERROR - requests.exceptions.HTTPError: "
        f"{code} Server Error: Bad Gateway for url: https://api.vendor.com/extract\n"
        f"Traceback (most recent call last):\n"
        f"  File \"extract.py\", line 88, in main\n"
        f"    r.raise_for_status()\n"
        f"requests.exceptions.HTTPError: {code} Server Error\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("extract_vendor", "-- noop\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "extract_vendor_dag",
            "task_id": "extract_vendor",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "requests.exceptions.HTTPError",
            "exception_message": f"{code} Server Error",
        },
        "ground_truth": {
            "failure_class": "upstream_5xx",
            "root_cause_summary": f"vendor API returned {code}; retry should succeed",
            "fix": {"kind": "retry", "files_changed": [], "must_include_strings": []},
            "severity": "P3",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_upstream_5xx"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_dep_conflict(out_dir: Path, seed: int = 0) -> Fixture:
    rng = random.Random(seed + 3000)
    pkg = rng.choice(["pandas", "sqlalchemy", "great_expectations", "duckdb"])
    fid = f"dep_conflict_{pkg}_{seed:03d}"
    log = (
        f"[2026-05-21 04:01:09] ERROR - Traceback (most recent call last):\n"
        f"  File \"/opt/airflow/dags/transform.py\", line 3, in <module>\n"
        f"    import {pkg}\n"
        f"ModuleNotFoundError: No module named '{pkg}'\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("transform", f"-- imports {pkg}\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "transform_dag",
            "task_id": "transform",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "ModuleNotFoundError",
            "exception_message": f"No module named '{pkg}'",
        },
        "ground_truth": {
            "failure_class": "dep_conflict",
            "root_cause_summary": f"missing/incompatible package: {pkg}",
            "fix": {"kind": "config_change", "files_changed": ["requirements.txt"],
                    "must_include_strings": [pkg]},
            "severity": "P2",
            "auto_fixable": False,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_dep_conflict"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_oom(out_dir: Path, seed: int = 0) -> Fixture:
    fid = f"oom_{seed:03d}"
    log = (
        "[2026-05-21 05:30:01] INFO  - loading parquet shard\n"
        "[2026-05-21 05:30:42] ERROR - Task process exited with exit code 137 "
        "(out-of-memory; SIGKILL by cgroup)\n"
        "  MemoryError: Unable to allocate 14.2 GiB for an array with shape (1900000000,)\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("bigjoin", "select * from lineitem join orders on l_orderkey=o_orderkey\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "bigjoin_dag",
            "task_id": "bigjoin",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "MemoryError",
            "exception_message": "Unable to allocate ...",
        },
        "ground_truth": {
            "failure_class": "oom",
            "root_cause_summary": "task exceeded worker memory; needs chunked read or larger node",
            "fix": {"kind": "config_change", "files_changed": ["models/bigjoin.sql"],
                    "must_include_strings": ["chunk"]},
            "severity": "P2",
            "auto_fixable": False,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_oom"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_auth_expiry(out_dir: Path, seed: int = 0) -> Fixture:
    fid = f"auth_expiry_{seed:03d}"
    log = (
        "[2026-05-21 06:01:11] ERROR - google.auth.exceptions.RefreshError: "
        "('invalid_grant: Token has been expired or revoked.',)\n"
        "401 Unauthorized\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("gcs_load", "-- gcs load\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "gcs_load_dag",
            "task_id": "gcs_load",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "google.auth.exceptions.RefreshError",
            "exception_message": "Token has been expired or revoked",
        },
        "ground_truth": {
            "failure_class": "auth_expiry",
            "root_cause_summary": "service-account token expired; needs rotation",
            "fix": {"kind": "secret_rotate", "files_changed": [], "must_include_strings": []},
            "severity": "P1",
            "auto_fixable": False,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_auth_expiry"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_idempotency(out_dir: Path, seed: int = 0) -> Fixture:
    fid = f"idempotency_{seed:03d}"
    log = (
        "[2026-05-21 07:11:09] ERROR - psycopg.errors.UniqueViolation: "
        'duplicate key value violates unique constraint "orders_pkey"\n'
        "DETAIL:  Key (o_orderkey)=(123456) already exists.\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("merge_orders", "insert into orders select * from staging.orders\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "merge_orders_dag",
            "task_id": "merge_orders",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UniqueViolation",
            "exception_message": "duplicate key value",
        },
        "ground_truth": {
            "failure_class": "idempotency",
            "root_cause_summary": "naive insert overlaps with previous run; needs MERGE/UPSERT",
            "fix": {"kind": "code_patch", "files_changed": ["models/merge_orders.sql"],
                    "must_include_strings": ["on conflict"]},
            "severity": "P2",
            "auto_fixable": False,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_idempotency"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_disk_full(out_dir: Path, seed: int = 0) -> Fixture:
    fid = f"disk_full_{seed:03d}"
    log = (
        "[2026-05-21 08:09:01] ERROR - OSError: [Errno 28] No space left on device\n"
        "  airflow.exceptions.AirflowException: XCom value exceeds 48 KB limit\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("export_large", "-- exports a lot via XCom\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "export_large_dag",
            "task_id": "export_large",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "OSError",
            "exception_message": "No space left on device",
        },
        "ground_truth": {
            "failure_class": "disk_full",
            "root_cause_summary": "XCom + logs filled volume; prune > 7d",
            "fix": {"kind": "config_change", "files_changed": [], "must_include_strings": []},
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_disk_full"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_dag_import(out_dir: Path, seed: int = 0) -> Fixture:
    fid = f"dag_import_{seed:03d}"
    log = (
        "[2026-05-21 09:00:00] ERROR - Scheduler: DagBag import errors:\n"
        "  /opt/airflow/dags/tpch.py:\n"
        "    Traceback (most recent call last):\n"
        '      File "/opt/airflow/dags/tpch.py", line 8, in <module>\n'
        "        dag = DAG(\"tpch\", schedule=\"@daily\", start_date=datetime(2026,5,1))\n"
        "    NameError: name 'datetime' is not defined\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    bad_dag = (
        "from airflow import DAG\n"
        # intentional missing import: from datetime import datetime
        "dag = DAG('tpch', schedule='@daily', start_date=datetime(2026,5,1))\n"
    )
    _init_repo(out_dir / "repo", {"dags/tpch.py": bad_dag, "README.md": "#\n"})
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "tpch",
            "task_id": "<dag_parse>",
            "run_id": f"parse__seed={seed}",
            "exception_type": "NameError",
            "exception_message": "name 'datetime' is not defined",
        },
        "ground_truth": {
            "failure_class": "dag_import",
            "root_cause_summary": "missing `from datetime import datetime` in DAG file",
            "fix": {"kind": "code_patch", "files_changed": ["dags/tpch.py"],
                    "must_include_strings": ["from datetime import datetime"]},
            "severity": "P1",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_dag_import"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


def inject_null_spike(out_dir: Path, seed: int = 0) -> Fixture:
    rng = random.Random(seed + 4000)
    col = rng.choice(["c_acctbal", "o_totalprice", "l_extendedprice"])
    fid = f"null_spike_{col}_{seed:03d}"
    log = (
        f"[2026-05-21 10:00:00] ERROR - dbt test failure: not_null_{col}\n"
        f"  Got 18421 results, expected 0.\n"
        f"  Column {col} has 18% NULLs (baseline 0.02%).\n"
    )
    schema = {t: dict(c) for t, c in TPCH_BASE_SCHEMA.items()}
    _init_repo(out_dir / "repo", _model_sql("dq_check", f"-- not_null({col})\n"))
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "dq_dag",
            "task_id": "dq_check",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "dbt.exceptions.TestFailure",
            "exception_message": f"not_null({col}) failed",
        },
        "ground_truth": {
            "failure_class": "null_spike",
            "root_cause_summary": f"sudden null rate on {col}; upstream issue, PR-only",
            "fix": {"kind": "code_patch", "files_changed": ["models/dq_check.sql"],
                    "must_include_strings": [col, "is not null"]},
            "severity": "P3",
            "auto_fixable": False,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "inject_null_spike"},
        "license": "MIT",
    }
    _write_fixture(out_dir, fixture, log, schema, schema)
    return Fixture(id=fid)


# Registry
INJECTORS: dict[str, Callable[[Path, int], Fixture]] = {
    "schema_rename_column": inject_schema_rename_column,
    "schema_drop_column": inject_schema_drop_column,
    "upstream_5xx": inject_upstream_5xx,
    "dep_conflict": inject_dep_conflict,
    "oom": inject_oom,
    "auth_expiry": inject_auth_expiry,
    "idempotency": inject_idempotency,
    "disk_full": inject_disk_full,
    "dag_import": inject_dag_import,
    "null_spike": inject_null_spike,
}


def generate_fixture(kind: str, out_dir: Path, seed: int = 0) -> Fixture:
    if kind not in INJECTORS:
        raise KeyError(f"unknown injector: {kind}")
    return INJECTORS[kind](out_dir, seed)

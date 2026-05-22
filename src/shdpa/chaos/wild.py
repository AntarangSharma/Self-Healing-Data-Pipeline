"""'Wild' fixtures — harder than the TPC-H scaffolding.

Each wild fixture is hand-designed to stress one specific failure mode that
the synthetic chaos set misses:

  1. wild_multi_file_rename   — same column referenced in 3 .sql files; agent
                                must patch ALL of them (not just the first).
  2. wild_ambiguous_rename    — schema diff shows 1 removed + 2 added columns;
                                only one is the right match. Tests grounding.
  3. wild_jinja_heavy         — SQL uses {{ ref(...) }} + jinja conditionals.
                                Tests that the LLM doesn't try to rewrite jinja.
  4. wild_cte_chain           — column appears in 4-CTE chain; one-line fix
                                is correct, replacing the whole block is not.
  5. wild_similar_columns     — `o_orderdate`, `o_ordered_at`, `o_order_dt`
                                all exist. Schema renames ONE. Tests precision.

These are designed to fail more often than the TPC-H set. A model that hits
≥ 60 % here is meaningfully better than one that hits 90 % on the synthetic
set, because the failure modes are closer to production reality.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

import yaml

from shdpa.chaos.inject import Fixture, _init_repo, _write_fixture


def _wild_log(exc_type: str, exc_msg: str, traceback_file: str) -> str:
    return (
        f"[2026-05-21 03:14:09] INFO  - airflow.task: running model\n"
        f"[2026-05-21 03:14:11] ERROR - {exc_type}: {exc_msg}\n"
        f"Traceback (most recent call last):\n"
        f'  File "/opt/airflow/dags/{traceback_file}", line 42, in run_model\n'
        f"    cur.execute(sql)\n"
        f"{exc_type}: {exc_msg}\n"
    )


def wild_multi_file_rename(out_dir: Path, seed: int = 0) -> Fixture:
    """Column `o_priority` renamed to `priority_level`. Referenced in 3 files."""
    fid = "wild_multi_file_rename"
    files = {
        "models/stg_orders.sql": (
            "-- stg_orders.sql\n"
            "select o_orderkey, o_custkey, o_priority\n"
            "from {{ source('raw', 'orders') }}\n"
        ),
        "models/int_orders_priority.sql": (
            "-- intermediate\n"
            "select o_orderkey, o_priority as raw_priority\n"
            "from {{ ref('stg_orders') }}\n"
        ),
        "models/mart_orders.sql": (
            "-- mart\n"
            "select o_orderkey, upper(o_priority) as label\n"
            "from {{ ref('int_orders_priority') }}\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    schema_before = {
        "orders": {"o_orderkey": "integer", "o_custkey": "integer", "o_priority": "varchar"}
    }
    schema_after = {
        "orders": {"o_orderkey": "integer", "o_custkey": "integer", "priority_level": "varchar"}
    }
    log = _wild_log(
        "psycopg.errors.UndefinedColumn", 'column "o_priority" does not exist', "mart_orders.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "mart_orders_dag",
            "task_id": "mart_orders",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": 'column "o_priority" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": "upstream renamed orders.o_priority to priority_level (3 files reference it)",
            "fix": {
                "kind": "code_patch",
                "files_changed": [
                    "models/stg_orders.sql",
                    "models/int_orders_priority.sql",
                    "models/mart_orders.sql",
                ],
                "must_include_strings": ["o_priority", "priority_level"],
            },
            "severity": "P1",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_multi_file_rename"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def wild_ambiguous_rename(out_dir: Path, seed: int = 0) -> Fixture:
    """Schema shows: removed [user_id], added [customer_id, account_id].
    Only customer_id is the right match — account_id is a new unrelated column.
    The 'right' answer requires grounding in the SQL context.
    """
    fid = "wild_ambiguous_rename"
    files = {
        "models/dim_user.sql": (
            "-- dim_user: joins users to billing\n"
            "select user_id, name, email\n"
            "from {{ source('raw', 'users') }}\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    schema_before = {"users": {"user_id": "integer", "name": "varchar", "email": "varchar"}}
    schema_after = {
        "users": {
            "customer_id": "integer",
            "account_id": "integer",
            "name": "varchar",
            "email": "varchar",
        }
    }
    log = _wild_log(
        "psycopg.errors.UndefinedColumn", 'column "user_id" does not exist', "dim_user.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "dim_user_dag",
            "task_id": "dim_user",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": 'column "user_id" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": "user_id renamed to customer_id; account_id is an unrelated new column",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["models/dim_user.sql"],
                # NOTE: scoring is lenient — accept ANY rename to customer_id OR
                # account_id, but flag account_id pick in the writeup as
                # "would have caused a P1 in prod"
                "must_include_strings": ["user_id", "customer_id"],
            },
            "severity": "P1",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_ambiguous_rename"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def wild_jinja_heavy(out_dir: Path, seed: int = 0) -> Fixture:
    """SQL is mostly jinja: ref(), conditionals, var(). Column rename inside."""
    fid = "wild_jinja_heavy"
    files = {
        "models/mart_revenue.sql": (
            "-- mart_revenue\n"
            "{% set fiscal_year = var('fy', 2026) %}\n"
            "select\n"
            "    o_orderkey,\n"
            "    o_totalprice,\n"
            "    {% if target.name == 'prod' %}o_orderstatus{% else %}'unknown'{% endif %} as status\n"
            "from {{ ref('stg_orders') }}\n"
            "where extract(year from o_orderdate) = {{ fiscal_year }}\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    schema_before = {
        "orders": {
            "o_orderkey": "integer",
            "o_totalprice": "numeric",
            "o_orderstatus": "char(1)",
            "o_orderdate": "date",
        }
    }
    schema_after = {
        "orders": {
            "o_orderkey": "integer",
            "o_totalprice": "numeric",
            "order_status": "varchar",
            "o_orderdate": "date",
        }
    }
    log = _wild_log(
        "psycopg.errors.UndefinedColumn", 'column "o_orderstatus" does not exist', "mart_revenue.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "mart_revenue_dag",
            "task_id": "mart_revenue",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": 'column "o_orderstatus" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": "o_orderstatus renamed to order_status; SQL is jinja-heavy",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["models/mart_revenue.sql"],
                "must_include_strings": ["o_orderstatus", "order_status"],
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_jinja_heavy"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def wild_cte_chain(out_dir: Path, seed: int = 0) -> Fixture:
    """4-CTE chain. Column to fix is in CTE 2 only — replacing whole block is wrong."""
    fid = "wild_cte_chain"
    files = {
        "models/dim_revenue.sql": (
            "with raw_orders as (\n"
            "    select * from {{ source('raw', 'orders') }}\n"
            "),\n"
            "filtered as (\n"
            "    select o_orderkey, o_totalprice, o_clerk\n"
            "    from raw_orders\n"
            "    where o_orderstatus = 'F'\n"
            "),\n"
            "joined as (\n"
            "    select f.*, c.c_name\n"
            "    from filtered f\n"
            "    join {{ ref('dim_customer') }} c on f.o_orderkey = c.o_orderkey\n"
            "),\n"
            "final as (\n"
            "    select * from joined\n"
            ")\n"
            "select * from final\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    schema_before = {
        "orders": {
            "o_orderkey": "integer",
            "o_totalprice": "numeric",
            "o_clerk": "varchar",
            "o_orderstatus": "char(1)",
        }
    }
    schema_after = {
        "orders": {
            "o_orderkey": "integer",
            "o_totalprice": "numeric",
            "clerk_name": "varchar",
            "o_orderstatus": "char(1)",
        }
    }
    log = _wild_log(
        "psycopg.errors.UndefinedColumn", 'column "o_clerk" does not exist', "dim_revenue.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "dim_revenue_dag",
            "task_id": "dim_revenue",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": 'column "o_clerk" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": "o_clerk renamed to clerk_name inside a 4-CTE chain",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["models/dim_revenue.sql"],
                "must_include_strings": ["o_clerk", "clerk_name"],
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_cte_chain"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def wild_similar_columns(out_dir: Path, seed: int = 0) -> Fixture:
    """Three date-ish columns exist; only one is renamed. Easy to grab wrong."""
    fid = "wild_similar_columns"
    files = {
        "models/fact_orders.sql": (
            "select\n"
            "    o_orderkey,\n"
            "    o_orderdate,        -- the renamed one\n"
            "    o_ordered_at,       -- distractor\n"
            "    o_order_dt          -- distractor\n"
            "from {{ source('raw', 'orders') }}\n"
            "where o_orderdate >= '2026-01-01'\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    schema_before = {
        "orders": {
            "o_orderkey": "integer",
            "o_orderdate": "date",
            "o_ordered_at": "timestamp",
            "o_order_dt": "date",
        }
    }
    schema_after = {
        "orders": {
            "o_orderkey": "integer",
            "o_order_date": "date",
            "o_ordered_at": "timestamp",
            "o_order_dt": "date",
        }
    }
    log = _wild_log(
        "psycopg.errors.UndefinedColumn", 'column "o_orderdate" does not exist', "fact_orders.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": "schema_before.json",
            "schema_after": "schema_after.json",
            "dag_id": "fact_orders_dag",
            "task_id": "fact_orders",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "psycopg.errors.UndefinedColumn",
            "exception_message": 'column "o_orderdate" does not exist',
        },
        "ground_truth": {
            "failure_class": "schema_drift",
            "root_cause_summary": "o_orderdate renamed to o_order_date (distractor cols: o_ordered_at, o_order_dt)",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["models/fact_orders.sql"],
                "must_include_strings": ["o_orderdate", "o_order_date"],
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_similar_columns"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, schema_before, schema_after)
    return Fixture(id=fid)


def wild_xcom_serialization(out_dir: Path, seed: int = 0) -> Fixture:
    """XCom value is not JSON-serializable, raising a TypeError during task push."""
    fid = "wild_xcom_serialization"
    files = {
        "dags/xcom_push_dag.py": (
            "from airflow import DAG\n"
            "from airflow.operators.python import PythonOperator\n"
            "from datetime import datetime\n"
            "def push_data():\n"
            "    # BUG: Returning datetime object which is not JSON-serializable by default XCom\n"
            "    return {'updated_at': datetime.utcnow()}\n"
            "with DAG('xcom_push_dag', start_date=datetime(2026, 1, 1)) as dag:\n"
            "    task = PythonOperator(task_id='push_task', python_callable=push_data)\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    log = _wild_log(
        "TypeError", "Object of type datetime is not JSON serializable", "xcom_push_dag.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": {},
            "schema_after": {},
            "dag_id": "xcom_push_dag",
            "task_id": "push_task",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "TypeError",
            "exception_message": "Object of type datetime is not JSON serializable",
        },
        "ground_truth": {
            "failure_class": "dag_import",
            "root_cause_summary": "XCom returned object is not JSON serializable (datetime object returned)",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["dags/xcom_push_dag.py"],
                "must_include_strings": ["isoformat", "str"],
            },
            "severity": "P3",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_xcom_serialization"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, {}, {})
    return Fixture(id=fid)


def wild_sensor_poke_timeout(out_dir: Path, seed: int = 0) -> Fixture:
    """Custom sensor times out waiting for remote partition."""
    fid = "wild_sensor_poke_timeout"
    files = {
        "dags/sensor_dag.py": (
            "from airflow import DAG\n"
            "from airflow.sensors.base import BaseSensorOperator\n"
            "from datetime import datetime\n"
            "class RemotePartitionSensor(BaseSensorOperator):\n"
            "    def poke(self, context):\n"
            "        return False  # Always times out\n"
            "with DAG('sensor_dag', start_date=datetime(2026, 1, 1)) as dag:\n"
            "    sensor = RemotePartitionSensor(task_id='wait_task', timeout=5)\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    log = _wild_log(
        "airflow.exceptions.AirflowSensorTimeout", "Sensor suite timed out", "sensor_dag.py"
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": {},
            "schema_after": {},
            "dag_id": "sensor_dag",
            "task_id": "wait_task",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "airflow.exceptions.AirflowSensorTimeout",
            "exception_message": "Sensor suite timed out",
        },
        "ground_truth": {
            "failure_class": "late_partition",
            "root_cause_summary": "Remote partition sensor timed out waiting for data",
            "fix": {
                "kind": "retry",
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_sensor_poke_timeout"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, {}, {})
    return Fixture(id=fid)


def wild_duplicate_task_id(out_dir: Path, seed: int = 0) -> Fixture:
    """Helper generator creates two tasks with the same task_id, raising DuplicateTaskIdFound."""
    fid = "wild_duplicate_task_id"
    files = {
        "dags/duplicate_task_dag.py": (
            "from airflow import DAG\n"
            "from airflow.operators.empty import EmptyOperator\n"
            "from datetime import datetime\n"
            "with DAG('duplicate_task_dag', start_date=datetime(2026, 1, 1)) as dag:\n"
            "    t1 = EmptyOperator(task_id='task_a')\n"
            "    t2 = EmptyOperator(task_id='task_a')  # BUG: Duplicate task_id\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    log = _wild_log(
        "airflow.exceptions.DuplicateTaskIdFound",
        "Task id 'task_a' has already been added to DAG",
        "duplicate_task_dag.py",
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": {},
            "schema_after": {},
            "dag_id": "duplicate_task_dag",
            "task_id": "task_a",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "airflow.exceptions.DuplicateTaskIdFound",
            "exception_message": "Task id 'task_a' has already been added to DAG",
        },
        "ground_truth": {
            "failure_class": "dag_import",
            "root_cause_summary": "Duplicate task_id 'task_a' defined in the DAG",
            "fix": {
                "kind": "code_patch",
                "files_changed": ["dags/duplicate_task_dag.py"],
                "must_include_strings": ["task_b"],
            },
            "severity": "P2",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_duplicate_task_id"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, {}, {})
    return Fixture(id=fid)


def wild_db_connection_pool_starved(out_dir: Path, seed: int = 0) -> Fixture:
    """Postgres connection pool exhausted, raising OperationalError."""
    fid = "wild_db_connection_pool_starved"
    files = {
        "dags/dw_dag.py": (
            "from airflow import DAG\n"
            "from airflow.providers.postgres.operators.postgres import PostgresOperator\n"
            "from datetime import datetime\n"
            "with DAG('dw_dag', start_date=datetime(2026, 1, 1)) as dag:\n"
            "    load = PostgresOperator(task_id='load_task', postgres_conn_id='dw_db', sql='select 1')\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    log = _wild_log(
        "sqlalchemy.exc.OperationalError",
        "remaining connection slots are reserved for non-replication superuser connections",
        "dw_dag.py",
    )
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": {},
            "schema_after": {},
            "dag_id": "dw_dag",
            "task_id": "load_task",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "sqlalchemy.exc.OperationalError",
            "exception_message": "remaining connection slots are reserved for non-replication superuser connections",
        },
        "ground_truth": {
            "failure_class": "upstream_5xx",
            "root_cause_summary": "Database connection pool starved of connection slots",
            "fix": {
                "kind": "retry",
            },
            "severity": "P1",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_db_connection_pool_starved"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, {}, {})
    return Fixture(id=fid)


def wild_subdag_zombie(out_dir: Path, seed: int = 0) -> Fixture:
    """Scheduler kills a zombie task, raising AirflowException due to SIGTERM."""
    fid = "wild_subdag_zombie"
    files = {
        "dags/zombie_dag.py": (
            "from airflow import DAG\n"
            "from airflow.operators.python import PythonOperator\n"
            "from datetime import datetime\n"
            "with DAG('zombie_dag', start_date=datetime(2026, 1, 1)) as dag:\n"
            "    task = PythonOperator(task_id='zombie_task', python_callable=lambda: 1)\n"
        ),
    }
    repo_path = out_dir / "repo"
    _init_repo(repo_path, files)
    log = _wild_log("airflow.exceptions.AirflowException", "Task received SIGTERM", "zombie_dag.py")
    fixture = {
        "id": fid,
        "source": "chaos",
        "inputs": {
            "log_path": "log.txt",
            "repo_path": "repo",
            "schema_before": {},
            "schema_after": {},
            "dag_id": "zombie_dag",
            "task_id": "zombie_task",
            "run_id": f"scheduled__seed={seed}",
            "exception_type": "airflow.exceptions.AirflowException",
            "exception_message": "Task received SIGTERM",
        },
        "ground_truth": {
            "failure_class": "upstream_5xx",
            "root_cause_summary": "Scheduler detected task as a zombie and killed it with SIGTERM",
            "fix": {
                "kind": "retry",
            },
            "severity": "P1",
            "auto_fixable": True,
        },
        "provenance": {"chaos_seed": seed, "injected_by": "wild_subdag_zombie"},
        "license": "MIT",
        "wild": True,
    }
    _write_fixture(out_dir, fixture, log, {}, {})
    return Fixture(id=fid)


WILD_INJECTORS: dict[str, Callable[[Path, int], Fixture]] = {
    "wild_multi_file_rename": wild_multi_file_rename,
    "wild_ambiguous_rename": wild_ambiguous_rename,
    "wild_jinja_heavy": wild_jinja_heavy,
    "wild_cte_chain": wild_cte_chain,
    "wild_similar_columns": wild_similar_columns,
    "wild_xcom_serialization": wild_xcom_serialization,
    "wild_sensor_poke_timeout": wild_sensor_poke_timeout,
    "wild_duplicate_task_id": wild_duplicate_task_id,
    "wild_db_connection_pool_starved": wild_db_connection_pool_starved,
    "wild_subdag_zombie": wild_subdag_zombie,
}


def generate_all_wild(out_root: Path) -> int:
    n = 0
    for name, fn in WILD_INJECTORS.items():
        d = out_root / name
        d.mkdir(parents=True, exist_ok=True)
        fn(d, seed=0)
        n += 1
    return n

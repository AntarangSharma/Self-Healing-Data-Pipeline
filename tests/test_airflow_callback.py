import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add airflow/plugins to sys.path so we can import shdpa_callback
plugins_path = Path(__file__).resolve().parent.parent / "airflow" / "plugins"
if str(plugins_path) not in sys.path:
    sys.path.insert(0, str(plugins_path))

from shdpa_callback import shdpa_on_failure_callback, _safe_str, _tail_log


def test_safe_str():
    assert _safe_str("hello") == "hello"

    class FailingStr:
        def __str__(self):
            raise ValueError("bad str")

        def __repr__(self):
            return "FailingStrRepr"

    res = _safe_str(FailingStr())
    assert res == "FailingStrRepr"


def test_tail_log(tmp_path):
    # Test directly reading log filepath
    log_file = tmp_path / "test.log"
    log_file.write_text("line 1\nline 2\nline 3\n")

    mock_ti = MagicMock()
    mock_ti.log_filepath = str(log_file)
    assert _tail_log(mock_ti, n_lines=2) == "line 2\nline 3\n"

    # Test fallback to log_url
    mock_ti2 = MagicMock()
    mock_ti2.log_filepath = None
    mock_ti2.log_url = "http://airflow/log"
    assert _tail_log(mock_ti2) == "http://airflow/log"


def test_airflow_callback_post_format():
    mock_ti = MagicMock()
    mock_ti.task_id = "test_task"
    mock_ti.run_id = "test_run"
    mock_ti.log_filepath = None
    mock_ti.log_url = "http://airflow/log"

    mock_dag = MagicMock()
    mock_dag.dag_id = "test_dag"

    mock_exc = Exception("Test exception message")

    context = {
        "task_instance": mock_ti,
        "exception": mock_exc,
        "dag": mock_dag,
    }

    with patch("shdpa_callback.urlopen") as mock_urlopen, \
         patch("shdpa_callback.Request") as mock_req_class:

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        shdpa_on_failure_callback(context)

        mock_req_class.assert_called_once()
        args, kwargs = mock_req_class.call_args
        url = args[0]
        assert url == "http://shdpa:8080/incidents"

        body_json = kwargs["data"].decode("utf-8")
        body = json.loads(body_json)
        assert body["source"] == "airflow_callback"
        assert body["dag_id"] == "test_dag"
        assert body["task_id"] == "test_task"
        assert body["run_id"] == "test_run"
        assert body["exception_type"] == "Exception"
        assert body["exception_message"] == "Test exception message"

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add repo root to sys.path so we can import dbt
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from dbt.adapters.shdpa_dbt_callback import main as dbt_main, _to_incident, _post


def test_post_success():
    with patch("dbt.adapters.shdpa_dbt_callback.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert _post("http://localhost/test", {"test": "data"}) is True


def test_post_fail():
    with patch("dbt.adapters.shdpa_dbt_callback.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = Exception("conn error")
        assert _post("http://localhost/test", {"test": "data"}) is False


def test_to_incident():
    node = {
        "unique_id": "model.test_project.my_model",
        "status": "fail",
        "message": "Validation failed",
        "compiled_code": "SELECT * FROM my_table",
    }
    project = Path("/tmp/my_project")
    inc = _to_incident(node, project)
    assert inc["source"] == "manual"
    assert inc["dag_id"] == "dbt:my_project"
    assert inc["task_id"] == "model.test_project.my_model"
    assert inc["exception_type"] == "DbtTestFailure"
    assert "compiled SQL" in inc["log_text"]


def test_dbt_callback_main(tmp_path):
    project_dir = tmp_path / "my_project"
    target_dir = project_dir / "target"
    target_dir.mkdir(parents=True)

    # Write a mock run_results.json
    run_results = {
        "results": [
            {
                "unique_id": "model.test_project.my_model",
                "status": "fail",
                "message": "Validation failed",
                "compiled_code": "SELECT * FROM my_table",
            },
            {
                "unique_id": "model.test_project.other_model",
                "status": "success",
                "message": None,
                "compiled_code": None,
            }
        ]
    }
    (target_dir / "run_results.json").write_text(json.dumps(run_results))

    with patch("dbt.adapters.shdpa_dbt_callback.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        code = dbt_main(["shdpa_dbt_callback", str(project_dir)])
        assert code == 0

        # Assert urlopen was called once (since only one result failed)
        assert mock_urlopen.call_count == 1

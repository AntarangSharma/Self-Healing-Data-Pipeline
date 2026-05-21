import shutil
import tempfile
from pathlib import Path
from shdpa.chaos import INJECTORS, generate_fixture


def test_each_injector_produces_a_valid_fixture():
    tmp = Path(tempfile.mkdtemp())
    try:
        for name in INJECTORS:
            out = tmp / name
            generate_fixture(name, out, seed=0)
            assert (out / "fixture.yaml").exists()
            assert (out / "log.txt").exists()
            assert (out / "schema_before.json").exists()
            assert (out / "schema_after.json").exists()
            assert (out / "repo").exists()
    finally:
        shutil.rmtree(tmp)

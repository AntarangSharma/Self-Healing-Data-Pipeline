.PHONY: install fmt lint type test fixtures eval demo clean

PY := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYV := $(VENV)/bin/python
SHDPA := $(VENV)/bin/shdpa

$(VENV):
	$(PY) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

install: $(VENV) ## install in editable mode with dev deps

fmt: $(VENV)
	$(VENV)/bin/ruff format src tests

lint: $(VENV)
	$(VENV)/bin/ruff check src tests

type: $(VENV)
	$(VENV)/bin/mypy src

test: $(VENV)
	$(VENV)/bin/pytest -ra

fixtures: $(VENV) ## generate 20 fixtures (2 per class × 10 classes)
	rm -rf fixtures
	$(SHDPA) gen-fixtures --out fixtures --n-per-class 2

eval: $(VENV) ## run B0,B1,B2,ours on the fixture set
	$(SHDPA) eval --fixtures fixtures --policy b0,b1,b2,ours --out results.jsonl

demo: $(VENV) ## run the agent on the reference incident (schema rename)
	@if [ ! -d "fixtures" ]; then $(MAKE) fixtures; fi
	$(SHDPA) demo --fixture fixtures/schema_rename_column__seed_000

quickstart: install fixtures eval ## end-to-end: install, gen fixtures, eval

clean:
	rm -rf $(VENV) results.jsonl fixtures __pycache__ .pytest_cache .mypy_cache .ruff_cache

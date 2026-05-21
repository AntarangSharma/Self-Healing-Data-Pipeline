"""Chaos injectors. Each produces a fixture (log, schemas, repo snapshot, ground truth)."""
from shdpa.chaos.inject import INJECTORS, generate_fixture
__all__ = ["INJECTORS", "generate_fixture"]

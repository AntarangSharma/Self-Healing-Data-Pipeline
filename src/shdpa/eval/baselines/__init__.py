"""Baselines to beat.

B0: restart-only (no diagnosis, returns 'retry' for every incident)
B1: rules-only (regex → class → templated fix)
B2: single LLM call (logs pasted, no tools)
"""

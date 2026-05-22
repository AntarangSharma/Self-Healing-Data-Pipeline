-- shdpa_on_run_end: dbt post-hook that triggers the agent on test failure.
--
-- Wiring:
--   In dbt_project.yml:
--     on-run-end:
--       - "{{ shdpa_on_run_end() }}"
--
-- The macro writes a JSON line to target/shdpa_failures.jsonl for each failed
-- result. The companion Python adapter (`dbt/adapters/shdpa_dbt_callback.py`)
-- reads that file post-run and POSTs each row to the agent's /incidents.
--
-- We write to a file (not call the agent directly) because dbt macros run
-- inside the warehouse — no outbound HTTP. The Python wrapper is the bridge.

{% macro shdpa_on_run_end() %}
  {% if execute %}
    {% set out = [] %}
    {% for r in results %}
      {% if r.status in ('error', 'fail') %}
        {% set row = {
          "node_id":   r.node.unique_id,
          "name":      r.node.name,
          "resource_type": r.node.resource_type,
          "status":    r.status,
          "message":   r.message,
          "execution_time": r.execution_time,
          "compiled_code": (r.node.compiled_code or "")[:4000],
          "path":      r.node.original_file_path,
        } %}
        {% do out.append(row) %}
      {% endif %}
    {% endfor %}
    {% if out | length > 0 %}
      {% do log("shdpa: " ~ (out|length) ~ " failed nodes written to target/shdpa_failures.jsonl", info=True) %}
      {% set _ = modules.shdpa_write(out) if modules.get('shdpa_write') else None %}
    {% endif %}
  {% endif %}
{% endmacro %}

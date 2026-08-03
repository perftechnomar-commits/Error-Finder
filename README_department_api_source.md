# Department auto source → Marorka API

This package changes only the **Department auto source** branch of the existing Streamlit noon-report validator. The **Manual upload**, validation rules, filters, dashboard, exports, and session-state logic remain unchanged.

## Files

- `marorka_api_source.py` — fetches OData ReportData, follows pagination, pivots `ValueDescription` / `ReportedValue`, applies the All vessels Power Query calculations, and produces an in-memory Excel workbook with a `Table` sheet.
- `apply_department_api_patch.py` — patches the current `app.py` and creates a backup first.
- `streamlit_secrets_api_source.toml` — secrets template.

## Installation

1. Put `marorka_api_source.py` and `apply_department_api_patch.py` beside the current Streamlit `app.py`.
2. Run:

```bash
python apply_department_api_patch.py app.py
```

3. Copy the required values from `streamlit_secrets_api_source.toml` into `.streamlit/secrets.toml` or Streamlit Cloud Secrets.
4. Ensure these packages already exist in `requirements.txt`:

```text
pandas
requests
openpyxl
streamlit
```

5. Deploy/restart the app.

The patch creates `app.before_api_source_patch.py` before changing `app.py`.

## Runtime behavior

- API window: **today minus 5 days** through **tomorrow exclusive**, matching the Power Query.
- Excludes `Intake Report` and `Fuel Change Report`.
- Uses the first API value per report/tag, matching `List.First`.
- Keeps all pivoted API tags and adds the derived columns required by the validator.
- Caches the transformed result for 10 minutes.
- **Reload API source** increments the cache token and fetches fresh data immediately.
- On API failure, the existing **Manual upload** option remains available.

## Deliberate robustness improvement

Power Query `ReorderColumns` can fail when a newly missing/renamed optional API tag is absent. The Python version orders the validator-critical columns first and keeps every other returned tag afterward. Missing optional tags therefore do not crash the entire source load.

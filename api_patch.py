from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys

IMPORT_LINE = (
    "from marorka_api_source import build_department_uploaded_file\n"
)

OLD_BRANCH_PATTERN = re.compile(
    r'''if source_mode == "Department auto source":\n'''
    r'''(?P<body>.*?)'''
    r'''\nelse:\n''',
    flags=re.DOTALL,
)

NEW_BRANCH = '''if source_mode == "Department auto source":
    reload_col, _ = st.columns([1, 4])
    if reload_col.button("Reload API source", use_container_width=True):
        st.session_state["auto_source_refresh_token"] += 1

    try:
        with st.spinner("Loading and transforming Marorka API data..."):
            api_file, api_result = build_department_uploaded_file(
                st.session_state["auto_source_refresh_token"]
            )
        uploaded_files = [api_file]
        st.caption(
            f"API source: {api_result.start_date:%Y-%m-%d} to "
            f"{(api_result.end_date_exclusive - timedelta(days=1)):%Y-%m-%d} | "
            f"{api_result.raw_rows:,} raw tag rows -> "
            f"{api_result.report_rows:,} report rows"
        )
    except Exception as exc:  # noqa: BLE001 - user-facing source error
        st.error(f"Department API source could not be loaded: {exc}")
        st.info("Switch to Manual upload as backup, or check the MARORKA_* Streamlit Secrets.")
        st.stop()

else:
'''


def add_import(text: str) -> str:
    if "from marorka_api_source import" in text:
        return text

    # timedelta is already used by the historical API variants, but make sure the
    # replacement branch has it available.
    datetime_match = re.search(r"^from datetime import ([^\n]+)$", text, flags=re.MULTILINE)
    if datetime_match:
        imported = [part.strip() for part in datetime_match.group(1).split(",")]
        if "timedelta" not in imported:
            imported.append("timedelta")
            text = (
                text[: datetime_match.start()]
                + "from datetime import " + ", ".join(imported)
                + text[datetime_match.end() :]
            )
    else:
        text = "from datetime import timedelta\n" + text

    # Put the new local import after the existing import block.
    candidates = list(re.finditer(r"^(?:from|import) .+$", text, flags=re.MULTILINE))
    if not candidates:
        return IMPORT_LINE + text
    insertion = candidates[-1].end()
    return text[:insertion] + "\n" + IMPORT_LINE.rstrip("\n") + text[insertion:]


def patch_app(path: Path) -> Path:
    text = path.read_text(encoding="utf-8")
    text = add_import(text)

    matches = list(OLD_BRANCH_PATTERN.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one Department auto source branch, "
            f"but found {len(matches)}. No changes were written."
        )

    patched = OLD_BRANCH_PATTERN.sub(NEW_BRANCH, text, count=1)
    backup = path.with_name(path.stem + ".before_api_source_patch" + path.suffix)
    shutil.copy2(path, backup)
    path.write_text(patched, encoding="utf-8")
    return backup


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python apply_department_api_patch.py path/to/app.py")
    app_path = Path(sys.argv[1]).resolve()
    if not app_path.is_file():
        raise SystemExit(f"File not found: {app_path}")
    backup = patch_app(app_path)
    print(f"Patched: {app_path}")
    print(f"Backup:  {backup}")


if __name__ == "__main__":
    main()

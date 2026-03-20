from __future__ import annotations

from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = MODULE_DIR.parent


def resolve_storage_dir(storage_dir: str | Path | None = None) -> Path:
    if storage_dir is not None:
        path = Path(storage_dir).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Storage directory does not exist: {path}")
        return path

    candidates = [
        DATA_DIR / "storage files output",
        DATA_DIR / "tmp_ingest_check",
        DATA_DIR / "tmp_ingest_year_filter",
    ]
    for candidate in candidates:
        if (candidate / "contracts_fixed.parquet").exists():
            return candidate.resolve()

    checked = "\n".join(f"- {path}" for path in candidates)
    raise FileNotFoundError(
        "Could not find a storage parquet directory. Checked:\n"
        f"{checked}"
    )


def resolve_storage_output_dir(storage_dir: str | Path | None = None) -> Path:
    return resolve_storage_dir(storage_dir)


def resolve_profile_path(profile_path: str | Path | None = None) -> Path:
    if profile_path is not None:
        path = Path(profile_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Profile JSON does not exist: {path}")
        return path

    default_path = MODULE_DIR / "4c6a58e2-f666-4d3d-b8c0-55d32a781314.json"
    if default_path.exists():
        return default_path.resolve()

    raise FileNotFoundError(f"Could not find default profile JSON: {default_path}")

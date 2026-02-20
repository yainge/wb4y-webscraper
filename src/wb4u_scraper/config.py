from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScraperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WB4U_",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Tableau source
    tableau_url: str = (
        "https://public.tableau.com/views/"
        "MonitorConsumentenmarktEnergie/Variabeleenvastecontracten"
    )
    tableau_delay_ms: int = Field(default=700, ge=200, le=5000)

    # Retry policy
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_wait_seconds: float = Field(default=2.0, ge=0.5)
    retry_max_wait_seconds: float = Field(default=30.0, ge=5.0)

    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])
    data_dir: Optional[Path] = None
    exports_dir: Optional[Path] = None

    # Database
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")

    # Output formats
    write_parquet: bool = True
    write_jsonl: bool = True

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    # Schema drift
    drift_fail_on_new_columns: bool = False
    drift_fail_on_missing_columns: bool = True

    def model_post_init(self, __context: object) -> None:
        if self.data_dir is None:
            self.data_dir = self.project_root / "data"
        if self.exports_dir is None:
            self.exports_dir = self.project_root / "exports"


def get_settings() -> ScraperSettings:
    return ScraperSettings()

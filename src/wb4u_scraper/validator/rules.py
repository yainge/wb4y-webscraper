from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from wb4u_scraper.models.price_observation import PriceObservation

logger = structlog.get_logger()


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    record_index: int
    field: str
    message: str
    value: Any = None


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    total_records: int = 0

    @property
    def has_critical_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def log_summary(self) -> None:
        logger.info(
            "validation_summary",
            total_records=self.total_records,
            errors=self.error_count,
            warnings=self.warning_count,
        )
        for issue in self.issues[:20]:
            log_fn = logger.error if issue.severity == "error" else logger.warning
            log_fn(
                "validation_issue",
                severity=issue.severity,
                record_index=issue.record_index,
                field=issue.field,
                message=issue.message,
            )


def validate_normalized(records: list[PriceObservation]) -> ValidationReport:
    """Apply all business rules to normalized price observations."""
    report = ValidationReport(total_records=len(records))

    for i, rec in enumerate(records):
        # Rule 1: Provider name must not be empty
        if not rec.provider_name:
            report.issues.append(ValidationIssue("error", i, "provider_name", "Empty provider name"))

        # Rule 2: Value must be in reasonable range
        if rec.unit == "eur_per_kwh" and rec.meter_direction == "consumption":
            if not (-0.50 <= rec.value <= 2.00):
                report.issues.append(
                    ValidationIssue(
                        "warning",
                        i,
                        "value",
                        f"Electricity price {rec.value} outside expected range [-0.50, 2.00]",
                        rec.value,
                    )
                )
        elif rec.unit == "eur_per_m3":
            if not (0.0 <= rec.value <= 5.00):
                report.issues.append(
                    ValidationIssue(
                        "warning",
                        i,
                        "value",
                        f"Gas price {rec.value} outside expected range [0.0, 5.00]",
                        rec.value,
                    )
                )
        elif rec.unit == "eur_per_month":
            if not (0.0 <= rec.value <= 100.0):
                report.issues.append(
                    ValidationIssue(
                        "warning",
                        i,
                        "value",
                        f"Monthly cost {rec.value} outside expected range [0.0, 100.0]",
                        rec.value,
                    )
                )

        # Rule 3: valid_from should be set
        if not rec.valid_from:
            report.issues.append(ValidationIssue("warning", i, "valid_from", "Missing valid_from date"))

        # Rule 4: contract_type should not be 'unknown'
        if rec.contract_type == "unknown":
            report.issues.append(ValidationIssue("warning", i, "contract_type", "Unknown contract type"))

        # Rule 5: Feed-in prices should be non-negative
        if rec.meter_direction == "feed_in" and rec.value < 0:
            report.issues.append(
                ValidationIssue(
                    "warning",
                    i,
                    "value",
                    f"Negative feed-in value {rec.value} — expected positive (credit)",
                    rec.value,
                )
            )

    return report

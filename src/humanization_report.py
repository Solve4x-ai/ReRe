"""
Last-applied humanization values for real-time UI display.
Updated by player (delay jitter, drift, micro-pauses) and input_backend (nulls, QPC).
"""

from typing import Any

_report: dict[str, Any] = {
    "delay_jitter_ms": None,
    "variable_key_hold_ms": None,
    "drift_factor": None,
    "micro_pause_ms": None,
    "insert_nulls_count": None,
    "qpc_used": None,
}


def report_delay_jitter_ms(value: float) -> None:
    _report["delay_jitter_ms"] = value


def report_drift_factor(value: float) -> None:
    _report["drift_factor"] = value


def report_micro_pause_ms(value: float | None) -> None:
    _report["micro_pause_ms"] = value


def report_variable_key_hold_ms(value: float | None) -> None:
    _report["variable_key_hold_ms"] = value


def report_insert_nulls(count: int) -> None:
    _report["insert_nulls_count"] = count


def report_qpc_used(used: bool, time_value: int | None = None) -> None:
    _report["qpc_used"] = used
    if time_value is not None:
        _report["qpc_time_value"] = time_value


def get_report() -> dict[str, Any]:
    """Return a copy of the last-applied report for UI display."""
    return dict(_report)

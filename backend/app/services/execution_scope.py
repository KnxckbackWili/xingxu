"""Rules that separate execution work from reminder-only project preparation."""

from typing import Optional

REMINDER_ONLY_PHASE_NAMES = frozenset({"项目准备"})


def is_execution_phase(name: Optional[str]) -> bool:
    return bool(name) and name not in REMINDER_ONLY_PHASE_NAMES

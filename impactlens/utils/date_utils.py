"""
Date utilities for report generation.

Provides helpers for computing dynamic date ranges such as current month
and previous month for monthly comparison reports.
"""

from datetime import date, timedelta
from typing import List, Tuple


def get_first_day_of_month(year: int, month: int) -> date:
    """Return the first day of the given month."""
    return date(year, month, 1)


def get_last_day_of_month(year: int, month: int) -> date:
    """Return the last day of the given month."""
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def get_previous_month(year: int, month: int) -> Tuple[int, int]:
    """Return (year, month) for the month before the given month."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def get_monthly_phases(reference_date: date = None) -> List[Tuple[str, str, str]]:
    """
    Compute two phases for month-over-month comparison.

    Uses the reference_date to determine which two months to compare:
    - Previous month: full calendar month before reference_date's month
    - Current month:  1st of reference_date's month up to reference_date

    Setting reference_date to the last day of a past month (e.g. 2026-05-31)
    lets you pin the comparison to any two consecutive months:
      2026-05-31 → April 2026 vs May 2026
      2026-06-10 → May 2026  vs Jun 2026 (partial)

    Args:
        reference_date: Date to compute months relative to. Defaults to today.
            Set this via ``comparison_reference_date`` in the config YAML.

    Returns:
        List of (phase_name, start_date_str, end_date_str) tuples, e.g.:
        [
            ("Apr 2026", "2026-04-01", "2026-04-30"),
            ("May 2026", "2026-05-01", "2026-05-31"),
        ]
    """
    if reference_date is None:
        reference_date = date.today()

    cur_year = reference_date.year
    cur_month = reference_date.month
    cur_start = get_first_day_of_month(cur_year, cur_month)
    cur_end = reference_date
    cur_name = cur_start.strftime("%b %Y")

    prev_year, prev_month = get_previous_month(cur_year, cur_month)
    prev_start = get_first_day_of_month(prev_year, prev_month)
    prev_end = get_last_day_of_month(prev_year, prev_month)
    prev_name = prev_start.strftime("%b %Y")

    return [
        (prev_name, prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")),
        (cur_name, cur_start.strftime("%Y-%m-%d"), cur_end.strftime("%Y-%m-%d")),
    ]


def get_monthly_phases_n(n: int, reference_date: date = None) -> List[Tuple[str, str, str]]:
    """
    Compute N monthly phases ending at (and including) reference_date's month.

    The last phase is the current (partial) month up to reference_date.
    All earlier phases are full calendar months going backwards.

    Examples with n=3 and today = 2026-06-12:
        Apr 2026: 2026-04-01 → 2026-04-30  (full)
        May 2026: 2026-05-01 → 2026-05-31  (full)
        Jun 2026: 2026-06-01 → 2026-06-12  (partial, up to today)

    Args:
        n:              Number of months to include (must be >= 1).
        reference_date: Reference date (defaults to today).

    Returns:
        List of (phase_name, start_date_str, end_date_str) tuples,
        oldest month first.
    """
    if reference_date is None:
        reference_date = date.today()

    n = max(1, n)
    phases = []

    cur_year = reference_date.year
    cur_month = reference_date.month

    # Build phases from newest → oldest, then reverse
    year, month = cur_year, cur_month
    for i in range(n):
        start = get_first_day_of_month(year, month)
        end = reference_date if i == 0 else get_last_day_of_month(year, month)
        name = start.strftime("%b %Y")
        phases.append((name, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        year, month = get_previous_month(year, month)

    phases.reverse()
    return phases

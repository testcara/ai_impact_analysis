"""Utility functions for Jira data analysis."""

import csv
import re
from datetime import datetime


def calculate_days_between(start_date, end_date, inclusive=True):
    """
    Calculate the number of days between two dates.

    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        inclusive: If True, includes both start and end dates (adds 1 to result)

    Returns:
        Number of days or None if calculation fails
    """
    if not start_date or not end_date:
        return None

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end - start).days
        if inclusive:
            days += 1
        return days if days >= 0 else None
    except (ValueError, TypeError):
        return None


def calculate_daily_throughput(start_date, end_date, item_count):
    """
    Calculate daily throughput based on date range and item count.

    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        item_count: Number of items to calculate throughput for

    Returns:
        Daily throughput (items per day) or None if calculation fails
    """
    days = calculate_days_between(start_date, end_date, inclusive=True)
    if days and days > 0:
        return item_count / days
    return None


def calculate_throughput_variants(item_count, analysis_days, leave_days=0, capacity=1.0):
    """
    Calculate 4 throughput variants considering leave days and capacity.

    This function provides 4 different throughput calculations to account for
    team size (capacity) and availability (leave days):

    1. Baseline: Team throughput without adjustments
    2. Skip leave: Team throughput accounting for vacation
    3. Capacity: Average per-capacity throughput (comparable across team sizes)
    4. Both: Average per-capacity throughput excluding leave days

    Args:
        item_count: Number of items (PRs, issues, etc.)
        analysis_days: Number of days in the analysis period
        leave_days: Number of leave days during the period (default: 0)
        capacity: Team capacity as FTE (Full-Time Equivalent)
                 For individuals: 0.0-1.0 (1.0 = full time, 0.5 = half time)
                 For teams: sum of all members' capacity (e.g., 6.0 for 6-person team)
                 (default: 1.0)

    Returns:
        Dictionary with 4 throughput variants:
        {
            'baseline': float or None,           # Team throughput
            'skip_leave': float or None,         # Team throughput (excl. leave)
            'capacity': float or None,           # Per-capacity throughput
            'both': float or None                # Per-capacity throughput (excl. leave)
        }

    Examples:
        >>> # Single developer, no leave
        >>> calculate_throughput_variants(10, 30, 0, 1.0)
        {'baseline': 0.333, 'skip_leave': 0.333, 'capacity': 0.333, 'both': 0.333}

        >>> # Single developer, 5 days leave
        >>> calculate_throughput_variants(10, 30, 5, 1.0)
        {'baseline': 0.333, 'skip_leave': 0.4, 'capacity': 0.333, 'both': 0.4}

        >>> # Team of 6, no leave - 60 items total
        >>> calculate_throughput_variants(60, 30, 0, 6.0)
        {'baseline': 2.0,      # 60 / 30 = 2.0 items/day (team)
         'skip_leave': 2.0,    # same as baseline (no leave)
         'capacity': 0.333,    # 60 / (30 * 6) = 0.333 items/capacity/day
         'both': 0.333}        # same as capacity (no leave)

        >>> # Team of 6, 10 days total leave - 60 items
        >>> calculate_throughput_variants(60, 30, 10, 6.0)
        {'baseline': 2.0,      # 60 / 30 = 2.0 items/day (team)
         'skip_leave': 3.0,    # 60 / (30-10) = 3.0 items/day (team, excl. leave)
         'capacity': 0.333,    # 60 / (30 * 6) = 0.333 items/capacity/day
         'both': 0.5}          # 60 / ((30-10) * 6) = 0.5 items/capacity/day (excl. leave)
    """
    if not analysis_days or analysis_days <= 0:
        return {"baseline": None, "skip_leave": None, "capacity": None, "both": None}

    # Variant 1: Baseline (no adjustments)
    baseline = item_count / analysis_days

    # Variant 2: Skip leave days
    effective_days_leave = analysis_days - leave_days
    skip_leave = item_count / effective_days_leave if effective_days_leave > 0 else None

    # Variant 3: Based on capacity
    effective_days_capacity = analysis_days * capacity
    capacity_based = item_count / effective_days_capacity if effective_days_capacity > 0 else None

    # Variant 4: Both leave days and capacity
    effective_days_both = (analysis_days - leave_days) * capacity
    both = item_count / effective_days_both if effective_days_both > 0 else None

    return {
        "baseline": baseline,
        "skip_leave": skip_leave,
        "capacity": capacity_based,
        "both": both,
    }


def convert_date_to_jql(date_str):
    """
    Convert YYYY-MM-DD format date to Jira JQL relative time expression.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        JQL time expression (e.g., "-300d" for 300 days ago)
    """
    if not date_str:
        return None

    try:
        input_date = datetime.strptime(date_str, "%Y-%m-%d")
        today = datetime.now()

        days_diff = (today - input_date).days

        if days_diff == 0:
            return "startOfDay()"
        elif days_diff > 0:
            return f'"-{days_diff}d"'
        else:
            return f'"{abs(days_diff)}d"'
    except ValueError:
        return f'"{date_str}"'


def parse_datetime(datetime_str):
    """
    Parse Jira datetime string to datetime object.

    Args:
        datetime_str: Jira datetime string

    Returns:
        datetime object or None on error
    """
    if not datetime_str:
        return None

    try:
        return datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            return datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None


def calculate_state_durations(issue):
    """
    Calculate time spent in each state for an issue.

    Args:
        issue: Jira issue dict with changelog

    Returns:
        Dict mapping state names to statistics (total_seconds, count)
    """
    state_stats = {}

    changelog = issue.get("changelog", {})
    histories = changelog.get("histories", [])

    created_str = issue["fields"].get("created")
    current_status = issue["fields"].get("status", {}).get("name", "Unknown")
    resolution_str = issue["fields"].get("resolutiondate")

    if not created_str:
        return {}

    created_date = parse_datetime(created_str)
    if not created_date:
        return {}

    # Build status transition history
    status_transitions = []

    for history in histories:
        history_created = history.get("created")
        if not history_created:
            continue

        transition_date = parse_datetime(history_created)
        if not transition_date:
            continue

        for item in history.get("items", []):
            if item.get("field") == "status":
                from_status = item.get("fromString")
                to_status = item.get("toString")
                status_transitions.append(
                    {"date": transition_date, "from": from_status, "to": to_status}
                )

    # Sort by time
    status_transitions.sort(key=lambda x: x["date"])

    # Determine initial status
    if status_transitions:
        initial_status = status_transitions[0]["from"]
    else:
        initial_status = current_status

    # Calculate time spent in each state
    current_state = initial_status
    current_state_start = created_date

    # Initialize first state
    if current_state:
        if current_state not in state_stats:
            state_stats[current_state] = {"total_seconds": 0, "count": 0}
        state_stats[current_state]["count"] += 1

    # Process all transitions
    for transition in status_transitions:
        if current_state:
            duration = (transition["date"] - current_state_start).total_seconds()
            state_stats[current_state]["total_seconds"] += duration

        current_state = transition["to"]
        current_state_start = transition["date"]

        if current_state not in state_stats:
            state_stats[current_state] = {"total_seconds": 0, "count": 0}
        state_stats[current_state]["count"] += 1

    # Calculate time for last state
    if current_state:
        if resolution_str:
            end_date = parse_datetime(resolution_str)
            if not end_date:
                end_date = datetime.now(current_state_start.tzinfo)
        else:
            end_date = datetime.now(current_state_start.tzinfo)

        duration = (end_date - current_state_start).total_seconds()
        state_stats[current_state]["total_seconds"] += duration

    return state_stats


def build_jql_query(project_key, start_date=None, end_date=None, status=None, assignee=None):
    """
    Build a JQL query string from parameters.

    Args:
        project_key: Jira project key
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        status: Issue status filter
        assignee: Assignee filter

    Returns:
        JQL query string
    """
    jql_parts = [f'project = "{project_key}"']

    if assignee:
        jql_parts.append(f'assignee = "{assignee}"')

    if start_date or end_date:
        if start_date:
            start_jql = convert_date_to_jql(start_date)
            jql_parts.append(f"resolved >= {start_jql}")

        if end_date:
            end_jql = convert_date_to_jql(end_date)
            jql_parts.append(f"resolved <= {end_jql}")
    else:
        if status:
            jql_parts.append(f'status = "{status}"')

    return " AND ".join(jql_parts)


def read_tsv_report(filepath):
    """
    Read TSV/CSV report file and return as list of rows.

    Args:
        filepath: Path to TSV or CSV file

    Returns:
        List of lists (rows)
    """
    rows = []

    # Detect delimiter
    delimiter = "\t" if filepath.endswith(".tsv") else ","

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            rows.append(row)

    return rows


def normalize_username(username):
    """
    Normalize username by removing common prefixes/suffixes:
    - Remove @redhat.com, @gmail.com, etc.
    - Remove rh-ee- prefix
    - Remove -1, -2, etc. suffix

    Args:
        username: Username string to normalize

    Returns:
        Normalized username string
    """
    # Remove email domain
    username = username.split("@")[0]
    # Remove rh-ee- prefix
    if username.startswith("rh-ee-"):
        username = username[6:]  # len("rh-ee-") = 6
    # Remove -1, -2, etc. suffix
    username = re.sub(r"-\d+$", "", username)
    return username


def convert_markdown_to_plain_text(text):
    """
    Convert Markdown formatting to plain text for Google Sheets.

    Args:
        text: Text with Markdown formatting

    Returns:
        Plain text with Markdown removed
    """
    # Remove bold: **text** -> text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)

    # Remove italic: *text* or _text_ -> text
    # For asterisk italics
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    # For underscore italics - only match if surrounded by whitespace or boundaries
    # to avoid matching underscores in filenames like combined_pr_report_20251215.tsv
    text = re.sub(r"(?<!\w)_([^_\s]+?)_(?!\w)", r"\1", text)

    # Remove headers: ### text -> text
    text = re.sub(r"^#{1,6}\s+", "", text)

    # Remove inline code: `text` -> text
    text = re.sub(r"`(.+?)`", r"\1", text)

    # Remove links: [text](url) -> text
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)

    return text


def read_ai_analysis_report(filepath):
    """
    Read AI analysis report and convert to plain text for Google Sheets.

    Removes Markdown formatting and ensures content is readable in a single cell.

    Args:
        filepath: Path to AI analysis report file

    Returns:
        Single row with complete report text in one cell [[full_text]]
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Clean up content for Google Sheets readability
    lines = content.split("\n")
    cleaned_lines = []

    for line in lines:
        # Replace tabs with spaces to prevent cell splitting
        line = line.replace("\t", "    ")

        stripped = line.strip()

        # Skip separator lines (====== or ------)
        # Check if line is only made of = or - characters (any length >= 3)
        if (
            stripped
            and len(stripped) >= 3
            and (all(c == "=" for c in stripped) or all(c == "-" for c in stripped))
        ):
            cleaned_lines.append("")  # Replace with blank line
            continue

        # Remove Markdown formatting for cleaner display
        # Convert "## Title" to "Title" (remove heading markers)
        if stripped.startswith("## "):
            line = line.replace("## ", "", 1)
        elif stripped.startswith("# "):
            line = line.replace("# ", "", 1)

        # Convert "- Item" to "• Item" (bullet points)
        if stripped.startswith("- "):
            line = line.replace("- ", "• ", 1)

        # Keep numbered lists as-is (they're already plain text friendly)

        cleaned_lines.append(line)

    # Join everything into one cell - Google Sheets will handle wrapping
    full_text = "\n".join(cleaned_lines)

    # Return as single cell for maximum readability
    return [[full_text]]


def generate_sheet_name_from_report(report_path: str, config_path: str = None) -> str:
    """
    Generate Google Sheets tab name from report file path.

    This function replicates the naming logic from upload_to_sheets.py to ensure
    consistent naming across data sheets and visualization sheets.

    Args:
        report_path: Path to the report file (e.g., "reports/team/jira/combined_jira_report_20250116.tsv")
        config_path: Optional config file path for extracting sheet prefix

    Returns:
        Sheet name with all prefixes applied (e.g., "team - PROJ Jira Report - Combined")

    Examples:
        >>> generate_sheet_name_from_report("reports/team1/jira/combined_jira_report_20250116.tsv")
        'Jira Report - Combined'
        >>> generate_sheet_name_from_report("reports/team1/github/combined_pr_report_20250116.tsv")
        'PR Report - Combined'
    """
    import os
    from pathlib import Path
    from impactlens.utils.workflow_utils import extract_sheet_prefix

    filename = Path(report_path).stem

    # Determine base sheet name from filename pattern
    # Check if it's an aggregated report
    if filename.startswith("aggregated_jira_report"):
        sheet_name = "Jira Report - Aggregated"
    elif filename.startswith("aggregated_pr_report"):
        sheet_name = "PR Report - Aggregated"
    # Check if it's a monthly comparison report (stored in monthly/ subdirectory)
    elif "monthly" in str(Path(report_path).parent).lower() and filename.startswith("jira_comparison_"):
        sheet_name = "Jira Report - Monthly Comparison"
    elif "monthly" in str(Path(report_path).parent).lower() and filename.startswith("pr_comparison_"):
        sheet_name = "PR Report - Monthly Comparison"
    # Check if it's an AI analysis report (gemini_analysis_* or ai_analysis_*)
    elif filename.startswith("gemini_analysis_combined") or filename.startswith(
        "ai_analysis_combined"
    ):
        sheet_name = "AI Analysis - Combined"
    elif filename.startswith("gemini_analysis_pr") or filename.startswith("ai_analysis_pr"):
        sheet_name = "AI Analysis - PR"
    elif filename.startswith("gemini_analysis_jira") or filename.startswith("ai_analysis_jira"):
        sheet_name = "AI Analysis - Jira"
    # Check if it's a combined PR report (may have project prefix)
    elif "combined_pr_report" in filename:
        sheet_name = "PR Report - Combined"
    # Check if it's a combined Jira report (may have project prefix)
    elif "combined_jira_report" in filename:
        sheet_name = "Jira Report - Combined"
    # Check if it's a PR comparison report
    elif filename.startswith("pr_comparison_"):
        parts = filename.replace("pr_comparison_", "").split("_")
        if parts[0] == "general":
            sheet_name = "PR Report - Team"
        else:
            normalized = normalize_username(parts[0])
            sheet_name = f"PR Report - {normalized}"
    # Check if it's a Jira comparison report
    elif filename.startswith("jira_comparison_"):
        parts = filename.replace("jira_comparison_", "").split("_")
        if parts[0] == "general":
            sheet_name = "Jira Report - Team"
        else:
            normalized = normalize_username(parts[0])
            sheet_name = f"Jira Report - {normalized}"
    # Fallback for old comparison_report_* naming (for backwards compatibility)
    else:
        parts = filename.replace("comparison_report_", "").split("_")
        if parts[0] == "general":
            sheet_name = "Jira Report - Team"
        else:
            normalized = normalize_username(parts[0])
            sheet_name = f"Jira Report - {normalized}"

    # Add project/repo name to sheet name (from environment variables set by config)
    # BUT: Skip for aggregated reports since they combine multiple projects
    is_aggregated = "aggregated" in sheet_name.lower()

    if not is_aggregated:
        # Priority: Check Jira first (covers both "Jira Report" and "AI Analysis - Jira")
        if "jira" in sheet_name.lower():
            project_key = os.getenv("JIRA_PROJECT_KEY", "")
            if project_key:
                sheet_name = f"{project_key} {sheet_name}"
        # Then check PR and AI Analysis - PR
        elif "pr" in sheet_name.lower():
            # Support both GitHub and GitLab/generic naming conventions
            repo_name = os.getenv("GIT_REPO_NAME", "") or os.getenv("GITHUB_REPO_NAME", "")
            if repo_name:
                sheet_name = f"{repo_name} {sheet_name}"

    # Add top-level directory prefix for complex scenarios (if config_path is provided)
    # Extract prefix from config path (e.g., "cue" from config/cue/cue-konfluxui/)
    sheet_prefix = extract_sheet_prefix(config_path) if config_path else ""
    if sheet_prefix:
        sheet_name = f"{sheet_prefix} - {sheet_name}"

    return sheet_name

"""
Shared utilities for report generation.

This module provides common functions used across different report generators
to avoid code duplication.
"""

import glob
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Any, Tuple, Dict

from impactlens.utils.anonymization import anonymize_name
from impactlens.utils.workflow_utils import MIN_PHASES_FOR_COMPARISON

# Documentation URL constant
METRICS_GUIDE_URL = "https://github.com/janaki29/impactlens/blob/master/docs/METRICS_GUIDE.md"


def save_report_output(
    content: str,
    start_date: str,
    end_date: str,
    report_type: str,
    output_format: str,
    identifier: Optional[str] = None,
    output_dir: str = "reports",
    hide_individual_names: bool = False,
) -> str:
    """
    Save report output to file (unified function for both Jira and PR reports).

    Args:
        content: Report content (text or JSON string)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        report_type: "jira" or "pr"
        output_format: "txt" or "json"
        identifier: Optional assignee/author (for filename)
        output_dir: Output directory
        hide_individual_names: If True, anonymize the filename

    Returns:
        Output filename path

    Examples:
        >>> save_report_output(text, "2024-01-01", "2024-03-31", "jira", "txt", "wlin")
        'reports/jira/jira_report_wlin_20240101_20240331.txt'
    """
    os.makedirs(output_dir, exist_ok=True)

    # Format dates for filename
    date_range = f"{start_date}_{end_date}".replace("-", "")

    # Determine file prefix based on type and format
    if output_format == "txt":
        prefix = f"{report_type}_report_"
    else:  # json
        prefix = f"{report_type}_metrics_"

    # Build filename
    if identifier:
        # Get file identifier (normalized and optionally anonymized)
        file_id = get_identifier_for_file(identifier, hide_individual_names)
        filename = os.path.join(output_dir, f"{prefix}{file_id}_{date_range}.{output_format}")
    else:
        filename = os.path.join(output_dir, f"{prefix}general_{date_range}.{output_format}")

    # Write file
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename


def generate_comparison_report_header(
    report_type: str,
    identifier: Optional[str],
    project_info: Optional[str],
    reports: List[Dict],
    phase_names: List[str],
) -> List[str]:
    """
    Generate common header section for comparison reports (Jira/PR).

    Args:
        report_type: "JIRA" or "PR"
        identifier: Optional assignee/author name
        project_info: Optional project key or repository name
        reports: List of parsed report dictionaries
        phase_names: List of phase names

    Returns:
        List of formatted header lines

    Examples:
        >>> generate_comparison_report_header("JIRA", "wlin", "KONFLUX", reports, ["Phase 1", "Phase 2"])
        ['JIRA AI Impact Analysis Report - wlin', 'Report Generated: January 15, 2026', ...]
    """
    lines = []

    # Title
    if identifier:
        lines.append(f"{report_type} AI Impact Analysis Report - {identifier}")
    else:
        lines.append(f"{report_type} AI Impact Analysis Report - Team Overall")

    lines.append(f"Report Generated: {datetime.now().strftime('%B %d, %Y')}")

    if project_info:
        label = "Project" if report_type == "JIRA" else "Repository"
        lines.append(f"{label}: {project_info}")

    lines.append("")

    # Add description for multi-phase analysis
    if len(reports) >= 2:
        lines.append("This report compares team metrics across multiple phases.")
        lines.append("")

    # Phase info with date ranges
    for i, (name, report) in enumerate(zip(phase_names, reports), 1):
        time_range = report.get("time_range", {})
        start_date = time_range.get("start_date", "N/A")
        end_date = time_range.get("end_date", "N/A")
        lines.append(f"Phase {i}: {name} ({start_date} to {end_date})")

    lines.append("")

    return lines


def build_jira_project_prefix(project_settings: Optional[Dict]) -> Optional[str]:
    """
    Build project prefix for Jira reports from project settings.

    Args:
        project_settings: Dictionary containing project configuration

    Returns:
        Project key (e.g., "KONFLUX") or None if not available

    Examples:
        >>> build_jira_project_prefix({"jira_project_key": "KONFLUX"})
        'KONFLUX'
        >>> build_jira_project_prefix({})
        None
    """
    if not project_settings:
        return None
    return project_settings.get("jira_project_key")


def build_pr_project_prefix(project_settings: Optional[Dict]) -> Optional[str]:
    """
    Build project prefix for PR reports from project settings.

    Supports both GitHub and GitLab/generic naming conventions:
    - github_repo_owner / github_repo_name (GitHub)
    - git_repo_owner / git_repo_name (GitLab/generic)

    Args:
        project_settings: Dictionary containing project configuration

    Returns:
        Project prefix in "owner/repo" format, or just "repo" if owner not available,
        or None if neither is available

    Examples:
        >>> build_pr_project_prefix({"github_repo_owner": "konflux-ci", "github_repo_name": "konflux-ui"})
        'konflux-ci/konflux-ui'
        >>> build_pr_project_prefix({"git_repo_owner": "metadata/comet", "git_repo_name": "comet"})
        'metadata/comet/comet'
        >>> build_pr_project_prefix({"github_repo_name": "konflux-ui"})
        'konflux-ui'
        >>> build_pr_project_prefix({})
        None
    """
    if not project_settings:
        return None

    # Support both GitHub and GitLab/generic naming conventions
    repo_owner = project_settings.get("github_repo_owner") or project_settings.get("git_repo_owner")
    repo_name = project_settings.get("github_repo_name") or project_settings.get("git_repo_name")

    if repo_owner and repo_name:
        return f"{repo_owner}/{repo_name}"
    elif repo_name:
        return repo_name
    return None


def get_identifier_for_display(name_or_email: str, hide_individual_names: bool = False) -> str:
    """
    Get display identifier for a user (for terminal output, headers, etc.).

    This function handles the complete transformation pipeline:
    1. Normalize the input (remove email domain, etc.)
    2. Anonymize if requested

    Args:
        name_or_email: Username or email (e.g., "wlin@redhat.com" or "wlin")
        hide_individual_names: Whether to anonymize the name

    Returns:
        Display identifier (e.g., "wlin" or "Developer-1AC5")

    Examples:
        >>> get_identifier_for_display("wlin@redhat.com", False)
        'wlin'
        >>> get_identifier_for_display("wlin@redhat.com", True)
        'Developer-1AC5'
    """
    normalized = normalize_username(name_or_email)
    return anonymize_name(normalized) if hide_individual_names else normalized


def get_identifier_for_file(name_or_email: str, hide_individual_names: bool = False) -> str:
    """
    Get identifier for file naming (same logic as display, for consistency).

    This is an alias for get_identifier_for_display to make the intent clear
    when used for file naming.

    Args:
        name_or_email: Username or email
        hide_individual_names: Whether to anonymize the name

    Returns:
        File identifier (e.g., "wlin" or "Developer-1AC5")
    """
    return get_identifier_for_display(name_or_email, hide_individual_names)


def normalize_username(username):
    """
    Normalize username by removing common prefixes/suffixes.

    This ensures consistent identifiers across filenames, sheet names, and reports.

    Transformations:
    - Remove @redhat.com, @gmail.com, etc. (email domain)
    - Remove rh-ee- prefix (Red Hat employee prefix)
    - Remove -1, -2, etc. suffix (numeric suffixes)

    Examples:
        wlin@redhat.com    -> wlin
        sbudhwar-1         -> sbudhwar
        rh-ee-djanaki      -> djanaki
        rh-ee-mtakac       -> mtakac
        rakshett           -> rakshett

    Args:
        username: Username string to normalize

    Returns:
        Normalized username string
    """
    if not username:
        return username
    # Remove email domain
    username = username.split("@")[0]
    # Remove rh-ee- prefix
    if username.startswith("rh-ee-"):
        username = username[6:]  # len("rh-ee-") = 6
    # Remove -1, -2, etc. suffix
    username = re.sub(r"-\d+$", "", username)
    return username


def calculate_percentage_change(before, after):
    """
    Calculate percentage change between two values.

    Formula: (after - before) / before * 100
    - Positive % = increase
    - Negative % = decrease

    Args:
        before: Value from earlier period
        after: Value from later period

    Returns:
        Percentage change as float
    """
    if before == 0:
        return None  # Can't calculate percentage change from 0
    return ((after - before) / before) * 100


def format_metric_changes(metric_changes, top_n=5):
    """
    Format metric changes into increases and decreases sections.

    Args:
        metric_changes: List of metric change dictionaries with keys:
            - name: Metric name
            - before: Value before
            - after: Value after
            - change: Percentage change
            - unit: Unit string (e.g., "d", "h", "%")
            - is_absolute: (optional) If True, shows absolute change instead of %
        top_n: Number of top changes to show (default: 5)

    Returns:
        List of formatted output lines
    """
    output = []

    # Separate into increases and decreases based on percentage change
    increases = []
    decreases = []

    for metric in metric_changes:
        if metric["change"] > 0:
            increases.append(metric)
        elif metric["change"] < 0:
            decreases.append(metric)

    # Sort by absolute change magnitude (biggest changes first)
    increases.sort(key=lambda x: abs(x["change"]), reverse=True)
    decreases.sort(key=lambda x: abs(x["change"]), reverse=True)

    # Show top N increases
    output.append("")
    output.append(f"Top {top_n} Increases in Metrics:")
    if len(increases) > 0:
        for metric in increases[:top_n]:
            if metric.get("is_absolute"):
                # Special case for absolute changes (e.g., AI Adoption from 0%)
                output.append(
                    f"• {metric['name']}: {metric['before']:.2f}{metric['unit']} → "
                    f"{metric['after']:.2f}{metric['unit']} "
                    f"(+{metric['change']:.2f}{metric['unit']} absolute change)"
                )
            else:
                output.append(
                    f"• {metric['name']}: {metric['before']:.2f}{metric['unit']} → "
                    f"{metric['after']:.2f}{metric['unit']} ({metric['change']:+.1f}% change)"
                )
            # Add variants if available (for grouped metrics like Daily Throughput)
            if "variants" in metric and metric["variants"]:
                for variant in metric["variants"]:
                    output.append(variant)
    else:
        output.append("• No increases detected")

    # Show top N decreases
    output.append("")
    output.append(f"Top {top_n} Decreases in Metrics:")
    if len(decreases) > 0:
        for metric in decreases[:top_n]:
            output.append(
                f"• {metric['name']}: {metric['before']:.2f}{metric['unit']} → "
                f"{metric['after']:.2f}{metric['unit']} ({metric['change']:+.1f}% change)"
            )
            # Add variants if available (for grouped metrics like Daily Throughput)
            if "variants" in metric and metric["variants"]:
                for variant in metric["variants"]:
                    output.append(variant)
    else:
        output.append("• No decreases detected")

    return output


def find_comparison_reports(
    report_type,
    identifier=None,
    reports_dir="reports",
    hide_individual_names=False,
):
    """
    Find all matching report files for comparison.

    This is a shared utility for both Jira and PR comparison scripts.

    Args:
        report_type: "jira" or "pr"
        identifier: Optional identifier (assignee for Jira, author for PR)
        reports_dir: Directory to search for reports
        hide_individual_names: Whether names are anonymized

    Returns:
        List of sorted report file paths
    """
    if not os.path.exists(reports_dir):
        return []

    # Determine file prefix based on report type
    if report_type == "jira":
        file_prefix = "jira_metrics_"
    elif report_type == "pr":
        file_prefix = "pr_metrics_"
    else:
        raise ValueError(f"Invalid report_type: {report_type}. Must be 'jira' or 'pr'")

    files = []
    for filename in os.listdir(reports_dir):
        if not filename.startswith(file_prefix):
            continue
        if not filename.endswith(".json"):
            continue

        if identifier:
            # Get file identifier (normalized and optionally anonymized)
            file_id = get_identifier_for_file(identifier, hide_individual_names)
            if f"{file_prefix}{file_id}_" in filename:
                files.append(os.path.join(reports_dir, filename))
        else:
            if f"{file_prefix}general_" in filename:
                files.append(os.path.join(reports_dir, filename))

    return sorted(files)


def validate_report_files(
    report_files, identifier, reports_dir, report_type, hide_individual_names
):
    """
    Validate that we have enough report files for comparison.

    Args:
        report_files: List of report file paths
        identifier: Optional identifier (assignee/author)
        reports_dir: Directory containing reports
        report_type: "jira" or "pr"
        hide_individual_names: Whether names are anonymized

    Returns:
        0 if valid, error code (1) if invalid

    Prints error messages to stdout.
    """
    file_prefix = "jira_metrics_" if report_type == "jira" else "pr_metrics_"
    identifier_label = "assignee" if report_type == "jira" else "author"

    if len(report_files) == 0:
        if identifier:
            print(f"Error: No reports found for {identifier_label} '{identifier}'")
        else:
            print("Error: No general reports found")
        print("\nLooking for files matching pattern:")
        if identifier:
            file_id = get_identifier_for_file(identifier, hide_individual_names)
            print(f"  {reports_dir}/{file_prefix}{file_id}_*.json")
        else:
            print(f"  {reports_dir}/{file_prefix}general_*.json")
        return 1

    # Changed from 2 to 1: Comparison reports are needed even for single phase
    # because they provide the TSV format that combines team + individual members horizontally
    if len(report_files) < MIN_PHASES_FOR_COMPARISON:
        print(f"Warning: No report files found")
        return 1

    return 0


def limit_and_display_reports(report_files, max_reports=4):
    """
    Limit number of reports and display them.

    Args:
        report_files: List of report file paths (must be sorted)
        max_reports: Maximum number of reports to use (default: 4)

    Returns:
        Limited list of report files
    """
    # Use all reports if <= max_reports, otherwise use the most recent ones
    if len(report_files) > max_reports:
        print(
            f"Found {len(report_files)} reports, using the {max_reports} most recent for comparison:"
        )
        report_files = sorted(report_files)[-max_reports:]
    else:
        report_files = sorted(report_files)

    print(f"Analyzing {len(report_files)} reports:")
    for i, f in enumerate(report_files, 1):
        print(f"  Phase {i}: {f}")
    print()

    return report_files


def reconcile_phase_names(phase_names, report_files):
    """
    Reconcile phase names from config with actual report files.

    Args:
        phase_names: List of phase names from config (can be empty)
        report_files: List of report file paths

    Returns:
        Tuple of (phase_names, report_files) - both potentially modified
    """
    # Use phase names from config, limit report files to match config phases
    if phase_names and len(report_files) > len(phase_names):
        print(
            f"Warning: Found {len(report_files)} reports but config only has {len(phase_names)} phases"
        )
        print(f"Using only the {len(phase_names)} most recent reports to match config")
        report_files = sorted(report_files)[-len(phase_names) :]
    elif not phase_names:
        # No config available, use generic names for all found reports
        phase_names = [f"Phase {i+1}" for i in range(len(report_files))]

    return phase_names, report_files


def add_throughput_metric_change(metric_changes, first_report, last_report):
    """
    Add Daily Throughput metric change with all variants to metric_changes list.

    This is a shared utility for both Jira and PR reports to avoid code duplication.
    Groups all throughput variants under a single "Daily Throughput" entry.

    Args:
        metric_changes: List to append metric change to
        first_report: First period report data (dict) - must contain daily_throughput fields
        last_report: Last period report data (dict) - must contain daily_throughput fields

    Note:
        Both Jira and PR reports now store pre-calculated throughput values in the same structure:
        - daily_throughput
        - daily_throughput_skip_leave
        - daily_throughput_capacity
        - daily_throughput_both
    """
    first_throughput = first_report.get("daily_throughput", 0)
    last_throughput = last_report.get("daily_throughput", 0)

    # Store all variants for detailed breakdown display
    throughput_variants = []

    # Basic throughput
    pct_change_basic = calculate_percentage_change(first_throughput, last_throughput)
    change_str_basic = f" ({pct_change_basic:+.1f}% change)" if pct_change_basic is not None else ""
    throughput_variants.append(
        f"  - Daily Throughput: {first_throughput:.2f}/d → {last_throughput:.2f}/d{change_str_basic}"
    )

    # Skip leave days variant
    first_skip_leave = first_report.get("daily_throughput_skip_leave")
    last_skip_leave = last_report.get("daily_throughput_skip_leave")
    if first_skip_leave is not None and last_skip_leave is not None:
        pct_change_skip_leave = calculate_percentage_change(first_skip_leave, last_skip_leave)
        change_str = (
            f" ({pct_change_skip_leave:+.1f}% change)" if pct_change_skip_leave is not None else ""
        )
        throughput_variants.append(
            f"  - Skip leave days: {first_skip_leave:.2f}/d → {last_skip_leave:.2f}/d{change_str}"
        )

    # Capacity variant
    first_capacity = first_report.get("daily_throughput_capacity")
    last_capacity = last_report.get("daily_throughput_capacity")
    if first_capacity is not None and last_capacity is not None:
        pct_change_capacity = calculate_percentage_change(first_capacity, last_capacity)
        change_str = (
            f" ({pct_change_capacity:+.1f}% change)" if pct_change_capacity is not None else ""
        )
        throughput_variants.append(
            f"  - Average per capacity: {first_capacity:.2f}/d → {last_capacity:.2f}/d{change_str}"
        )

    # Both (capacity + excl. leave) variant
    first_both = first_report.get("daily_throughput_both")
    last_both = last_report.get("daily_throughput_both")
    if first_both is not None and last_both is not None:
        pct_change_both = calculate_percentage_change(first_both, last_both)
        change_str = f" ({pct_change_both:+.1f}% change)" if pct_change_both is not None else ""
        throughput_variants.append(
            f"  - Per capacity, excl. leave: {first_both:.2f}/d → {last_both:.2f}/d{change_str}"
        )

    # Add Daily Throughput metric change with variants
    pct_change = calculate_percentage_change(first_throughput, last_throughput)
    if pct_change is not None:
        metric_changes.append(
            {
                "name": "Daily Throughput",
                "before": first_throughput,
                "after": last_throughput,
                "change": pct_change,
                "unit": "/d",
                "is_absolute": False,
                "variants": throughput_variants,
            }
        )


def add_metric_change(metric_changes, name, before, after, unit, is_absolute=False):
    """
    Helper to add a metric change to the list if valid.

    Args:
        metric_changes: List to append to
        name: Metric name
        before: Value from earlier period
        after: Value from later period
        unit: Unit string (e.g., "d", "h", "%")
        is_absolute: If True, shows absolute change instead of % (for 0 baseline)
    """
    # Skip if both values are the same (no change)
    if before == after:
        return

    # Auto-detect if we should use absolute change (when before is 0 and after is non-zero)
    if not is_absolute and before == 0 and after != 0:
        is_absolute = True

    if is_absolute:
        # For absolute changes (e.g., going from 0% to X%)
        metric_changes.append(
            {
                "name": name,
                "before": before,
                "after": after,
                "change": after - before,  # Absolute change
                "unit": unit,
                "is_absolute": True,
            }
        )
    else:
        # Regular percentage change
        pct_change = calculate_percentage_change(before, after)
        if pct_change is not None:
            metric_changes.append(
                {
                    "name": name,
                    "before": before,
                    "after": after,
                    "change": pct_change,
                    "unit": unit,
                    "is_absolute": False,
                }
            )


def generate_comparison_report(
    report_files: List[str],
    report_generator: Any,
    phase_names: List[str],
    identifier: Optional[str] = None,
    output_dir: str = "reports",
    output_file: Optional[str] = None,
    report_type: str = "jira",
    phase_configs: Optional[List[Tuple[str, str, str]]] = None,
    project_prefix: Optional[str] = None,
    hide_individual_names: bool = False,
) -> str:
    """
    Generate comparison report from multiple phase reports.

    This is a shared utility function used by both Jira and PR comparison scripts.

    Args:
        report_files: List of report file paths to compare
        report_generator: Report generator instance with parse and generate_comparison_tsv methods
        phase_names: List of phase names
        identifier: Optional identifier (assignee for Jira, author for PR)
        output_dir: Output directory for the comparison report
        output_file: Optional custom output filename
        report_type: "jira" or "pr" for file naming
        phase_configs: Optional list of (name, start_date, end_date) tuples from config (for displaying phase dates)
        project_prefix: Optional prefix for filename (e.g., project_key for Jira, repo_name for PR)

    Returns:
        Path to generated comparison report file
    """
    # Parse all reports
    print("Parsing reports...")
    parsed_reports = []

    for report_file in report_files:
        print(f"  Parsing {os.path.basename(report_file)}...")
        if report_type == "jira":
            parsed = report_generator.parse_jira_report(report_file)
        else:  # pr
            parsed = report_generator.parse_pr_report(report_file)
        parsed_reports.append(parsed)

    # Generate comparison TSV
    print("\nGenerating comparison report...")

    # Build kwargs for generate_comparison_tsv
    tsv_kwargs = {
        "reports": parsed_reports,
        "phase_names": phase_names,
    }

    # Add identifier (different parameter names for different report types)
    if report_type == "jira":
        tsv_kwargs["assignee"] = identifier
        # Add project_key if available
        if project_prefix:
            tsv_kwargs["project_key"] = project_prefix
    else:  # pr
        tsv_kwargs["author"] = identifier
        # For PR reports, project_prefix should be in "owner/repo" format
        # Parse it to get repo_owner and repo_name
        if project_prefix:
            if "/" in project_prefix:
                parts = project_prefix.split("/", 1)
                tsv_kwargs["repo_owner"] = parts[0]
                tsv_kwargs["repo_name"] = parts[1]
            else:
                # If no "/" separator, assume it's just the repo name
                tsv_kwargs["repo_name"] = project_prefix

    # Add phase_configs if available (for displaying phase dates)
    if phase_configs:
        tsv_kwargs["phase_configs"] = phase_configs

    comparison_tsv = report_generator.generate_comparison_tsv(**tsv_kwargs)

    # Determine output filename
    os.makedirs(output_dir, exist_ok=True)

    if output_file:
        output_path = output_file
    else:
        # Extract timestamp from the last (most recent) report file
        last_report_file = os.path.basename(report_files[-1])

        # Different timestamp patterns for different report types
        if report_type == "jira":
            # Pattern: jira_report_xxx_YYYYMMDD_HHMMSS.txt
            timestamp_match = re.search(r"_(\d{8}_\d{6})\.txt$", last_report_file)
        else:  # pr
            # Pattern: pr_metrics_xxx_YYYYMMDD_YYYYMMDD.json
            timestamp_match = re.search(r"_(\d{8}_\d{8})\.json$", last_report_file)

        if timestamp_match:
            timestamp = timestamp_match.group(1)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build filename (without project prefix to keep filenames simple)
        if identifier:
            filename = f"{report_type}_comparison_{identifier}_{timestamp}.tsv"
        else:
            filename = f"{report_type}_comparison_general_{timestamp}.tsv"

        output_path = os.path.join(output_dir, filename)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(comparison_tsv)

    if not hide_individual_names:
        print(f"\n✓ Report generated: {output_path}")
        print("\nYou can now:")
        print(f"  1. Open {output_path} in any text editor")
        print("  2. Copy all content (Ctrl+A, Ctrl+C)")
        print("  3. Paste directly into Google Sheets (no need to split columns)")
        print("  4. The data will automatically be placed in separate columns")
    else:
        print(f"\n✓ Comparison report generated (filename hidden for privacy)")

    return output_path


def combine_comparison_reports(
    reports_dir: str,
    report_type: str = "jira",
    title: Optional[str] = None,
    project_prefix: Optional[str] = None,
    hide_individual_names: bool = False,
    visualization_link: Optional[str] = None,
) -> str:
    """
    Combine all individual member comparison reports into a single report grouped by metric.

    This creates a combined view where each metric shows all team members' values
    side-by-side for comparison.

    Args:
        reports_dir: Directory containing comparison reports
        report_type: "jira" or "pr"
        title: Optional title for the combined report
        project_prefix: Optional prefix for filename (e.g., project_key for Jira, repo_name for PR)
        hide_individual_names: Whether to anonymize individual names and hide sensitive fields
        visualization_link: Github png link

    Returns:
        Path to generated combined report file
    """
    reports_dir = Path(reports_dir)

    # Find all individual comparison reports (exclude "general")
    if report_type == "jira":
        pattern = str(reports_dir / "jira_comparison_*_*.tsv")
    else:
        pattern = str(reports_dir / "pr_comparison_*_*.tsv")

    all_files = glob.glob(pattern)

    # Include all reports (both general and individual members)
    report_files = all_files

    if not report_files:
        # Return None instead of raising error - caller will handle gracefully
        # This happens when there's only 1 phase (no comparison reports generated)
        return None

    print(f"Found {len(report_files)} reports to combine")

    # Parse all reports and extract member names and metrics
    members_data = {}  # {member_name: {metric_name: [phase1_val, phase2_val, ...]}}
    phase_names = None

    for report_file in sorted(report_files):
        # Extract member identifier from filename
        # Pattern: jira_comparison_IDENTIFIER_TIMESTAMP.tsv or pr_comparison_IDENTIFIER_TIMESTAMP.tsv
        # IDENTIFIER can be: "general", "Developer-XXXX" (anonymized), or "username" (non-anonymized)
        basename = os.path.basename(report_file)
        parts = basename.split("_")
        if len(parts) >= 3:
            member_identifier = parts[2]  # e.g., "general", "Developer-1AC5", "wlin"
        else:
            continue

        # Use the identifier from filename directly (already in correct format)
        display_member_name = member_identifier

        print(f"  Processing {display_member_name}...")

        # Parse the report
        with open(report_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Find the metrics table
        metric_data = {}
        in_table = False

        for line in lines:
            line = line.rstrip("\n")

            # Skip until we find the header line with "Metric\t"
            if line.startswith("Metric\t"):
                in_table = True
                # Extract phase names from header
                if phase_names is None:
                    phase_names = line.split("\t")[1:]  # Skip "Metric" column
                continue

            if not in_table:
                continue

            # Stop at empty line or special sections
            if (
                not line.strip()
                or line.startswith("Note:")
                or line.startswith("Key Changes:")
                or line.startswith("Top ")
            ):
                break

            # Parse metric line
            parts = line.split("\t")
            if len(parts) >= 2:
                metric_name = parts[0]

                # Skip sensitive fields when anonymizing
                if hide_individual_names and metric_name in [
                    "Leave Days",
                    "Capacity",
                    "Team Member Email",
                ]:
                    continue

                values = parts[1:]
                metric_data[metric_name] = values

        members_data[display_member_name] = metric_data

    if not members_data or not phase_names:
        raise ValueError("Failed to parse comparison reports")

    # Get all unique metrics (use first member's metrics as template)
    first_member = next(iter(members_data.values()))
    all_metrics = list(first_member.keys())

    # Build combined report
    lines = []

    # Header
    if title:
        lines.append(title)
    else:
        lines.append(
            f"{report_type.upper()} AI Impact Analysis - Combined Report (Grouped by Metric)"
        )

    lines.append(f"Generated: {datetime.now().strftime('%B %d, %Y')}")
    if project_prefix:
        lines.append(f"Project: {project_prefix}")
    lines.append("")
    lines.append(
        "This report provides grouped tabular metrics data for team and individual comparison across multiple phases."
    )
    if visualization_link:
        lines.append(
            "For visual analysis of individual performance distributions, see the visualization report link below."
        )
    lines.append("")

    # Add visualization link if available
    if visualization_link:
        lines.append(f"Visualization Report: {visualization_link}")
        lines.append("")

    # Add phase info (extract from phase names)
    for i, phase_name in enumerate(phase_names, 1):
        lines.append(f"Phase {i}: {phase_name}")
    lines.append("")
    lines.append("")

    # Sort members for consistent output
    sorted_members = sorted(members_data.keys())

    # Put "general" at the beginning and rename to "team"
    if "general" in sorted_members:
        sorted_members.remove("general")
        sorted_members.insert(0, "general")

    # For each metric, create a section
    for metric in all_metrics:
        lines.append(f"=== {metric} ===")

        # Header: Phase + all members (display "team" instead of "general")
        display_members = ["team" if m == "general" else m for m in sorted_members]
        header = "Phase\t" + "\t".join(display_members)
        lines.append(header)

        # For each phase, gather all members' values
        for phase_idx, phase_name in enumerate(phase_names):
            row_values = [phase_name]

            for member in sorted_members:
                member_data = members_data.get(member, {})
                metric_values = member_data.get(metric, [])

                # Get value for this phase
                if phase_idx < len(metric_values):
                    row_values.append(metric_values[phase_idx])
                else:
                    row_values.append("N/A")

            lines.append("\t".join(row_values))

        lines.append("")  # Empty line between sections

    # Determine output filename (without project prefix to keep filenames simple)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"combined_{report_type}_report_{timestamp}.tsv"

    output_file = reports_dir / filename

    # Write output
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_file

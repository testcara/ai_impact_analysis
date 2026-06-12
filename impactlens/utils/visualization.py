"""
Visualization utilities for generating charts from combined reports.

This module provides functions to generate box plots and line charts
to visualize team metrics trends across different phases.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import matplotlib

    matplotlib.use("Agg")  # Non-interactive backend for CI/server environments
    import matplotlib.pyplot as plt
    import numpy as np

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not installed. Charts will not be generated.")
    print("Install with: pip install matplotlib")


def parse_combined_report_section(lines: List[str], section_name: str) -> Optional[Dict]:
    """
    Parse a section from combined report TSV format.

    Args:
        lines: List of lines from the TSV file
        section_name: Name of the section (e.g., "Daily Throughput")

    Returns:
        Dictionary with structure:
        {
            'phases': ['Phase 1', 'Phase 2', ...],
            'team': [val1, val2, ...],
            'members': {
                'Developer-1': [val1, val2, ...],
                'Developer-2': [val1, val2, ...],
            }
        }
        Returns None if section not found or parsing fails.
    """
    # Find section header
    section_header = f"=== {section_name} ==="
    try:
        # Try with newline first (most common)
        start_idx = lines.index(section_header + "\n")
    except ValueError:
        try:
            # Try without newline (in case it's the last line)
            start_idx = lines.index(section_header)
        except ValueError:
            return None

    # Parse column headers (Phase\tteam\tDeveloper-1\t...)
    header_line = lines[start_idx + 1]
    columns = header_line.strip().split("\t")

    if len(columns) < 2 or columns[0] != "Phase" or columns[1] != "team":
        return None

    member_names = columns[2:]  # All columns after 'team'

    # Parse data rows
    data = {"phases": [], "team": [], "members": {name: [] for name in member_names}}

    # Read until next section or end
    idx = start_idx + 2
    while idx < len(lines):
        line = lines[idx].strip()

        # Stop at next section or empty line
        if line.startswith("===") or line == "":
            break

        values = line.split("\t")
        if len(values) < 2:
            break

        phase_name = values[0]
        team_value = values[1]
        member_values = values[2:]

        data["phases"].append(phase_name)
        data["team"].append(_parse_value(team_value))

        for i, member_name in enumerate(member_names):
            if i < len(member_values):
                data["members"][member_name].append(_parse_value(member_values[i]))
            else:
                data["members"][member_name].append(None)

        idx += 1

    return data


def _parse_value(value_str: str) -> Optional[float]:
    """
    Parse a value from TSV (handles formats like '0.58/d', '12.5d', '50%', 'N/A').

    Returns:
        Float value or None if N/A or invalid
    """
    value_str = value_str.strip()

    if value_str == "N/A" or value_str == "":
        return None

    # Remove units: /d, d, %, h, x
    for unit in ["/d", "d", "%", "h", "x"]:
        value_str = value_str.replace(unit, "")

    try:
        return float(value_str)
    except ValueError:
        return None


def generate_boxplot(
    data: Dict, metric_name: str, output_path: str, unit: str = "", title_prefix: str = ""
) -> bool:
    """
    Generate box plot showing team member distribution across phases.

    Args:
        data: Parsed section data from parse_combined_report_section()
        metric_name: Name of the metric (e.g., "Daily Throughput")
        output_path: Path to save the chart (e.g., "reports/charts/throughput.png")
        unit: Unit string to display on Y-axis (e.g., "/d", "days", "%")
        title_prefix: Optional prefix for chart title (e.g., "Konflux UI - ")

    Returns:
        True if chart generated successfully, False otherwise
    """
    if not MATPLOTLIB_AVAILABLE:
        return False

    if not data or not data["phases"]:
        print(f"No data available for {metric_name}")
        return False

    # Prepare data for box plot
    phases = data["phases"]

    # Collect member values for each phase (excluding None values)
    member_distributions = []
    for phase_idx in range(len(phases)):
        phase_data = []
        for member_name, values in data["members"].items():
            if phase_idx < len(values) and values[phase_idx] is not None:
                phase_data.append(values[phase_idx])
        member_distributions.append(phase_data)

    # Create figure with single plot (smaller size for compact display)
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.5))

    # === Box Plot ===
    bp = ax.boxplot(member_distributions, labels=phases, patch_artist=True)

    # Customize box plot colors
    for patch in bp["boxes"]:
        patch.set_facecolor("#93c5fd")  # Light blue
        patch.set_alpha(0.7)

    for whisker in bp["whiskers"]:
        whisker.set(color="#1e40af", linewidth=1.5)

    for cap in bp["caps"]:
        cap.set(color="#1e40af", linewidth=1.5)

    for median in bp["medians"]:
        median.set(color="#dc2626", linewidth=2)  # Red median line

    # Use metric name only (title_prefix already shown in HTML header)
    ax.set_title(f"{metric_name}", fontsize=14, fontweight="bold")
    ax.set_ylabel(f"{metric_name} ({unit})" if unit else metric_name, fontsize=12)
    ax.set_xlabel("Phase", fontsize=12)
    ax.grid(True, alpha=0.3, axis="y")
    ax.tick_params(axis="x", rotation=15)

    plt.tight_layout()

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Save figure with high DPI for better quality in Google Sheets
    plt.savefig(output_path, dpi=95, bbox_inches="tight")
    plt.close()

    print(f"Chart saved: {output_path}")
    return True


def generate_html_visualization_report(
    report_path: str, chart_files: List[str], output_path: Optional[str] = None
) -> str:
    """
    Generate HTML visualization report combining all charts.

    Args:
        report_path: Path to combined report TSV file
        chart_files: List of generated chart PNG file paths
        output_path: Path to save HTML file. If None, uses same location as report_path

    Returns:
        Path to generated HTML file
    """
    import base64
    from datetime import datetime

    # Read report metadata
    with open(report_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Extract title and metadata
    report_title = "Combined Report Visualization"
    project_name = ""
    generation_date = datetime.now().strftime("%B %d, %Y")

    # Detect report type
    report_type = "Jira" if "jira" in report_path.lower() else "PR"

    for line in lines[:10]:
        if "Report" in line and "Generated:" in line:
            generation_date = line.split("Generated:", 1)[1].strip()
        elif "Repository:" in line or "Project:" in line:
            project_name = line.split(":", 1)[1].strip()
            report_title = f"{project_name} - {report_type} Visualization Report"

    # If no project name found, use generic title with type
    if not project_name:
        report_title = f"{report_type} Visualization Report"

    # Count actual metrics from report (count === sections)
    total_metrics = sum(
        1 for line in lines if line.strip().startswith("===") and line.strip().endswith("===")
    )

    # Prepare exclusion notes based on report type
    if report_type == "Jira":
        excluded_note = "Total Issues Completed, etc. (cumulative/count metrics less suitable for distribution analysis)"
    else:  # PR
        excluded_note = "Total PRs Merged, Non-AI PRs, Claude/Cursor PRs, Total Lines/Files, etc. (cumulative/count metrics less suitable for distribution analysis)"

    # Determine output path
    if output_path is None:
        report_dir = Path(report_path).parent
        report_name = Path(report_path).stem
        output_path = str(report_dir / f"{report_name}_visualization.html")

    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: white;
            padding: 40px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
        }}
        h1 {{
            color: #1a1a1a;
            border-bottom: 3px solid #2563eb;
            padding-bottom: 10px;
            margin-bottom: 10px;
        }}
        h2 {{
            color: #2563eb;
            border-left: 4px solid #2563eb;
            padding-left: 15px;
            margin-top: 30px;
            margin-bottom: 20px;
        }}
        .metadata {{
            color: #666;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .metadata p {{
            margin: 5px 0;
        }}
        .info-row {{
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
        }}
        .info-box {{
            flex: 1;
            padding: 20px;
            border-radius: 4px;
        }}
        .guide-section {{
            background-color: #eff6ff;
            border-left: 4px solid #2563eb;
        }}
        .guide-section h3 {{
            color: #1e40af;
            margin-top: 0;
            margin-bottom: 15px;
            font-size: 16px;
        }}
        .guide-section p {{
            margin: 8px 0;
            color: #374151;
            font-size: 14px;
        }}
        .guide-section ul {{
            margin: 8px 0;
            padding-left: 20px;
            color: #374151;
            font-size: 14px;
        }}
        .guide-section li {{
            margin: 5px 0;
        }}
        .guide-section strong {{
            color: #1e40af;
        }}
        .warning-box {{
            background-color: #fef3c7;
            border-left: 4px solid #f59e0b;
        }}
        .warning-box h3 {{
            color: #92400e;
            margin-top: 0;
            margin-bottom: 10px;
            font-size: 16px;
        }}
        .warning-box p {{
            margin: 5px 0;
            color: #78350f;
            font-size: 14px;
        }}
        .warning-box ul {{
            margin: 8px 0;
            padding-left: 20px;
            font-size: 13px;
        }}
        .warning-box li {{
            margin: 4px 0;
        }}
        @media (max-width: 768px) {{
            .info-row {{
                flex-direction: column;
            }}
        }}
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }}
        .chart-section {{
            page-break-inside: avoid;
        }}
        .chart-container {{
            background-color: #fafafa;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }}
        @media (max-width: 900px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            text-align: center;
            color: #666;
            font-size: 14px;
        }}
        @media print {{
            body {{
                background-color: white;
            }}
            .container {{
                box-shadow: none;
                padding: 20px;
            }}
            .guide-section, .warning-box {{
                page-break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{report_title}</h1>
        <div class="metadata">
            <p><strong>Generated:</strong> {generation_date}</p>
            <p><strong>Source Report:</strong> {Path(report_path).name}</p>
            <p><strong>Data Source:</strong> Individual team members only (team aggregated column excluded)</p>
            <p><strong>Visualized Metrics:</strong> {len(chart_files)} out of {total_metrics} total metrics</p>
            <p style="font-size: 13px; color: #888; margin-top: 8px;">
                <strong>Not visualized:</strong> {excluded_note}
            </p>
        </div>

        <div class="info-row">
            <div class="info-box guide-section">
                <h3>📊 How to Read Box Plots</h3>
                <p><strong>Box:</strong> 50% of data (Q1-Q3) | <strong>Red Line:</strong> Median | <strong>Whiskers:</strong> Min-max range | <strong>Dots:</strong> Outliers</p>
                <p style="margin-top: 15px;"><strong>What to Look For:</strong></p>
                <ul style="margin-top: 8px;">
                    <li>📈 Higher median = Better (throughput)</li>
                    <li>📉 Lower median = Better (time)</li>
                    <li>📏 Narrow box = Consistent team</li>
                    <li>📐 Wide box = High variation</li>
                </ul>
            </div>

            <div class="info-box warning-box">
                <h3>⚠️ Important Notes</h3>
                <p><strong>Data Quality:</strong></p>
                <ul>
                    <li>Excludes N/A values from charts</li>
                    <li>Box plots need 3+ members to be meaningful</li>
                    <li>CI reports use anonymized IDs (e.g., Developer-A3F2)</li>
                </ul>
                <p><strong>Tips:</strong></p>
                <ul>
                    <li>Compare multiple metrics for complete insights</li>
                    <li>Consider team changes and external factors</li>
                </ul>
            </div>
        </div>

        <h2>📈 Metrics Visualization</h2>
        <div class="charts-grid">
"""

    # Add each chart as a section in grid
    for chart_path in chart_files:
        chart_name = Path(chart_path).stem.replace("_", " ").title()

        # Read image and encode as base64 (embed in HTML)
        with open(chart_path, "rb") as img_file:
            img_data = base64.b64encode(img_file.read()).decode("utf-8")

        html_content += f"""
            <div class="chart-section">
                <div class="chart-container">
                    <img src="data:image/png;base64,{img_data}" alt="{chart_name}">
                </div>
            </div>
"""

    # Close grid
    html_content += """
        </div>
"""

    # Add footer
    html_content += f"""
        <div class="footer">
            <p>Generated by ImpactLens | <a href="https://github.com/testcara/impactlens">GitHub</a></p>
            <p>For detailed metric explanations, see <a href="https://github.com/testcara/impactlens/blob/master/docs/METRICS_GUIDE.md">Metrics Guide</a></p>
        </div>
    </div>
</body>
</html>
"""

    # Write HTML file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nHTML visualization report saved: {output_path}")
    return output_path


def generate_charts_from_combined_report(
    report_path: str,
    output_dir: str,
    metrics_config: Optional[List[Tuple[str, str]]] = None,
    create_sheets_visualization: bool = False,
    spreadsheet_id: Optional[str] = None,
    upload_charts_to_github: bool = True,
    github_repo: str = "janaki29/impactlens-charts",
    team_name: Optional[str] = None,
    config_path: Optional[str] = None,
    replace_existing: bool = False,
) -> tuple[List[str], Optional[Dict]]:
    """
    Generate charts for all key metrics in a combined report.

    Args:
        report_path: Path to combined report TSV file
        output_dir: Directory to save generated charts
        metrics_config: List of (metric_name, unit) tuples to visualize
                       If None, auto-detects report type and uses default metrics
        create_sheets_visualization: If True, create Google Sheet with embedded charts
        spreadsheet_id: Existing spreadsheet ID for visualization sheet (creates new if None)
        upload_charts_to_github: If True, upload PNG charts to GitHub repository (default: True)
        github_repo: GitHub repository in format "owner/repo" (default: testcara/impactlens-charts)
        team_name: Team name for organizing charts in GitHub (auto-detected from report path if None)
        config_path: Config file path for extracting sheet prefix (optional)
        replace_existing: If True, delete old sheets with same name but different timestamp

    Returns:
        Tuple of:
        - List of generated chart file paths
        - Dict with visualization info (chart_github_urls, sheet_info) or None
    """
    if not MATPLOTLIB_AVAILABLE:
        print("matplotlib not available, skipping chart generation")
        return []

    # Auto-detect report type if metrics_config not provided
    if metrics_config is None:
        # Check if it's a Jira or PR report by looking at the filename or content
        is_jira_report = "jira" in report_path.lower()

        if is_jira_report:
            # Jira metrics (order matches combined report structure)
            metrics_config = [
                # Throughput metrics
                ("Daily Throughput (skip leave days)", "/d"),
                ("Daily Throughput (average per capacity)", "/d"),
                ("Daily Throughput (average per capacity, excl. leave)", "/d"),
                ("Daily Throughput", "/d"),
                # Closure time
                ("Average Closure Time", "days"),
                ("Longest Closure Time", "days"),
                # State times
                ("New State Avg Time", "days"),
                ("To Do State Avg Time", "days"),
                ("In Progress State Avg Time", "days"),
                ("Review State Avg Time", "days"),
                ("Release Pending State Avg Time", "days"),
                ("Waiting State Avg Time", "days"),
                # Re-entry rates
                ("To Do Re-entry Rate", "x"),
                ("In Progress Re-entry Rate", "x"),
                ("Review Re-entry Rate", "x"),
                ("Waiting Re-entry Rate", "x"),
                # Issue types
                ("Story Percentage", "%"),
                ("Task Percentage", "%"),
                ("Bug Percentage", "%"),
                ("Epic Percentage", "%"),
            ]
        else:
            # PR metrics (order matches combined report structure)
            metrics_config = [
                # Throughput metrics
                ("Daily Throughput (skip leave days)", "/d"),
                ("Daily Throughput (average per capacity)", "/d"),
                ("Daily Throughput (average per capacity, excl. leave)", "/d"),
                ("Daily Throughput", "/d"),
                # AI metrics
                ("AI Adoption Rate", "%"),
                ("AI-Assisted PRs", "PRs"),
                # Time metrics
                ("Avg Time to Merge per PR (days)", "days"),
                ("Avg Time to First Review per PR (hours)", "hours"),
                # Review metrics
                ("Avg Changes Requested per PR", "count"),
                ("Avg Commits per PR", "count"),
                ("Avg Reviewers per PR", "count"),
                ("Avg Comments per PR", "count"),
                # Code change metrics
                ("Avg Lines Added per PR", "lines"),
                ("Avg Lines Deleted per PR", "lines"),
                ("Avg Files Changed per PR", "files"),
            ]

    # Read report file
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Report file not found: {report_path}")
        return []

    # Extract title prefix from report (e.g., "Konflux UI - ")
    title_prefix = ""
    for line in lines[:10]:
        if "Repository:" in line or "Project:" in line:
            title_prefix = line.split(":", 1)[1].strip() + " - "
            break

    generated_charts = []

    # Generate chart for each metric
    for metric_name, unit in metrics_config:
        data = parse_combined_report_section(lines, metric_name)

        if data is None:
            print(f"Metric not found in report: {metric_name}")
            continue

        # Create safe filename
        safe_name = metric_name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        output_path = os.path.join(output_dir, f"{safe_name}.png")

        success = generate_boxplot(
            data=data,
            metric_name=metric_name,
            output_path=output_path,
            unit=unit,
            title_prefix=title_prefix,
        )

        if success:
            generated_charts.append(output_path)

    print(f"\nGenerated {len(generated_charts)} charts in {output_dir}")

    # Upload PNG charts to GitHub if requested
    chart_links = []
    github_urls = {}
    if upload_charts_to_github and generated_charts:
        try:
            from impactlens.utils.github_charts_uploader import (
                upload_charts_to_github as github_upload,
            )

            # Extract metadata from report path
            report_file = Path(report_path)

            # Determine report type
            report_type = "jira" if "jira" in report_path.lower() else "pr"

            # Auto-detect team name if not provided
            if team_name is None:
                # Extract team name from path (e.g., reports/test-ci-team1/jira/...)
                path_parts = report_file.parts
                team_name = "unknown"
                if "reports" in path_parts:
                    reports_idx = path_parts.index("reports")
                    if reports_idx + 1 < len(path_parts):
                        team_name = path_parts[reports_idx + 1]

            # Upload to GitHub
            github_urls = github_upload(
                chart_files=generated_charts,
                repo=github_repo,
                team_name=team_name,
                report_type=report_type,
            )

            # Build chart links for GitHub URLs
            for chart_path in generated_charts:
                filename = os.path.basename(chart_path)
                if filename in github_urls:
                    chart_links.append(
                        {
                            "path": chart_path,
                            "name": filename,
                            "embedUrl": github_urls[filename],
                            "webViewLink": github_urls[filename],
                        }
                    )

        except Exception as e:
            print(f"⚠️  Failed to upload charts to GitHub: {e}")

    # Create Google Sheets visualization if requested
    sheet_info = None
    if create_sheets_visualization and chart_links:
        try:
            from impactlens.clients.sheets_client import get_sheets_service
            from impactlens.utils.sheets_visualization import create_visualization_sheet

            print(f"\n📊 Creating Google Sheets visualization...")
            service = get_sheets_service()
            sheet_info = create_visualization_sheet(
                service=service,
                report_path=report_path,
                chart_github_links=chart_links,
                spreadsheet_id=spreadsheet_id,
                config_path=config_path,
                replace_existing=replace_existing,
            )
        except Exception as e:
            print(f"⚠️  Failed to create Sheets visualization: {e}")

    # Return results
    result_info = None
    if chart_links or sheet_info or github_urls:
        result_info = {
            "chart_github_links": chart_links,  # Chart links for Sheets visualization (GitHub URLs)
            "chart_github_urls": github_urls,  # Raw GitHub URLs dict
            "sheet_info": sheet_info,
        }

    return generated_charts, result_info


# ---------------------------------------------------------------------------
# Monthly AI Trend chart
# ---------------------------------------------------------------------------

def generate_monthly_comparison_chart(
    monthly_phases: List[Tuple[str, str, str]],
    reports_dir: str,
    output_path: str,
    title_prefix: str = "",
) -> bool:
    """
    Generate a grouped bar chart comparing key PR metrics across N months.

    Reads pr_metrics_*.json files from the monthly/ subdirectory (one per phase)
    and produces a side-by-side bar chart showing:
      - AI-Assisted PRs (purple)
      - Non-AI PRs (gray)
      - AI Adoption Rate % line (blue, right Y-axis)

    Args:
        monthly_phases: List of (name, start, end) tuples from get_monthly_phases_n().
        reports_dir:    Parent reports directory (e.g. reports/github).
        output_path:    Where to save the PNG.
        title_prefix:   Optional project name prefix.

    Returns:
        True on success, False otherwise.
    """
    if not MATPLOTLIB_AVAILABLE:
        return False

    import json as _json
    from pathlib import Path as _Path

    monthly_dir = _Path(reports_dir) / "monthly"

    # Collect stats per phase from JSON files
    phase_stats = []
    for phase_name, start, end in monthly_phases:
        pattern = f"pr_metrics_general_{start.replace('-', '')}_{end.replace('-', '')}.json"
        json_file = monthly_dir / pattern
        if not json_file.exists():
            # Try any matching file for this period
            candidates = list(monthly_dir.glob(f"pr_metrics_general_{start.replace('-', '')}_*.json"))
            json_file = candidates[0] if candidates else None

        if json_file and json_file.exists():
            try:
                with open(json_file, "r") as fh:
                    data = _json.load(fh)
                stats = data.get("statistics", {})
                phase_stats.append({
                    "name": phase_name,
                    "ai": stats.get("ai_assisted_prs", 0) or 0,
                    "non_ai": stats.get("non_ai_prs", 0) or 0,
                    "ai_rate": stats.get("ai_adoption_rate", 0) or 0,
                    "total": stats.get("total_prs", 0) or 0,
                })
            except Exception:
                phase_stats.append({"name": phase_name, "ai": 0, "non_ai": 0, "ai_rate": 0, "total": 0})
        else:
            phase_stats.append({"name": phase_name, "ai": 0, "non_ai": 0, "ai_rate": 0, "total": 0})

    if not phase_stats:
        return False

    months = [d["name"] for d in phase_stats]
    ai_vals = [d["ai"] for d in phase_stats]
    non_ai_vals = [d["non_ai"] for d in phase_stats]
    ai_pcts = [d["ai_rate"] for d in phase_stats]
    n = len(months)
    x = list(range(n))
    bar_w = 0.35

    fig, ax1 = plt.subplots(figsize=(max(7, n * 2.2), 5.5))

    bars_ai = ax1.bar(
        [i - bar_w / 2 for i in x], ai_vals, width=bar_w,
        color="#7c3aed", label="AI-Assisted PRs", zorder=3,
    )
    bars_non = ax1.bar(
        [i + bar_w / 2 for i in x], non_ai_vals, width=bar_w,
        color="#6b7280", label="Non-AI PRs", zorder=3,
    )

    ax1.set_ylabel("PR Count", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(months, fontsize=11)
    ax1.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax1.set_axisbelow(True)
    max_bar = max(max(ai_vals, default=0), max(non_ai_vals, default=0))
    ax1.set_ylim(0, max(max_bar * 1.3, 1))

    ax2 = ax1.twinx()
    line_ai, = ax2.plot(
        x, ai_pcts, color="#93c5fd", linewidth=2,
        marker="o", markersize=6, label="AI %", zorder=4,
    )
    ax2.set_ylabel("AI Adoption %", fontsize=11)
    ax2.set_ylim(0, 100)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))

    full_title = f"{title_prefix}Monthly PR Comparison" if title_prefix else "Monthly PR Comparison"
    ax1.set_title(full_title, fontsize=14, fontweight="bold", pad=14)
    fig.text(
        0.5, 0.93,
        "AI-assisted vs Non-AI PRs per month. Line shows AI adoption rate.",
        ha="center", fontsize=9, color="#6b7280",
    )

    handles = [bars_ai, bars_non, line_ai]
    labels = ["AI-Assisted PRs", "Non-AI PRs", "AI %"]
    ax1.legend(handles, labels, loc="upper left", fontsize=9, framealpha=0.8)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=95, bbox_inches="tight")
    plt.close()
    print(f"Monthly comparison chart saved: {output_path}")
    return True


def generate_monthly_metrics_chart(
    monthly_phases: List[Tuple[str, str, str]],
    reports_dir: str,
    output_path: str,
    title_prefix: str = "",
) -> bool:
    """
    Generate a 2×2 subplot chart comparing key PR metrics across N months.

    Panels:
      Top-left:     AI-Assisted vs Non-AI PRs (grouped bars)
      Top-right:    Daily Throughput (PRs/day)
      Bottom-left:  Avg Time to First Review (hours)
      Bottom-right: Avg Comments per PR

    Args:
        monthly_phases: List of (name, start, end) from get_monthly_phases_n().
        reports_dir:    Parent reports directory (e.g. reports/github).
        output_path:    Where to save the PNG.
        title_prefix:   Optional project name prefix.

    Returns:
        True on success, False otherwise.
    """
    if not MATPLOTLIB_AVAILABLE:
        return False

    import json as _json
    from pathlib import Path as _Path

    monthly_dir = _Path(reports_dir) / "monthly"

    phase_stats = []
    for phase_name, start, end in monthly_phases:
        pattern = f"pr_metrics_general_{start.replace('-', '')}_{end.replace('-', '')}.json"
        json_file = monthly_dir / pattern
        if not json_file.exists():
            candidates = list(monthly_dir.glob(f"pr_metrics_general_{start.replace('-', '')}_*.json"))
            json_file = candidates[0] if candidates else None

        entry = {"name": phase_name, "ai": 0, "non_ai": 0, "throughput": 0.0,
                 "review_time": 0.0, "comments": 0.0}
        if json_file and json_file.exists():
            try:
                with open(json_file, "r") as fh:
                    data = _json.load(fh)
                stats = data.get("statistics", {})
                overall = stats.get("non_ai_stats") or stats.get("ai_stats") or {}
                entry = {
                    "name": phase_name,
                    "ai":          int(stats.get("ai_assisted_prs", 0) or 0),
                    "non_ai":      int(stats.get("non_ai_prs", 0) or 0),
                    "throughput":  float(stats.get("daily_throughput", 0) or 0),
                    "review_time": float(overall.get("avg_time_to_first_review_hours", 0) or 0),
                    "comments":    float(overall.get("avg_comments", 0) or 0),
                }
            except Exception:
                pass
        phase_stats.append(entry)

    if not phase_stats:
        return False

    months = [d["name"] for d in phase_stats]
    n = len(months)
    x = list(range(n))
    bar_w = 0.35

    fig, axes = plt.subplots(2, 2, figsize=(max(10, n * 2.5), 8))
    fig.suptitle(
        f"{title_prefix}Monthly PR Metrics" if title_prefix else "Monthly PR Metrics",
        fontsize=14, fontweight="bold", y=0.98,
    )

    def _bar_labels(ax):
        for bar in ax.patches:
            h = bar.get_height()
            if h > 0:
                ax.annotate(
                    f"{h:.1f}",
                    xy=(bar.get_x() + bar.get_width() / 2, h),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=8,
                )

    def _style(ax, ylabel):
        ax.set_xticks(x)
        ax.set_xticklabels(months, fontsize=9)
        ax.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
        ax.set_axisbelow(True)
        ax.set_ylabel(ylabel, fontsize=9)

    # Panel 1 – AI-Assisted vs Non-AI PRs
    ax1 = axes[0, 0]
    ai_vals   = [d["ai"]     for d in phase_stats]
    nai_vals  = [d["non_ai"] for d in phase_stats]
    ax1.bar([i - bar_w / 2 for i in x], ai_vals,  width=bar_w, color="#7c3aed", label="AI-Assisted", zorder=3)
    ax1.bar([i + bar_w / 2 for i in x], nai_vals, width=bar_w, color="#6b7280", label="Non-AI",      zorder=3)
    ax1.set_title("AI-Assisted vs Non-AI PRs", fontsize=11)
    ax1.legend(fontsize=8, framealpha=0.8)
    _style(ax1, "PR Count")
    _bar_labels(ax1)

    # Panel 2 – Daily Throughput
    ax2 = axes[0, 1]
    tput = [d["throughput"] for d in phase_stats]
    ax2.bar(x, tput, color="#3b82f6", zorder=3)
    ax2.set_title("Daily Throughput", fontsize=11)
    _style(ax2, "PRs / day")
    _bar_labels(ax2)

    # Panel 3 – Avg Time to First Review
    ax3 = axes[1, 0]
    rev = [d["review_time"] for d in phase_stats]
    ax3.bar(x, rev, color="#f59e0b", zorder=3)
    ax3.set_title("Avg Time to First Review", fontsize=11)
    _style(ax3, "Hours")
    _bar_labels(ax3)

    # Panel 4 – Avg Comments per PR
    ax4 = axes[1, 1]
    cmts = [d["comments"] for d in phase_stats]
    ax4.bar(x, cmts, color="#10b981", zorder=3)
    ax4.set_title("Avg Comments per PR", fontsize=11)
    _style(ax4, "Comments")
    _bar_labels(ax4)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=95, bbox_inches="tight")
    plt.close()
    print(f"Monthly metrics chart saved: {output_path}")
    return True


def collect_monthly_commit_stats(json_files: List[str]) -> List[Dict]:
    """
    Read a collection of pr_metrics_*.json files and aggregate commit stats by month.

    For each merged PR the JSON records:
      - merged_at  (ISO-8601 timestamp)
      - ai_commits_count
      - total_commits

    Args:
        json_files: Paths to pr_metrics JSON files (all phases / periods).

    Returns:
        List of dicts sorted by month, each with keys:
          month       – "YYYY-MM"
          ai          – total AI commits that month
          human       – total Human commits that month
          total       – ai + human
          ai_pct      – AI percentage (0–100)
    """
    import json as _json
    from collections import defaultdict

    monthly: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ai": 0, "human": 0})

    for path in json_files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
        except Exception:
            continue

        for pr in data.get("prs", []):
            merged_at = pr.get("merged_at") or pr.get("merge_date") or ""
            if not merged_at:
                continue
            try:
                month_key = merged_at[:7]  # "YYYY-MM"
            except Exception:
                continue

            ai_c = int(pr.get("ai_commits_count", 0) or 0)
            total_c = int(pr.get("total_commits", 0) or 0)
            human_c = max(0, total_c - ai_c)

            monthly[month_key]["ai"] += ai_c
            monthly[month_key]["human"] += human_c

    result = []
    for month in sorted(monthly.keys()):
        ai = monthly[month]["ai"]
        human = monthly[month]["human"]
        total = ai + human
        ai_pct = round(ai / total * 100, 1) if total > 0 else 0.0
        result.append({"month": month, "ai": ai, "human": human, "total": total, "ai_pct": ai_pct})

    return result


def generate_monthly_trend_chart(
    monthly_stats: List[Dict],
    output_path: str,
    title_prefix: str = "",
) -> bool:
    """
    Generate the Monthly AI Trend bar+line chart (matches the screenshot style).

    Purple bars  = AI commits
    Gray bars    = Human commits
    Blue line    = AI share %  (right Y-axis)

    Args:
        monthly_stats: Output of collect_monthly_commit_stats().
        output_path:   Where to save the PNG (directory is created if needed).
        title_prefix:  Optional project name prefix for the chart title.

    Returns:
        True on success, False if matplotlib is unavailable or data is empty.
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Warning: matplotlib not available – skipping Monthly AI Trend chart.")
        return False

    if not monthly_stats:
        print("No monthly stats data – skipping Monthly AI Trend chart.")
        return False

    months = [d["month"] for d in monthly_stats]
    # Shorten last label with '*' if current month is not yet complete
    from datetime import date as _date
    today = _date.today()
    cur_month_key = today.strftime("%Y-%m")
    display_months = []
    for m in months:
        if m == cur_month_key:
            display_months.append(m + "*")
        else:
            display_months.append(m)

    ai_vals = [d["ai"] for d in monthly_stats]
    human_vals = [d["human"] for d in monthly_stats]
    ai_pcts = [d["ai_pct"] for d in monthly_stats]

    n = len(months)
    x = list(range(n))
    bar_w = 0.38

    fig, ax1 = plt.subplots(figsize=(max(10, n * 0.9), 5.5))

    # --- Bars ---
    bars_ai = ax1.bar(
        [i - bar_w / 2 for i in x], ai_vals, width=bar_w,
        color="#7c3aed", label="AI", zorder=3,
    )
    bars_human = ax1.bar(
        [i + bar_w / 2 for i in x], human_vals, width=bar_w,
        color="#6b7280", label="Human", zorder=3,
    )

    ax1.set_ylabel("Commits", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(display_months, rotation=30, ha="right", fontsize=9)
    ax1.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax1.set_axisbelow(True)
    ax1.tick_params(axis="y", labelsize=9)

    # Start Y-axis from 0, leave headroom
    max_commits = max((a + h) for a, h in zip(ai_vals, human_vals)) if monthly_stats else 1
    ax1.set_ylim(0, max_commits * 1.25)

    # --- AI % line (right Y-axis) ---
    ax2 = ax1.twinx()
    line_ai, = ax2.plot(
        x, ai_pcts, color="#93c5fd", linewidth=2,
        marker="o", markersize=5, label="AI %", zorder=4,
    )
    ax2.set_ylabel("AI %", fontsize=11)
    ax2.set_ylim(0, 100)
    ax2.tick_params(axis="y", labelsize=9)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v)}%"))

    # --- Title & subtitle ---
    full_title = f"{title_prefix}Monthly AI Trend" if title_prefix else "Monthly AI Trend"
    ax1.set_title(full_title, fontsize=14, fontweight="bold", pad=14)
    fig.text(
        0.5, 0.93,
        "AI vs human commit volume per month. Line shows AI share percentage.",
        ha="center", fontsize=9, color="#6b7280",
    )

    # --- Legend ---
    handles = [bars_ai, bars_human, line_ai]
    labels = ["AI", "Human", "AI %"]
    ax1.legend(handles, labels, loc="upper left", fontsize=9, framealpha=0.8)

    plt.tight_layout(rect=[0, 0, 1, 0.93])

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    plt.savefig(output_path, dpi=95, bbox_inches="tight")
    plt.close()

    print(f"Monthly trend chart saved: {output_path}")
    return True


def generate_monthly_trend_report(
    reports_dir: str,
    output_dir: Optional[str] = None,
    github_repo: str = "janaki29/impactlens-charts",
    team_name: Optional[str] = None,
    spreadsheet_id: Optional[str] = None,
    config_path: Optional[str] = None,
    replace_existing: bool = False,
    title_prefix: str = "",
) -> Optional[Dict]:
    """
    End-to-end: collect JSON data → generate chart → upload to GitHub → embed in Google Sheets.

    Args:
        reports_dir:        Directory that contains pr_metrics_*.json files (all phases).
        output_dir:         Where to write the PNG (defaults to reports_dir/charts/).
        github_repo:        "owner/repo" for chart image storage.
        team_name:          Used as subfolder in the charts repo.
        spreadsheet_id:     Google Sheets spreadsheet ID.
        config_path:        Path to config YAML (for sheet prefix extraction).
        replace_existing:   Delete old "Monthly AI Trend" tabs before creating a new one.
        title_prefix:       Project name prefix for the chart title.

    Returns:
        Dict with sheet_info / chart links, or None on failure.
    """
    if not MATPLOTLIB_AVAILABLE:
        print("Warning: matplotlib not available – skipping Monthly AI Trend report.")
        return None

    reports_path = Path(reports_dir)

    # Collect all pr_metrics JSON files (from all sub-directories)
    json_files = list(reports_path.rglob("pr_metrics_*.json"))
    if not json_files:
        print(f"No pr_metrics_*.json found under {reports_dir} – skipping Monthly AI Trend.")
        return None

    print(f"\n📈 Generating Monthly AI Trend from {len(json_files)} JSON file(s)...")

    monthly_stats = collect_monthly_commit_stats([str(f) for f in json_files])
    if not monthly_stats:
        print("No monthly commit data found – skipping Monthly AI Trend chart.")
        return None

    # Output PNG path
    charts_dir = output_dir or str(reports_path / "charts")
    png_path = os.path.join(charts_dir, "monthly_ai_trend.png")

    success = generate_monthly_trend_chart(
        monthly_stats=monthly_stats,
        output_path=png_path,
        title_prefix=title_prefix,
    )
    if not success:
        return None

    # Upload to GitHub
    chart_links = []
    try:
        from impactlens.utils.github_charts_uploader import (
            upload_charts_to_github as github_upload,
        )

        # Auto-detect team name
        if team_name is None:
            path_parts = reports_path.parts
            team_name = "unknown"
            if "reports" in path_parts:
                idx = path_parts.index("reports")
                if idx + 1 < len(path_parts):
                    team_name = path_parts[idx + 1]

        github_urls = github_upload(
            chart_files=[png_path],
            repo=github_repo,
            team_name=team_name,
            report_type="pr",
        )

        filename = os.path.basename(png_path)
        if filename in github_urls:
            chart_links.append({
                "path": png_path,
                "name": "Monthly AI Trend",
                "embedUrl": github_urls[filename],
                "webViewLink": github_urls[filename],
            })
    except Exception as e:
        print(f"⚠️  Could not upload Monthly AI Trend chart to GitHub: {e}")

    if not chart_links:
        return None

    # Create Google Sheets visualization tab
    sheet_info = None
    try:
        from impactlens.clients.sheets_client import get_sheets_service
        from impactlens.utils.sheets_visualization import create_visualization_sheet

        service = get_sheets_service()

        # We need a dummy report_path for create_visualization_sheet metadata.
        # Use the PNG path itself – the function only uses it for report type detection.
        sheet_info = create_visualization_sheet(
            service=service,
            report_path=png_path,
            chart_github_links=chart_links,
            spreadsheet_id=spreadsheet_id,
            sheet_name="Monthly AI Trend",
            config_path=config_path,
            replace_existing=replace_existing,
        )
        if sheet_info:
            print(f"✓ Monthly AI Trend tab created: {sheet_info.get('url', '')}")
    except Exception as e:
        print(f"⚠️  Could not create Monthly AI Trend Sheets tab: {e}")

    return {"chart_links": chart_links, "sheet_info": sheet_info}

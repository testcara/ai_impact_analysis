#!/usr/bin/env python3
"""
Generate GitHub PR AI Impact Analysis Report.

This script orchestrates the complete GitHub PR report generation workflow:
1. Load configuration
2. Generate PR metrics for each configured phase
3. Create comparison report
4. Optionally upload to Google Sheets
"""

import sys
import argparse
import subprocess
import traceback
from pathlib import Path
from typing import List, Optional

from impactlens.utils.common_args import add_pr_report_args
from impactlens.utils.workflow_utils import (
    Colors,
    get_project_root,
    cleanup_old_reports,
    upload_to_google_sheets,
    handle_comparison_report_generation,
    load_members_from_yaml,
    load_and_resolve_config,
    aggregate_member_values_for_phases,
)
from impactlens.utils.date_utils import get_monthly_phases
from impactlens.utils.report_utils import (
    normalize_username,
    combine_comparison_reports,
    get_identifier_for_display,
    build_pr_project_prefix,
)
from impactlens.core.report_aggregator import ReportAggregator


def print_header(title: str, subtitle: Optional[str] = None) -> None:
    """Print formatted header."""
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
    print(f"{Colors.BLUE}{title}{Colors.NC}")
    if subtitle:
        print(f"{Colors.BLUE}{subtitle}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
    print()


def generate_phase_metrics(
    phase_name: str,
    start_date: str,
    end_date: str,
    author: Optional[str] = None,
    incremental: bool = False,
    output_dir: Optional[str] = None,
    hide_individual_names: bool = False,
    config_file: Optional[Path] = None,
    leave_days: float = 0,
    capacity: float = 1.0,
) -> bool:
    """Generate PR metrics for a single phase."""
    args = [
        sys.executable,
        "-m",
        "impactlens.scripts.get_pr_metrics",
        "--start",
        start_date,
        "--end",
        end_date,
    ]

    if author:
        args.extend(["--author", author])

    if incremental:
        args.append("--incremental")

    if output_dir:
        args.extend(["--output-dir", str(output_dir)])

    if hide_individual_names:
        args.append("--hide-individual-names")

    if config_file:
        args.extend(["--config", str(config_file)])

    if leave_days > 0:
        args.extend(["--leave-days", str(leave_days)])

    if capacity != 1.0:
        args.extend(["--capacity", str(capacity)])

    try:
        subprocess.run(args, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def generate_comparison_report(
    author: Optional[str] = None,
    output_dir: Optional[str] = None,
    config_file: Optional[Path] = None,
    hide_individual_names: bool = False,
) -> bool:
    """Generate comparison report from phase metrics."""
    args = [
        sys.executable,
        "-m",
        "impactlens.scripts.generate_pr_comparison_report",
    ]

    if author:
        args.extend(["--author", author])

    if output_dir:
        args.extend(["--reports-dir", str(output_dir)])

    if config_file:
        args.extend(["--config", str(config_file)])

    if hide_individual_names:
        args.append("--hide-individual-names")

    try:
        subprocess.run(args, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def generate_all_members_reports(
    members_file: Path,
    script_name: str,
    no_upload: bool = False,
    upload_members: bool = False,
    config_file: Optional[Path] = None,
    hide_individual_names: bool = False,
) -> int:
    """
    Generate reports for all team members.

    Args:
        members_file: Path to config file with team members
        script_name: Script module name to invoke
        no_upload: If True, skip all uploads
        upload_members: If True, upload member reports (default: False, only team report is uploaded)
        config_file: Optional custom config file path
        hide_individual_names: If True, anonymize individual names in reports
    """
    print_header("Generating reports for all team members")

    # Load detailed member information (includes both name and email)
    members_detailed = load_members_from_yaml(members_file)
    if not members_detailed:
        print(f"{Colors.RED}Error: No team members found in {members_file}{Colors.NC}")
        return 1

    # Generate team overall report first (always upload unless --no-upload)
    print(f"{Colors.BLUE}>>> Generating Team Overall Report{Colors.NC}")
    print()
    cmd = [sys.executable, "-m", script_name]
    if config_file:
        cmd.extend(["--config", str(config_file)])
    if no_upload:
        cmd.append("--no-upload")
    if hide_individual_names:
        cmd.append("--hide-individual-names")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"{Colors.RED}  ✗ Failed to generate team report{Colors.NC}")
        return 1
    print()
    print()

    # Generate individual reports for each member
    # Only upload if --upload-members is specified (and --no-upload is not set)
    failed_members = []
    for member_id, member_info in members_detailed.items():
        # Use 'name' (GitHub username) for API query
        # The script will automatically look up email from config for anonymization
        git_username = member_info.get("git_username") or member_id
        member_email = member_info.get("email")

        # Get display identifier for member (use email for anonymization if available)
        display_identifier = member_email if member_email else git_username
        display_member = get_identifier_for_display(display_identifier, hide_individual_names)
        print(f"{Colors.BLUE}>>> Generating Report for: {display_member}{Colors.NC}")
        print()

        # Pass GitHub username for API query
        # The script will find the corresponding email from config automatically
        cmd = [sys.executable, "-m", script_name, git_username]
        if config_file:
            cmd.extend(["--config", str(config_file)])
        # Skip upload for member reports unless --upload-members is specified
        if no_upload or not upload_members:
            cmd.append("--no-upload")
        if hide_individual_names:
            cmd.append("--hide-individual-names")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failed_members.append(git_username)
        print()
        print()

    # Summary
    print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
    if failed_members:
        print(
            f"{Colors.YELLOW}⚠ All team member reports completed with {len(failed_members)} failures{Colors.NC}"
        )
        print(f"{Colors.YELLOW}Failed: {', '.join(failed_members)}{Colors.NC}")
    else:
        print(f"{Colors.GREEN}✓ All team member reports completed successfully!{Colors.NC}")
    print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
    print()

    print(f"{Colors.BLUE}To combine all reports into a single TSV, run:{Colors.NC}")
    print(f"{Colors.BLUE}  python3 -m {script_name} --combine-only{Colors.NC}")
    print()

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate GitHub PR AI Impact Analysis Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m impactlens.script.generate_pr_report                    # Team overall
  python3 -m impactlens.script.generate_pr_report wlin              # Individual
  python3 -m impactlens.script.generate_pr_report --all-members      # All members
  python3 -m impactlens.script.generate_pr_report --combine-only     # Combine only
  python3 -m impactlens.script.generate_pr_report --incremental      # Incremental mode
        """,
    )

    parser = argparse.ArgumentParser(...)
    add_pr_report_args(parser)
    args = parser.parse_args()

    project_root = get_project_root()
    default_config_file = project_root / "config" / "pr_report_config.yaml"
    custom_config_file = Path(args.config) if args.config else None
    default_reports_dir = project_root / "reports" / "github"

    # Validate, load config, and resolve output directory
    result = load_and_resolve_config(
        custom_config_file, default_config_file, default_reports_dir, "PR config"
    )
    if result is None:
        return 1

    phases, default_author, reports_dir, project_settings, root_configs = result
    config_file = custom_config_file if custom_config_file else default_config_file

    # Handle --combine-only flag
    if args.combine_only:
        print_header("Combining Existing GitHub PR Reports")

        # Clean up old combined reports before generating new one
        # Note: Only clean combined reports, not comparison reports (which are needed as input)
        print(f"{Colors.YELLOW}Cleaning up old combined reports...{Colors.NC}")
        for old_combined in Path(reports_dir).glob("combined_pr_report_*.tsv"):
            old_combined.unlink()
            print(f"{Colors.GREEN}  ✓ Removed {old_combined.name}{Colors.NC}")
        print()

        try:
            # Build project_prefix from repo owner and name
            project_prefix = build_pr_project_prefix(project_settings)

            output_file = combine_comparison_reports(
                reports_dir=str(reports_dir),
                report_type="pr",
                title="GitHub PR AI Impact Analysis - Combined Report (Grouped by Metric)",
                project_prefix=project_prefix,
                hide_individual_names=args.hide_individual_names,
            )

            if output_file is None:
                print(
                    f"{Colors.YELLOW}ℹ️  No comparison reports found (single phase mode), skipping combine step{Colors.NC}"
                )
                print()
            else:
                print(f"{Colors.GREEN}✓ Combined report generated: {output_file.name}{Colors.NC}")
                print()

                # Upload to Google Sheets if not disabled
                upload_to_google_sheets(
                    output_file, skip_upload=args.no_upload, config_path=custom_config_file
                )

                print()
                print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")
                print(f"{Colors.GREEN}✓ Combined report completed successfully!{Colors.NC}")
                print(f"{Colors.GREEN}{'=' * 40}{Colors.NC}")

        except Exception as e:
            print(f"{Colors.RED}Error combining reports: {e}{Colors.NC}")
            return 1

        # Check if aggregation config exists and run aggregation
        # Look for aggregation_config.yaml in two places:
        # 1. Same directory as the config file (for single team)
        # 2. Parent directory (for multi-team with aggregation at parent level)
        config_dir = config_file.parent
        aggregation_config = config_dir / "aggregation_config.yaml"
        if not aggregation_config.exists():
            aggregation_config = config_dir.parent / "aggregation_config.yaml"

        if aggregation_config.exists():
            print()
            print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
            print(f"{Colors.BLUE}Found aggregation config, running aggregation...{Colors.NC}")
            print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
            print()
            try:
                aggregator = ReportAggregator(str(aggregation_config))
                pr_output = aggregator.aggregate_pr_reports()
                if pr_output:
                    print(f"{Colors.GREEN}✓ PR aggregation completed: {pr_output.name}{Colors.NC}")
                else:
                    print(f"{Colors.YELLOW}⚠ No PR reports found for aggregation{Colors.NC}")
            except Exception as e:
                print(f"{Colors.RED}Error during aggregation: {e}{Colors.NC}")
                # Don't fail the whole script if aggregation fails
                traceback.print_exc()

        return 0

    # Handle --all-members flag
    if args.all_members:
        return generate_all_members_reports(
            config_file,  # Use same config file for team members
            "impactlens.scripts.generate_pr_report",
            no_upload=args.no_upload,
            upload_members=args.upload_members,
            config_file=config_file,
            hide_individual_names=args.hide_individual_names,
        )

    # Determine author
    author = args.author or default_author or None

    # For anonymization consistency: use email if available, otherwise use author
    # This ensures the same person gets the same hash in both Jira and PR reports
    anonymization_identifier = author
    if author:
        # Try to find email for this author from config
        members_detailed = load_members_from_yaml(config_file)
        for member_id, member_info in members_detailed.items():
            if member_info.get("git_username") == author:
                # Found the member, use email for anonymization if available
                if member_info.get("email"):
                    anonymization_identifier = member_info.get("email")
                break

    if author:
        # Get display identifier for author (use anonymization_identifier for consistent hash)
        display_author = get_identifier_for_display(
            anonymization_identifier, args.hide_individual_names
        )
        print_header("GitHub PR Analysis Report Generator", f"Author: {display_author}")
    else:
        print_header("GitHub PR Analysis Report Generator", "Team Overall Report")

    print()

    # Step 1: Cleanup old reports
    print(f"{Colors.YELLOW}Step 1: Cleaning up old files...{Colors.NC}")
    # Use anonymization_identifier for consistent file naming
    identifier = (
        normalize_username(anonymization_identifier) if anonymization_identifier else "general"
    )
    cleanup_old_reports(reports_dir, identifier, "pr")
    print()

    # Load leave_days and capacity from team members (using shared utility)
    leave_days_list, capacity_list = aggregate_member_values_for_phases(
        config_file, phases, author=author
    )

    # Step 2-N: Generate metrics for each phase
    step_num = 2

    for phase_index, (phase_name, start_date, end_date) in enumerate(phases):
        print(
            f"{Colors.YELLOW}Step {step_num}: Collecting PR metrics for '{phase_name}' ({start_date} to {end_date})...{Colors.NC}"
        )

        # Get leave_days for this phase
        phase_leave_days = 0
        if leave_days_list and phase_index < len(leave_days_list):
            phase_leave_days = leave_days_list[phase_index]

        # Get capacity for this phase
        phase_capacity = 1.0
        if capacity_list and phase_index < len(capacity_list):
            phase_capacity = capacity_list[phase_index]

        success = generate_phase_metrics(
            phase_name,
            start_date,
            end_date,
            author=author,
            incremental=args.incremental,
            output_dir=str(reports_dir),
            hide_individual_names=args.hide_individual_names,
            config_file=config_file,
            leave_days=phase_leave_days,
            capacity=phase_capacity,
        )

        if success:
            print(f"{Colors.GREEN}  ✓ '{phase_name}' metrics collected{Colors.NC}")
        else:
            print(f"{Colors.RED}  ✗ Failed to collect '{phase_name}' metrics{Colors.NC}")
            return 1

        print()
        step_num += 1

    # Generate comparison report (only if multiple phases)
    result = handle_comparison_report_generation(
        phases=phases,
        step_num=step_num,
        report_type="pr",
        reports_dir=reports_dir,
        identifier=identifier,
        config_file=config_file,
        hide_individual_names=args.hide_individual_names,
        no_upload=args.no_upload,
        custom_config_file=custom_config_file,
        generate_comparison_func=generate_comparison_report,
        user_param_name="author",
        user_param_value=author,
    )
    if result != 0:
        return result

    # Monthly AI Trend: bar+line chart across all months (team-level only)
    if root_configs.get("monthly_trend") and not author and not args.all_members:
        _run_monthly_trend(
            config_file=config_file,
            custom_config_file=custom_config_file,
            reports_dir=reports_dir,
            no_upload=args.no_upload,
            project_settings=project_settings,
            root_configs=root_configs,
        )

    # Monthly comparison: generate a separate N-month comparison report + visual chart
    if root_configs.get("monthly_comparison") and not author and not args.all_members:
        _run_pr_monthly_comparison(
            config_file=config_file,
            custom_config_file=custom_config_file,
            reports_dir=reports_dir,
            hide_individual_names=args.hide_individual_names,
            no_upload=args.no_upload,
            incremental=args.incremental,
            comparison_reference_date=root_configs.get("comparison_reference_date"),
            trend_months=root_configs.get("trend_months", 2),
            project_settings=project_settings,
        )

    print(f"{Colors.GREEN}Done!{Colors.NC}")
    return 0


def _run_monthly_trend(
    config_file: Path,
    custom_config_file: Optional[Path],
    reports_dir: Path,
    no_upload: bool,
    project_settings: dict,
    root_configs: dict,
) -> None:
    """Generate and upload the Monthly AI Trend chart."""
    import os as _os

    print()
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
    print(f"{Colors.BLUE}Monthly AI Trend Chart{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")

    try:
        from impactlens.utils.visualization import generate_monthly_trend_report

        repo_name = project_settings.get("git_repo_name", "")
        title_prefix = f"{repo_name} - " if repo_name else ""

        spreadsheet_id = _os.environ.get("GOOGLE_SPREADSHEET_ID", "")
        github_repo = _os.environ.get("CHARTS_GITHUB_REPO", "janaki29/impactlens-charts")
        replace_existing = root_configs.get("replace_existing_reports", False)

        result = generate_monthly_trend_report(
            reports_dir=str(reports_dir),
            github_repo=github_repo,
            spreadsheet_id=spreadsheet_id if not no_upload else None,
            config_path=str(custom_config_file) if custom_config_file else str(config_file),
            replace_existing=replace_existing,
            title_prefix=title_prefix,
        )

        if result and result.get("sheet_info"):
            url = result["sheet_info"].get("url", "")
            print(f"{Colors.GREEN}  ✓ Monthly AI Trend tab created: {url}{Colors.NC}")
        elif result:
            print(f"{Colors.GREEN}  ✓ Monthly AI Trend chart generated{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}  ⚠ Monthly AI Trend chart could not be generated{Colors.NC}")
    except Exception as e:
        print(f"{Colors.YELLOW}  ⚠ Monthly AI Trend failed: {e}{Colors.NC}")

    print()


def _run_pr_monthly_comparison(
    config_file: Path,
    custom_config_file: Optional[Path],
    reports_dir: Path,
    hide_individual_names: bool,
    no_upload: bool,
    incremental: bool = False,
    comparison_reference_date: Optional[str] = None,
    trend_months: int = 2,
    project_settings: Optional[dict] = None,
) -> None:
    """Generate an N-month PR comparison report (data TSV + visual bar chart tab)."""
    from datetime import date as _date
    from impactlens.utils.date_utils import get_monthly_phases_n

    ref_date = None
    if comparison_reference_date:
        try:
            ref_date = _date.fromisoformat(comparison_reference_date)
        except ValueError:
            print(f"{Colors.YELLOW}  ⚠ Invalid comparison_reference_date '{comparison_reference_date}', using today{Colors.NC}")

    monthly_phases = get_monthly_phases_n(trend_months, ref_date)
    monthly_dir = reports_dir / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)

    print()
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
    month_names = ", ".join(p[0] for p in monthly_phases)
    print(f"{Colors.BLUE}Monthly Comparison (PR): {month_names}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")

    for phase_name, start_date, end_date in monthly_phases:
        print(f"{Colors.YELLOW}  Fetching '{phase_name}' ({start_date} → {end_date})...{Colors.NC}")
        success = generate_phase_metrics(
            phase_name=phase_name,
            start_date=start_date,
            end_date=end_date,
            config_file=config_file,
            output_dir=str(monthly_dir),
            hide_individual_names=hide_individual_names,
            incremental=incremental,
        )
        if success:
            print(f"{Colors.GREEN}  ✓ '{phase_name}' done{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}  ⚠ '{phase_name}' failed, skipping monthly comparison{Colors.NC}")
            return

    # Generate the comparison TSV using month names directly (bypasses config phase names)
    try:
        from impactlens.utils.report_utils import (
            find_comparison_reports as _find_cmp_reports,
            generate_comparison_report as _util_gen_cmp_report,
            reconcile_phase_names as _reconcile_names,
            build_pr_project_prefix as _build_prefix,
        )
        from impactlens.core.pr_report_generator import PRReportGenerator as _PRReportGen

        report_files = _find_cmp_reports(
            report_type="pr",
            identifier=None,
            reports_dir=str(monthly_dir),
        )

        month_names = [p[0] for p in monthly_phases]
        month_names, report_files = _reconcile_names(month_names, report_files)

        output_path = _util_gen_cmp_report(
            report_files=report_files,
            report_generator=_PRReportGen(),
            phase_names=month_names,
            identifier=None,
            output_dir=str(monthly_dir),
            output_file=None,
            report_type="pr",
            project_prefix=_build_prefix(project_settings or {}),
            hide_individual_names=hide_individual_names,
        )
        comparison_generated = bool(output_path)
    except Exception as e:
        print(f"{Colors.YELLOW}  ⚠ Monthly comparison report generation failed: {e}{Colors.NC}")
        comparison_generated = False

    if not comparison_generated:
        print(f"{Colors.YELLOW}  ⚠ Monthly comparison report generation failed{Colors.NC}")
        return

    # Upload comparison TSV to Google Sheets
    monthly_tsvs = sorted(monthly_dir.glob("pr_comparison_general_*.tsv"), reverse=True)
    if monthly_tsvs:
        latest = monthly_tsvs[0]
        print(f"{Colors.GREEN}  ✓ Monthly comparison report: {latest.name}{Colors.NC}")
        upload_to_google_sheets(latest, skip_upload=no_upload, config_path=custom_config_file)
    else:
        print(f"{Colors.YELLOW}  ⚠ No monthly comparison TSV found{Colors.NC}")

    # Generate AI vs Non-AI comparison bar chart → "Monthly Comparison (Visual)" tab
    _run_monthly_comparison_chart(
        monthly_phases=monthly_phases,
        reports_dir=reports_dir,
        monthly_dir=monthly_dir,
        custom_config_file=custom_config_file,
        project_settings=project_settings or {},
        no_upload=no_upload,
    )

    # Generate key-metrics 2×2 chart → "Monthly Metrics (Visual)" tab
    _run_monthly_metrics_chart(
        monthly_phases=monthly_phases,
        reports_dir=reports_dir,
        monthly_dir=monthly_dir,
        custom_config_file=custom_config_file,
        project_settings=project_settings or {},
        no_upload=no_upload,
    )

    print()


def _run_monthly_comparison_chart(
    monthly_phases,
    reports_dir: Path,
    monthly_dir: Path,
    custom_config_file: Optional[Path],
    project_settings: dict,
    no_upload: bool,
) -> None:
    """Generate and upload the monthly comparison bar chart to Google Sheets."""
    import os as _os
    from impactlens.utils.visualization import generate_monthly_comparison_chart

    repo_name = project_settings.get("git_repo_name", "")
    title_prefix = f"{repo_name} - " if repo_name else ""
    png_path = str(monthly_dir / "charts" / "monthly_pr_comparison.png")

    success = generate_monthly_comparison_chart(
        monthly_phases=monthly_phases,
        reports_dir=str(reports_dir),
        output_path=png_path,
        title_prefix=title_prefix,
    )
    if not success:
        print(f"{Colors.YELLOW}  ⚠ Monthly comparison chart could not be generated{Colors.NC}")
        return

    if no_upload:
        print(f"{Colors.GREEN}  ✓ Monthly comparison chart saved (upload skipped){Colors.NC}")
        return

    try:
        from impactlens.utils.github_charts_uploader import upload_charts_to_github
        from impactlens.clients.sheets_client import get_sheets_service
        from impactlens.utils.sheets_visualization import create_visualization_sheet

        github_repo = _os.environ.get("CHARTS_GITHUB_REPO", "janaki29/impactlens-charts")

        path_parts = reports_dir.parts
        team_name = "unknown"
        if "reports" in path_parts:
            idx = path_parts.index("reports")
            if idx + 1 < len(path_parts):
                team_name = path_parts[idx + 1]

        github_urls = upload_charts_to_github(
            chart_files=[png_path],
            repo=github_repo,
            team_name=team_name,
            report_type="pr",
        )

        import os as _os2
        filename = _os2.path.basename(png_path)
        if filename not in github_urls:
            print(f"{Colors.YELLOW}  ⚠ Chart upload to GitHub failed{Colors.NC}")
            return

        chart_links = [{
            "path": png_path,
            "name": "Monthly Comparison (Visual)",
            "embedUrl": github_urls[filename],
            "webViewLink": github_urls[filename],
        }]

        service = get_sheets_service()
        sheet_info = create_visualization_sheet(
            service=service,
            report_path=png_path,
            chart_github_links=chart_links,
            spreadsheet_id=_os.environ.get("GOOGLE_SPREADSHEET_ID", ""),
            sheet_name="Monthly Comparison (Visual)",
            config_path=str(custom_config_file) if custom_config_file else None,
            replace_existing=True,
        )
        if sheet_info:
            print(f"{Colors.GREEN}  ✓ 'Monthly Comparison (Visual)' tab created{Colors.NC}")
    except Exception as e:
        print(f"{Colors.YELLOW}  ⚠ Monthly comparison chart upload failed: {e}{Colors.NC}")


def _run_monthly_metrics_chart(
    monthly_phases,
    reports_dir: Path,
    monthly_dir: Path,
    custom_config_file: Optional[Path],
    project_settings: dict,
    no_upload: bool,
) -> None:
    """Generate and upload the 2×2 monthly key-metrics bar chart to Google Sheets."""
    import os as _os
    from impactlens.utils.visualization import generate_monthly_metrics_chart

    repo_name = project_settings.get("git_repo_name", "")
    title_prefix = f"{repo_name} - " if repo_name else ""
    png_path = str(monthly_dir / "charts" / "monthly_pr_metrics.png")

    success = generate_monthly_metrics_chart(
        monthly_phases=monthly_phases,
        reports_dir=str(reports_dir),
        output_path=png_path,
        title_prefix=title_prefix,
    )
    if not success:
        print(f"{Colors.YELLOW}  ⚠ Monthly metrics chart could not be generated{Colors.NC}")
        return

    if no_upload:
        print(f"{Colors.GREEN}  ✓ Monthly metrics chart saved (upload skipped){Colors.NC}")
        return

    try:
        from impactlens.utils.github_charts_uploader import upload_charts_to_github
        from impactlens.clients.sheets_client import get_sheets_service
        from impactlens.utils.sheets_visualization import create_visualization_sheet

        github_repo = _os.environ.get("CHARTS_GITHUB_REPO", "janaki29/impactlens-charts")

        path_parts = reports_dir.parts
        team_name = "unknown"
        if "reports" in path_parts:
            idx = path_parts.index("reports")
            if idx + 1 < len(path_parts):
                team_name = path_parts[idx + 1]

        github_urls = upload_charts_to_github(
            chart_files=[png_path],
            repo=github_repo,
            team_name=team_name,
            report_type="pr",
        )

        import os as _os2
        filename = _os2.path.basename(png_path)
        if filename not in github_urls:
            print(f"{Colors.YELLOW}  ⚠ Metrics chart upload to GitHub failed{Colors.NC}")
            return

        chart_links = [{
            "path": png_path,
            "name": "Monthly Metrics (Visual)",
            "embedUrl": github_urls[filename],
            "webViewLink": github_urls[filename],
        }]

        service = get_sheets_service()
        sheet_info = create_visualization_sheet(
            service=service,
            report_path=png_path,
            chart_github_links=chart_links,
            spreadsheet_id=_os.environ.get("GOOGLE_SPREADSHEET_ID", ""),
            sheet_name="Monthly Metrics (Visual)",
            config_path=str(custom_config_file) if custom_config_file else None,
            replace_existing=True,
        )
        if sheet_info:
            print(f"{Colors.GREEN}  ✓ 'Monthly Metrics (Visual)' tab created{Colors.NC}")
    except Exception as e:
        print(f"{Colors.YELLOW}  ⚠ Monthly metrics chart upload failed: {e}{Colors.NC}")


if __name__ == "__main__":
    sys.exit(main())

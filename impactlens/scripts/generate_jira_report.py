#!/usr/bin/env python3
"""
Generate Jira AI Impact Analysis Report.

This script orchestrates the complete Jira report generation workflow:
1. Load configuration
2. Generate reports for each configured phase
3. Create comparison report
4. Optionally upload to Google Sheets
"""

import sys
import argparse
import subprocess
import traceback
from pathlib import Path
from typing import List, Optional

from impactlens.utils.common_args import add_jira_report_args
from impactlens.utils.workflow_utils import (
    Colors,
    get_project_root,
    cleanup_old_reports,
    upload_to_google_sheets,
    handle_comparison_report_generation,
    load_members_emails,
    load_and_resolve_config,
    load_members_from_yaml,
    aggregate_member_values_for_phases,
)
from impactlens.utils.date_utils import get_monthly_phases
from impactlens.utils.report_utils import (
    normalize_username,
    combine_comparison_reports,
    get_identifier_for_display,
    build_jira_project_prefix,
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


def generate_phase_report(
    phase_name: str,
    start_date: str,
    end_date: str,
    assignee: Optional[str] = None,
    config_file: Optional[Path] = None,
    leave_days: int = 0,
    capacity: float = 1.0,
    output_dir: Optional[str] = None,
    hide_individual_names: bool = False,
) -> bool:
    """Generate report for a single phase."""
    args = [
        sys.executable,
        "-m",
        "impactlens.scripts.get_jira_metrics",
        "--start",
        start_date,
        "--end",
        end_date,
    ]

    if assignee:
        args.extend(["--assignee", assignee])
    elif config_file and config_file.exists():
        args.extend(["--config", str(config_file)])

    if leave_days > 0:
        args.extend(["--leave-days", str(leave_days)])

    if capacity != 1.0:
        args.extend(["--capacity", str(capacity)])

    if output_dir:
        args.extend(["--output-dir", str(output_dir)])

    if hide_individual_names:
        args.append("--hide-individual-names")

    try:
        subprocess.run(args, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def generate_comparison_report(
    assignee: Optional[str] = None,
    output_dir: Optional[str] = None,
    config_file: Optional[Path] = None,
    hide_individual_names: bool = False,
) -> bool:
    """Generate comparison report from phase reports."""
    args = [
        sys.executable,
        "-m",
        "impactlens.scripts.generate_jira_comparison_report",
    ]

    if assignee:
        args.extend(["--assignee", assignee])

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
        config_file: Optional custom config file to pass to subcommands
        hide_individual_names: If True, anonymize individual names in reports
    """
    print_header("Generating reports for all team members")

    members = load_members_emails(members_file)
    if not members:
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
    for member in members:
        # Get display identifier for member
        display_member = get_identifier_for_display(member, hide_individual_names)
        print(f"{Colors.BLUE}>>> Generating Report for: {display_member}{Colors.NC}")
        print()
        cmd = [sys.executable, "-m", script_name, member]
        if config_file:
            cmd.extend(["--config", str(config_file)])
        # Skip upload for member reports unless --upload-members is specified
        if no_upload or not upload_members:
            cmd.append("--no-upload")
        if hide_individual_names:
            cmd.append("--hide-individual-names")
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failed_members.append(member)
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
        description="Generate Jira AI Impact Analysis Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m impactlens.script.generate_jira_report                      # Team overall
  python3 -m impactlens.script.generate_jira_report wlin@redhat.com     # Individual
  python3 -m impactlens.script.generate_jira_report --all-members        # All members
  python3 -m impactlens.script.generate_jira_report --combine-only       # Combine only
        """,
    )
    parser = argparse.ArgumentParser(...)
    add_jira_report_args(parser)
    args = parser.parse_args()

    project_root = get_project_root()
    default_config_file = project_root / "config" / "jira_report_config.yaml"
    custom_config_file = Path(args.config) if args.config else None
    default_reports_dir = project_root / "reports" / "jira"

    # Validate, load config, and resolve output directory
    result = load_and_resolve_config(
        custom_config_file, default_config_file, default_reports_dir, "Jira config"
    )
    if result is None:
        return 1

    phases, default_assignee, reports_dir, project_settings, root_configs = result
    config_file = custom_config_file if custom_config_file else default_config_file
    # Handle --combine-only flag
    if args.combine_only:
        print_header("Combining Existing Jira Reports")

        # Clean up old combined reports before generating new one
        # Note: Only clean combined reports, not comparison reports (which are needed as input)
        print(f"{Colors.YELLOW}Cleaning up old combined reports...{Colors.NC}")
        for old_combined in Path(reports_dir).glob("combined_jira_report_*.tsv"):
            old_combined.unlink()
            print(f"{Colors.GREEN}  ✓ Removed {old_combined.name}{Colors.NC}")
        print()

        try:
            # Get project key for display in combined report
            project_key = build_jira_project_prefix(project_settings)

            output_file = combine_comparison_reports(
                reports_dir=str(reports_dir),
                report_type="jira",
                title="Jira AI Impact Analysis - Combined Report (Grouped by Metric)",
                project_prefix=project_key,
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
                upload_to_google_sheets(
                    output_file, skip_upload=args.no_upload, config_path=custom_config_file
                )
        except Exception as e:
            print(f"{Colors.RED}Error combining reports: {e}{Colors.NC}")
            traceback.print_exc()
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
                jira_output = aggregator.aggregate_jira_reports()
                if jira_output:
                    print(
                        f"{Colors.GREEN}✓ Jira aggregation completed: {jira_output.name}{Colors.NC}"
                    )
                else:
                    print(f"{Colors.YELLOW}⚠ No Jira reports found for aggregation{Colors.NC}")
            except Exception as e:
                print(f"{Colors.RED}Error during aggregation: {e}{Colors.NC}")
                # Don't fail the whole script if aggregation fails
                traceback.print_exc()

        return 0

    # Handle --all-members flag
    if args.all_members:
        return generate_all_members_reports(
            config_file,  # Use same config file for team members
            "impactlens.scripts.generate_jira_report",
            no_upload=args.no_upload,
            upload_members=args.upload_members,
            config_file=config_file,
            hide_individual_names=args.hide_individual_names,
        )

    # Determine assignee
    assignee = args.assignee or default_assignee or None

    if assignee:
        # Get display identifier for assignee
        display_assignee = get_identifier_for_display(assignee, args.hide_individual_names)
        print_header("AI Impact Analysis Report Generator", f"Assignee: {display_assignee}")
    else:
        print_header("AI Impact Analysis Report Generator", "Team Overall Report")

    print()

    # Step 1: Cleanup old reports
    print(f"{Colors.YELLOW}Step 1: Cleaning up old files...{Colors.NC}")
    identifier = normalize_username(assignee) if assignee else "general"
    cleanup_old_reports(reports_dir, identifier, "jira")
    print()

    # Step 2-N: Generate reports for each phase
    step_num = 2
    # Use config file for team members filtering (only when not filtering by assignee)
    team_config_file = config_file if not assignee else None

    # Load leave_days and capacity from team members (using shared utility)
    leave_days_list, capacity_list = aggregate_member_values_for_phases(
        config_file, phases, author=assignee
    )

    for phase_index, (phase_name, start_date, end_date) in enumerate(phases):
        print(
            f"{Colors.YELLOW}Step {step_num}: Generating report for '{phase_name}' ({start_date} to {end_date})...{Colors.NC}"
        )

        # Get leave_days for this phase
        phase_leave_days = 0
        if leave_days_list and phase_index < len(leave_days_list):
            phase_leave_days = leave_days_list[phase_index]

        # Get capacity for this phase
        phase_capacity = 1.0
        if capacity_list and phase_index < len(capacity_list):
            phase_capacity = capacity_list[phase_index]

        success = generate_phase_report(
            phase_name,
            start_date,
            end_date,
            assignee=assignee,
            config_file=team_config_file,
            leave_days=phase_leave_days,
            capacity=phase_capacity,
            output_dir=str(reports_dir),
            hide_individual_names=args.hide_individual_names,
        )

        if success:
            print(f"{Colors.GREEN}  ✓ '{phase_name}' report generated{Colors.NC}")
        else:
            print(f"{Colors.RED}  ✗ Failed to generate '{phase_name}' report{Colors.NC}")
            return 1

        print()
        step_num += 1

    # Generate comparison report (TSV format combining team + individuals for Google Sheets)
    result = handle_comparison_report_generation(
        phases=phases,
        step_num=step_num,
        report_type="jira",
        reports_dir=reports_dir,
        identifier=identifier,
        config_file=config_file,
        hide_individual_names=args.hide_individual_names,
        no_upload=args.no_upload,
        custom_config_file=custom_config_file,
        generate_comparison_func=generate_comparison_report,
        user_param_name="assignee",
        user_param_value=assignee,
    )
    if result != 0:
        return result

    # Monthly comparison: generate a separate prev-month vs current-month report
    if root_configs.get("monthly_comparison") and not assignee and not args.all_members:
        _run_jira_monthly_comparison(
            config_file=config_file,
            custom_config_file=custom_config_file,
            reports_dir=reports_dir,
            hide_individual_names=args.hide_individual_names,
            no_upload=args.no_upload,
            comparison_reference_date=root_configs.get("comparison_reference_date"),
        )

    print(f"{Colors.GREEN}Done!{Colors.NC}")
    return 0


def _run_jira_monthly_comparison(
    config_file: Path,
    custom_config_file: Optional[Path],
    reports_dir: Path,
    hide_individual_names: bool,
    no_upload: bool,
    comparison_reference_date: Optional[str] = None,
) -> None:
    """Generate a Previous Month vs Current Month Jira comparison report."""
    from datetime import date as _date
    ref_date = None
    if comparison_reference_date:
        try:
            ref_date = _date.fromisoformat(comparison_reference_date)
        except ValueError:
            print(f"{Colors.YELLOW}  ⚠ Invalid comparison_reference_date '{comparison_reference_date}', using today{Colors.NC}")
    monthly_phases = get_monthly_phases(ref_date)
    monthly_dir = reports_dir / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)

    print()
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")
    print(f"{Colors.BLUE}Monthly Comparison (Jira){Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 40}{Colors.NC}")

    for phase_name, start_date, end_date in monthly_phases:
        print(f"{Colors.YELLOW}  Fetching '{phase_name}' ({start_date} → {end_date})...{Colors.NC}")
        success = generate_phase_report(
            phase_name=phase_name,
            start_date=start_date,
            end_date=end_date,
            config_file=config_file,
            output_dir=str(monthly_dir),
            hide_individual_names=hide_individual_names,
        )
        if success:
            print(f"{Colors.GREEN}  ✓ '{phase_name}' done{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}  ⚠ '{phase_name}' failed, skipping monthly comparison{Colors.NC}")
            return

    # Generate the comparison TSV from the monthly JSON files
    success = generate_comparison_report(
        output_dir=str(monthly_dir),
        config_file=config_file,
        hide_individual_names=hide_individual_names,
    )
    if not success:
        print(f"{Colors.YELLOW}  ⚠ Monthly comparison report generation failed{Colors.NC}")
        return

    # Upload the monthly comparison TSV to Google Sheets
    monthly_tsvs = sorted(monthly_dir.glob("jira_comparison_general_*.tsv"), reverse=True)
    if monthly_tsvs:
        latest = monthly_tsvs[0]
        print(f"{Colors.GREEN}  ✓ Monthly comparison report: {latest.name}{Colors.NC}")
        upload_to_google_sheets(latest, skip_upload=no_upload, config_path=custom_config_file)
    else:
        print(f"{Colors.YELLOW}  ⚠ No monthly comparison TSV found{Colors.NC}")

    print()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Generate Monthly AI Trend chart and Google Sheets tab.

Reads all pr_metrics_*.json files found under a reports directory,
aggregates AI vs Human commit counts by calendar month, and produces:
  - A PNG bar+line chart (purple AI bars, gray Human bars, blue AI% line)
  - A "Monthly AI Trend" tab in Google Sheets (via =IMAGE() embedding)

Usage:
    python3 -m impactlens.scripts.generate_monthly_trend \\
        --reports-dir reports/github \\
        [--output-dir reports/github/charts] \\
        [--config config/konfluxui/pr_report_config.yaml] \\
        [--no-upload]
"""

import sys
import os
import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Monthly AI Trend chart for Google Sheets",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Directory containing pr_metrics_*.json files (default: reports/github)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write chart PNG (default: <reports-dir>/charts)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to pr_report_config.yaml (used for Sheets prefix and spreadsheet ID)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip upload to GitHub and Google Sheets (generate PNG only)",
    )
    parser.add_argument(
        "--title-prefix",
        default=None,
        help="Project/team prefix for chart title (auto-detected from config if not set)",
    )
    args = parser.parse_args()

    # Resolve reports directory
    from impactlens.utils.workflow_utils import get_project_root

    project_root = get_project_root()

    if args.reports_dir:
        reports_dir = Path(args.reports_dir)
    else:
        reports_dir = project_root / "reports" / "github"

    if not reports_dir.exists():
        print(f"Reports directory not found: {reports_dir}")
        return 1

    # Load config for spreadsheet ID, repo, replace_existing, title prefix
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "")
    github_repo = os.environ.get("CHARTS_GITHUB_REPO", "janaki29/impactlens-charts")
    replace_existing = False
    title_prefix = args.title_prefix or ""
    config_path = None

    if args.config:
        config_path = args.config
        try:
            import yaml

            with open(args.config, "r") as fh:
                cfg = yaml.safe_load(fh) or {}

            replace_existing = cfg.get("replace_existing_reports", False)

            # Auto-extract title prefix from repo name if not provided
            if not title_prefix:
                project = cfg.get("project", {})
                repo_name = project.get("git_repo_name", "")
                if repo_name:
                    title_prefix = repo_name + " - "

            # Spreadsheet ID from config overrides env var
            if cfg.get("google_spreadsheet_id"):
                spreadsheet_id = cfg["google_spreadsheet_id"]
        except Exception as e:
            print(f"[WARNING] Could not load config {args.config}: {e}")

    from impactlens.utils.visualization import generate_monthly_trend_report

    result = generate_monthly_trend_report(
        reports_dir=str(reports_dir),
        output_dir=args.output_dir,
        github_repo=github_repo,
        team_name=None,
        spreadsheet_id=spreadsheet_id if not args.no_upload else None,
        config_path=config_path,
        replace_existing=replace_existing,
        title_prefix=title_prefix,
    )

    if result is None:
        print("Monthly AI Trend generation failed or produced no output.")
        return 1

    sheet_info = result.get("sheet_info")
    if sheet_info:
        url = sheet_info.get("url", "")
        sheet_name = sheet_info.get("sheet_name", "Monthly AI Trend")
        print(f"\n✓ Tab '{sheet_name}' ready: {url}")
    else:
        print("\n✓ Monthly AI Trend chart generated (Sheets upload skipped).")

    return 0


if __name__ == "__main__":
    sys.exit(main())

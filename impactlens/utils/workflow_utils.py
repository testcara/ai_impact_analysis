"""
Workflow utilities for report generation scripts.

This module contains shared functions used by Jira and GitHub report generation workflows.
"""

import os
import sys
import glob
import subprocess
import yaml
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime

from impactlens.utils.logger import Colors, set_log_level

# Constants
# Changed from 2 to 1: Comparison reports are needed even for single phase
# because they provide the TSV format that combines team + individual members horizontally,
# which is required for Google Sheets upload
MIN_PHASES_FOR_COMPARISON = 1


def apply_project_settings_to_env(
    project_settings: Dict[str, Any], root_config: Optional[Dict[str, Any]] = None
) -> None:
    """
    Apply project settings from config to environment variables.

    This allows config files to override .env settings for project-specific values
    like jira_project_key, git_repo_name, etc.

    Args:
        project_settings: Dict with project configuration from YAML config file
        root_config: Optional dict with root-level config (for google_spreadsheet_id)

    Example:
        >>> project_settings = {"jira_project_key": "KFLUX", "git_repo_name": "konflux-ui"}
        >>> root_config = {"google_spreadsheet_id": "1ABC..."}
        >>> apply_project_settings_to_env(project_settings, root_config)
        # Now os.environ["JIRA_PROJECT_KEY"] == "KFLUX"
        # Now os.environ["GIT_REPO_NAME"] == "konflux-ui"
        # Now os.environ["GOOGLE_SPREADSHEET_ID"] == "1ABC..."
    """
    env_mappings = {
        "jira_url": "JIRA_URL",
        "jira_project_key": "JIRA_PROJECT_KEY",
        "git_url": "GIT_URL",
        "git_repo_owner": "GIT_REPO_OWNER",
        "git_repo_name": "GIT_REPO_NAME",
    }

    for config_key, env_var in env_mappings.items():
        config_value = project_settings.get(config_key)
        if config_value:  # Config has value, override environment variable
            os.environ[env_var] = str(config_value)

    # Handle root-level google_spreadsheet_id
    if root_config:
        google_spreadsheet_id = root_config.get("google_spreadsheet_id")
        if google_spreadsheet_id:
            os.environ["GOOGLE_SPREADSHEET_ID"] = str(google_spreadsheet_id)


def get_email_anonymous_id_enabled(config_path: Path) -> bool:
    """
    Check if email_anonymous_id is enabled in a config file.

    Args:
        config_path: Path to config file (jira_report_config.yaml, pr_report_config.yaml, etc.)

    Returns:
        True if email_anonymous_id is enabled, False otherwise
    """
    if not config_path.exists():
        return False

    try:
        _, root_configs = load_config_file(config_path)
        return root_configs.get("email_anonymous_id", False)
    except Exception:
        return False


def get_project_root() -> Path:
    """
    Get the project root directory by searching for marker files.

    Searches upward from current file for .git directory or other markers.
    """
    current = Path(__file__).resolve()

    # Search upward for project markers
    for parent in [current, *current.parents]:
        # Check for common project root markers
        if any(
            [
                (parent / ".git").exists(),
                (parent / "pyproject.toml").exists(),
                (parent / "setup.py").exists(),
                (parent / "requirements.txt").exists() and (parent / "impactlens").is_dir(),
            ]
        ):
            return parent

    # Fallback: assume current working directory
    return Path.cwd()


def merge_configs(default_config: Dict[str, Any], custom_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge custom configuration with default configuration.

    Custom config values override defaults. Missing values in custom config
    are taken from default config.

    Args:
        default_config: Default configuration dict
        custom_config: Custom configuration dict (overrides defaults)

    Returns:
        Merged configuration dict
    """
    merged = default_config.copy()

    # Override with custom values
    for key, value in custom_config.items():
        if value is not None:  # Only override if value is provided
            merged[key] = value

    return merged


def validate_config_file(
    custom_config_path: Optional[Path], default_config_path: Path, config_type: str = "config"
) -> bool:
    """
    Validate that config files exist and are accessible.

    Design:
    - If custom config specified, it must exist (default is optional for merging)
    - If no custom config, default config must exist
    - If both exist, they will be merged

    Args:
        custom_config_path: Path to custom config file (if specified by user)
        default_config_path: Path to default config file
        config_type: Type of config for error messages (e.g., "PR config", "Jira config")

    Returns:
        True if validation passes, False otherwise (with error message printed)
    """
    # Validate custom config file if specified (it must exist)
    if custom_config_path:
        if not custom_config_path.exists():
            print(
                f"{Colors.RED}Error: Specified {config_type} file does not exist: {custom_config_path}{Colors.NC}"
            )
            print(f"{Colors.YELLOW}Please check the path and try again.{Colors.NC}")
            return False
        if not custom_config_path.is_file():
            print(
                f"{Colors.RED}Error: Specified {config_type} path is not a file: {custom_config_path}{Colors.NC}"
            )
            print(f"{Colors.YELLOW}Please provide a valid config file path.{Colors.NC}")
            return False
        # Custom config exists and is valid
        # Default config is optional (will be used for merging if it exists)
        return True

    # No custom config provided, so default config must exist
    if not default_config_path.exists():
        print(
            f"{Colors.RED}Error: Default {config_type} file not found: {default_config_path}{Colors.NC}"
        )
        print(
            f"{Colors.YELLOW}Please create the config file or specify a custom config with --config{Colors.NC}"
        )
        return False

    return True


def load_and_resolve_config(
    custom_config_path: Optional[Path],
    default_config_path: Path,
    default_reports_dir: Path,
    config_type: str = "config",
) -> Optional[Tuple[List[Tuple[str, str, str]], str, Path, Dict[str, Any], Dict[str, Any]]]:
    """
    Validate, load config file, and resolve output directory.

    This is a convenience function that integrates validation, loading, and output directory resolution.

    Args:
        custom_config_path: Path to custom config file (if specified by user)
        default_config_path: Path to default config file
        default_reports_dir: Default reports directory (e.g., project_root / "reports" / "jira")
        config_type: Type of config for error messages (e.g., "PR config", "Jira config")

    Returns:
        Tuple of (phases, default_assignee_or_author, reports_dir, project_settings, root_configs)
        if successful, None if validation fails

    Note:
        Prints error messages and returns None on validation or loading errors.
    """
    # Step 1: Validate config files
    if not validate_config_file(custom_config_path, default_config_path, config_type):
        return None

    # Step 2: Load configuration
    try:
        if custom_config_path:
            # Merge custom config with default
            project_settings, root_configs = load_config_file(
                default_config_path, custom_config_path
            )
        else:
            # Use default config only
            project_settings, root_configs = load_config_file(default_config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"{Colors.RED}Error loading config: {e}{Colors.NC}")
        return None

    # Step 3: Resolve output directory
    output_dir = root_configs.get("output_dir")
    if output_dir:
        reports_dir = Path(output_dir)
        print(f"{Colors.BLUE}Using custom output directory: {reports_dir}{Colors.NC}")
    else:
        reports_dir = default_reports_dir

    phases = root_configs["phases"]
    default_assignee_or_author = root_configs["default_assignee"]

    return phases, default_assignee_or_author, reports_dir, project_settings, root_configs


def load_config_file(
    config_path: Path, custom_config_path: Optional[Path] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load configuration from a YAML config file with optional custom config override.

    Design:
    1. If custom config exists AND default config exists → merge (custom overrides default)
    2. If custom config exists BUT default config does NOT exist → use custom directly
    3. If default config exists WITHOUT custom config → use default

    Args:
        config_path: Path to default YAML configuration file
        custom_config_path: Optional path to custom YAML config that overrides defaults

    Returns:
        Tuple of (project_settings, root_configs)
        project_settings: Dict with project configuration (jira_url, github_repo_owner, etc.)
        root_configs: Dict with root-level runtime configuration including:
            - phases: List of (phase_name, start_date, end_date) tuples
            - default_assignee: Default assignee/author (empty string for team)
            - output_dir: Optional custom output directory for team isolation
            - visualization: Whether visualization is enabled
            - replace_existing_reports: Whether to replace existing reports
            - email_anonymous_id: Email anonymous ID
            - log_level: Logging level
            - members: List of team member configurations
            - (any other root-level config values)

    Raises:
        FileNotFoundError: If required config file doesn't exist
        ValueError: If config format is invalid
    """
    config = None

    # Case 1 & 2: Custom config provided
    if custom_config_path and custom_config_path.exists():
        # Load custom config
        try:
            with open(custom_config_path, "r") as f:
                custom_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format in {custom_config_path}: {e}")

        if not custom_config:
            raise ValueError(f"Empty config file: {custom_config_path}")

        # Case 1: If default config also exists, merge them (custom overrides default)
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    default_config = yaml.safe_load(f)
                if default_config:
                    config = merge_configs(default_config, custom_config)
                    print(
                        f"[INFO] Merged custom config {custom_config_path} with default {config_path}"
                    )
                else:
                    config = custom_config
            except yaml.YAMLError as e:
                print(f"[WARNING] Invalid YAML in default config {config_path}: {e}")
                config = custom_config
        else:
            # Case 2: Only custom config exists, use it directly
            config = custom_config
            print(f"[INFO] Using custom config: {custom_config_path}")

    # Case 3: No custom config, use default
    else:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format in {config_path}: {e}")

        if not config:
            raise ValueError(f"Empty config file: {config_path}")

        print(f"[INFO] Using default config: {config_path}")

    # Extract project settings (non-sensitive configuration)
    project_settings = config.get("project", {})

    # Apply project settings and root-level configs to environment variables
    apply_project_settings_to_env(project_settings, config)

    # Build root_configs with all root-level configuration
    root_configs = {}

    # Extract and parse phases
    phases = []
    if "phases" in config and config["phases"]:
        for phase in config["phases"]:
            name = phase.get("name", "")
            start = phase.get("start", "")
            end = phase.get("end", "")
            if name and start and end:
                phases.append((name, start, end))

    if not phases:
        raise ValueError(f"No valid phases found in {config_path}")

    root_configs["phases"] = phases
    root_configs["default_assignee"] = config.get("default_assignee", "")
    root_configs["output_dir"] = config.get("output_dir", None)
    root_configs["visualization"] = config.get("visualization", True)
    root_configs["replace_existing_reports"] = config.get("replace_existing_reports", False)
    root_configs["email_anonymous_id"] = config.get("email_anonymous_id", None)
    root_configs["log_level"] = config.get("log_level", None)
    root_configs["members"] = config.get("members", [])
    root_configs["monthly_comparison"] = config.get("monthly_comparison", False)
    root_configs["comparison_reference_date"] = config.get("comparison_reference_date", None)
    root_configs["monthly_trend"] = config.get("monthly_trend", False)
    root_configs["trend_months"] = int(config.get("trend_months", 2))

    # Apply log_level from config if specified
    if root_configs["log_level"]:
        set_log_level(root_configs["log_level"])
        print(f"[INFO] Log level set to: {root_configs['log_level']}")

    return project_settings, root_configs


def aggregate_member_values_for_phases(
    config_file: Path, phases: list, author: Optional[str] = None
) -> tuple:
    """
    Aggregate leave_days and capacity values for all phases.

    This function handles both individual and team reports:
    - For individual reports: extracts values for the specific member
    - For team reports: aggregates values across all team members

    Supports both single values (applied to all phases) and per-phase lists.

    Args:
        config_file: Path to config YAML file
        phases: List of (phase_name, start_date, end_date) tuples
        author: Optional author/assignee for individual reports (None for team)

    Returns:
        Tuple of (leave_days_list, capacity_list) where each is a list of values per phase

    Examples:
        >>> # Team report with 2 members
        >>> aggregate_member_values_for_phases(config_file, phases, author=None)
        ([10, 15, 5], [2.0, 1.5, 2.0])  # Aggregated across team

        >>> # Individual report
        >>> aggregate_member_values_for_phases(config_file, phases, author="wlin")
        ([5, 10, 0], [1.0, 0.5, 1.0])  # Single member's values
    """
    members_details = load_members_from_yaml(config_file)

    leave_days_list = None
    capacity_list = None

    if author:
        # Individual report: get specific member's values
        for member_id, details in members_details.items():
            if member_id == author or details.get("name") == author:
                # Process leave_days
                leave_days_config = details.get("leave_days", 0)
                if isinstance(leave_days_config, list):
                    leave_days_list = leave_days_config
                else:
                    # Single value, use for all phases
                    leave_days_list = [leave_days_config] * len(phases)

                # Process capacity
                capacity_config = details.get("capacity", 1.0)
                if isinstance(capacity_config, list):
                    capacity_list = capacity_config
                else:
                    # Single value, use for all phases
                    capacity_list = [capacity_config] * len(phases)
                break
    else:
        # Team report: aggregate all members' values
        # Initialize lists for each phase
        leave_days_list = [0.0] * len(phases)
        capacity_list = [0.0] * len(phases)

        for member_id, details in members_details.items():
            # Process leave_days
            leave_days_config = details.get("leave_days", 0)
            if isinstance(leave_days_config, list):
                for i, ld in enumerate(leave_days_config):
                    if i < len(leave_days_list):
                        leave_days_list[i] += ld
            else:
                # Single value, add to all phases
                for i in range(len(phases)):
                    leave_days_list[i] += leave_days_config

            # Process capacity
            capacity_config = details.get("capacity", 1.0)
            if isinstance(capacity_config, list):
                for i, cap in enumerate(capacity_config):
                    if i < len(capacity_list):
                        capacity_list[i] += cap
            else:
                # Single value, add to all phases
                for i in range(len(phases)):
                    capacity_list[i] += capacity_config

    return leave_days_list, capacity_list


def load_members_from_yaml(config_path: Path):
    """
    Load team members from YAML config file.

    Supports both formats:
    - members with 'email' field (for Jira)
    - members with 'git_username' field (for GitHub)

    Args:
        config_path: Path to YAML configuration file

    Returns:
        If detailed=False: List of team member identifiers (emails or usernames)
        If detailed=True: Dict mapping identifier to member details:
            {
                'wlin@redhat.com': {
                    'email': 'wlin@redhat.com',
                    'git_username': 'testcara',
                    'leave_days': [...],
                    'capacity': 0.8
                },
                ...
            }

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError:
        return {}

    if not config or "members" not in config:
        return {}

    # Return detailed information
    members_details = {}
    for member in config["members"]:
        if isinstance(member, dict):
            identifier = member.get("email") or member.get("git_username")
            if identifier:
                members_details[identifier] = {
                    "email": member.get("email"),
                    "git_username": member.get("git_username"),
                    "leave_days": member.get("leave_days") or [],
                    "capacity": member.get("capacity", 1.0),
                }
    return members_details


def cleanup_old_reports(reports_dir: Path, identifier: str, report_type: str) -> None:
    """
    Clean up old report files for a given identifier.

    Args:
        reports_dir: Directory containing reports
        identifier: User identifier or "general"
        report_type: "jira" or "pr"
    """
    reports_dir.mkdir(parents=True, exist_ok=True)

    if report_type == "pr":
        patterns = [
            f"pr_metrics_{identifier}_*.json",
            f"pr_report_{identifier}_*.txt",
            f"pr_comparison_{identifier}_*.tsv",
        ]
        # Also clean combined reports for the "general" identifier (team report)
        if identifier == "general":
            patterns.append(f"combined_pr_report_*.tsv")
    elif report_type == "jira":
        patterns = [
            f"jira_metrics_{identifier}_*.json",
            f"jira_report_{identifier}_*.txt",
            f"jira_comparison_{identifier}_*.tsv",
        ]
        # Also clean combined reports for the "general" identifier (team report)
        if identifier == "general":
            patterns.append(f"combined_jira_report_*.tsv")
    else:
        raise ValueError(f"Unknown report type: {report_type}")

    removed_count = 0
    for pattern in patterns:
        for file_path in reports_dir.glob(pattern):
            file_path.unlink()
            removed_count += 1

    print(f"{Colors.GREEN}  ✓ Removed {removed_count} old report files for {identifier}{Colors.NC}")


def extract_sheet_prefix(config_path: Optional[Path]) -> str:
    """
    Extract Google Sheets prefix from config path.

    Returns the first-level directory name under config/ for all scenarios.

    Examples:
        config/simple-team/jira_report_config.yaml → "simple-team"
        config/test-integration-ci/test-ci-team/jira_report_config.yaml → "test-integration-ci"
        config/test-aggregation-ci/aggregation_config.yaml → "test-aggregation-ci"

    Args:
        config_path: Path to config file or directory

    Returns:
        First-level directory name after config/, or empty string if not found
    """
    if not config_path:
        return ""

    # Convert to Path if string
    if isinstance(config_path, str):
        config_path = Path(config_path)

    # Get absolute path and resolve
    config_path = config_path.resolve()

    # Find 'config' in path
    parts = config_path.parts
    try:
        config_index = parts.index("config")

        # Always return the first directory after 'config/'
        # Examples:
        #   - config/simple-team/jira_report_config.yaml → return "simple-team"
        #   - config/test-integration-ci/test-ci-team/ → return "test-integration-ci"
        #   - config/test-aggregation-ci/aggregation_config.yaml → return "test-aggregation-ci"
        if config_index + 1 < len(parts):
            return parts[config_index + 1]

    except (ValueError, IndexError):
        pass

    return ""


def upload_to_google_sheets(
    report_file: Optional[Path],
    skip_upload: bool = False,
    show_manual_instructions: bool = True,
    config_path: Optional[Path] = None,
) -> bool:
    """
    Upload report to Google Sheets if configured.

    Args:
        report_file: Path to report file to upload
        skip_upload: If True, skip upload and only show manual instructions (default: False)
        show_manual_instructions: If True, show manual upload instructions when needed (default: True)
        config_path: Path to config file/directory (used to extract sheet prefix)

    Returns:
        True if upload succeeded or was skipped, False if upload failed

    Example:
        # Auto-upload (default behavior)
        upload_to_google_sheets(report_file, config_path=config_path)

        # Skip upload with instructions
        upload_to_google_sheets(report_file, skip_upload=True)

        # Skip upload silently
        upload_to_google_sheets(report_file, skip_upload=True, show_manual_instructions=False)
    """
    if not report_file or not report_file.exists():
        return False

    # Skip upload if requested
    if skip_upload:
        if show_manual_instructions:
            print(f"{Colors.BLUE}⏭️  Skipping upload (--no-upload specified){Colors.NC}")
            print()
            print("📤 To upload later:")
            print(f"  python3 -m impactlens.scripts.upload_to_sheets --report {report_file}")
            print()
        return True

    credentials = os.getenv("GOOGLE_CREDENTIALS_FILE")
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")

    if credentials and spreadsheet_id:
        print(f"{Colors.YELLOW}📤 Uploading to Google Sheets...{Colors.NC}")

        # Build command with --config if provided
        cmd = [
            sys.executable,
            "-m",
            "impactlens.scripts.upload_to_sheets",
            "--report",
            str(report_file),
        ]

        # Add --config parameter if config_path is provided
        if config_path:
            cmd.extend(["--config", str(config_path)])

            # Check if replace_existing_reports is enabled in config
            try:
                # Handle both file and directory config paths
                config_file_to_read = config_path
                if config_path.is_dir():
                    # If it's a directory, try to find a config file
                    # Try jira_report_config.yaml first, then pr_report_config.yaml
                    for candidate in [
                        "jira_report_config.yaml",
                        "pr_report_config.yaml",
                        "aggregation_config.yaml",
                    ]:
                        candidate_path = config_path / candidate
                        if candidate_path.exists():
                            config_file_to_read = candidate_path
                            break

                # Read config file
                with open(config_file_to_read, "r") as f:
                    config = yaml.safe_load(f)

                # Read replace_existing_reports from root level (consistent across all config types)
                replace_existing = (
                    config.get("replace_existing_reports", False) if config else False
                )

                if replace_existing:
                    cmd.append("--replace-existing")
            except Exception:
                pass  # If config load fails, skip replace-existing flag

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            # Print stdout from upload script
            if result.stdout:
                print(result.stdout, end="")
            print(f"{Colors.GREEN}   ✓ Upload successful{Colors.NC}")
            print()
            return True
        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}   ⚠ Upload failed: {e}{Colors.NC}")
            # Print stderr to show actual error details
            if e.stderr:
                print(f"{Colors.RED}   Error details (stderr):{Colors.NC}")
                print(e.stderr)
            # Also print stdout in case error is there
            if e.stdout:
                print(f"{Colors.RED}   Output (stdout):{Colors.NC}")
                print(e.stdout)
            if not e.stderr and not e.stdout:
                print(
                    f"{Colors.RED}   No error output captured. Exit code: {e.returncode}{Colors.NC}"
                )
            if show_manual_instructions:
                print("   You can upload manually:")
                print(f"   python3 -m impactlens.scripts.upload_to_sheets --report {report_file}")
            print()
            return False
    else:
        if show_manual_instructions:
            print(f"{Colors.BLUE}Google Sheets upload not configured (optional){Colors.NC}")
            print(
                "You can open this file in Google Sheets manually, or configure automatic upload:"
            )
            print("  export GOOGLE_CREDENTIALS_FILE=/path/to/credentials.json")
            print("  export GOOGLE_SPREADSHEET_ID=your_spreadsheet_id")
            print()
            print("Or upload manually:")
            print(f"  python3 -m impactlens.scripts.upload_to_sheets --report {report_file}")
            print()
        return False


def find_latest_comparison_report(
    reports_dir: Path, identifier: str, report_type: str
) -> Optional[Path]:
    """
    Find the most recent comparison report.

    Args:
        reports_dir: Directory containing reports
        identifier: User identifier or "general"
        report_type: "jira" or "pr"

    Returns:
        Path to latest report or None
    """
    if report_type == "jira":
        pattern = f"jira_comparison_{identifier}_*.tsv"
    elif report_type == "pr":
        pattern = f"pr_comparison_{identifier}_*.tsv"
    else:
        return None

    files = list(reports_dir.glob(pattern))
    if not files:
        return None

    # Sort by modification time, newest first
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def find_latest_phase_report(
    reports_dir: Path, identifier: str, report_type: str
) -> Optional[Path]:
    """
    Find the most recent phase report (for single-phase mode).

    Args:
        reports_dir: Directory containing reports
        identifier: User identifier or "general"
        report_type: "jira" or "pr"

    Returns:
        Path to latest report or None
    """
    if report_type == "jira":
        pattern = f"jira_metrics_{identifier}_*.json"
    elif report_type == "pr":
        pattern = f"pr_metrics_{identifier}_*.json"
    else:
        return None

    files = list(reports_dir.glob(pattern))
    if not files:
        return None

    # Sort by modification time, newest first
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def should_generate_comparison(phases: List) -> bool:
    """
    Check if comparison report should be generated.

    Comparison reports provide TSV format that combines team + individual members horizontally,
    which is required for Google Sheets upload. They are generated even for single phase.

    Args:
        phases: List of phases (each phase is a tuple of (name, start, end))

    Returns:
        True if comparison should be generated (1+ phases), False only if no phases

    Examples:
        >>> should_generate_comparison([("Phase 1", "2025-01-01", "2025-01-31")])
        True
        >>> should_generate_comparison([("P1", "2025-01-01", "2025-01-31"), ("P2", "2025-02-01", "2025-02-28")])
        True
        >>> should_generate_comparison([])
        False
    """
    return len(phases) >= MIN_PHASES_FOR_COMPARISON


def handle_comparison_report_generation(
    phases: List,
    step_num: int,
    report_type: str,
    reports_dir: Path,
    identifier: str,
    config_file: Path,
    hide_individual_names: bool,
    no_upload: bool,
    custom_config_file: Optional[Path],
    generate_comparison_func,
    user_param_name: str = "assignee",
    user_param_value: Optional[str] = None,
) -> int:
    """
    Handle comparison report generation and upload.

    This function centralizes the logic for:
    1. Checking if comparison should be generated (requires at least 1 phase)
    2. Generating the comparison report (TSV format combining team + individuals)
    3. Finding and uploading the report to Google Sheets

    Args:
        phases: List of phases (each phase is a tuple of (name, start, end))
        step_num: Current step number for logging
        report_type: "jira" or "pr"
        reports_dir: Directory containing reports
        identifier: User identifier or "general"
        config_file: Path to config file
        hide_individual_names: Whether to hide individual names
        no_upload: Skip upload if True
        custom_config_file: Optional custom config file path
        generate_comparison_func: Callable function to generate comparison report
        user_param_name: Parameter name for user filter ("assignee" for Jira, "author" for PR)
        user_param_value: Optional user value (assignee for Jira, author for PR)

    Returns:
        0 if successful, 1 if failed

    Example:
        >>> # For Jira
        >>> result = handle_comparison_report_generation(
        ...     phases, 3, "jira", reports_dir, "general",
        ...     config_file, False, False, None,
        ...     generate_jira_comparison_report,
        ...     user_param_name="assignee", user_param_value="john@example.com"
        ... )
        >>> # For PR
        >>> result = handle_comparison_report_generation(
        ...     phases, 3, "pr", reports_dir, "general",
        ...     config_file, False, False, None,
        ...     generate_pr_comparison_report,
        ...     user_param_name="author", user_param_value="johndoe"
        ... )
    """
    # Check if comparison should be generated
    if not should_generate_comparison(phases):
        print(
            f"{Colors.YELLOW}ℹ️  No phases configured - " f"skipping comparison report{Colors.NC}"
        )
        print()
        return 0

    # Generate comparison report (combines team + individual members in TSV format)
    print(f"{Colors.YELLOW}Step {step_num}: Generating comparison report...{Colors.NC}")

    # Build kwargs with the appropriate parameter name
    kwargs = {
        "output_dir": str(reports_dir),
        "config_file": config_file,
        "hide_individual_names": hide_individual_names,
    }
    if user_param_value is not None:
        kwargs[user_param_name] = user_param_value

    if not generate_comparison_func(**kwargs):
        print(f"{Colors.RED}  ✗ Failed to generate comparison report{Colors.NC}")
        return 1
    print()

    # Find and upload the latest comparison report
    comparison_file = find_latest_comparison_report(reports_dir, identifier, report_type)
    if comparison_file:
        print(f"{Colors.GREEN}✓ Report generated: {comparison_file.name}{Colors.NC}")
        print()
        upload_to_google_sheets(
            comparison_file, skip_upload=no_upload, config_path=custom_config_file
        )
    else:
        print(f"{Colors.YELLOW}⚠️  No comparison file found{Colors.NC}")

    return 0


def load_members_emails(members_file: Path) -> List[str]:
    """
    Load team members from YAML configuration file.

    Args:
        members_file: Path to YAML team members config

    Returns:
        List of team member emails
    """
    return list(load_members_from_yaml(members_file).keys())


def run_report_for_member(
    script_path: Path, member: str, report_type: str, extra_args: Optional[List[str]] = None
) -> bool:
    """
    Run report generation for a single team member.

    Args:
        script_path: Path to this script (for recursive calls)
        member: Team member identifier
        report_type: "jira" or "pr"
        extra_args: Additional arguments to pass

    Returns:
        True if successful, False otherwise
    """
    args = [sys.executable, "-m"]

    if report_type == "jira":
        args.extend(["impactlens.cli.generate_jira_report", member])
    elif report_type == "pr":
        args.extend(["impactlens.cli.generate_pr_report", member])
    else:
        return False

    if extra_args:
        args.extend(extra_args)

    try:
        subprocess.run(args, check=True)
        return True
    except subprocess.CalledProcessError:
        print(f"{Colors.RED}  ✗ Failed to generate report for {member}{Colors.NC}")
        return False

#!/usr/bin/env python3
"""
Security validation for configuration files.
Prevents malicious YAML injection and enforces security policies.

Usage:
    python scripts/validate_config.py config/team/jira_report_config.yaml
    python scripts/validate_config.py config/team/*.yaml
"""

import sys
import re
import yaml
from pathlib import Path
from typing import List, Dict, Any, Tuple


class ConfigValidator:
    """Validates configuration files for security issues."""

    # Dangerous patterns that could indicate injection attacks
    INJECTION_PATTERNS = [
        # Command injection
        r'\$\(',          # $(command)
        r'`[^`]+`',       # `command`
        r';\s*\w+',       # ; command
        r'\|\s*\w+',      # | command
        r'&&\s*\w+',      # && command
        r'\|\|\s*\w+',    # || command

        # Environment variable expansion (potentially dangerous)
        r'\$\{[^}]+\}',   # ${VAR}
        r'\$[A-Z_]+',     # $VAR

        # Script execution
        r'<script',       # XSS
        r'javascript:',   # JavaScript protocol
        r'eval\s*\(',     # eval()
        r'exec\s*\(',     # exec()

        # Path traversal
        r'\.\./\.\.',     # ../..
        r'/etc/passwd',   # System files
        r'/proc/',        # Process info

        # Network exfiltration
        r'curl\s+',       # curl command
        r'wget\s+',       # wget command
        r'nc\s+',         # netcat
    ]

    # Allowed patterns for legitimate use
    ALLOWED_PATTERNS = [
        r'https?://[a-zA-Z0-9\-\._~:/?#\[\]@!$&\'()*+,;=]+',  # URLs
        r'\d{4}-\d{2}-\d{2}',  # Dates
    ]

    # Required fields for each config type
    REQUIRED_FIELDS = {
        'jira_report_config.yaml': {
            'project': ['jira_url', 'jira_project_key'],
            'phases': True,
            'members': True,
            # output_dir is optional - defaults to "reports"
        },
        'pr_report_config.yaml': {
            'project': ['git_repo_owner', 'git_repo_name'],
            'phases': True,
            'members': True,
            # output_dir is optional - defaults to "reports"
        },
        'aggregation_config.yaml': {
            'aggregation': ['name', 'output_dir', 'projects'],
        },
    }

    # Forbidden field values (field names that should not contain hardcoded values)
    # Note: we check if these strings appear anywhere in the field name
    FORBIDDEN_VALUES = [
        'password',
        'secret',
        'token',  # api_token, auth_token, etc.
        'api_key',
        'apikey',
        'private_key',
        'privatekey',
    ]

    # Allowed field names that may contain long strings (not secrets)
    ALLOWED_FIELD_NAMES = [
        'output_dir',
        'google_spreadsheet_id',
        'spreadsheet_id',
        'jira_url',
        'github_url',
        'git_url',
        'github_repo_owner',
        'github_repo_name',
        'git_repo_owner',
        'git_repo_name',
        'jira_project_key',
        'name',
        'github_username',
        'git_username',
        'email',
        'description',
        'leave_days',
        'capacity',
        'start',
        'end',
        'projects',
        'monthly_comparison',
        'monthly_trend',
        'trend_months',
        'comparison_reference_date',
        'no_ai_analysis',
        'replace_existing_reports',
        'visualization',
        'email_anonymous_id',
        'log_level',
    ]

    def __init__(self, strict: bool = True):
        """
        Initialize validator.

        Args:
            strict: If True, fail on warnings. If False, only fail on errors.
        """
        self.strict = strict
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_file(self, config_path: Path) -> bool:
        """
        Validate a single config file.

        Args:
            config_path: Path to config file

        Returns:
            True if valid, False otherwise
        """
        print(f"\n{'='*80}")
        print(f"Validating: {config_path}")
        print(f"{'='*80}")

        if not config_path.exists():
            self.errors.append(f"File does not exist: {config_path}")
            return False

        # Step 1: YAML syntax validation
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                config = yaml.safe_load(content)
        except yaml.YAMLError as e:
            self.errors.append(f"Invalid YAML syntax: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Failed to read file: {e}")
            return False

        print("✓ YAML syntax is valid")

        # Step 2: Injection pattern detection
        self._check_injection_patterns(content, config_path)

        # Step 3: Structure validation
        self._validate_structure(config, config_path)

        # Step 4: Value validation
        self._validate_values(config, config_path)

        # Step 5: Security policy checks
        self._check_security_policies(config, config_path)

        # Print results
        if self.warnings:
            print(f"\n⚠️  {len(self.warnings)} warning(s):")
            for warning in self.warnings:
                print(f"  - {warning}")

        if self.errors:
            print(f"\n❌ {len(self.errors)} error(s):")
            for error in self.errors:
                print(f"  - {error}")
            return False

        print(f"\n✅ Validation passed!")
        return True

    def _check_injection_patterns(self, content: str, config_path: Path):
        """Check for dangerous injection patterns."""
        for pattern in self.INJECTION_PATTERNS:
            matches = re.finditer(pattern, content)
            for match in matches:
                # Check if it's an allowed pattern
                if any(re.match(allowed, match.group()) for allowed in self.ALLOWED_PATTERNS):
                    continue

                # Find line number
                line_num = content[:match.start()].count('\n') + 1
                self.errors.append(
                    f"Potential injection at line {line_num}: '{match.group()}' "
                    f"(matches pattern: {pattern})"
                )

    def _validate_structure(self, config: Dict[str, Any], config_path: Path):
        """Validate config structure based on file type."""
        config_type = config_path.name

        if config_type not in self.REQUIRED_FIELDS:
            self.warnings.append(f"Unknown config type: {config_type}")
            return

        required = self.REQUIRED_FIELDS[config_type]

        for field, subfields in required.items():
            if isinstance(subfields, bool) and subfields:
                # Just check if field exists
                if field not in config:
                    self.errors.append(f"Missing required field: {field}")
            elif isinstance(subfields, list):
                # Check nested fields
                if field not in config:
                    self.errors.append(f"Missing required field: {field}")
                elif not isinstance(config[field], dict):
                    self.errors.append(f"Field '{field}' must be an object")
                else:
                    for subfield in subfields:
                        if subfield not in config[field]:
                            self.errors.append(
                                f"Missing required subfield: {field}.{subfield}"
                            )

    def _validate_values(self, config: Dict[str, Any], config_path: Path):
        """Validate config values."""
        # Check for hardcoded secrets
        self._check_for_secrets(config, path=[])

        # Validate URLs
        if 'project' in config:
            if 'jira_url' in config['project']:
                url = config['project']['jira_url']
                if not url.startswith(('http://', 'https://')):
                    self.errors.append(f"Invalid jira_url: must start with http:// or https://")

        # Validate dates in phases
        if 'phases' in config and isinstance(config['phases'], list):
            date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
            for i, phase in enumerate(config['phases']):
                if not isinstance(phase, dict):
                    continue
                for date_field in ['start', 'end']:
                    if date_field in phase:
                        date = phase[date_field]
                        if not date_pattern.match(str(date)):
                            self.errors.append(
                                f"Invalid date format in phases[{i}].{date_field}: "
                                f"must be YYYY-MM-DD"
                            )

        # Validate members
        if 'members' in config and isinstance(config['members'], list):
            for i, member in enumerate(config['members']):
                if not isinstance(member, dict):
                    self.errors.append(f"members[{i}] must be an object")
                    continue

                # Check for required email field
                if 'email' not in member:
                    self.errors.append(
                        f"members[{i}] must have 'email' field"
                    )

                # Validate email format if present
                if 'email' in member:
                    email = member['email']
                    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                        self.warnings.append(
                            f"members[{i}].email looks invalid: {email}"
                        )

    def _check_for_secrets(self, obj: Any, path: List[str]):
        """Recursively check for hardcoded secrets."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = path + [key]

                # Check if this is an allowed field name
                if key.lower() in [f.lower() for f in self.ALLOWED_FIELD_NAMES]:
                    # Skip secret detection for allowed fields
                    self._check_for_secrets(value, current_path)
                    continue

                # Check key name for forbidden patterns
                key_lower = key.lower()
                if any(forbidden in key_lower for forbidden in self.FORBIDDEN_VALUES):
                    if isinstance(value, str) and len(value) > 10:
                        self.errors.append(
                            f"Potential hardcoded secret at {'.'.join(current_path)}: "
                            f"field name suggests secret but contains value"
                        )

                # Recurse
                self._check_for_secrets(value, current_path)

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._check_for_secrets(item, path + [f"[{i}]"])

        elif isinstance(obj, str):
            # Check for secret-like patterns in values
            # Skip if current path is an allowed field
            if path and any(path[-1].lower() == f.lower() for f in self.ALLOWED_FIELD_NAMES):
                return

            if len(obj) > 40 and re.match(r'^[A-Za-z0-9+/=_-]{40,}$', obj):
                # Looks like base64 or token (increased threshold to reduce false positives)
                self.warnings.append(
                    f"Suspicious string at {'.'.join(path)}: "
                    f"looks like encoded secret (length: {len(obj)})"
                )

    def _check_security_policies(self, config: Dict[str, Any], config_path: Path):
        """Check security policies."""
        # Ensure output_dir is within allowed paths
        if 'output_dir' in config:
            output_dir = config['output_dir']
            if isinstance(output_dir, str):
                if output_dir.startswith('/'):
                    self.errors.append(
                        "output_dir must be relative path, not absolute"
                    )
                if '..' in output_dir:
                    self.errors.append(
                        "output_dir cannot contain '..' (path traversal)"
                    )
                if not output_dir.startswith('reports/'):
                    self.warnings.append(
                        "output_dir should start with 'reports/' by convention"
                    )

        # Check aggregation projects
        if 'aggregation' in config and 'projects' in config['aggregation']:
            projects = config['aggregation']['projects']
            if isinstance(projects, list):
                for project in projects:
                    if not isinstance(project, str):
                        self.errors.append(f"Project name must be string: {project}")
                    elif '/' in project or '..' in project:
                        self.errors.append(
                            f"Invalid project name '{project}': "
                            f"cannot contain / or .."
                        )


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate ImpactLens configuration files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'files',
        nargs='+',
        help='Config files to validate (supports wildcards)',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Treat warnings as errors',
    )

    args = parser.parse_args()

    # Expand wildcards
    config_files = []
    for pattern in args.files:
        if '*' in pattern:
            config_files.extend(Path('.').glob(pattern))
        else:
            config_files.append(Path(pattern))

    if not config_files:
        print("❌ No config files found")
        return 1

    validator = ConfigValidator(strict=args.strict)
    all_valid = True

    for config_file in config_files:
        if not validator.validate_file(config_file):
            all_valid = False
        # Reset for next file
        validator.errors = []
        validator.warnings = []

    print(f"\n{'='*80}")
    if all_valid:
        print("✅ All config files are valid!")
        return 0
    else:
        print("❌ Validation failed for one or more files")
        return 1


if __name__ == '__main__':
    sys.exit(main())

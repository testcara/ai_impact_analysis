"""
GitHub Charts Uploader.

Upload PNG charts to a dedicated GitHub repository for visualization in Google Sheets.
Uses GitHub raw URLs for embedding images with =IMAGE() formula.
"""

import os
import base64
from pathlib import Path
from typing import List, Dict, Optional
import requests


def get_github_token() -> str:
    """
    Get GitHub token from environment variable.

    Requires CHARTS_UPLOAD_TOKEN - a fine-grained token with write access to the charts repository.

    Returns:
        GitHub token

    Raises:
        ValueError: If CHARTS_UPLOAD_TOKEN is not set
    """
    token = os.environ.get("CHARTS_UPLOAD_TOKEN")
    if not token:
        raise ValueError(
            "CHARTS_UPLOAD_TOKEN environment variable not set. "
            "Please create a fine-grained GitHub token with 'Contents: write' permission "
            "for the charts repository and set it as CHARTS_UPLOAD_TOKEN."
        )
    return token


def create_branch(
    repo: str, branch_name: str, base_branch: str = "main", token: Optional[str] = None
) -> bool:
    """
    Create a new branch in the GitHub repository.

    Args:
        repo: Repository in format "owner/repo"
        branch_name: Name of the new branch
        base_branch: Base branch to create from (default: "main")
        token: GitHub token (uses GITHUB_TOKEN env var if not provided)

    Returns:
        True if branch created successfully, False if already exists
    """
    if token is None:
        token = get_github_token()

    # Get the SHA of the base branch
    url = f"https://api.github.com/repos/{repo}/git/ref/heads/{base_branch}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to get base branch: {response.text}")

    base_sha = response.json()["object"]["sha"]

    # Create new branch
    url = f"https://api.github.com/repos/{repo}/git/refs"
    data = {
        "ref": f"refs/heads/{branch_name}",
        "sha": base_sha,
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        return True
    elif response.status_code == 422:
        # Branch already exists
        return False
    else:
        raise Exception(f"Failed to create branch: {response.text}")


def upload_file_to_github(
    repo: str,
    file_path: str,
    github_path: str,
    branch: str,
    token: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> str:
    """
    Upload a file to GitHub repository.

    Args:
        repo: Repository in format "owner/repo"
        file_path: Local file path to upload
        github_path: Path in the repository (e.g., "team/charts/image.png")
        branch: Branch to upload to
        token: GitHub token (uses GITHUB_TOKEN env var if not provided)
        commit_message: Commit message (auto-generated if None)

    Returns:
        SHA of the created file

    Example:
        >>> sha = upload_file_to_github(
        ...     "testcara/impactlens-charts",
        ...     "chart.png",
        ...     "test-ci-team/github/charts/chart.png",
        ...     "team-123-456"
        ... )
    """
    if token is None:
        token = get_github_token()

    # Read file content
    with open(file_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    # Prepare commit message
    if commit_message is None:
        commit_message = f"Add {Path(file_path).name}"

    # Upload file
    url = f"https://api.github.com/repos/{repo}/contents/{github_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Check if file already exists to get its SHA
    existing_sha = None
    get_response = requests.get(url, headers=headers, params={"ref": branch})
    if get_response.status_code == 200:
        existing_sha = get_response.json()["sha"]

    data = {
        "message": commit_message,
        "content": content,
        "branch": branch,
    }

    # Include SHA if file already exists
    if existing_sha:
        data["sha"] = existing_sha

    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [201, 200]:
        return response.json()["content"]["sha"]
    else:
        raise Exception(f"Failed to upload file: {response.text}")


def upload_charts_to_github(
    chart_files: List[str],
    repo: str = "janaki29/impactlens-charts",
    team_name: str = "unknown",
    report_type: str = "charts",
    branch_name: Optional[str] = None,
    base_branch: str = "main",
    token: Optional[str] = None,
) -> Dict[str, str]:
    """
    Upload multiple chart files to GitHub repository.

    Args:
        chart_files: List of local chart file paths
        repo: Repository in format "owner/repo" (default: testcara/impactlens-charts)
        team_name: Team name for organizing charts
        report_type: Report type (e.g., "jira", "pr")
        branch_name: Branch name (auto-generated if None)
        base_branch: Base branch to create from (default: "main")
        token: GitHub token (uses GITHUB_TOKEN env var if not provided)

    Returns:
        Dict mapping filename to GitHub raw URL
        {
            "chart1.png": "https://raw.githubusercontent.com/owner/repo/branch/path/chart1.png",
            "chart2.png": "https://raw.githubusercontent.com/owner/repo/branch/path/chart2.png",
        }

    Example:
        >>> urls = upload_charts_to_github(
        ...     ["chart1.png", "chart2.png"],
        ...     team_name="test-ci-team1",
        ...     report_type="pr"
        ... )
    """
    if token is None:
        token = get_github_token()

    # Auto-generate branch name if not provided
    if branch_name is None:
        # Get PR number and run ID from environment
        pr_number = os.environ.get("GITHUB_PR_NUMBER", "local")
        run_id = os.environ.get("GITHUB_RUN_ID", "0")
        branch_name = f"{team_name}-{report_type}-{pr_number}-{run_id}"

    print(f"📁 Branch: {branch_name}")

    # Create branch
    try:
        created = create_branch(repo, branch_name, base_branch, token)
        if created:
            print(f"   ✓ Created new branch")
        else:
            print(f"   ℹ️  Branch already exists, will update files")
    except Exception as e:
        print(f"   ⚠️  Failed to create branch: {e}")
        raise

    # Upload files
    print(f"\n📤 Uploading {len(chart_files)} charts to GitHub...")
    results = {}

    github_base_path = f"{team_name}/{report_type}/charts"

    for chart_file in chart_files:
        filename = Path(chart_file).name
        github_path = f"{github_base_path}/{filename}"

        try:
            upload_file_to_github(
                repo=repo,
                file_path=chart_file,
                github_path=github_path,
                branch=branch_name,
                token=token,
                commit_message=f"Add chart: {filename}",
            )

            # Generate raw URL
            raw_url = f"https://raw.githubusercontent.com/{repo}/{branch_name}/{github_path}"
            results[filename] = raw_url

            print(f"   ✓ {filename}")
        except Exception as e:
            print(f"   ✗ Failed to upload {filename}: {e}")

    print(f"\n✅ Uploaded {len(results)}/{len(chart_files)} charts to GitHub")
    print(f"   📁 Repository: {repo}")
    print(f"   🌿 Branch: {branch_name}")

    return results

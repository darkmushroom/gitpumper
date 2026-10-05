#!/usr/bin/env python3
"""
gitpumper.py: Extract GitHub PRs and Commits within a date range for LLM review.
Zero third-party dependencies required.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def get_token(cli_token: Optional[str] = None) -> Optional[str]:
    """Resolve token from CLI flag, env vars, .env, or gh CLI."""
    if cli_token:
        return cli_token

    for env_var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(env_var)
        if val:
            return val.strip()

    # Check local .env file
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() in ("GITHUB_TOKEN", "GH_TOKEN"):
                        return v.strip().strip("'\"")
        except Exception:
            pass

    # Fallback to GitHub CLI if installed and authenticated
    try:
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        if res.stdout.strip():
            return res.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return None


def parse_repo(repo_str: str) -> Tuple[str, str]:
    """Parse 'owner/repo' or 'https://github.com/owner/repo' into (owner, repo)."""
    clean = repo_str.strip().rstrip("/")
    if "github.com/" in clean:
        clean = clean.split("github.com/")[-1]
    if clean.endswith(".git"):
        clean = clean[:-4]
    parts = clean.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid repository format: '{repo_str}'. Expected 'owner/repo'.")
    return parts[0], parts[1]


def api_request(url: str, token: Optional[str]) -> Tuple[Any, Dict[str, str]]:
    """Execute authenticated GitHub REST API request."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gitpumper-llm-dump",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            sys.exit("Error: 401 Unauthorized. Ensure your GitHub token is valid.")
        elif e.code == 404:
            sys.exit(
                f"Error: 404 Not Found for {url}.\n"
                "If this is a private repository, ensure your token has permission and SAML SSO is enabled."
            )
        elif e.code == 403:
            sys.exit(f"Error: 403 Forbidden / Rate Limited: {body}")
        else:
            sys.exit(f"HTTP Error {e.code}: {body}")


def fetch_commits(
    owner: str,
    repo: str,
    since_iso: str,
    until_iso: str,
    token: Optional[str],
) -> List[Dict[str, Any]]:
    """Paginate and fetch commits in date range."""
    commits = []
    page = 1
    base_url = f"https://api.github.com/repos/{owner}/{repo}/commits"

    while True:
        params = {
            "since": since_iso,
            "until": until_iso,
            "per_page": "100",
            "page": str(page),
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        data, headers = api_request(url, token)

        if not isinstance(data, list) or not data:
            break

        commits.extend(data)

        # Check pagination Link header
        link_header = headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break
        page += 1

    return commits


def fetch_pull_requests(
    owner: str,
    repo: str,
    since_date: str,
    until_date: str,
    token: Optional[str],
    pr_filter: str = "merged",
) -> List[Dict[str, Any]]:
    """Fetch PRs via GitHub Search API using date filter (merged or created)."""
    prs = []
    page = 1
    base_url = "https://api.github.com/search/issues"

    # Example query: repo:owner/repo is:pr merged:2026-09-01..2026-10-01
    q = f"repo:{owner}/{repo} is:pr {pr_filter}:{since_date}..{until_date}"

    while True:
        params = {
            "q": q,
            "sort": pr_filter,
            "order": "desc",
            "per_page": "100",
            "page": str(page),
        }
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        data, headers = api_request(url, token)

        items = data.get("items", [])
        if not items:
            break

        prs.extend(items)

        total_count = data.get("total_count", 0)
        if len(prs) >= total_count:
            break

        link_header = headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break
        page += 1

    return prs


def clean_markdown_body(body: Optional[str]) -> str:
    """Strip HTML comments and collapse empty lines to save tokens."""
    if not body:
        return "(No description provided)"
    # Strip HTML comments (PR template instructions)
    cleaned = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    # Collapse 3+ consecutive newlines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() or "(No description provided)"


def format_output(
    owner: str,
    repo: str,
    since_str: str,
    until_str: str,
    prs: List[Dict[str, Any]],
    commits: List[Dict[str, Any]],
    skip_merge_commits: bool = True,
) -> str:
    """Format extracted data into token-dense markdown suitable for an LLM."""
    lines = [
        f"# Repository Digest: {owner}/{repo}",
        f"**Date Range:** {since_str} to {until_str}",
        f"**Pull Requests:** {len(prs)} | **Commits:** {len(commits)}",
        "",
        "---",
        "## Pull Requests",
        "",
    ]

    if not prs:
        lines.append("_No pull requests found in this date range._\n")
    else:
        for pr in prs:
            pr_num = pr.get("number")
            title = pr.get("title", "").strip()
            author = pr.get("user", {}).get("login", "unknown")
            state = pr.get("state", "unknown")
            created_at = pr.get("created_at", "")[:10]
            closed_at = (pr.get("closed_at") or "")[:10]
            body = clean_markdown_body(pr.get("body"))

            lines.append(f"### PR #{pr_num}: {title}")
            lines.append(f"- **Author:** @{author} | **State:** {state} | **Created:** {created_at} | **Closed/Merged:** {closed_at}")
            lines.append("- **Description:**")
            # Indent description for structure
            for bline in body.splitlines():
                lines.append(f"  {bline}")
            lines.append("")

    lines.extend([
        "---",
        "## Commits",
        "",
    ])

    filtered_commits = []
    for c in commits:
        msg = c.get("commit", {}).get("message", "").strip()
        first_line = msg.splitlines()[0] if msg else ""
        if skip_merge_commits and (
            first_line.startswith("Merge pull request ") or first_line.startswith("Merge branch ")
        ):
            continue
        filtered_commits.append(c)

    if not filtered_commits:
        lines.append("_No commits found in this date range._\n")
    else:
        for c in filtered_commits:
            sha = c.get("sha", "")[:7]
            commit_data = c.get("commit", {})
            author = commit_data.get("author", {}).get("name", "unknown")
            date_str = commit_data.get("author", {}).get("date", "")[:10]
            msg = commit_data.get("message", "").strip()

            msg_lines = msg.splitlines()
            subject = msg_lines[0] if msg_lines else ""
            body_lines = msg_lines[1:] if len(msg_lines) > 1 else []

            lines.append(f"- `{sha}` ({date_str}) **{author}**: {subject}")
            if body_lines:
                clean_body = "\n".join(b.strip() for b in body_lines if b.strip())
                if clean_body:
                    for bl in clean_body.splitlines():
                        lines.append(f"    {bl}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Dump GitHub PRs and Commits in a date range for LLM review."
    )
    parser.add_argument("repo", help="Target repo as 'owner/repo' or GitHub URL")
    parser.add_argument("--since", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument(
        "--until",
        default=datetime.date.today().isoformat(),
        help="End date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--pr-filter",
        choices=["merged", "created", "updated"],
        default="merged",
        help="Date filter criteria for PRs (default: merged)",
    )
    parser.add_argument(
        "--include-merge-commits",
        action="store_true",
        help="Include standard merge commits (e.g. 'Merge branch...')",
    )
    parser.add_argument("--token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN env var)")
    parser.add_argument("-o", "--output", help="Output text file path (defaults to stdout)")

    args = parser.parse_args()

    owner, repo = parse_repo(args.repo)
    token = get_token(args.token)

    # Format ISO 8601 for commits API
    since_iso = f"{args.since}T00:00:00Z"
    until_iso = f"{args.until}T23:59:59Z"

    sys.stderr.write(f"Fetching PRs ({args.pr_filter}: {args.since}..{args.until}) for {owner}/{repo}...\n")
    prs = fetch_pull_requests(owner, repo, args.since, args.until, token, args.pr_filter)

    sys.stderr.write(f"Fetching Commits ({args.since}..{args.until}) for {owner}/{repo}...\n")
    commits = fetch_commits(owner, repo, since_iso, until_iso, token)

    formatted = format_output(
        owner=owner,
        repo=repo,
        since_str=args.since,
        until_str=args.until,
        prs=prs,
        commits=commits,
        skip_merge_commits=not args.include_merge_commits,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(formatted)
        sys.stderr.write(f"Done! Written to {args.output}\n")
    else:
        print(formatted)


if __name__ == "__main__":
    main()

# gitpumper

A lightweight Python script to extract GitHub pull requests and commit messages within a specified date range, formatted into token-efficient Markdown for LLM analysis and code reviews.

Requires **Python 3.8+** with **zero external dependencies** (uses only standard library modules).

---

## Features

- **LLM-Optimized Output**: Formats PRs and commits into clean, structured Markdown, stripping noisy HTML template comments and consecutive blank lines to save context tokens.
- **Private & Public Repo Support**: Works with GitHub Personal Access Tokens (PATs) via environment variables, `.env` files, or local `gh` CLI credentials.
- **Merge Commit Filtering**: Automatically filters out repetitive branch merge commits (`Merge branch '...'`) by default.
- **No Clone Needed**: Queries GitHub's REST and Search APIs directly without downloading the repository.

---

## Authentication (for Private Repos)

To access private repositories (including external repositories where you are a collaborator), use a **GitHub Classic Personal Access Token (PAT)** with the **`repo`** scope.

> **Why Classic PAT?** Fine-grained PATs are restricted to repositories you or your own organizations administer. A Classic PAT with `repo` scope inherits your account's access to all private repositories you have permission to view.

### Generating a Classic Token
1. Go to **GitHub Settings → Developer Settings → Personal access tokens → Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Select the **`repo`** checkbox (Full control of private repositories).
4. *(If applicable)* If the target repository belongs to an organization with SAML Single Sign-On (SSO), click **Configure SSO** next to your generated token and authorize the organization.

### Setting the Token

#### Option 1: Environment Variable (Recommended)
```bash
export GITHUB_TOKEN="ghp_..."
```

#### Option 2: Local `.env` File
Create a `.env` file in this directory (automatically ignored by Git):
```env
GITHUB_TOKEN=ghp_...
```

#### Option 3: GitHub CLI
If you already use the GitHub CLI and are logged in (`gh auth login`), `gitpumper` will automatically retrieve your token via `gh auth token` if `GITHUB_TOKEN` is not set.

---

## Usage Examples

### Run on this repository (`darkmushroom/gitpumper`)

Dump all merged PRs and commits from the past month into a text file:

```bash
./gitpumper.py darkmushroom/gitpumper --since 2026-09-01 --until 2026-10-05 -o dump.txt
```

Print output directly to standard output (e.g., to pipe to clipboard or an LLM CLI):

```bash
./gitpumper.py darkmushroom/gitpumper --since 2026-09-01
```

### Match PRs by creation date instead of merge date

```bash
./gitpumper.py darkmushroom/gitpumper --since 2026-09-01 --pr-filter created -o prs_created.txt
```

### Include branch merge commits

```bash
./gitpumper.py darkmushroom/gitpumper --since 2026-09-01 --include-merge-commits -o full_dump.txt
```

---

## CLI Reference

```text
usage: gitpumper.py [-h] --since SINCE [--until UNTIL]
                    [--pr-filter {merged,created,updated}]
                    [--include-merge-commits] [--token TOKEN] [-o OUTPUT]
                    repo

positional arguments:
  repo                  Target repository ('owner/repo' or full GitHub URL)

options:
  -h, --help            Show help message and exit
  --since SINCE         Start date (YYYY-MM-DD, required)
  --until UNTIL         End date (YYYY-MM-DD, defaults to today)
  --pr-filter {merged,created,updated}
                        PR date filter criteria (default: merged)
  --include-merge-commits
                        Include standard branch merge commits
  --token TOKEN         GitHub PAT (overrides GITHUB_TOKEN env var)
  -o, --output OUTPUT   Output file path (defaults to stdout)
```

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

USERNAME = "priyanshshrivastav23-source"


def get_token():
    """Retrieve GitHub token from environment variables."""
    return (
        os.environ.get("GH_TOKEN")
        or os.environ.get("METRICS_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    )


def make_request(url, data=None, token=""):
    """Safe HTTP request with timeout and error handling."""
    headers = {
        "User-Agent": "GitHub-Stats-Updater/2.0",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"[WARN] HTTP {e.code} for URL {url}: {e.reason} | Body: {error_body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Network error for {url}: {str(e)}", file=sys.stderr)
        return None


def graphql_query(query, variables, token):
    """Execute a GitHub GraphQL query with error tolerance."""
    url = "https://api.github.com/graphql"
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    res = make_request(url, data=payload, token=token)
    if not res:
        return None
    if "errors" in res:
        print(f"[WARN] GraphQL errors: {res['errors']}", file=sys.stderr)
    return res.get("data")


def fetch_github_stats(token):
    """Fetch complete statistics using GraphQL and REST."""
    # 1. Fetch user creation year & total owned repos count
    init_query = """
    query($username: String!) {
      user(login: $username) {
        createdAt
        repositories(ownerAffiliations: OWNER, first: 100) {
          totalCount
        }
        contributionsCollection {
          contributionYears
        }
      }
    }
    """
    init_data = graphql_query(init_query, {"username": USERNAME}, token)
    
    # Fallbacks in case of API failure
    created_at_str = "2025-08-22"
    years = [2025, 2026]
    owned_repos_count = 8
    
    if init_data and init_data.get("user"):
      user_obj = init_data["user"]
      created_at_str = user_obj.get("createdAt", "2025-08-22")[:10]
      owned_repos_count = user_obj.get("repositories", {}).get("totalCount", 8)
      contrib_coll = user_obj.get("contributionsCollection") or {}
      years = contrib_coll.get("contributionYears", [2025, 2026])

    try:
        dt_created = datetime.strptime(created_at_str, "%Y-%m-%d")
        formatted_created = dt_created.strftime("%b %d, %Y")
    except Exception:
        formatted_created = "Aug 22, 2025"

    all_days = {}
    total_contributions = 0
    total_commit_contributions = 0

    # 2. Iterate each contribution year via GraphQL
    year_query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $username) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    for y in sorted(years):
        from_date = f"{y}-01-01T00:00:00Z"
        to_date = f"{y}-12-31T23:59:59Z"
        y_data = graphql_query(year_query, {"username": USERNAME, "from": from_date, "to": to_date}, token)
        
        if y_data and y_data.get("user"):
            coll = y_data["user"].get("contributionsCollection") or {}
            total_commit_contributions += coll.get("totalCommitContributions", 0)
            cal = coll.get("contributionCalendar") or {}
            total_contributions += cal.get("totalContributions", 0)
            for week in cal.get("weeks", []):
                for day in week.get("contributionDays", []):
                    all_days[day["date"]] = day["contributionCount"]

    # 3. Supplemental REST calculation for total commits in accessible repos
    rest_commits = 0
    try:
        repos_data = make_request(f"https://api.github.com/users/{USERNAME}/repos?per_page=100&type=all", token=token)
        if isinstance(repos_data, list):
            for repo in repos_data:
                repo_full_name = repo.get("full_name")
                if not repo_full_name:
                    continue
                # Fetch commits authored by user
                commits_url = f"https://api.github.com/repos/{repo_full_name}/commits?author={USERNAME}&per_page=100"
                c_data = make_request(commits_url, token=token)
                if isinstance(c_data, list):
                    rest_commits += len(c_data)
    except Exception as e:
        print(f"[WARN] REST commits calculation exception: {e}", file=sys.stderr)

    # Use the highest verified commit count between GraphQL and REST
    total_commits = max(total_commit_contributions, rest_commits)
    if total_commits == 0 and total_contributions > 0:
        total_commits = total_contributions

    # 4. Calculate Streaks
    sorted_dates = sorted(all_days.keys())
    longest_streak = 0
    longest_start = None
    longest_end = None
    curr_t = 0
    t_start = None

    for d in sorted_dates:
        if all_days[d] > 0:
            if curr_t == 0:
                t_start = d
            curr_t += 1
            if curr_t > longest_streak:
                longest_streak = curr_t
                longest_start = t_start
                longest_end = d
        else:
            curr_t = 0
            t_start = None

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_utc = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    current_streak = 0
    current_start = None
    current_end = None

    idx = len(sorted_dates) - 1
    while idx >= 0 and sorted_dates[idx] > today_utc:
        idx -= 1

    today_count = all_days.get(today_utc, 0)
    yesterday_count = all_days.get(yesterday_utc, 0)

    if today_count > 0:
        current_end = today_utc
        p = idx
        while p >= 0 and all_days.get(sorted_dates[p], 0) > 0:
            current_streak += 1
            current_start = sorted_dates[p]
            p -= 1
    elif yesterday_count > 0:
        current_end = yesterday_utc
        if yesterday_utc in sorted_dates:
            p = sorted_dates.index(yesterday_utc)
            while p >= 0 and all_days.get(sorted_dates[p], 0) > 0:
                current_streak += 1
                current_start = sorted_dates[p]
                p -= 1

    def fmt_range(s, e):
        if not s or not e:
            return "None"
        try:
            d1 = datetime.strptime(s, "%Y-%m-%d").strftime("%b %d")
            d2 = datetime.strptime(e, "%Y-%m-%d").strftime("%b %d")
            return f"{d1} - {d2}"
        except Exception:
            return f"{s} - {e}"

    current_streak_range = fmt_range(current_start, current_end)
    longest_streak_range = fmt_range(longest_start, longest_end)

    return {
        "username": USERNAME,
        "total_commits": total_commits,
        "total_contributions": total_contributions,
        "total_repos": owned_repos_count,
        "current_streak": current_streak,
        "current_streak_range": current_streak_range,
        "longest_streak": longest_streak,
        "longest_streak_range": longest_streak_range,
        "created_formatted": formatted_created,
    }


def generate_svgs(stats):
    """Generate dark-mode SVG card markup."""
    # 1. GitHub Stats Card
    stats_svg = f"""<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Stats Card">
  <style>
    .header {{ font: 700 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; }}
    .stat-label {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; }}
    .stat-value {{ font: 700 16px 'Segoe UI', Ubuntu, Sans-Serif; fill: #FFFFFF; }}
  </style>
  <rect x="0.5" y="0.5" width="494" height="194" rx="8" fill="#242938" stroke="#30363D"/>
  
  <text x="30" y="38" class="header">⚡ Priyansh's GitHub Stats</text>
  
  <g transform="translate(30, 54)">
    <!-- Total Commits -->
    <g transform="translate(0, 16)">
      <circle cx="6" cy="6" r="4" fill="#27E8A7"/>
      <text x="24" y="11" class="stat-label">Total Commits:</text>
      <text x="210" y="11" class="stat-value">{stats['total_commits']}</text>
    </g>
    
    <!-- Total Contributions -->
    <g transform="translate(0, 44)">
      <circle cx="6" cy="6" r="4" fill="#89DDFF"/>
      <text x="24" y="11" class="stat-label">Total Contributions:</text>
      <text x="210" y="11" class="stat-value">{stats['total_contributions']}</text>
    </g>
    
    <!-- Current Streak -->
    <g transform="translate(0, 72)">
      <circle cx="6" cy="6" r="4" fill="#FF7B72"/>
      <text x="24" y="11" class="stat-label">Current Streak:</text>
      <text x="210" y="11" class="stat-value">{stats['current_streak']} Days 🔥</text>
    </g>
    
    <!-- Repositories -->
    <g transform="translate(0, 100)">
      <circle cx="6" cy="6" r="4" fill="#D2A8FF"/>
      <text x="24" y="11" class="stat-label">Total Repositories:</text>
      <text x="210" y="11" class="stat-value">{stats['total_repos']}</text>
    </g>
  </g>
</svg>"""

    # 2. Streak Stats Card
    streak_svg = f"""<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Streak Card">
  <style>
    .big-num {{ font: 700 28px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; text-anchor: middle; }}
    .curr-num {{ font: 700 30px 'Segoe UI', Ubuntu, Sans-Serif; fill: #89DDFF; text-anchor: middle; }}
    .lbl {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; text-anchor: middle; }}
    .sub-lbl {{ font: 400 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #27E8A7; text-anchor: middle; }}
  </style>
  <rect x="0.5" y="0.5" width="494" height="194" rx="8" fill="#242938" stroke="#30363D"/>
  
  <!-- Divider Lines -->
  <line x1="165" y1="28" x2="165" y2="170" stroke="#30363D" stroke-width="1"/>
  <line x1="330" y1="28" x2="330" y2="170" stroke="#30363D" stroke-width="1"/>
  
  <!-- Column 1: Total Contributions -->
  <g transform="translate(82.5, 48)">
    <text x="0" y="32" class="big-num">{stats['total_contributions']}</text>
    <text x="0" y="68" class="lbl">Total Contributions</text>
    <text x="0" y="98" class="sub-lbl">{stats['created_formatted']} - Present</text>
  </g>
  
  <!-- Column 2: Current Streak -->
  <g transform="translate(247.5, 48)">
    <circle cx="0" cy="22" r="38" stroke="#82AAFF" stroke-width="4" fill="none"/>
    <text x="0" y="-12" text-anchor="middle" font-size="20">🔥</text>
    <text x="0" y="32" class="curr-num">{stats['current_streak']}</text>
    <text x="0" y="92" class="lbl" font-weight="700" fill="#89DDFF">Current Streak</text>
    <text x="0" y="116" class="sub-lbl">{stats['current_streak_range']}</text>
  </g>
  
  <!-- Column 3: Longest Streak -->
  <g transform="translate(412.5, 48)">
    <text x="0" y="32" class="big-num">{stats['longest_streak']}</text>
    <text x="0" y="68" class="lbl">Longest Streak</text>
    <text x="0" y="98" class="sub-lbl">{stats['longest_streak_range']}</text>
  </g>
</svg>"""

    return stats_svg, streak_svg


def main():
    token = get_token()
    print(f"Starting GitHub stats refresh for '{USERNAME}'...")
    if token:
        print("[INFO] Authenticated request with provided token.")
    else:
        print("[WARN] No token found; attempting unauthenticated request.")

    stats = fetch_github_stats(token)
    print(f"Calculated Stats: Commits={stats['total_commits']}, Contributions={stats['total_contributions']}, Repos={stats['total_repos']}")
    print(f"Streaks: Current={stats['current_streak']} ({stats['current_streak_range']}), Longest={stats['longest_streak']} ({stats['longest_streak_range']})")

    stats_svg, streak_svg = generate_svgs(stats)

    # Resolve assets directory relative to the repository root
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent.parent
    assets_dir = repo_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    github_stats_path = assets_dir / "github-stats.svg"
    streak_stats_path = assets_dir / "streak-stats.svg"

    with open(github_stats_path, "w", encoding="utf-8") as f:
        f.write(stats_svg)

    with open(streak_stats_path, "w", encoding="utf-8") as f:
        f.write(streak_svg)

    print(f"Successfully wrote {github_stats_path} and {streak_stats_path}!")


if __name__ == "__main__":
    main()

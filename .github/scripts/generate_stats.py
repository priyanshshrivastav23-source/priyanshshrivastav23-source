import os
import json
import urllib.request
import subprocess
from datetime import datetime, timezone, timedelta

def get_git_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return "priyanshshrivastav23-source", token
    input_data = "protocol=https\nhost=github.com\n\n"
    res = subprocess.run(['git', 'credential', 'fill'], input=input_data, text=True, capture_output=True, check=True)
    for line in res.stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1].strip()
        elif line.startswith("username="):
            username = line.split("=", 1)[1].strip()
    return username, token

def rest_get(token, endpoint):
    url = f"https://api.github.com{endpoint}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Antigravity-Stats-Updater",
            "Accept": "application/vnd.github+json"
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def graphql_query(token, query, variables=None):
    url = "https://api.github.com/graphql"
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Antigravity-Stats-Updater",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    username, token = get_git_token()
    print(f"Generating stats for {username}...")
    
    # 1. Fetch all repositories (public and private)
    all_repos = []
    page = 1
    while True:
        repos_page = rest_get(token, f"/user/repos?per_page=100&page={page}&affiliation=owner,collaborator,organization_member")
        if isinstance(repos_page, list) and len(repos_page) > 0:
            all_repos.extend(repos_page)
            page += 1
        else:
            break

    total_public_repos = sum(1 for r in all_repos if not r["private"])
    total_private_repos = sum(1 for r in all_repos if r["private"])
    total_repos_count = len(all_repos)

    # 2. Count commits across all repos (public + private)
    total_public_commits = 0
    total_private_commits = 0
    
    for repo in all_repos:
        repo_name = repo["full_name"]
        is_private = repo["private"]
        c_page = 1
        commits_list = []
        while True:
            c_data = rest_get(token, f"/repos/{repo_name}/commits?per_page=100&page={c_page}")
            if isinstance(c_data, list) and len(c_data) > 0:
                commits_list.extend(c_data)
                if len(c_data) < 100:
                    break
                c_page += 1
            else:
                break
                
        user_c_count = 0
        for c in commits_list:
            author_obj = c.get("author") or {}
            author_login = (author_obj.get("login") or "").lower()
            
            commit_info = c.get("commit", {})
            commit_author = commit_info.get("author", {})
            c_name = (commit_author.get("name") or "").strip().lower()
            c_email = (commit_author.get("email") or "").strip().lower()
            
            if author_login == username.lower() or "priyansh" in c_name or "priyansh" in c_email:
                user_c_count += 1
                
        if is_private:
            total_private_commits += user_c_count
        else:
            total_public_commits += user_c_count

    total_commits = total_public_commits + total_private_commits

    # 3. Fetch GraphQL Contributions and Streak
    viewer_query = """
    query {
      viewer {
        contributionsCollection {
          contributionYears
        }
      }
    }
    """
    res = graphql_query(token, viewer_query)
    years = res["data"]["viewer"]["contributionsCollection"]["contributionYears"]
    
    all_days = {}
    total_contributions = 0
    for y in sorted(years):
        from_date = f"{y}-01-01T00:00:00Z"
        to_date = f"{y}-12-31T23:59:59Z"
        y_q = """
        query($from: DateTime!, $to: DateTime!) {
          viewer {
            contributionsCollection(from: $from, to: $to) {
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
        y_res = graphql_query(token, y_q, {"from": from_date, "to": to_date})
        cal = y_res["data"]["viewer"]["contributionsCollection"]["contributionCalendar"]
        total_contributions += cal["totalContributions"]
        for w in cal["weeks"]:
            for d in w["contributionDays"]:
                all_days[d["date"]] = d["contributionCount"]

    sorted_dates = sorted(all_days.keys())
    
    # Calculate streak
    longest_streak = 0
    curr_t = 0
    for d in sorted_dates:
        if all_days[d] > 0:
            curr_t += 1
            if curr_t > longest_streak:
                longest_streak = curr_t
        else:
            curr_t = 0

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_utc = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    current_streak = 0
    idx = len(sorted_dates) - 1
    while idx >= 0 and sorted_dates[idx] > today_utc:
        idx -= 1
        
    today_count = all_days.get(today_utc, 0)
    yesterday_count = all_days.get(yesterday_utc, 0)
    
    if today_count > 0:
        p = idx
        while p >= 0 and all_days[sorted_dates[p]] > 0:
            current_streak += 1
            p -= 1
    elif yesterday_count > 0:
        p = sorted_dates.index(yesterday_utc)
        while p >= 0 and all_days[sorted_dates[p]] > 0:
            current_streak += 1
            p -= 1

    print(f"Stats: Total Commits: {total_commits} ({total_private_commits} private, {total_public_commits} public)")
    print(f"Total Contributions: {total_contributions}, Current Streak: {current_streak}, Longest Streak: {longest_streak}")

    # Generate Beautiful Modern SVG Stats Card (blueberry theme matching your profile)
    stats_svg = f"""<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Stats Card">
  <style>
    .header {{ font: 700 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; }}
    .stat-label {{ font: 600 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: #82AAFF; }}
    .stat-value {{ font: 700 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: #FFFFFF; }}
    .stat-sub {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #27E8A7; }}
    .rank-circle {{ stroke: #82AAFF; stroke-width: 4; fill: none; }}
    .rank-text {{ font: 800 24px 'Segoe UI', Ubuntu, Sans-Serif; fill: #89DDFF; }}
  </style>
  <rect x="0.5" y="0.5" width="494" height="194" rx="8" fill="#242938" stroke="#30363D"/>
  
  <text x="25" y="35" class="header">⚡ Priyansh's GitHub Stats (All Repos)</text>
  
  <g transform="translate(25, 55)">
    <!-- Total Authored Commits -->
    <g transform="translate(0, 15)">
      <circle cx="6" cy="6" r="4" fill="#27E8A7"/>
      <text x="20" y="10" class="stat-label">Total Commits:</text>
      <text x="175" y="10" class="stat-value">{total_commits}</text>
      <text x="205" y="10" class="stat-sub">({total_private_commits} private, {total_public_commits} public)</text>
    </g>
    
    <!-- Total Contributions -->
    <g transform="translate(0, 42)">
      <circle cx="6" cy="6" r="4" fill="#89DDFF"/>
      <text x="20" y="10" class="stat-label">Total Contributions:</text>
      <text x="175" y="10" class="stat-value">{total_contributions}</text>
      <text x="205" y="10" class="stat-sub">(public + private graph)</text>
    </g>
    
    <!-- Current Streak -->
    <g transform="translate(0, 69)">
      <circle cx="6" cy="6" r="4" fill="#FF7B72"/>
      <text x="20" y="10" class="stat-label">Current Streak:</text>
      <text x="175" y="10" class="stat-value">{current_streak} Days</text>
      <text x="245" y="10" class="stat-sub">(Active today 🔥)</text>
    </g>
    
    <!-- Repositories -->
    <g transform="translate(0, 96)">
      <circle cx="6" cy="6" r="4" fill="#D2A8FF"/>
      <text x="20" y="10" class="stat-label">Total Repositories:</text>
      <text x="175" y="10" class="stat-value">{total_repos_count}</text>
      <text x="205" y="10" class="stat-sub">({total_private_repos} private, {total_public_repos} public)</text>
    </g>
  </g>
  
  <!-- Badge Graphic / Level -->
  <g transform="translate(420, 105)">
    <circle cx="0" cy="0" r="32" class="rank-circle"/>
    <text x="0" y="8" text-anchor="middle" class="rank-text">A+</text>
  </g>
</svg>"""

    os.makedirs("C:/Users/HP/.gemini/antigravity/brain/2db16fc2-ad03-4dbc-99a2-7c10db40961b/scratch/assets", exist_ok=True)
    with open("C:/Users/HP/.gemini/antigravity/brain/2db16fc2-ad03-4dbc-99a2-7c10db40961b/scratch/assets/github-stats.svg", "w", encoding="utf-8") as f:
        f.write(stats_svg)
    print("Generated assets/github-stats.svg successfully!")

if __name__ == "__main__":
    main()

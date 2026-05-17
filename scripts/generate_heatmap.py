#!/usr/bin/env python3
import os, json, time, math
import requests
from datetime import timedelta, date, datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

TOKEN   = os.environ["GH_TOKEN"]
ORG     = os.environ.get("ORG_NAME", "shb-aidev-ais")
HEADERS = {"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json"}

def gh_get(url, params=None):
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait  = max(reset - int(time.time()), 1)
            print("[rate-limit] " + str(wait) + "s 대기...")
            time.sleep(wait)
            continue
        if r.status_code == 409:
            return []
        r.raise_for_status()
        return r.json()

def get_repos():
    repos, page = [], 1
    while True:
        data = gh_get("https://api.github.com/orgs/" + ORG + "/repos",
                      params={"type": "all", "per_page": 100, "page": page})
        if not data:
            break
        repos.extend(data)
        page += 1
    print("[info] 리포지토리 " + str(len(repos)) + "개 발견")
    return repos

def fetch_commit_detail(repo_name, sha):
    try:
        detail = gh_get("https://api.github.com/repos/" + ORG + "/" + repo_name + "/commits/" + sha)
        stats  = detail.get("stats", {})
        lines  = stats.get("additions", 0) + stats.get("deletions", 0)
        score  = 1 + min(lines / 50, 10)
        files_changed = len(detail.get("files", []))
        return score, files_changed
    except Exception:
        return 1, 0

def collect_commits(repos):
    daily            = defaultdict(float)
    repo_daily_files = defaultdict(lambda: defaultdict(int))
    tasks = []
    for repo in repos:
        name = repo["name"]
        print("  -> " + name + " 커밋 목록 수집 중...")
        page = 1
        while True:
            commits = gh_get(
                "https://api.github.com/repos/" + ORG + "/" + name + "/commits",
                params={"per_page": 100, "page": page}
            )
            if not commits or not isinstance(commits, list):
                break
            for c in commits:
                date_str = c["commit"]["author"]["date"][:10]
                tasks.append((date_str, c["sha"], name))
            if len(commits) < 100:
                break
            page += 1
    print("[info] 총 " + str(len(tasks)) + "개 커밋 병렬 상세 조회 시작 (workers=10)...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {
            executor.submit(fetch_commit_detail, name, sha): (date_str, name)
            for date_str, sha, name in tasks
        }
        done = 0
        for future in as_completed(future_map):
            date_str, name = future_map[future]
            score, files_changed = future.result()
            daily[date_str]                  += score
            repo_daily_files[name][date_str] += files_changed
            done += 1
            if done % 100 == 0:
                print("  [" + str(done) + "/" + str(len(tasks)) + "] 처리 중...")
    return daily, repo_daily_files

def color(val, max_val):
    if val == 0 or max_val == 0:
        return "#ebedf0"
    pct = val / max_val
    if pct < 0.25: return "#9be9a8"
    if pct < 0.50: return "#40c463"
    if pct < 0.75: return "#30a14e"
    return "#216e39"

def _fmt(v):
    return str(int(v) // 1000) + "K" if v >= 1000 else str(int(v))

NOW_STR = datetime.now().strftime("%Y-%m-%d %H:%M")

# ── Workload 히스토리 (단일 합산, 연필 스타일, 흑백) ──────────
def make_file_history_svg(repo_daily_files, output_path):
    today = date.today()
    start = today - timedelta(weeks=26)
    all_dates = []
    d = start
    while d <= today:
        all_dates.append(d)
        d += timedelta(days=1)
    n_dates = len(all_dates)

    cumsum = 0
    total_series = []
    for d in all_dates:
        for rname, dmap in repo_daily_files.items():
            cumsum += dmap.get(str(d), 0)
        total_series.append(cumsum)

    max_val = max(total_series) if total_series else 1

    PAD_L, PAD_R, PAD_T, PAD_B = 60, 30, 50, 45
    W, H = 760, 295
    CW = W - PAD_L - PAD_R
    CH = H - PAD_T - PAD_B

    def px(i):
        return PAD_L + int(i / max(n_dates - 1, 1) * CW)
    def py(val):
        return PAD_T + CH - int(float(val) / max_val * CH)

    y_ticks = [int(max_val * i / 4) for i in range(5)]
    month_ticks = []
    for i, d in enumerate(all_dates):
        if d.day == 1:
            month_ticks.append((i, str(d.month) + "월"))

    e = []

    e.append(
        "<defs>"
        "<filter id=\"pencil\" x=\"-5%\" y=\"-5%\" width=\"110%\" height=\"110%\">"
        "<feTurbulence type=\"fractalNoise\" baseFrequency=\"0.9\" numOctaves=\"4\" seed=\"5\" result=\"noise\"/>"
        "<feDisplacementMap in=\"SourceGraphic\" in2=\"noise\" scale=\"1.6\" xChannelSelector=\"R\" yChannelSelector=\"G\"/>"
        "</filter>"
        "<filter id=\"pline\" x=\"-2%\" y=\"-30%\" width=\"104%\" height=\"160%\">"
        "<feTurbulence type=\"fractalNoise\" baseFrequency=\"0.015 0.9\" numOctaves=\"3\" seed=\"11\" result=\"noise\"/>"
        "<feDisplacementMap in=\"SourceGraphic\" in2=\"noise\" scale=\"1.8\" xChannelSelector=\"R\" yChannelSelector=\"G\"/>"
        "</filter>"
        "<filter id=\"rough\" x=\"-5%\" y=\"-5%\" width=\"110%\" height=\"110%\">"
        "<feTurbulence type=\"turbulence\" baseFrequency=\"0.05\" numOctaves=\"2\" seed=\"2\" result=\"noise\"/>"
        "<feDisplacementMap in=\"SourceGraphic\" in2=\"noise\" scale=\"2\" xChannelSelector=\"R\" yChannelSelector=\"G\"/>"
        "</filter>"
        "</defs>"
    )

    e.append("<rect width=\"" + str(W) + "\" height=\"" + str(H) + "\" fill=\"#ffffff\"/>")

    e.append(
        "<text x=\"" + str(W // 2) + "\" y=\"32\" text-anchor=\"middle\""
        " font-size=\"14\" font-weight=\"bold\" font-family=\"Georgia,serif\""
        " fill=\"#111111\" filter=\"url(#pencil)\">"
        "Workload (6 months)</text>"
    )

    for v in y_ticks:
        y = py(v)
        e.append(
            "<line x1=\"" + str(PAD_L) + "\" y1=\"" + str(y) +
            "\" x2=\"" + str(PAD_L + CW) + "\" y2=\"" + str(y) +
            "\" stroke=\"#cccccc\" stroke-width=\"0.7\""
            " stroke-dasharray=\"4,5\" filter=\"url(#rough)\"/>"
        )
        e.append(
            "<text x=\"" + str(PAD_L - 6) + "\" y=\"" + str(y + 4) +
            "\" text-anchor=\"end\" font-size=\"10\" font-family=\"Georgia,serif\""
            " fill=\"#333333\">" + _fmt(v) + "</text>"
        )

    for i, label in month_ticks:
        x = px(i)
        e.append(
            "<text x=\"" + str(x) + "\" y=\"" + str(PAD_T + CH + 20) +
            "\" text-anchor=\"middle\" font-size=\"11\" font-family=\"Georgia,serif\""
            " fill=\"#333333\" filter=\"url(#pencil)\">" + label + "</text>"
        )

    e.append(
        "<line x1=\"" + str(PAD_L - 1) + "\" y1=\"" + str(PAD_T - 8) +
        "\" x2=\"" + str(PAD_L - 1) + "\" y2=\"" + str(PAD_T + CH + 6) +
        "\" stroke=\"#111111\" stroke-width=\"2\" filter=\"url(#pline)\"/>"
    )
    e.append(
        "<line x1=\"" + str(PAD_L - 8) + "\" y1=\"" + str(PAD_T + CH + 1) +
        "\" x2=\"" + str(PAD_L + CW + 8) + "\" y2=\"" + str(PAD_T + CH + 1) +
        "\" stroke=\"#111111\" stroke-width=\"2\" filter=\"url(#pline)\"/>"
    )

    area_pts = str(PAD_L) + "," + str(PAD_T + CH)
    for i, v in enumerate(total_series):
        area_pts += " " + str(px(i)) + "," + str(py(v))
    area_pts += " " + str(px(n_dates - 1)) + "," + str(PAD_T + CH)
    e.append("<polygon points=\"" + area_pts + "\" fill=\"#e8e8e8\" opacity=\"0.6\"/>")

    pts = " ".join(str(px(i)) + "," + str(py(v)) for i, v in enumerate(total_series))
    e.append(
        "<polyline points=\"" + pts + "\""
        " fill=\"none\" stroke=\"#111111\" stroke-width=\"2.4\""
        " stroke-linejoin=\"round\" stroke-linecap=\"round\""
        " filter=\"url(#pline)\"/>"
    )

    lx = px(n_dates - 1)
    lv = total_series[-1]
    e.append(
        "<circle cx=\"" + str(lx) + "\" cy=\"" + str(py(lv)) +
        "\" r=\"4\" fill=\"#111111\" filter=\"url(#pencil)\"/>"
    )
    e.append(
        "<text x=\"" + str(lx - 6) + "\" y=\"" + str(py(lv) - 8) +
        "\" text-anchor=\"end\" font-size=\"10\" font-family=\"Georgia,serif\""
        " fill=\"#111111\">" + _fmt(lv) + "</text>"
    )

    e.append(
        "<text x=\"" + str(PAD_L) + "\" y=\"" + str(H - 6) +
        "\" font-size=\"9\" font-family=\"Georgia,serif\" fill=\"#888888\">"
        "기준: " + NOW_STR + "</text>"
    )

    svg = (
        "<svg xmlns=\"http://www.w3.org/2000/svg\""
        " width=\"" + str(W) + "\" height=\"" + str(H) + "\">\n"
        + "\n".join(e) + "\n</svg>"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(svg)
    print("[done] " + output_path)

# ── 연간 히트맵 ────────────────────────────────────────────────
def make_annual_svg(daily, output_path, text_color="#cccccc"):
    today = date.today()
    start = today - timedelta(weeks=26)
    start = start - timedelta(days=(start.weekday() + 1) % 7)
    dates   = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    values  = [daily.get(str(d), 0) for d in dates]
    max_val = max(values) if any(v > 0 for v in values) else 1
    CELL, STEP, LEFT, TOP = 13, 15, 24, 22
    COLS = math.ceil(len(dates) / 7)
    W, H = LEFT + COLS * STEP + 10, TOP + 7 * STEP + 54
    cells, months = [], {}
    for i, d in enumerate(dates):
        col, row = i // 7, i % 7
        x, y = LEFT + col * STEP, TOP + row * STEP
        v = daily.get(str(d), 0)
        cells.append(
            "<rect x=\"" + str(x) + "\" y=\"" + str(y) +
            "\" width=\"" + str(CELL) + "\" height=\"" + str(CELL) +
            "\" rx=\"2\" fill=\"" + color(v, max_val) + "\">"
            "<title>" + str(d) + " (" + str(round(v, 1)) + ")</title></rect>"
        )
        if d.day == 1:
            months[col] = str(d.month)
    day_ko = ["일","월","화","수","목","금","토"]
    dlabels = [
        "<text x=\"" + str(LEFT - 4) + "\" y=\"" + str(TOP + row * STEP + CELL - 2) +
        "\" text-anchor=\"end\" font-size=\"9\" fill=\"" + text_color + "\">" +
        day_ko[row] + "</text>"
        for row in [1, 3, 5]
    ]
    mlabels = [
        "<text x=\"" + str(LEFT + col * STEP) + "\" y=\"" + str(TOP - 6) +
        "\" font-size=\"9\" fill=\"" + text_color + "\">" + name + "</text>"
        for col, name in months.items()
    ]
    lx = LEFT
    ly = TOP + 7 * STEP + 8
    legend = [
        "<text x=\"" + str(lx) + "\" y=\"" + str(ly + 10) +
        "\" font-size=\"9\" fill=\"" + text_color + "\">적음</text>"
    ]
    for idx, c in enumerate(["#ebedf0","#9be9a8","#40c463","#30a14e","#216e39"]):
        legend.append(
            "<rect x=\"" + str(lx + 28 + idx * STEP) + "\" y=\"" + str(ly) +
            "\" width=\"" + str(CELL) + "\" height=\"" + str(CELL) +
            "\" rx=\"2\" fill=\"" + c + "\"/>"
        )
    legend.append(
        "<text x=\"" + str(lx + 28 + 5 * STEP + 4) + "\" y=\"" + str(ly + 10) +
        "\" font-size=\"9\" fill=\"" + text_color + "\">많음</text>"
    )
    legend.append(
        "<text x=\"" + str(lx) + "\" y=\"" + str(ly + 28) +
        "\" font-size=\"9\" fill=\"" + text_color + "\">기준: " + NOW_STR + "</text>"
    )
    svg = (
        "<svg xmlns=\"http://www.w3.org/2000/svg\""
        " width=\"" + str(W) + "\" height=\"" + str(H) + "\">\n"
        + "".join(mlabels + dlabels + cells + legend) + "\n</svg>"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(svg)
    print("[done] " + output_path)

# ── 요일별 막대 ────────────────────────────────────────────────
DAY_KO = ["일","월","화","수","목","금","토"]

def make_weekday_bar_svg(daily, days, title, output_path,
                         text_color="#cccccc", title_color="#e0e0e0", small_color="#999999"):
    today  = date.today()
    counts = defaultdict(float)
    for i in range(days):
        d = today - timedelta(days=i)
        counts[(d.weekday() + 1) % 7] += daily.get(str(d), 0)
    max_val = max(counts.values()) if counts else 1
    BAR_H, BAR_GAP, LEFT, TOP, MAX_W = 22, 6, 28, 30, 280
    H = TOP + 7 * (BAR_H + BAR_GAP) + 34
    W = LEFT + MAX_W + 55
    bars = []
    for wd in range(7):
        val   = counts.get(wd, 0)
        bar_w = max(int((val / max_val) * MAX_W), 2)
        y     = TOP + wd * (BAR_H + BAR_GAP)
        bars.append(
            "<text x=\"" + str(LEFT - 4) + "\" y=\"" + str(y + BAR_H - 6) +
            "\" text-anchor=\"end\" font-size=\"12\" fill=\"" + text_color + "\">" +
            DAY_KO[wd] + "</text>"
        )
        bars.append(
            "<rect x=\"" + str(LEFT) + "\" y=\"" + str(y) +
            "\" width=\"" + str(bar_w) + "\" height=\"" + str(BAR_H) +
            "\" rx=\"3\" fill=\"" + color(val, max_val) + "\">"
            "<title>" + DAY_KO[wd] + ": " + str(round(val, 1)) + "점</title></rect>"
        )
        bars.append(
            "<text x=\"" + str(LEFT + bar_w + 5) + "\" y=\"" + str(y + BAR_H - 6) +
            "\" font-size=\"10\" fill=\"" + text_color + "\">" +
            str(round(val, 1)) + "</text>"
        )
    svg = (
        "<svg xmlns=\"http://www.w3.org/2000/svg\""
        " width=\"" + str(W) + "\" height=\"" + str(H) + "\">\n"
        "<text x=\"" + str(W // 2) + "\" y=\"18\" text-anchor=\"middle\""
        " font-size=\"13\" font-weight=\"bold\" fill=\"" + title_color + "\">" + title + "</text>\n"
        + "".join(bars)
        + "\n<text x=\"" + str(LEFT) + "\" y=\"" + str(H - 6) +
        "\" font-size=\"9\" fill=\"" + small_color + "\">기준: " + NOW_STR + "</text>"
        "\n</svg>"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(svg)
    print("[done] " + output_path)

# ── 메인 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    repos = get_repos()
    daily, repo_daily_files = collect_commits(repos)

    cache_path     = "scripts/heatmap_cache.json"
    rdf_cache_path = "scripts/repo_file_cache.json"

    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cached = json.load(f)
        for k, v in daily.items():
            cached[k] = cached.get(k, 0) + v
        daily = cached
    with open(cache_path, "w") as f:
        json.dump(dict(daily), f, indent=2)

    if os.path.exists(rdf_cache_path):
        with open(rdf_cache_path) as f:
            rdf_cached = json.load(f)
        for rname, dmap in repo_daily_files.items():
            if rname not in rdf_cached:
                rdf_cached[rname] = {}
            for k, v in dmap.items():
                rdf_cached[rname][k] = rdf_cached[rname].get(k, 0) + v
        repo_daily_files = rdf_cached
    with open(rdf_cache_path, "w") as f:
        json.dump(dict(repo_daily_files), f, indent=2)

    make_file_history_svg(repo_daily_files, "profile/file_history.svg")

    for days, label, key in [(7,"최근 1주","1w"),(14,"최근 2주","2w"),(30,"최근 1달","1m")]:
        make_weekday_bar_svg(daily, days, label + " 요일별 활동",
                             "profile/heatmap_" + key + "_dark.svg",  "#cccccc","#e0e0e0","#999999")
        make_weekday_bar_svg(daily, days, label + " 요일별 활동",
                             "profile/heatmap_" + key + "_light.svg", "#333333","#111111","#666666")

    make_annual_svg(daily, "profile/heatmap_dark.svg",  "#cccccc")
    make_annual_svg(daily, "profile/heatmap_light.svg", "#333333")

    print("[all done]")

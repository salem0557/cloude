#!/usr/bin/env python3
"""Weekly Riyadh IT job market report.

Reads the jobs collected by the job boards (Salem + Othman = IT roles in
Riyadh/Hail), computes stats for the last 7 days, and produces:

- a ready-to-paste LinkedIn post (English, with hashtags),
- a bar chart image (docs/report/chart.png) to attach to the post,
- docs/report/data/report.json consumed by the report page, keeping
  every past edition.

Runs every Sunday morning via .github/workflows/report.yml; posting to
LinkedIn stays manual (copy + paste) so no LinkedIn rules are broken.
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DOCS = Path(__file__).resolve().parent.parent / "docs"
REPORT_DIR = DOCS / "report"
DATA_FILE = REPORT_DIR / "data" / "report.json"

BOARDS = [
    DOCS / "data" / "jobs.json",          # Salem: IT management / data / DX
    DOCS / "othman" / "data" / "jobs.json",  # Othman: IT support / sysadmin
]

SITE = "https://salem0557.github.io/cloude/"
WINDOW_DAYS = 7
TOP_KEYWORDS = 6
TOP_COMPANIES = 3


def load_jobs():
    jobs = []
    for path in BOARDS:
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                jobs.extend(json.load(fh).get("jobs", []))
    return jobs


def in_window(job, start, end):
    return start <= (job.get("first_seen") or "") < end


def fmt_day(date):
    return date.strftime("%b %-d") if hasattr(date, "strftime") else date


def build_post(week_label, total, prev_total, top_kw, top_co):
    lines = [f"\U0001F4CA Riyadh IT job market — week of {week_label}", ""]
    trend = ""
    if prev_total:
        pct = round((total - prev_total) / prev_total * 100)
        arrow = "⬆️ up" if pct >= 0 else "⬇️ down"
        trend = f" — {arrow} {abs(pct)}% vs last week"
    lines.append(f"{total} new IT job openings appeared on Riyadh job boards "
                 f"this week{trend}.")
    if top_kw:
        lines += ["", "\U0001F525 Most in-demand areas:"]
        for n, (kw, count) in enumerate(top_kw, 1):
            lines.append(f"{n}. {kw} — {count} roles")
    if top_co:
        names = ", ".join(name for name, _ in top_co)
        lines += ["", f"\U0001F3E2 Actively hiring: {names}"]
    lines += [
        "",
        "I track this automatically with a free job board I built — "
        f"refreshed every few hours, no login needed:\n{SITE}",
        "",
        "Which of these areas are you hiring for — or moving into? "
        "Let me know in the comments \U0001F447",
        "",
        "#Riyadh #SaudiArabia #ITJobs #DigitalTransformation #TechJobs "
        "#Hiring #Vision2030",
    ]
    return "\n".join(lines)


def draw_chart(week_label, top_kw):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    labels = [kw for kw, _ in reversed(top_kw)]
    counts = [c for _, c in reversed(top_kw)]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    bars = ax.barh(labels, counts, color="#1f6feb")
    ax.bar_label(bars, padding=4, fontsize=11, fontweight="bold")
    ax.set_title(f"New Riyadh IT jobs by area — week of {week_label}",
                 fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("new job openings")
    ax.spines[["top", "right"]].set_visible(False)
    ax.margins(x=0.12)
    fig.text(0.99, 0.01, SITE, ha="right", fontsize=8, color="#66718a")
    fig.tight_layout()
    fig.savefig(REPORT_DIR / "chart.png")
    plt.close(fig)


def main():
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    prev_start = (today - timedelta(days=2 * WINDOW_DAYS)).isoformat()
    week_label = (f"{fmt_day(today - timedelta(days=WINDOW_DAYS - 1))} – "
                  f"{fmt_day(today)}")

    jobs = load_jobs()
    week = [j for j in jobs if in_window(j, start, end)]
    prev = [j for j in jobs if in_window(j, prev_start, start)]

    keywords = Counter(kw for j in week for kw in j.get("keywords", []))
    companies = Counter(j["company"] for j in week
                        if (j.get("company") or "").strip())
    top_kw = keywords.most_common(TOP_KEYWORDS)
    top_co = companies.most_common(TOP_COMPANIES)

    post = build_post(week_label, len(week), len(prev), top_kw, top_co)
    if top_kw:
        draw_chart(week_label, top_kw)

    report = {
        "week_label": week_label,
        "week_end": today.isoformat(),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(week),
        "prev_total": len(prev),
        "top_keywords": top_kw,
        "top_companies": top_co,
        "post_text": post,
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as fh:
            history = json.load(fh).get("reports", [])
    # Regenerating within the same week replaces that week's edition.
    history = [r for r in history if r.get("week_end") != report["week_end"]]
    history.insert(0, report)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump({"updated": report["generated"], "reports": history},
                  fh, ensure_ascii=False, indent=1)

    print(f"Report for {week_label}: {len(week)} new jobs "
          f"({len(prev)} previous week)\n")
    print(post)


if __name__ == "__main__":
    main()

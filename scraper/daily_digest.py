#!/usr/bin/env python3
"""Daily LinkedIn-routine digest, sent to Telegram.

Every morning this assembles a short to-do message:

- fresh LinkedIn posts collected in the last day (to reply to),
- one-click live LinkedIn search links for two rotating keywords,
- new jobs found in the last day on the Salem board,
- on Sundays, a reminder that the weekly market report is ready.

Needs two repository secrets (see README): TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID. Without them the message is printed instead of sent,
so the script is safe to run anywhere.
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

DOCS = Path(__file__).resolve().parent.parent / "docs"
SITE = "https://salem0557.github.io/cloude/"

KEYWORDS = [
    "IT Management",
    "IT Project Manager",
    "Data Acquisition",
    "Data Sharing",
    "Digital Transformation",
    "HR",
    "Saudi",
]

# Job-board keywords (Salem's profile) for the other-sites search links.
JOB_KEYWORDS = [
    "IT Management",
    "IT Project Manager",
    "Digital Transformation",
    "Data Management",
    "Program Manager",
    "Data Acquisition",
    "Data Sharing",
]

MAX_ITEMS = 5


def load(path):
    full = DOCS / path
    if full.exists():
        with open(full, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def esc(text, limit=70):
    text = (text or "").strip()
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return html.escape(text)


def live_search_url(keyword):
    q = quote(f'"{keyword}" Riyadh')
    return ("https://www.linkedin.com/search/results/content/"
            f"?keywords={q}&sortBy=%22date_posted%22&datePosted=%22past-24h%22")


def job_site_links(keyword):
    """One-click Riyadh searches on the sites that block automation —
    same links as the job board's manual-search row."""
    q = quote(keyword)
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    sites = [
        ("Google Jobs",
         f"https://www.google.com/search?q={q}%20jobs%20in%20Riyadh&ibp=htl;jobs"),
        ("Indeed", f"https://sa.indeed.com/jobs?q={q}&l=Riyadh"),
        ("Bayt", f"https://www.bayt.com/en/saudi-arabia/jobs/{slug}-jobs-in-riyadh/"),
        ("Naukrigulf", f"https://www.naukrigulf.com/{slug}-jobs-in-riyadh"),
        ("GulfTalent", f"https://www.gulftalent.com/saudi-arabia/jobs/title/{slug}"),
        ("Tanqeeb", f"https://www.tanqeeb.com/en/saudi-arabia/{slug}-jobs-in-riyadh"),
        ("Mihnati", f"https://www.mihnati.com/search/{slug}-jobs-in-riyadh"),
        ("Jooble", f"https://sa.jooble.org/jobs-{slug}/Riyadh"),
    ]
    return " | ".join(f'<a href="{url}">{html.escape(name)}</a>'
                      for name, url in sites)


def main():
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = [f"☀️ <b>Your LinkedIn plan — {now.strftime('%A, %b %d')}</b>"]

    posts = [p for p in load("posts/data/posts.json").get("posts", [])
             if (p.get("first_seen") or "") >= since]
    if posts:
        lines += ["", f"\U0001F4AC <b>{len(posts)} fresh post(s) to reply to:</b>"]
        for p in posts[:MAX_ITEMS]:
            author = f" — {esc(p['author'], 30)}" if p.get("author") else ""
            lines.append(f"• <a href=\"{p['url']}\">{esc(p['title'])}</a>{author}")
        if len(posts) > MAX_ITEMS:
            lines.append(f"  …and {len(posts) - MAX_ITEMS} more: "
                         f"<a href=\"{SITE}posts/\">posts page</a>")
    else:
        lines += ["", "\U0001F4AC No fresh posts collected overnight."]

    # Two rotating keywords a day keeps every keyword visited weekly.
    day = now.timetuple().tm_yday
    kw1 = KEYWORDS[(2 * day) % len(KEYWORDS)]
    kw2 = KEYWORDS[(2 * day + 1) % len(KEYWORDS)]
    lines += ["", "\U0001F50E <b>Live search (posts from last 24h):</b>",
              f"• <a href=\"{live_search_url(kw1)}\">{esc(kw1)}</a>"
              f" | <a href=\"{live_search_url(kw2)}\">{esc(kw2)}</a>",
              "Reply to 2-3 posts while they are still fresh — early "
              "comments get the views."]

    jobs = [j for j in load("data/jobs.json").get("jobs", [])
            if (j.get("first_seen") or "") >= since]
    if jobs:
        lines += ["", f"\U0001F4BC <b>{len(jobs)} new job(s) on your board:</b>"]
        for j in jobs[:MAX_ITEMS]:
            company = f" at {esc(j['company'], 30)}" if j.get("company") else ""
            lines.append(f"• <a href=\"{j['url']}\">{esc(j['title'])}</a>{company}")
        if len(jobs) > MAX_ITEMS:
            lines.append(f"  …and {len(jobs) - MAX_ITEMS} more: "
                         f"<a href=\"{SITE}\">job board</a>")

    job_kw = JOB_KEYWORDS[day % len(JOB_KEYWORDS)]
    lines += ["", f"\U0001F310 <b>Search the other job sites — "
              f"“{esc(job_kw)}” in Riyadh:</b>",
              job_site_links(job_kw)]

    if now.weekday() == 6:  # Sunday
        lines += ["", "\U0001F4CA <b>Weekly market report day!</b> Your "
                  f"ready-to-post report is at <a href=\"{SITE}report/\">the "
                  "report page</a> — copy it, attach the chart, and post it "
                  "this morning."]

    message = "\n".join(lines)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — dry run:\n")
        print(message)
        return

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=25,
    )
    if resp.status_code >= 400:
        print(f"Telegram error {resp.status_code}: {resp.text[:300]}",
              file=sys.stderr)
        sys.exit(1)
    print("Digest sent.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Riyadh Jobs Aggregator
======================

Fetches and displays job opportunities in Riyadh, Saudi Arabia and builds a
single browsable HTML page of links to:

  1. Featured live job listings (real postings, each title links to the
     application page).
  2. Search links for every major job site, pre-filtered to Riyadh.
  3. Career pages of major companies hiring in Riyadh.

Usage
-----
    python3 riyadh_jobs.py                       # build riyadh_jobs.html
    python3 riyadh_jobs.py -k "data scientist"   # tune the search keyword
    python3 riyadh_jobs.py -o out.html           # custom output file
    python3 riyadh_jobs.py --open                # build and open in browser

The program tries to fetch fresh listings from Indeed when run on a machine
with open internet access. If the network is unavailable or blocked, it falls
back to the bundled snapshot in data/featured_jobs.json so the page is always
populated.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import sys
import urllib.parse
import webbrowser

CITY = "Riyadh"
COUNTRY = "Saudi Arabia"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "data", "featured_jobs.json")

# ---------------------------------------------------------------------------
# Job sites: name -> function(keyword) -> Riyadh-filtered search URL
# ---------------------------------------------------------------------------
def _q(text: str) -> str:
    return urllib.parse.quote_plus(text)


JOB_SITES = {
    "LinkedIn Jobs": lambda k: f"https://www.linkedin.com/jobs/search/?keywords={_q(k)}&location={_q(CITY + ', ' + COUNTRY)}",
    "Indeed (Saudi Arabia)": lambda k: f"https://sa.indeed.com/jobs?q={_q(k)}&l={_q(CITY)}",
    "Bayt": lambda k: f"https://www.bayt.com/en/saudi-arabia/jobs/jobs-in-riyadh/?text={_q(k)}",
    "GulfTalent": lambda k: f"https://www.gulftalent.com/jobs/search?keywords={_q(k)}&location=riyadh",
    "Glassdoor": lambda k: f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={_q(k)}&locKeyword={_q(CITY)}",
    "Naukrigulf": lambda k: f"https://www.naukrigulf.com/{_q(k).replace('+', '-')}-jobs-in-riyadh-saudi-arabia",
    "Monster Gulf": lambda k: f"https://www.monstergulf.com/srp/results?query={_q(k)}&locations={_q(CITY)}",
    "Akhtaboot": lambda k: f"https://www.akhtaboot.com/en/saudi-arabia/jobs/riyadh?q={_q(k)}",
    "Tanqeeb": lambda k: f"https://saudi-arabia.tanqeeb.com/en/jobs/search?keywords={_q(k)}&q_location={_q(CITY)}",
    "DrJobPro": lambda k: f"https://www.drjobpro.com/jobs?searchKey={_q(k)}&city={_q(CITY)}&country=Saudi%20Arabia",
    "Laimoon": lambda k: f"https://saudi.laimoon.com/jobs/keyword/{_q(k)}/in-riyadh",
    "Indeed Glassdoor / Jooble": lambda k: f"https://jooble.org/SearchResult?rgns={_q(CITY)}&ukw={_q(k)}",
    "Jadarat (National Labor Gateway)": lambda k: "https://www.jadarat.sa/",
    "GOV Taqat / HRDF": lambda k: "https://www.taqat.sa/",
}

# ---------------------------------------------------------------------------
# Company career pages: major employers based in / hiring in Riyadh
# ---------------------------------------------------------------------------
COMPANY_SITES = {
    "Saudi Aramco": "https://www.aramco.com/en/careers",
    "SABIC": "https://www.sabic.com/en/careers",
    "stc (Saudi Telecom)": "https://careers.stc.com.sa/",
    "Saudi National Bank (SNB)": "https://www.alahli.com/en-us/about-us/Pages/careers.aspx",
    "Al Rajhi Bank": "https://www.alrajhibank.com.sa/en/careers",
    "Riyad Bank": "https://www.riyadbank.com/en/about-us/careers",
    "Public Investment Fund (PIF)": "https://www.pif.gov.sa/en/careers/",
    "NEOM": "https://www.neom.com/en-us/careers",
    "Qiddiya": "https://qiddiya.com/careers/",
    "ROSHN": "https://www.roshn.sa/en/careers",
    "Red Sea Global": "https://www.redseaglobal.com/en/careers",
    "Diriyah Company": "https://www.diriyah.sa/en/careers",
    "Saudia (Saudi Arabian Airlines)": "https://www.saudia.com/about-saudia/careers",
    "Riyadh Air": "https://www.riyadhair.com/careers",
    "Almarai": "https://www.almarai.com/en/careers/",
    "Mobily": "https://www.mobily.com.sa/en/careers",
    "Saudi Electricity Company (SEC)": "https://www.se.com.sa/en-us/Careers",
    "Ma'aden (Saudi Arabian Mining)": "https://www.maaden.com.sa/en/careers",
    "ACWA Power": "https://www.acwapower.com/en/careers/",
    "Elm Company": "https://elm.sa/en/careers",
    "Lucid Motors (KSA)": "https://lucidmotors.com/careers",
    "Bupa Arabia": "https://www.bupa.com.sa/en/careers",
    "King Faisal Specialist Hospital (KFSHRC)": "https://www.kfshrc.edu.sa/en/home/careers",
    "Dr. Sulaiman Al Habib (HMG)": "https://hmg.com.sa/en/careers/",
}


# ---------------------------------------------------------------------------
# Live fetch (best effort) + snapshot fallback
# ---------------------------------------------------------------------------
def fetch_live_indeed(keyword: str, limit: int = 25):
    """Best-effort scrape of sa.indeed.com. Returns [] on any failure."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    url = f"https://sa.indeed.com/jobs?q={_q(keyword)}&l={_q(CITY)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        for card in soup.select("div.job_seen_beacon, a.tapItem")[:limit]:
            title_el = card.select_one("h2 a, h2 span[title], a.jcs-JobTitle")
            company_el = card.select_one('span[data-testid="company-name"], span.companyName')
            link_el = card.select_one("h2 a, a.jcs-JobTitle")
            if not title_el:
                continue
            href = link_el.get("href", "") if link_el else ""
            if href and href.startswith("/"):
                href = "https://sa.indeed.com" + href
            jobs.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "—",
                "location": CITY,
                "posted": "",
                "type": "",
                "category": "Live results",
                "url": href or url,
            })
        return jobs
    except Exception:
        return []


def load_snapshot():
    try:
        with open(SNAPSHOT, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"jobs": [], "captured": "", "source": "n/a"}


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    return html.escape(s or "")


def render_html(jobs, source_label, captured, keyword, live: bool) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group featured jobs by category
    by_cat = {}
    for j in jobs:
        by_cat.setdefault(j.get("category", "Other"), []).append(j)

    job_cards = []
    for cat, items in by_cat.items():
        rows = []
        for j in items:
            meta = " · ".join(filter(None, [_esc(j.get("type")), _esc(j.get("posted"))]))
            rows.append(f"""
            <li class="job">
              <a class="job-title" href="{_esc(j['url'])}" target="_blank" rel="noopener">{_esc(j['title'])}</a>
              <div class="job-meta"><span class="company">{_esc(j.get('company','—'))}</span>
              <span class="loc">{_esc(j.get('location', CITY))}</span>{(' · ' + meta) if meta else ''}</div>
            </li>""")
        job_cards.append(f"""
        <section class="cat-block">
          <h3>{_esc(cat)} <span class="count">{len(items)}</span></h3>
          <ul class="job-list">{''.join(rows)}</ul>
        </section>""")

    site_rows = []
    for name, fn in JOB_SITES.items():
        site_rows.append(
            f'<a class="link-chip" href="{_esc(fn(keyword))}" target="_blank" rel="noopener">{_esc(name)}</a>'
        )

    company_rows = []
    for name, url in COMPANY_SITES.items():
        company_rows.append(
            f'<a class="link-chip company" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(name)}</a>'
        )

    status_badge = (
        '<span class="badge live">● live fetch</span>'
        if live
        else '<span class="badge snap">● bundled snapshot</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jobs in Riyadh, Saudi Arabia</title>
<style>
  :root {{
    --bg:#0f1419; --card:#1a2129; --ink:#e6edf3; --muted:#8b98a5;
    --accent:#1f9d55; --accent2:#2da44e; --chip:#222c36; --border:#2d3742;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         background:var(--bg); color:var(--ink); line-height:1.5; }}
  header {{ padding:32px 24px 20px; background:linear-gradient(135deg,#0b3d2e,#0f1419);
            border-bottom:1px solid var(--border); }}
  header h1 {{ margin:0 0 6px; font-size:26px; }}
  header p {{ margin:0; color:var(--muted); font-size:14px; }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:24px; }}
  h2 {{ font-size:19px; margin:34px 0 14px; border-left:3px solid var(--accent2); padding-left:10px; }}
  .badge {{ font-size:12px; padding:2px 9px; border-radius:20px; margin-left:10px; vertical-align:middle; }}
  .badge.live {{ background:#0d3320; color:#3fb950; border:1px solid #2da44e; }}
  .badge.snap {{ background:#2a2410; color:#d29922; border:1px solid #9e7912; }}
  .cat-block {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
               padding:14px 18px; margin-bottom:14px; }}
  .cat-block h3 {{ margin:4px 0 10px; font-size:15px; color:#cdd9e5; }}
  .count {{ background:var(--chip); color:var(--muted); border-radius:12px; font-size:12px;
            padding:1px 8px; margin-left:6px; }}
  .job-list {{ list-style:none; margin:0; padding:0; }}
  .job {{ padding:8px 0; border-bottom:1px solid var(--border); }}
  .job:last-child {{ border-bottom:none; }}
  .job-title {{ color:#58a6ff; text-decoration:none; font-weight:600; font-size:15px; }}
  .job-title:hover {{ text-decoration:underline; }}
  .job-meta {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  .company {{ color:#adbac7; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:9px; }}
  .link-chip {{ display:inline-block; background:var(--chip); color:var(--ink); text-decoration:none;
               padding:8px 14px; border-radius:8px; border:1px solid var(--border); font-size:14px;
               transition:all .15s; }}
  .link-chip:hover {{ border-color:var(--accent2); color:#fff; background:#243a30; }}
  .link-chip.company {{ }}
  footer {{ color:var(--muted); font-size:12px; text-align:center; padding:30px 0 50px; }}
  a {{ color:#58a6ff; }}
</style>
</head>
<body>
<header>
  <h1>🇸🇦 Jobs in {CITY}, {COUNTRY}</h1>
  <p>Search keyword: <strong>{_esc(keyword)}</strong> &nbsp;·&nbsp; Generated {now} &nbsp;·&nbsp; {len(jobs)} featured listings</p>
</header>
<div class="wrap">

  <h2>Featured job listings {status_badge}</h2>
  <p style="color:var(--muted);font-size:13px;margin-top:-6px;">
     Source: {_esc(source_label)}{(' · captured ' + _esc(captured)) if captured else ''}.
     Click any title to open the application page.</p>
  {''.join(job_cards) if job_cards else '<p>No listings available.</p>'}

  <h2>Search all job sites — pre-filtered to {CITY}</h2>
  <p style="color:var(--muted);font-size:13px;margin-top:-6px;">
     Each link runs a "<strong>{_esc(keyword)}</strong>" search in {CITY} on that site.</p>
  <div class="chips">{''.join(site_rows)}</div>

  <h2>Company career pages</h2>
  <p style="color:var(--muted);font-size:13px;margin-top:-6px;">
     Official careers portals of major employers based in / hiring in {CITY}.</p>
  <div class="chips">{''.join(company_rows)}</div>

</div>
<footer>
  Built by riyadh_jobs.py · Featured data from Indeed · Re-run with internet access to refresh live listings.
</footer>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Build an HTML page of Riyadh job links.")
    parser.add_argument("-k", "--keyword", default="jobs",
                        help="Search keyword/title (default: jobs)")
    parser.add_argument("-o", "--output", default=os.path.join(HERE, "riyadh_jobs.html"),
                        help="Output HTML file (default: riyadh_jobs.html)")
    parser.add_argument("--no-live", action="store_true",
                        help="Skip live fetch; use bundled snapshot only")
    parser.add_argument("--open", action="store_true", dest="open_browser",
                        help="Open the generated page in the default browser")
    args = parser.parse_args(argv)

    live = False
    jobs = []
    source_label = ""
    captured = ""

    if not args.no_live:
        print(f"Fetching live listings for '{args.keyword}' in {CITY}...", file=sys.stderr)
        jobs = fetch_live_indeed(args.keyword)
        if jobs:
            live = True
            source_label = "Indeed (live fetch)"
            captured = _dt.datetime.now().strftime("%Y-%m-%d")
            print(f"  -> {len(jobs)} live listings.", file=sys.stderr)
        else:
            print("  -> live fetch unavailable/blocked; using bundled snapshot.", file=sys.stderr)

    if not jobs:
        snap = load_snapshot()
        jobs = snap.get("jobs", [])
        source_label = snap.get("source", "snapshot")
        captured = snap.get("captured", "")

    page = render_html(jobs, source_label, captured, args.keyword, live)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"Wrote {args.output}  ({len(jobs)} featured jobs, "
          f"{len(JOB_SITES)} job sites, {len(COMPANY_SITES)} company pages)")

    if args.open_browser:
        webbrowser.open("file://" + os.path.abspath(args.output))


if __name__ == "__main__":
    main()

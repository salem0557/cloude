#!/usr/bin/env python3
"""
Riyadh Jobs Aggregator
======================

A search page for jobs in Riyadh, Saudi Arabia.

Run the local server, open it in your browser, and type a query (e.g. "Data").
The page searches **on the page** — it filters a bundled set of real Riyadh
listings AND tries a live fetch from Indeed, then shows the merged results
inline. Clicking any result opens the outside site to apply. It also offers
one-click links to run the same search on every other major job board and the
career pages of major Riyadh employers.

Usage
-----
    python3 riyadh_jobs.py                 # start server on http://localhost:8000
    python3 riyadh_jobs.py serve -p 8080   # custom port
    python3 riyadh_jobs.py serve --no-live # disable live fetch (bundled only)
    python3 riyadh_jobs.py build           # write a static offline riyadh_jobs.html

Live fetch needs:  pip install requests beautifulsoup4
If the network is blocked, search still works over the bundled snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CITY = "Riyadh"
COUNTRY = "Saudi Arabia"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "data", "featured_jobs.json")

# ---------------------------------------------------------------------------
# Link directories. Each job site has a URL template with a {q} token and a
# mode: "q"=encoded query param, "slug"=hyphenated path, "fixed"=no keyword.
# Link URLs are built in the browser (see JS), so this is the single source.
# ---------------------------------------------------------------------------
JOB_SITES = [
    ("LinkedIn Jobs", "https://www.linkedin.com/jobs/search/?keywords={q}&location=Riyadh%2C%20Saudi%20Arabia", "q"),
    ("Indeed (Saudi Arabia)", "https://sa.indeed.com/jobs?q={q}&l=Riyadh", "q"),
    ("Bayt", "https://www.bayt.com/en/saudi-arabia/jobs/jobs-in-riyadh/?text={q}", "q"),
    ("GulfTalent", "https://www.gulftalent.com/jobs/search?keywords={q}&location=riyadh", "q"),
    ("Glassdoor", "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locKeyword=Riyadh", "q"),
    ("Monster Gulf", "https://www.monstergulf.com/srp/results?query={q}&locations=Riyadh", "q"),
    ("Akhtaboot", "https://www.akhtaboot.com/en/saudi-arabia/jobs/riyadh?q={q}", "q"),
    ("Tanqeeb", "https://saudi-arabia.tanqeeb.com/en/jobs/search?keywords={q}&q_location=Riyadh", "q"),
    ("DrJobPro", "https://www.drjobpro.com/jobs?searchKey={q}&city=Riyadh&country=Saudi%20Arabia", "q"),
    ("Jooble", "https://jooble.org/SearchResult?rgns=Riyadh&ukw={q}", "q"),
    ("Naukrigulf", "https://www.naukrigulf.com/{q}-jobs-in-riyadh-saudi-arabia", "slug"),
    ("Laimoon", "https://saudi.laimoon.com/jobs/keyword/{q}/in-riyadh", "slug"),
    ("Jadarat (National Gateway)", "https://www.jadarat.sa/", "fixed"),
    ("Taqat / HRDF", "https://www.taqat.sa/", "fixed"),
]

COMPANY_SITES = [
    ("Saudi Aramco", "https://www.aramco.com/en/careers"),
    ("SABIC", "https://www.sabic.com/en/careers"),
    ("stc (Saudi Telecom)", "https://careers.stc.com.sa/"),
    ("Saudi National Bank (SNB)", "https://www.alahli.com/en-us/about-us/Pages/careers.aspx"),
    ("Al Rajhi Bank", "https://www.alrajhibank.com.sa/en/careers"),
    ("Riyad Bank", "https://www.riyadbank.com/en/about-us/careers"),
    ("Public Investment Fund (PIF)", "https://www.pif.gov.sa/en/careers/"),
    ("NEOM", "https://www.neom.com/en-us/careers"),
    ("Qiddiya", "https://qiddiya.com/careers/"),
    ("ROSHN", "https://www.roshn.sa/en/careers"),
    ("Red Sea Global", "https://www.redseaglobal.com/en/careers"),
    ("Diriyah Company", "https://www.diriyah.sa/en/careers"),
    ("Saudia (Saudi Arabian Airlines)", "https://www.saudia.com/about-saudia/careers"),
    ("Riyadh Air", "https://www.riyadhair.com/careers"),
    ("Almarai", "https://www.almarai.com/en/careers/"),
    ("Mobily", "https://www.mobily.com.sa/en/careers"),
    ("Saudi Electricity Company (SEC)", "https://www.se.com.sa/en-us/Careers"),
    ("Ma'aden (Saudi Arabian Mining)", "https://www.maaden.com.sa/en/careers"),
    ("ACWA Power", "https://www.acwapower.com/en/careers/"),
    ("Elm Company", "https://elm.sa/en/careers"),
    ("Lucid Motors (KSA)", "https://lucidmotors.com/careers"),
    ("Bupa Arabia", "https://www.bupa.com.sa/en/careers"),
    ("King Faisal Specialist Hospital (KFSHRC)", "https://www.kfshrc.edu.sa/en/home/careers"),
    ("Dr. Sulaiman Al Habib (HMG)", "https://hmg.com.sa/en/careers/"),
]


# ---------------------------------------------------------------------------
# Data: snapshot + filtering + live fetch
# ---------------------------------------------------------------------------
def load_snapshot():
    try:
        with open(SNAPSHOT, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"jobs": [], "captured": "", "source": "n/a"}


_SNAP = load_snapshot()
_SNAP_JOBS = _SNAP.get("jobs", [])


def filter_jobs(jobs, query):
    """Keep jobs where every whitespace token of query is a substring of the
    job's title + company + category (case-insensitive). Empty query -> all."""
    q = (query or "").strip().lower()
    if not q:
        return list(jobs)
    tokens = q.split()
    out = []
    for j in jobs:
        hay = " ".join([
            str(j.get("title", "")), str(j.get("company", "")),
            str(j.get("category", "")), str(j.get("type", "")),
        ]).lower()
        if all(t in hay for t in tokens):
            out.append(j)
    return out


def fetch_live_indeed(query, limit=25, timeout=8):
    """Best-effort live scrape of sa.indeed.com. Returns [] on any failure."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    kw = query.strip() or "jobs"
    url = f"https://sa.indeed.com/jobs?q={urllib.parse.quote_plus(kw)}&l={urllib.parse.quote_plus(CITY)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
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
                "location": CITY, "posted": "", "type": "",
                "category": "Live from Indeed", "url": href or url,
            })
        return jobs
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Front-end (shared by server + static build). Tokens are filled with .replace.
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jobs in Riyadh, Saudi Arabia</title>
<style>
  :root{--bg:#0f1419;--card:#1a2129;--ink:#e6edf3;--muted:#8b98a5;--accent:#2da44e;
        --chip:#222c36;--border:#2d3742;--blue:#58a6ff;}
  *{box-sizing:border-box;}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--ink);line-height:1.5;}
  /* Sticky search bar at the very top */
  .topbar{position:sticky;top:0;z-index:20;background:linear-gradient(135deg,#0b3d2e,#0f1419);
          border-bottom:1px solid var(--border);padding:18px 24px;}
  .topbar h1{margin:0 0 12px;font-size:20px;}
  .topbar h1 small{color:var(--muted);font-weight:400;font-size:13px;}
  .searchrow{display:flex;gap:10px;max-width:760px;}
  #q{flex:1;padding:13px 16px;font-size:16px;border-radius:10px;border:1px solid var(--border);
     background:#0d1117;color:var(--ink);outline:none;}
  #q:focus{border-color:var(--accent);}
  #go{padding:13px 22px;font-size:15px;font-weight:600;border:none;border-radius:10px;
      background:var(--accent);color:#fff;cursor:pointer;}
  #go:hover{background:#3cb85f;}
  .wrap{max-width:1040px;margin:0 auto;padding:22px 24px 60px;}
  h2{font-size:18px;margin:30px 0 6px;border-left:3px solid var(--accent);padding-left:10px;}
  .hint{color:var(--muted);font-size:13px;margin:0 0 14px;}
  .status{color:var(--muted);font-size:13px;min-height:18px;margin:6px 0;}
  .cat-block{background:var(--card);border:1px solid var(--border);border-radius:10px;
             padding:12px 18px;margin-bottom:14px;}
  .cat-block h3{margin:4px 0 8px;font-size:14px;color:#cdd9e5;}
  .count{background:var(--chip);color:var(--muted);border-radius:12px;font-size:12px;padding:1px 8px;margin-left:6px;}
  .job-list{list-style:none;margin:0;padding:0;}
  .job{padding:8px 0;border-bottom:1px solid var(--border);}
  .job:last-child{border-bottom:none;}
  .job-title{color:var(--blue);text-decoration:none;font-weight:600;font-size:15px;}
  .job-title:hover{text-decoration:underline;}
  .job-meta{color:var(--muted);font-size:13px;margin-top:2px;}
  .company{color:#adbac7;}
  .chips{display:flex;flex-wrap:wrap;gap:9px;}
  .link-chip{display:inline-block;background:var(--chip);color:var(--ink);text-decoration:none;
             padding:8px 14px;border-radius:8px;border:1px solid var(--border);font-size:14px;transition:all .15s;}
  .link-chip:hover{border-color:var(--accent);color:#fff;background:#243a30;}
  .empty{color:var(--muted);font-style:italic;padding:6px 0;}
  .badge{font-size:11px;padding:2px 8px;border-radius:20px;margin-left:8px;vertical-align:middle;}
  .badge.live{background:#0d3320;color:#3fb950;border:1px solid #2da44e;}
  .spin{display:inline-block;width:12px;height:12px;border:2px solid #2da44e44;border-top-color:#2da44e;
        border-radius:50%;animation:s .7s linear infinite;vertical-align:middle;margin-right:6px;}
  @keyframes s{to{transform:rotate(360deg);}}
</style>
</head>
<body>
<div class="topbar">
  <h1>🇸🇦 Jobs in Riyadh, Saudi Arabia <small>__MODE_LABEL__</small></h1>
  <div class="searchrow">
    <input id="q" type="text" placeholder="Search jobs (e.g. Data, Nurse, Accountant)…" autocomplete="off">
    <button id="go">Search</button>
  </div>
</div>

<div class="wrap">
  <div class="status" id="status"></div>

  <h2>Results <span id="rescount" class="count">0</span></h2>
  <p class="hint">Matches from listings, shown here on the page. Click a title to open the site and apply.</p>
  <div id="results"></div>

  <h2>Run this search on other job sites</h2>
  <p class="hint">These open the same search on each board in a new tab.</p>
  <div class="chips" id="sitelinks"></div>

  <h2>Company career pages</h2>
  <p class="hint">Official careers portals of major employers in Riyadh.</p>
  <div class="chips" id="companylinks"></div>
</div>

<script>
const MODE = "__MODE__";                 // "server" or "static"
const SITES = __SITES__;                  // [[name, template, kind], ...]
const COMPANIES = __COMPANIES__;          // [[name, url], ...]
const EMBED_JOBS = __JOBS__;              // used in static mode

function slugify(s){return s.trim().toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'')||'jobs';}
function buildSiteUrl(tpl, kind, q){
  if(kind==='fixed') return tpl;
  if(kind==='slug')  return tpl.replace('{q}', slugify(q));
  return tpl.replace('{q}', encodeURIComponent(q.trim()));
}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}

function renderLinks(q){
  document.getElementById('sitelinks').innerHTML = SITES.map(([n,t,k])=>
    `<a class="link-chip" target="_blank" rel="noopener" href="${esc(buildSiteUrl(t,k,q))}">${esc(n)}</a>`).join('');
  document.getElementById('companylinks').innerHTML = COMPANIES.map(([n,u])=>
    `<a class="link-chip" target="_blank" rel="noopener" href="${esc(u)}">${esc(n)}</a>`).join('');
}

function jobCard(j){
  const meta=[j.type,j.posted].filter(Boolean).join(' · ');
  return `<li class="job"><a class="job-title" target="_blank" rel="noopener" href="${esc(j.url)}">${esc(j.title)}</a>
    <div class="job-meta"><span class="company">${esc(j.company||'—')}</span> · ${esc(j.location||'Riyadh')}${meta?(' · '+esc(meta)):''}</div></li>`;
}
function groupByCategory(jobs){
  const m={}; jobs.forEach(j=>{(m[j.category||'Other']=m[j.category||'Other']||[]).push(j);}); return m;
}
function renderJobs(jobs){
  const el=document.getElementById('results');
  document.getElementById('rescount').textContent=jobs.length;
  if(!jobs.length){el.innerHTML='<p class="empty">No matching listings. Try a broader keyword, or use the job-site links below.</p>';return;}
  const g=groupByCategory(jobs);
  el.innerHTML=Object.keys(g).map(cat=>
    `<section class="cat-block"><h3>${esc(cat)} <span class="count">${g[cat].length}</span></h3>
     <ul class="job-list">${g[cat].map(jobCard).join('')}</ul></section>`).join('');
}

function filterLocal(jobs,q){
  q=(q||'').trim().toLowerCase(); if(!q) return jobs.slice();
  const toks=q.split(/\s+/);
  return jobs.filter(j=>{const h=((j.title||'')+' '+(j.company||'')+' '+(j.category||'')+' '+(j.type||'')).toLowerCase();
    return toks.every(t=>h.includes(t));});
}

let seq=0;
async function doSearch(q){
  renderLinks(q);
  const status=document.getElementById('status');
  if(MODE==='static'){
    renderJobs(filterLocal(EMBED_JOBS,q));
    status.textContent='Searched '+EMBED_JOBS.length+' bundled listings (offline mode).';
    return;
  }
  const my=++seq;
  // Phase 1: instant bundled filter
  status.innerHTML='Searching bundled listings…';
  let bundled=[];
  try{const r=await fetch('/api/search?live=0&q='+encodeURIComponent(q));const d=await r.json();bundled=d.jobs||[];}catch(e){}
  if(my!==seq) return;
  renderJobs(bundled);
  // Phase 2: live fetch, merged on top
  status.innerHTML='<span class="spin"></span>Fetching live results from Indeed…';
  let live=[];
  try{const r=await fetch('/api/search?live=1&q='+encodeURIComponent(q));const d=await r.json();live=d.jobs||[];}catch(e){}
  if(my!==seq) return;
  // de-dupe by title+company
  const seen=new Set(bundled.map(j=>(j.title+'|'+j.company).toLowerCase()));
  const extra=live.filter(j=>!seen.has((j.title+'|'+j.company).toLowerCase()));
  renderJobs(extra.concat(bundled));
  status.textContent = (extra.length? (extra.length+' live + ') : '') + bundled.length +
                       ' bundled listings.' + (extra.length? '' : ' (Live fetch returned nothing — network may be blocked.)');
}

let t;
const input=document.getElementById('q');
input.addEventListener('input',()=>{clearTimeout(t);t=setTimeout(()=>doSearch(input.value),350);});
input.addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(t);doSearch(input.value);}});
document.getElementById('go').addEventListener('click',()=>{clearTimeout(t);doSearch(input.value);});
doSearch('');   // initial load shows everything
</script>
</body>
</html>"""


def build_page(mode, jobs_for_static):
    mode_label = ("live + bundled search" if mode == "server" else "offline · bundled search")
    return (PAGE_TEMPLATE
            .replace("__MODE__", mode)
            .replace("__MODE_LABEL__", mode_label)
            .replace("__SITES__", json.dumps(JOB_SITES))
            .replace("__COMPANIES__", json.dumps(COMPANY_SITES))
            .replace("__JOBS__", json.dumps(jobs_for_static)))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    live_enabled = True

    def log_message(self, *args):  # quieter console
        pass

    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send(200, build_page("server", []), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/search":
            params = urllib.parse.parse_qs(parsed.query)
            q = (params.get("q", [""])[0])
            live = params.get("live", ["0"])[0] == "1"
            if live:
                jobs = fetch_live_indeed(q) if self.live_enabled else []
            else:
                jobs = filter_jobs(_SNAP_JOBS, q)
            self._send(200, json.dumps({"jobs": jobs, "live": live, "query": q}),
                       "application/json; charset=utf-8")
            return
        self._send(404, "Not found", "text/plain; charset=utf-8")


def serve(port, no_live, open_browser=True):
    Handler.live_enabled = not no_live
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    url = f"http://localhost:{port}/"
    print(f"Riyadh Jobs server running at {url}")
    print(f"  · {len(_SNAP_JOBS)} bundled listings | live fetch: {'OFF' if no_live else 'ON'}")
    print("  · Press Ctrl+C to stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Riyadh jobs search page (live + bundled).")
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="Run the local search server (default)")
    p_serve.add_argument("-p", "--port", type=int, default=8000)
    p_serve.add_argument("--no-live", action="store_true", help="Disable live fetch")
    p_serve.add_argument("--no-open", action="store_true", help="Do not auto-open the browser")

    p_build = sub.add_parser("build", help="Write a static offline HTML file")
    p_build.add_argument("-o", "--output", default=os.path.join(HERE, "riyadh_jobs.html"))

    args = parser.parse_args(argv)

    if args.cmd == "build":
        page = build_page("static", _SNAP_JOBS)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(page)
        print(f"Wrote {args.output} (static, {len(_SNAP_JOBS)} bundled listings, "
              f"client-side search).")
        return

    # default: serve
    port = getattr(args, "port", 8000)
    no_live = getattr(args, "no_live", False)
    no_open = getattr(args, "no_open", False)
    serve(port, no_live, open_browser=not no_open)


if __name__ == "__main__":
    main()

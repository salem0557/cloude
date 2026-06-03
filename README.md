# Riyadh Jobs Aggregator

A small Python program that fetches jobs in **Riyadh, Saudi Arabia** and builds a
single browsable **HTML page** of links from every major job site and company
career page.

The generated page (`riyadh_jobs.html`) has three sections:

1. **Featured job listings** — real, current postings where each title links
   straight to the application page.
2. **Search all job sites** — one-click search links (pre-filtered to Riyadh)
   for LinkedIn, Indeed, Bayt, GulfTalent, Glassdoor, Naukrigulf, Monster Gulf,
   Akhtaboot, Tanqeeb, DrJobPro, Laimoon, Jooble, and the Saudi national
   gateways (Jadarat / Taqat).
3. **Company career pages** — official careers portals of 24 major employers
   based in or hiring in Riyadh (Aramco, SABIC, stc, SNB, Al Rajhi, PIF, NEOM,
   Qiddiya, ROSHN, Red Sea Global, Riyadh Air, Saudia, Almarai, Ma'aden, ACWA
   Power, KFSHRC, and more).

## Usage

```bash
python3 riyadh_jobs.py                       # build riyadh_jobs.html
python3 riyadh_jobs.py -k "data scientist"   # tune the search keyword
python3 riyadh_jobs.py -o out.html           # custom output path
python3 riyadh_jobs.py --open                # build and open in a browser
python3 riyadh_jobs.py --no-live             # skip live fetch, use snapshot
```

Then open `riyadh_jobs.html` in any browser.

## How it fetches data

The program is **hybrid**:

- **Live fetch** — when run on a machine with open internet access, it scrapes
  fresh listings from Indeed (Saudi Arabia). Requires `requests` and
  `beautifulsoup4`:
  ```bash
  pip install requests beautifulsoup4
  ```
- **Snapshot fallback** — if the network is blocked or the scrape fails, it
  falls back to a bundled snapshot of real Indeed listings in
  `data/featured_jobs.json`, so the page is always populated.
- **Search + company links** — always generated locally, so they work with no
  network and never go stale.

## Why the hybrid design?

Major job boards (LinkedIn, Indeed, Bayt, GulfTalent…) use bot protection and
frequently block direct scraping or require API keys. Generating pre-filtered
**search links** is therefore the reliable way to cover "all job sites," while
the live fetch + bundled snapshot give you actual clickable listings on top.

## Files

| File | Purpose |
|------|---------|
| `riyadh_jobs.py` | Main program — fetches data and builds the HTML page |
| `data/featured_jobs.json` | Snapshot of real Riyadh listings (fallback seed) |
| `riyadh_jobs.html` | Generated output (open in a browser) |

## Refreshing the snapshot

Re-run `python3 riyadh_jobs.py` on a machine with internet access; live results
replace the snapshot automatically for that run. To update the saved snapshot
itself, edit `data/featured_jobs.json`.

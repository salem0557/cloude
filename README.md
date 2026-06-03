# Riyadh Jobs Aggregator

A **search page for jobs in Riyadh, Saudi Arabia**. A search bar sits at the top
of the page — type a query (e.g. `Data`) and matching jobs appear **inline on
the page**. Clicking a result opens the outside site so you can apply. The page
also gives one-click links to run the same search on every other major job
board and the career pages of major Riyadh employers.

## How searching works (hybrid)

When you search, the page does two things and merges the results:

1. **Bundled search (instant, offline):** filters a snapshot of ~95 real Riyadh
   listings (`data/featured_jobs.json`) and shows matches immediately.
2. **Live fetch (when online):** queries Indeed (Saudi Arabia) server-side and
   merges any fresh results on top, tagged *“Live from Indeed.”*

If the network is blocked or the live fetch returns nothing, search still works
over the bundled listings — so the page is never empty.

## Quick start

```bash
# 1. (optional, enables the live-fetch half)
pip install requests beautifulsoup4

# 2. start the local server — opens your browser automatically
python3 riyadh_jobs.py
```

Your browser opens `http://localhost:8000/`. Type in the search bar; results
update on the page as you type. Click any job title to open the site and apply.

### Commands

```bash
python3 riyadh_jobs.py                  # serve on http://localhost:8000 (default)
python3 riyadh_jobs.py serve -p 8080    # custom port
python3 riyadh_jobs.py serve --no-live  # bundled-only (skip live fetch)
python3 riyadh_jobs.py serve --no-open  # don't auto-open the browser
python3 riyadh_jobs.py build            # write a static offline riyadh_jobs.html
```

`build` produces a single HTML file you can double-click — it still has the
search bar and searches the bundled listings client-side (no server, no live
fetch).

## What's on the page

- **Results** — merged live + bundled listings, grouped by category. Each title
  links to the application page on the source site.
- **Run this search on other job sites** — opens the same query on LinkedIn,
  Indeed, Bayt, GulfTalent, Glassdoor, Monster Gulf, Akhtaboot, Tanqeeb,
  DrJobPro, Jooble, Naukrigulf, Laimoon, plus the Saudi national gateways
  (Jadarat / Taqat). These open in a new tab because those sites block in-page
  fetching from a browser.
- **Company career pages** — official portals of 24 major Riyadh employers
  (Aramco, SABIC, stc, SNB, Al Rajhi, PIF, NEOM, Qiddiya, ROSHN, Red Sea Global,
  Riyadh Air, Saudia, Almarai, Ma'aden, ACWA Power, KFSHRC, and more).

## Why can't the page fetch every site live in the browser?

LinkedIn, Indeed, Bayt, GulfTalent and similar boards block cross-site browser
requests (CORS) and bots. The live fetch therefore runs **server-side** inside
`riyadh_jobs.py`. For boards that can't be fetched, the page gives you a
pre-filled search link instead — one click runs your exact query on that site.

## Files

| File | Purpose |
|------|---------|
| `riyadh_jobs.py` | Server + search API + page; also builds the static file |
| `data/featured_jobs.json` | Snapshot of ~95 real Riyadh listings (bundled search) |
| `riyadh_jobs.html` | Optional static offline build (`python3 riyadh_jobs.py build`) |

To refresh the bundled snapshot, edit `data/featured_jobs.json`.

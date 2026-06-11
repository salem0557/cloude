# Riyadh IT Jobs — daily job search

Two job boards, updated automatically twice a day (about 06:23 and 15:23
Riyadh time) with jobs in **Riyadh, Saudi Arabia**:

- **Salem** — `https://salem0557.github.io/cloude/` — keywords: IT
  Management, IT Project Manager, Digital Transformation, Data Management,
  Program Manager, Data Acquisition, Data Sharing
- **Othman** — `https://salem0557.github.io/cloude/othman/` — keywords: IT
  Support, Help Desk, Technical Support, IT Specialist, System
  Administrator, IT Fresh Graduate
- **Omer** — `https://salem0557.github.io/cloude/omer/` — keywords: Supply
  Chain, Procurement, Logistics, Operations Manager, Mechanical Engineer,
  Maintenance Engineer, Facilities Management

Sources searched: **LinkedIn, Akhtaboot, GulfTalent, Tanqeeb** (and Jooble
once an API key is configured).

All jobs found are stored in [`docs/data/jobs.json`](docs/data/jobs.json) and
shown on a website where you can filter, search, and click through to apply.
Jobs are never deleted — newly found jobs are flagged **NEW**.

Source status (verified through live workflow runs):

- **LinkedIn** — works, main source of results.
- **Akhtaboot** — works; its keyword search is limited, so results are
  filtered for relevance from its newest Riyadh listings.
- **GulfTalent, Tanqeeb** — currently return 403 to GitHub's servers; probed
  once per run and picked up automatically if they ever unblock.
- **Jooble** — public site returns 403, but it offers a free official API:
  request a key at <https://jooble.org/api/about>, then add it as a repository
  secret named `JOOBLE_API_KEY` (Settings → Secrets and variables → Actions).
  The daily search starts using the API automatically.
- **Mihnati** — loads job listings only via JavaScript, impossible to read
  from plain HTTP; available as a manual link on the site.
- **Google Jobs, Indeed, Bayt, Naukrigulf** — no free automated access;
  one-click manual search links are on the website.

## One-time setup

1. **Merge this branch to `main`** (the daily schedule only runs from the
   default branch).
2. **Enable the website**: go to the repository **Settings → Pages**, under
   *Build and deployment* choose **Deploy from a branch**, select branch
   `main` and folder `/docs`, then save. After a minute the site will be live
   at `https://salem0557.github.io/cloude/`.

## Run it manually

Go to the **Actions** tab → **Daily Riyadh job search** → **Run workflow**.
The job list updates within a couple of minutes.

## Change keywords or city

Edit the `PROFILES` dict (or `CITY`) at the top of
[`scraper/search_jobs.py`](scraper/search_jobs.py) and commit.

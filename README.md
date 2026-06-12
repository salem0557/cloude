# Riyadh IT Jobs — daily job search

Three job boards, updated automatically every 5 hours with jobs in
**Riyadh and Hail, Saudi Arabia** — plus a **LinkedIn posts page**
(refreshed every 2 hours) for finding posts to reply to, described
[below](#linkedin-posts-page--posts-to-reply-to).

- **Salem** — `https://salem0557.github.io/cloude/` — keywords: IT
  Management, IT Project Manager, Digital Transformation, Data Management,
  Program Manager, Data Acquisition, Data Sharing
- **Othman** — `https://salem0557.github.io/cloude/othman/` — keywords: IT
  Support, Help Desk, Technical Support, IT Specialist, System
  Administrator, IT Fresh Graduate
- **Omer** — `https://salem0557.github.io/cloude/omer/` — searches **Riyadh
  and Hail** — keywords: Supply Chain, Procurement, Logistics, Operations
  Manager, Mechanical Engineer, Maintenance Engineer, Facilities Management

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

## LinkedIn posts page — posts to reply to

`https://salem0557.github.io/cloude/posts/` — finds **LinkedIn posts**
(not jobs) about *IT Management, IT Project Manager, Data Acquisition,
Data Sharing, Digital Transformation, HR, Saudi* from people in
Riyadh / Saudi Arabia, so you can reply to them and grow your visibility.
Refreshed **every 2 hours** by the *LinkedIn posts search* workflow
([`.github/workflows/posts.yml`](.github/workflows/posts.yml)); collected
posts are stored forever in
[`docs/posts/data/posts.json`](docs/posts/data/posts.json) and new ones
are flagged **NEW**. Each post has a **Mark replied** button (saved in
your browser) so you can track what you already answered.

How it finds posts — important honesty notes:

- **Live search buttons (always work)**: LinkedIn does not allow outside
  tools to read its feed, so the most reliable path is the row of
  one-click buttons at the top of the page. Each opens LinkedIn's own
  post search for a keyword + Riyadh, sorted by latest, filtered to the
  last 24 hours. This always shows the freshest posts.
- **Free auto-collection (best effort)**: every 2 hours the workflow asks
  Bing and DuckDuckGo for public LinkedIn posts
  (`site:linkedin.com/posts "<keyword>" Riyadh`). Search engines index
  only a fraction of LinkedIn posts and sometimes block automation, so
  expect a trickle, not a flood. Blocked engines are skipped and retried
  automatically next run. Verified through live workflow runs: Bing
  responds but loosely relaxes rare queries (irrelevant results are
  filtered out, often leaving nothing); DuckDuckGo's HTML endpoint
  currently serves GitHub's servers an empty page.
- **Free auto-collection that actually works — Tavily (recommended, no
  card)**: [Tavily](https://app.tavily.com) gives 1,000 free searches a
  month with no payment card. Sign up, copy the API key (`tvly-...`) from
  the dashboard, and add it as a repository secret named
  `TAVILY_API_KEY`. To fit the free quota, scheduled runs use Tavily
  three times a day (00:41, 08:41, 16:41 UTC); manual runs always include
  it.
- **Google option**: Google's official Programmable Search API gives 100
  free searches/day. **Caveat discovered in live testing: on newly created
  Google accounts this API returns 403 ("This project does not have the
  access to Custom Search JSON API") until a billing account (payment
  card) is linked** — and individual billing onboarding is not available
  in every country. If your Google account can link billing:
  1. Go to <https://programmablesearchengine.google.com> → **Add** → create
     an engine, and copy the **Search engine ID**.
  2. In Google Cloud Console, enable the **Custom Search API** and create
     an **API key** — both in the same project (watch out: accounts often
     have several projects with identical names).
  3. Add repository secrets `GOOGLE_CSE_ID` and `GOOGLE_CSE_KEY`.
  The next scheduled run picks either source up automatically.
- **Paid auto-collection (optional upgrade)**: add an Apify token
  (apify.com, roughly $5 free credit monthly, then pay-as-you-go) as a
  repository secret named `APIFY_TOKEN` and the workflow automatically
  also runs a LinkedIn post-search actor (default
  `harvestapi~linkedin-post-search`) that searches LinkedIn itself and
  returns fresh posts with author profile data; authors whose profile
  location is known and outside Saudi Arabia are filtered out. If the
  default actor's input schema doesn't match, set repository **variables**
  `APIFY_ACTOR` (actor id) and/or `APIFY_INPUT` (exact JSON input) — check
  the actor's page on Apify for its input format.
- **Author location is approximate**: without LinkedIn's permission no
  tool can truly filter by "author lives in Riyadh". Free mode keeps
  posts whose text mentions Riyadh / Saudi (English or Arabic); paid mode
  uses the author's profile location when the actor returns it.
- **Replies are always manual** — you click through and write your own
  reply. Auto-posting replies violates LinkedIn's terms and is the
  fastest way to get an account restricted instead of growing it.

Change the post keywords in the `KEYWORDS` list at the top of
[`scraper/search_posts.py`](scraper/search_posts.py) (and the matching
`KEYWORDS` constant in [`docs/posts/index.html`](docs/posts/index.html)).

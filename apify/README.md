# Saudi Arabia Jobs Scraper — Apify Actor

An [Apify](https://apify.com) actor that searches **LinkedIn, GulfTalent,
Akhtaboot, Tanqeeb and Jooble** for jobs by keyword and city, dedupes them, and
stores each job in the run's **dataset** (downloadable as JSON / CSV / Excel, or
via the Apify API).

It reuses the same parsers as the GitHub Pages scraper in
[`../scraper/search_jobs.py`](../scraper/search_jobs.py), so behaviour stays in
sync. The big win of running it on Apify is **proxy support**: GulfTalent and
Tanqeeb answer `403` to data-centre IPs (like GitHub's runners) but serve normal
pages through residential proxies.

## Input

All fields are optional — the actor runs with sensible Saudi Arabia defaults.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `keywords` | string[] | IT roles | Job titles to search for |
| `cities` | string[] | `Riyadh`, `Hail` | Cities to search |
| `country` | string | `Saudi Arabia` | Country the cities belong to |
| `sources` | string[] | all five | Boards to query |
| `maxItemsPerKeyword` | integer | `40` | Cap per source + keyword + city |
| `joobleApiKey` | string (secret) | — | Free key from <https://jooble.org/api/about>; switches Jooble to its official API |
| `proxyConfiguration` | proxy | Apify Proxy on | Residential recommended to unblock GulfTalent / Tanqeeb |

### Example input

```json
{
  "keywords": ["IT Support", "Help Desk", "System Administrator"],
  "cities": ["Riyadh"],
  "country": "Saudi Arabia",
  "sources": ["LinkedIn", "Akhtaboot", "Jooble"],
  "maxItemsPerKeyword": 40,
  "proxyConfiguration": { "useApifyProxy": true, "apifyProxyGroups": ["RESIDENTIAL"] }
}
```

## Output

Each dataset item looks like:

```json
{
  "title": "IT Project Manager",
  "company": "Example Co",
  "location": "Riyadh",
  "url": "https://www.linkedin.com/jobs/view/123456789",
  "posted": "2026-06-14",
  "source": "LinkedIn",
  "keywords": ["IT Project Manager"]
}
```

## Deploying it to Apify

1. Install the CLI: `npm install -g apify-cli`
2. Log in: `apify login`
3. From **this** folder, push the actor:

   ```bash
   cd apify
   apify push
   ```

   `apify push` reads `.actor/actor.json`, builds the `Dockerfile`, and uploads
   the build to your Apify account. Once built you can run it from the Apify
   Console, schedule it, or call it via the API.

### Run it locally first (optional)

```bash
cd apify
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
apify run            # or: python -m src
```

Results land in `storage/datasets/default/`. Without the Apify platform there's
no proxy, so GulfTalent / Tanqeeb may still return 403 locally — that's expected
and the run continues with the other sources.

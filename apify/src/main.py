"""Apify actor: scrape IT / general jobs from several Saudi Arabia job boards.

Reads its configuration from the actor input, fans out across
sources x keywords x cities, dedupes by canonical URL, and pushes every job to
the default dataset. Running on Apify means you can attach residential proxies,
which is what unblocks GulfTalent / Tanqeeb -- they answer 403 to data-centre
IPs (such as GitHub's runners) but serve normal pages through residential ones.
"""

from __future__ import annotations

import asyncio

from apify import Actor

from .jobs import SOURCES, ScrapeContext, SourceBlocked, make_session

DEFAULT_KEYWORDS = [
    "IT Management",
    "IT Project Manager",
    "Digital Transformation",
    "Data Management",
    "Program Manager",
]
DEFAULT_CITIES = ["Riyadh", "Hail"]
DEFAULT_COUNTRY = "Saudi Arabia"


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}

        keywords = actor_input.get("keywords") or DEFAULT_KEYWORDS
        cities = actor_input.get("cities") or DEFAULT_CITIES
        country = actor_input.get("country") or DEFAULT_COUNTRY
        sources = actor_input.get("sources") or list(SOURCES)
        max_per = int(actor_input.get("maxItemsPerKeyword") or 40)
        jooble_api_key = actor_input.get("joobleApiKey") or None

        # Resolve an (optional) proxy URL once; requests reuses it per session.
        proxy_url = None
        proxy_configuration = await Actor.create_proxy_configuration(
            actor_proxy_input=actor_input.get("proxyConfiguration"),
        )
        if proxy_configuration:
            proxy_url = await proxy_configuration.new_url()
            Actor.log.info("Using a proxy for outbound requests.")

        ctx = ScrapeContext(
            session=make_session(proxy_url),
            country=country,
            jooble_api_key=jooble_api_key,
        )

        Actor.log.info(
            "Searching %s for %d keyword(s) across %s",
            ", ".join(sources), len(keywords), ", ".join(cities),
        )

        by_url: dict[str, dict] = {}
        blocked: set[str] = set()

        for source in sources:
            searcher = SOURCES.get(source)
            if searcher is None:
                Actor.log.warning("Unknown source %r, skipping.", source)
                continue
            for keyword in keywords:
                if source in blocked:
                    break
                for city in cities:
                    try:
                        # Scraping is blocking (requests); keep the event loop free.
                        results = await asyncio.to_thread(searcher, ctx, keyword, city)
                    except SourceBlocked as exc:
                        Actor.log.warning(
                            "%s is blocking automation, skipping it: %s", source, exc,
                        )
                        blocked.add(source)
                        break
                    except Exception as exc:  # one bad source must not kill the run
                        Actor.log.warning("%s / '%s' (%s): %s", source, keyword, city, exc)
                        continue

                    results = results[:max_per]
                    Actor.log.info("%-11s '%s' (%s): %d jobs", source, keyword, city, len(results))
                    for job in results:
                        existing = by_url.get(job["url"])
                        if existing:
                            if keyword not in existing["keywords"]:
                                existing["keywords"].append(keyword)
                        else:
                            job["keywords"] = [keyword]
                            by_url[job["url"]] = job

        items = list(by_url.values())
        if items:
            await Actor.push_data(items)
        await Actor.set_status_message(f"Done — {len(items)} unique jobs found.")
        Actor.log.info("Pushed %d unique jobs to the dataset.", len(items))

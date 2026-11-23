# Waiting list

Things we've decided to do (or want to) that are on hold, grouped by what they're waiting for.
Updated as items move. Last updated: 2026-11-23 (news sources rebuilt: RSS feeds, GDELT raw files, Google News).

## Waiting on a decision or an account from you

| Item | Waiting for | Then |
| --- | --- | --- |
| "Where to watch / listen / read / play" links (affiliate) | Joining Apple, Amazon, Bookshop.org and a game-store affiliate program | Buttons on every title and story card, plus the disclosure line |
| Logo | You, Nov 23 | Site icon, share picture (`site/og.png`) and the organization logo in search results |
| Bluesky and Threads accounts | You, Nov 23 | Links on the site and in search metadata; Friday posts linking to the week's roundup (Bluesky: an app password; Threads: a Meta developer app) |
| First Friday newsletter issue | A PO box or virtual mailbox for Beehiiv's required mailing address (not a home address) | Send the This week page as the Friday issue. Sign-up boxes are already live (Beehiiv, free plan: therallyback.beehiiv.com) |
| Bluesky app password for the nightly search | Once the Bluesky account exists | Bluesky → Settings → Privacy and security → App passwords → add one; then GitHub repo → Settings → Secrets → Actions: `BLUESKY_HANDLE` (e.g. therallyback.bsky.social) and `BLUESKY_APP_PASSWORD` |
| Leftover GitHub branches (`mobile-simple`, `about-cols`, `wiki-test`, `discogs-test`, `honors-test`, `sources-test`) | Deleting them on GitHub (it won't let me) | Repo → Branches → delete |

## Waiting on the business plan

| Item | Plan phase | Notes |
| --- | --- | --- |
| LLC, tax ID, business bank account, trademark, logo | Step 0, Dec 2026 – Jan 2027 | About $1,500 one-time |
| Legal review of data-source licences, then pro terms | Before the first newsletter sponsorship (moved earlier; see "What's free and what's paid" in the plan) | Apple chart feeds (affiliate-program terms look compatible; check the RSS generator's own note when joining). Deezer, Google News and every publisher feed dropped Nov 23 (BBC, Guardian and Penske terms rule out our use; the rest as a precaution). New: TVmaze and Wikipedia's Top 25 Report, both CC BY-SA: credit needed on the site |
| Pro waitlist page and paid pilots | Phase A, Apr – Sep 2027 | Following is the free early signal for demand |
| Pro accounts, catalog upload, alerts, dashboard, API | Phase B, Oct 2027, only after the go/no-go gate | 10+ organizations waiting and 3 paying pilots |
| Licensed weekly "Rallyback 50" chart | Stream 4, free chart Q1 2028, sales Sep 2028 | The embeddable chart is the first step |
| A feed per followed title | When there's demand (or with pro alerts) | Following works in the browser for now |

## Waiting on data (these happen by themselves)

| Item | When |
| --- | --- |
| "Recently due" on Coming up and "How our predictions did" on This week | From late November, about a week after the first predicted dates |
| "Biggest this year" on This week | Once the record covers more than one month (December) |
| Staying power by cause (publishes itself on Track record) | About February 2027 (20+ finished comebacks per cause) |
| Expected bump from our own forecasts (on top of the backfill) | February – March 2027 |
| Lead time (Wikipedia vs. charts; publishes itself) | Spring 2027 |
| Calibrated forecasts from our own record (publishes itself) | May – June 2027 |
| Star power (publishes itself) | Second half of 2027 |
| Predictions for documentaries and biopics | Once enough of them have been checked |
| Full refresh of the prediction backfill | Once a year (run "Backfill predictions" in Actions) |

## Waiting on outside services

| Item | Status |
| --- | --- |
| Steam review counts | Steam blocks data requests from GitHub's servers; switched off automatically, player counts still work |
| Project Gutenberg top downloads | Gutenberg's own page turns away automated requests; now read from Gutendex (built on Gutenberg's catalog), top 128 books |
| GDELT news matching | Its search service refuses requests from shared cloud addresses (GitHub included); now read from GDELT's raw data files instead, alongside news sites' RSS feeds (`newsfeeds.py`, `gdeltfiles.py`); Google News dropped Nov 23 (its robots.txt disallows automated use of its search feed) |

## Cloudflare and the domain: done

The site lives at https://therallyback.com (Cloudflare, connected to this repo: every push to `main`,
including the nightly edition, publishes within a few minutes). Feeds, share links and title pages use
the new domain. The old address, inchurl2564.github.io/rally/, forwards every page to the same page on
therallyback.com and still serves the feeds, so existing subscriptions keep working.
www.therallyback.com forwards to therallyback.com (Cloudflare redirect rule "www to therallyback.com").
hello@therallyback.com forwards to the owner's inbox (Cloudflare Email Routing, one routing rule). It only receives;
replies come from the personal inbox unless Gmail's "Send mail as" is set up.

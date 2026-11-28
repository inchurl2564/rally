# Waiting list

Things we've decided to do (or want to) that are on hold, grouped by what they're waiting for.
Updated as items move. Last updated: 2026-11-23 (sources reviewed against their terms; new reason sources added; Currents and Bluesky keys in).

## Waiting on a decision or an account from you

| Item | Waiting for | Then |
| --- | --- | --- |
| "Where to watch / listen / read / play" links (affiliate) | Joining Apple, Amazon, Bookshop.org and a game-store affiliate program | Buttons on every title and story card, plus the disclosure line |
| First Friday newsletter issue | PO box ready (Nov 26; business mailing address for Castle Bridge Media, kept in the private accounts list). Waiting on: the owner entering it in Beehiiv. First issue planned for Friday Dec 4, 2026 (draft from the This week page, owner reviews in Beehiiv) | Send the This week page as the Friday issue, then remove the "first issue goes out soon" line from the Subscribe page (`subscribePage` in site/app.js). Sign-up boxes are already live (Beehiiv, free plan: therallyback.beehiiv.com) |
| Two-factor sign-in on every account (GitHub, Cloudflare, Google, Beehiiv, Bluesky, Currents) | You | Use an authenticator app or passkey, not text messages; save recovery codes offline; a password manager helps |
| Domain safety | You | Cloudflare → Domain Registration: auto-renew on, transfer lock on, card on file current |
| Email spoofing protection (SPF + DMARC) | You (I can walk you through it) | Two TXT records in Cloudflare DNS so nobody can send fake mail from @therallyback.com |
| Restrict the YouTube API key | You | Google Cloud Console → Credentials → the key → API restrictions: YouTube Data API v3 only |
| Monthly backups | You | Download the GitHub repository (Code → Download ZIP) and the Beehiiv subscriber list once a month |
| Emergency access | You | Decide who could run the site if you couldn't (password manager emergency access) |

## Planned next

| Item | Waiting for | Then |
| --- | --- | --- |
| YouTube channel (faceless, mostly text): a daily Short + a weekly longer video, 2-week trial | Deciding who builds the video system | It reads the site's existing data files; a person reviews each video; manual uploads until YouTube's compliance review. Details in HANDOFF.md, step 8b |

## Waiting on the business plan

| Item | Plan phase | Notes |
| --- | --- | --- |
| LLC, tax ID, business bank account, trademark, logo | Step 0, Dec 2026 – Jan 2027 | About $1,500 one-time |
| Legal review of data-source licences, then pro terms | Before the first newsletter sponsorship (moved earlier; see "What's free and what's paid" in the plan) | Apple chart feeds (affiliate-program terms look compatible; check the RSS generator's own note when joining). Deezer, Google News, Netflix Top 10 and every publisher feed ruled out Nov 23. In use and allowed: Wikipedia/Wikidata, GDELT files, Currents (credit shown), YouTube API, TVmaze and Top 25 Report (CC BY-SA credit needed on the site), MusicBrainz/ListenBrainz (CC0; MetaBrainz asks for support once there's revenue), Bluesky (counts and links only). The site's sources wording was updated to match on Nov 23 |
| Pro waitlist page and paid pilots | Phase A, Apr – Sep 2027 | Following is the free early signal for demand |
| Pro accounts, catalog upload, alerts, dashboard, API | Phase B, Oct 2027, only after the go/no-go gate | 10+ organizations waiting and 3 paying pilots |
| Licensed weekly "Rallyback 50" chart | Stream 4, free chart Q1 2028, sales Sep 2028 | The embeddable chart is the first step |
| A feed per followed title | When there's demand (or with pro alerts) | Following works in the browser for now |

## Storage to watch

| Item | When |
| --- | --- |
| Cloudflare Free allows 20,000 site files per deploy (1,516 on Nov 26 after bundling title data, growing ~80 a night) | Around July 2027: serve thin title pages from one shared page, or Workers Paid ($5/month, 100,000 files). Revisit in spring. The Monday morning report tracks it |
| GitHub recommends repos under 1 GB (22.6 MB on Nov 26, ~0.7 GB a year) | Around early 2028: move old run archives out of git |

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
| GDELT news matching | Its search service refuses shared cloud addresses; read from GDELT's raw data files instead (`gdeltfiles.py`), with the Currents News API as backup. Publisher feeds and Google News dropped Nov 23 over their terms |
| Entertainment trade news (Variety, Deadline-style) | No free source covers it well (Currents' index is thin on it); needs a paid licence once there's revenue |
| Discogs data files | Discogs now blocks automated downloads; not pursued |

## Cloudflare and the domain: done

The site lives at https://therallyback.com (Cloudflare, connected to this repo: every push to `main`,
including the nightly edition, publishes within a few minutes). Feeds, share links and title pages use
the new domain. The old address, inchurl2564.github.io/rally/, forwards every page to the same page on
therallyback.com and still serves the feeds, so existing subscriptions keep working.
www.therallyback.com forwards to therallyback.com (Cloudflare redirect rule "www to therallyback.com").
hello@therallyback.com forwards to the owner's inbox (Cloudflare Email Routing, one routing rule). It only receives;
replies come from the personal inbox unless Gmail's "Send mail as" is set up.

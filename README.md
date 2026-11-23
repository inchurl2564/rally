# The Rallyback

*The comeback report.*

Finds older films, TV shows, songs, albums, games and books that are suddenly getting attention again, explains why, and forecasts which ones are likely to come back next.

It runs every day on GitHub Actions and publishes a static site to GitHub Pages. It uses only open data and needs no API keys.

| Source | Used for |
|---|---|
| [Wikimedia bulk pageviews](https://dumps.wikimedia.org/other/pageview_complete/readme.html) (human traffic) | Watching ~35,000 notable older works every day |
| [Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews) | 12-month history, top-1,000 lists, desktop share |
| [Wikidata](https://www.wikidata.org/) (CC0) | What each work is, release dates, credits, sequels and adaptations |
| Wikipedia edit history | Edit bursts and edit summaries from the days a spike began |
| [GDELT](https://www.gdeltproject.org/) news API | Headlines from the days a spike began (best-effort) |
| [Steam](https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers) players and reviews | Older games people are playing (and reviewing) again |
| [iTunes charts](https://itunes.apple.com/us/rss/topmovies/limit=200/json) (songs, albums, movies, US) | Older works back on the charts |
| [Open Library](https://openlibrary.org/trending/daily) trending | Older books people are reading again |
| [Project Gutenberg](https://www.gutenberg.org/browse/scores/top) top 100 | Classic books being downloaded again |
| Wikipedia in 12 other languages | Whether a comeback is global or local |
| [Bluesky](https://docs.bsky.app/docs/api/app-bsky-feed-search-posts) public search | How many people are posting about it this week |

## The Rallyback Score

Every comeback gets one number from 0 to 100: the size of the jump (40%), the everyday audience (25%), how many other places confirm it (20%: charts, Steam, other-language Wikipedias, Bluesky) and staying power (15%). It ranks the site.

## The permanent record

Snapshots that can't be fetched after the fact are kept forever as open data:

- `site/data/signals/YYYY-MM.json`: every day's chart positions, Steam players and review totals, matched to works.
- `site/data/history/YYYY-MM.json`: every comeback, every day: lift, Rallyback Score, reason, stage and confirmations,
  plus its causes (`[kind, Wikidata ID, detail, date]`: the person who died, the new release, the person in the news)
  and each work's series or franchise. `names` gives a label for every ID, so the file reads on its own.
- `site/data/forecast_checks.json`: every forecast once its date has passed, with the bump that actually happened,
  the kind of release (sequel, remake, adaptation) and the Wikidata IDs of both works.

Over time this record shows how long each kind of comeback lasts and how big each kind of trigger tends to be.

## Who it's for

The main menu is for everyone. Each professional audience has its own view, linked from the footer ("For professionals"):

- **Journalists:** unexplained spikes, works that rose together around one person, and likely causes from news and edits.
- **Rights holders:** catalog titles at the *emerging* stage (the time to promote, reissue or license), plus upcoming sequels and adaptations.
- **Retail:** physical media, games and books with emerging or sustained demand.
- **Programmers:** films and TV people are rediscovering, plus upcoming anniversaries.
- **Researchers:** daily snapshots, a CSV, the forecast record and the method.

There are also **Coming up** (forecasts), **Track record** (how often it's right) and **Alerts** (feeds) tabs.

## What it does

1. **Watch:** each day, read the bulk pageview file and track notable older works, i.e. those with 10+ language editions released 10+ years ago. It also scans English Wikipedia's daily top 1,000.
2. **Second opinions:** record Steam player counts, iTunes chart positions and Open Library trending each day (`site/data/signals.json`), matched to works through Wikidata IDs. A jump (2× usual players, a new chart entry, a big climb) adds the work as a candidate and raises its rank; any signal is shown in the card's *Numbers & sources*.
3. **Measure:** compare the last 3 and 14 days with the median of the previous ~11 months. 3× over 14 days, or 2.5× over 3 days, counts as a revival. Each revival gets a stage: *emerging*, *peaking*, *sustained* or *fading*.
4. **Explain:** look in Wikidata for deaths of credited people, sequels, adaptations, remakes, new series entries, new work by the same creator, or anniversaries. For spikes Wikidata can't explain, read edit summaries, edit bursts and news headlines from the same days.
5. **Connect:** group spikes by a shared event, and group unexplained spikes by a shared person with the same timing.
6. **Filter:** set aside seasonal items (also up this time last year), spikes that are almost all desktop traffic (likely bots), and one-day surges from a feature on Wikipedia's front page (Today's featured article, Did you know, On this day).
7. **Forecast and check:** list upcoming sequels, adaptations and anniversaries for older works, then later check whether attention actually rose. The site publishes the hit rate, how often explanations are backed by independent evidence, and reader corrections.

These are leads, not conclusions. Wikidata is volunteer-edited, and news and edit lookups are best-effort. Verify before publishing or acting.

## Alerts

Feeds only for now: `site/feeds/*.xml` (Atom) covers all findings, unexplained comebacks, coming-up forecasts, film & TV, music, games, and books. The site's **Alerts** page lists them with copy buttons.

The daily email digest (a GitHub issue each run) is paused. To turn it back on, add the repository variable `EMAIL_DIGEST` = `true` (**Settings → Secrets and variables → Actions → Variables**).

## Reader tips

"Know why? Tell us" and "Report a correction" open a short form on the page that sends the tip to the Google Form
"The Rallyback: reader tips" (set in `TIPS_FORM` in `site/app.js`). Tips arrive in that form's
Responses tab (turn on email notifications there); readers never need a GitHub account. Corrections are marked "CORRECTION" in the first answer, and messages from the
contact form on About us are marked "CONTACT" (name in the first answer, message in the second, reply address in the email answer). The title,
year, edition and what the site said are filled in automatically.

When a tip checks out, add an editor's note to `annotations.json` with a `source` link and `"via": "reader tip"`.
The next nightly run moves the title out of Unexplained, and the **Case closed** strip on the Unexplained page
lists it for a week with "Solved thanks to a reader tip."

## Reader corrections

Every card has a **Report a correction** link that opens a pre-filled issue labelled `feedback`. Label reviewed reports `verified-correct` or `verified-wrong`, and the Accuracy tab counts them on the next run.

## Setup (one time)

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → Update The Rallyback → Run workflow** to run it immediately.
   After that it runs daily at 2 a.m. Pacific (09:00 or 10:00 UTC, depending on daylight saving time).

The first run takes longer (up to ~1 hour) because it builds the watchlist and downloads about 4 weeks of bulk pageview files. Early detection switches on once 8 days of bulk data exist. Later runs reuse the cache and take a few minutes.

## Run locally

Requires Python 3.10+. Only the standard library is used.

```bash
python3 radar.py --site site
```

```bash
python3 -m http.server -d site 8000
```

| Option | Default | Meaning |
|---|---|---|
| `--days` | 30 | Days of top-1,000 lists to scan |
| `--recent` | 14 | Days used to measure current attention |
| `--min-age` | 10 | Minimum years since release |
| `--min-lift` / `--early-lift` | 3.0 / 2.5 | 14-day / 3-day lift that counts |
| `--no-early` | off | Skip the bulk-file watchlist |
| `--bulk-new-days` | 28 | Max bulk files to download in one run (~1 min each) |
| `--no-news` | off | Skip GDELT news lookups |
| `--explain-max` | 30 | Max unexplained spikes to research per run |
| `--keep-runs` | 120 | Daily runs kept in the site archive |

Set `RADAR_CONTACT` to a URL or address so Wikimedia can identify your client, as their [User-Agent policy](https://meta.wikimedia.org/wiki/User-Agent_policy) asks. In Actions it's set to the repo URL automatically.

## Layout

```
radar.py      pipeline: discover, measure, explain (Wikidata), write site data
early.py      watchlist + bulk pageview files → early risers
signals.py    Steam, iTunes charts, Open Library, Gutenberg (via Gutendex) → daily record + signals
enrich.py     other-language Wikipedia, Bluesky, the Rallyback Score, permanent history
explain.py    edit bursts, edit summaries, news → likely cause; corroboration
forecast.py   upcoming sequels/adaptations/remakes, anniversaries
evaluate.py   forecast checks, corroboration, persistence, reader reports
feeds.py      Atom feeds + daily digest
site/         static site (index.html, app.js, style.css) and data/, feeds/
.github/workflows/radar.yml   daily run, digest issue, Pages deploy
```

## The archive

Each night `archive.py` turns the permanent record into:

- `site/data/works/<qid>.json`: a page per title, with every comeback (when, how big, why), its chart,
  what's coming for it and related titles. Opened on the site at `?work=<qid>`.
- `site/data/works/index.json`: every title we've tracked, for the "Search all titles" box.
- `site/w/<qid>.html`: a share link per title, with a proper title, description and picture for link
  previews; it opens the title page.
- `site/data/leaders.json` and `site/data/weekly/<week>.json`: the **This week** page (the 5 biggest,
  the best mystery, what's due next week, how predictions did, leaderboards, decades and franchises).

Also on the site: **Follow** (kept in the reader's browser), a confidence label on each story
(Confirmed / Likely / Possible), a corrections log on Track record (edit `site/data/corrections.json`:
`[{"date": "2026-12-01", "said": "...", "fixed": "..."}]`), and an embeddable chart at `embed.html?n=10`.

## Monitoring

The nightly run checks itself (`health.py` plus two workflow steps) and opens one GitHub issue labelled
`health`, which emails the repo owner, only when something needs a person:

- the run failed, or finished without producing a new edition;
- a source has been unavailable three nights in a row (Steam reviews are known to be off and are ignored);
- the number of comebacks suddenly halved or doubled;
- many Wikipedia pages skipped or Wikidata lookups failed;

While a problem lasts, each night adds a comment to the same issue. Close it once it's dealt with.
Quiet nights send nothing.

## Editor's notes: where they're filed

Each note in `annotations.json` says what kind of cause it is, and its titles are filed in that section:
`"cause": "release"` (a new film, show, game or book) → New releases, `"death"` → In memoriam,
`"news"` (the default) → In the news. An optional `"headline"` names the grouped story (`{n}` = how many titles), e.g. "Robert Pattinson's Bond casting brings back {n} titles". A release note can also name the new work's Wikidata ID in
`"new_work"`; titles the site already linked to that release then join the same story (e.g. the Hunger
Games films and novels, with Sunrise on the Reaping). Noted stories keep the **Confirmed** label.

## Where the site lives

**https://therallyback.com**, served by Cloudflare straight from this repository (the `site` folder);
every push to `main` publishes within minutes. `site/_headers` makes browsers always check for fresh
code. The old GitHub Pages address publishes `.github/pages-pointer` instead: it forwards every page to
the same page on therallyback.com and keeps serving the feeds.

## Title pages, search engines and the feed

Every title The Rallyback has caught gets a readable page at `/w/<Wikidata ID>.html` (written by
`archive.py` each night, plain HTML with no script needed): why it's back, how sure we are, a 12-month
chart, every comeback, related titles and, for books, free ways to read it (Project Gutenberg, Open
Library; looked up by `reading.py`). `sitemap.xml` and `robots.txt` list the pages for search engines,
and today's top stories are written into `index.html` so the homepage has text before the app loads.
Feed entries use the same plain-English reasons, link to the title page and are tagged by medium and reason.
Title pages with too little to say yet (one comeback of 2 days or less, no known reason) carry `noindex` and are
left out of the sitemap until they grow. `site/og.png` is the default share picture (made from an HTML card;
replace it once there's a logo). Each week also gets a permanent roundup page at `/week/<2026-W47>`, listed at `/week/`.

## News behind the reasons

`newsfeeds.py` keeps a rolling 75-day library of headlines from about 20 entertainment and culture
news feeds (Variety, Deadline, The Hollywood Reporter, IndieWire, Billboard, Rolling Stone, NME,
Pitchfork, Polygon, Kotaku, Eurogamer, GameSpot, Book Riot, the Guardian's culture sections, BBC
entertainment), read once a night and saved in the repository as one gzipped file per day
(`store/news/`, kept 75 days; GDELT headlines in `store/gdelt/`, kept 30 days; see `daystore.py`). Each comeback is searched by its
title in quotes in a headline (people by full name); comparisons ("'X' meets 'Y'") don't count.
What the library can't explain is looked up in GDELT's raw 15-minute data files (`gdeltfiles.py`: a
day of files, about 220 MB, read in under a minute; headlines that quote a title kept 30 days). Google News was dropped on 2026-11-23:
its robots.txt disallows automated access to its search feed, which Google's terms forbid. GDELT's search service refuses requests from
shared cloud addresses, so its raw files are read instead. To test the feeds from GitHub's servers, run `python newsfeeds.py --test "Title|film" "@Person Name"`.

When the news finds no reason for a work's comeback, `youtube.py` searches YouTube (official Data API v3,
`YOUTUBE_API_KEY` repository secret; up to 60 searches a night). A video counts only if its title names the
work and says what it is (trailer, film, scene, song...), has 100,000+ views and was posted from 14 days
before the comeback to 7 days after. One with 1M+ views and no other reason in its title makes the cause
"viral". Nothing from YouTube is stored between runs (YouTube's terms limit keeping raw API data).

Deezer's charts were dropped on 2026-11-23: its developer terms allow only approved, private,
non-commercial use, and forbid keeping a database of its content or any text and data mining.
Saved Deezer chart data was removed from `site/data` (it remains in git history only).

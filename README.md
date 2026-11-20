# Rally

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
| [Steam](https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers) current players | Older games people are playing again (recorded daily) |
| [iTunes charts](https://itunes.apple.com/us/rss/topmovies/limit=200/json) (songs, albums, movies) | Older works back on the charts (recorded daily) |
| [Open Library](https://openlibrary.org/trending/daily) trending | Older books people are reading again (recorded daily) |

## Who it's for

The site has a view for each audience:

- **Journalists:** unexplained spikes, works that rose together around one person, and likely causes from news and edits.
- **Rights holders:** catalog titles at the *emerging* stage (the time to promote, reissue or license), plus upcoming sequels and adaptations.
- **Retail:** physical media, games and books with emerging or sustained demand.
- **Programmers:** films and TV people are rediscovering, plus upcoming anniversaries.
- **Researchers:** daily snapshots, a CSV, the forecast record and the method.

There are also **Coming up** (forecasts), **Accuracy** (how often it's right) and **Get alerts** tabs.

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

- **Email:** each run posts a digest as a GitHub issue. Click **Watch → Custom → Issues** on this repo to get it by email.
- **Feeds:** `site/feeds/*.xml` (Atom) covers all findings, unexplained spikes, coming-up forecasts, film & TV, music, games, and books.

## Reader tips

Each mystery has a **Know why? Tell us** link that opens a short form (what's bringing it back, an optional link, an optional email). It posts to a form service you own. Set `TIPS_FORM` at the top of `site/app.js`:

- **Google Forms** (free; replies go to a Google Sheet and can email you): make a form with four short-answer/paragraph questions (*Work*, *Why*, *Link*, *Email*), then use **⋮ → Get pre-filled link** to find each question's `entry.NNN` name. `action` is `https://docs.google.com/forms/d/e/<form id>/formResponse`.
- **Formspree or similar:** `action` is your endpoint; field names can be anything.

Until `action` is set, the link opens a pre-filled GitHub issue instead.

## Reader corrections

Every card has a **Report a correction** link that opens a pre-filled issue labelled `feedback`. Label reviewed reports `verified-correct` or `verified-wrong`, and the Accuracy tab counts them on the next run.

## Setup (one time)

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → Update Rally → Run workflow** to run it immediately.
   After that it runs daily at 04:23 UTC.

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
signals.py    Steam, iTunes charts, Open Library → second opinions
explain.py    edit bursts, edit summaries, news → likely cause; corroboration
forecast.py   upcoming sequels/adaptations/remakes, anniversaries
evaluate.py   forecast checks, corroboration, persistence, reader reports
feeds.py      Atom feeds + daily digest
site/         static site (index.html, app.js, style.css) and data/, feeds/
.github/workflows/radar.yml   daily run, digest issue, Pages deploy
```

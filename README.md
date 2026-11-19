# Revival Radar

Finds older films, TV shows, songs, albums, games and books that are suddenly getting attention again, and works out the likely reason why.

It runs every day on GitHub Actions and publishes a static site to GitHub Pages. It uses only open, unrestricted data, with no API keys:

- **[Wikimedia Pageviews API](https://wikitech.wikimedia.org/wiki/Analytics/AQS/Pageviews)**: daily human views of every Wikipedia article (CC0)
- **[Wikidata](https://www.wikidata.org/)**: what each article is about, release dates, credits, sequels and adaptations (CC0)

## What it finds

| Finding | Meaning |
|---|---|
| **Shared triggers** | One event (a new sequel, a death, an upcoming release) linked to several older works spiking at once. |
| **Hidden common threads** | Spikes with no recorded cause on works that share a credited person and started rising within a week of each other. |
| **Explained revivals** | A death of someone credited, a sequel, adaptation, remake or series entry (released or upcoming), a new work by the same creator, or an anniversary near the start of the spike. |
| **No trigger found** | Big jumps Wikidata can't explain. These are leads worth investigating, such as memes, TV airings or ad placements. |
| **Filtered out** | Seasonal items that were also up this time last year, and spikes that are almost all desktop traffic (likely bots). |

These are leads, not conclusions. Wikidata is edited by volunteers and can be incomplete or wrong. Verify before publishing anything.

## How it works

1. **Discover**: collect every article in English Wikipedia's daily top 1,000 over the last 30 days.
2. **Classify**: use Wikidata to keep creative works released at least 10 years ago.
3. **Measure**: compare average daily views over the last 14 days with the median over the previous ~11 months. 3× or more counts as a revival.
4. **Explain**: query Wikidata for likely triggers near the start of each spike.
5. **Connect and filter**: group spikes by shared events and people, and set aside seasonal and bot-like spikes.

## Setup (one time)

1. Push this repo to GitHub.
2. Go to **Settings → Pages → Build and deployment** and set **Source** to **GitHub Actions**.
3. Go to **Actions → Update Revival Radar → Run workflow** to publish the first time.
   After that it runs daily at 04:23 UTC. The site will be at `https://<user>.github.io/<repo>/`.

The first run in Actions takes about 25 minutes because Wikimedia rate-limits requests. Later runs reuse cached pageview history and only fetch new days, which takes a few minutes.

## Run locally

Requires Python 3.10+. Only the standard library is used.

```bash
python3 radar.py --site site
```

```bash
python3 -m http.server -d site 8000
```

Then open http://localhost:8000.

Useful options:

| Option | Default | Meaning |
|---|---|---|
| `--days` | 30 | Days of top-article lists to scan |
| `--recent` | 14 | Days used to measure current attention |
| `--min-age` | 10 | Minimum years since release |
| `--min-lift` | 3.0 | Minimum lift over baseline to count as a revival |
| `--project` | `en.wikipedia` | Wiki to scan, e.g. `de.wikipedia` |
| `--keep-runs` | 120 | Archived daily runs to keep on the site |

Set `RADAR_CONTACT` to a URL or address so Wikimedia can identify your client, as their [User-Agent policy](https://meta.wikimedia.org/wiki/User-Agent_policy) asks. In Actions it's set to the repo URL automatically.

## Layout

```
radar.py                    data pipeline: fetch, measure, explain, write JSON
site/index.html, app.js, style.css
site/data/latest.json       newest run
site/data/runs/DATE.json    archive (one per day)
site/data/index.json        list of runs for the run picker
.github/workflows/radar.yml daily run + Pages deploy
```

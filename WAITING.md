# Waiting list

Things we've decided to do (or want to) that are on hold, grouped by what they're waiting for.
Updated as items move. Last updated: 2026-11-20.

## Waiting on a decision or an account from you

| Item | Waiting for | Then |
| --- | --- | --- |
| Own domain (therallyback.com) and move to Cloudflare Pages | Buying the domain; a free Cloudflare account | Point the domain at Cloudflare, move hosting (about a day). Needed before anything commercial: GitHub Pages doesn't allow it |
| "Where to watch / listen / read / play" links (affiliate) | The domain move above; joining Apple, Amazon, Bookshop.org and a game-store affiliate program | Buttons on every title and story card, plus the disclosure line |
| Newsletter sign-up and the weekly issue | Picking a newsletter service (Beehiiv suggested, free to 2,500 subscribers) | Sign-up boxes on the site; the This week page becomes the Friday issue |
| Reader tips going to a form instead of GitHub | A Google Form (or Formspree) link | Set `TIPS_FORM` in `site/app.js`; tips stop opening GitHub issues |
| A contact address on About us | Choosing an address you're happy to publish | Add it to About us and the footer |
| Email digest | Turning it back on (paused by choice: feeds only) | Add the `EMAIL_DIGEST = true` repository variable |
| Automatic "measures go live when ready" (staying power, lead time, star power, calibrated forecasts) | Your go-ahead on the setup I proposed (with or without "coming soon" progress lines) | Nightly calculation; each section appears on its own once it has enough examples |
| Documentaries and biopics in Coming up ("a new documentary about Queen…") | Your go-ahead | New Coming up list |
| "Warming up": titles climbing toward a comeback | Your go-ahead | New Coming up list |
| Leftover GitHub branches (`simplify`, `preview-template`, `predictions`) | Deleting them on GitHub (it won't let me) | Repo → Branches → delete |

## Waiting on the business plan

| Item | Plan phase | Notes |
| --- | --- | --- |
| LLC, tax ID, business bank account, trademark, logo | Step 0, Dec 2026 – Jan 2027 | About $1,500 one-time |
| Legal review of pro terms and data-source licences | Before charging anyone (Stream 3) | Deezer and Apple feed terms in particular |
| Pro waitlist page and paid pilots | Phase A, Apr – Sep 2027 | Following is the free early signal for demand |
| Pro accounts, catalog upload, alerts, dashboard, API | Phase B, Oct 2027, only after the go/no-go gate | 10+ organizations waiting and 3 paying pilots |
| Licensed weekly "Rallyback 50" chart | Stream 4, free chart Q1 2028, sales Sep 2028 | The embeddable chart is the first step |
| A feed per followed title | When there's demand (or with pro alerts) | Following works in the browser for now |

## Waiting on data (these happen by themselves)

| Item | When |
| --- | --- |
| Prediction backfill finishes; sequels and 50th+ anniversaries get predictions | Within hours (running now) |
| "Recently due" on Coming up and "How our predictions did" on This week | From late November, about a week after the first predicted dates |
| "Biggest this year" on This week | Once the record covers more than one month (December) |
| Staying power by cause | About February 2027 (20+ finished comebacks per cause) |
| Expected bump from our own forecasts (on top of the backfill) | February – March 2027 |
| Lead time (Wikipedia vs. charts) | Spring 2027 |
| Calibrated forecasts from our own record | May – June 2027 |
| Star power | Second half of 2027 |
| Full refresh of the prediction backfill | Once a year (run "Backfill predictions" in Actions) |

## Waiting on outside services

| Item | Status |
| --- | --- |
| Steam review counts | Steam blocks data requests from GitHub's servers; switched off automatically, player counts still work |
| Project Gutenberg top downloads | Was down for maintenance; retried automatically every night |
| GDELT news matching | Sometimes rate-limited; retried every night |

## Small fixes offered, not yet requested

- Hide weak two-title "linked by one person" groups (show only 3+).
- Group headlines that use the editor's note ("Robert Pattinson's Bond casting brings back 39 titles").
- Fix headlines where the new release has the same name as the original ("Zelda … thanks to Zelda").

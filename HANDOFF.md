# The Rallyback: handoff

Everything learned building and running The Rallyback, so a new session (or a new person) can pick up
without losing knowledge or strategy. Written 2026-11-26. Read this, then `README.md` (how the code works)
and `WAITING.md` (what's on hold and why). The business plan is a separate Claude doc (link below).

---

## 1. What it is

**The Rallyback** (therallyback.com) finds older movies, TV shows, songs, albums, games and books that people
are suddenly into again, and explains why: a sequel or remake, a death, an anniversary, an award, a story in
the news. When it can't find the reason, it says so and asks readers ("Unexplained").
Tagline in use: **"Where Everything Old is News Again."** (About us).

- **Repository:** `inchurl2564/rally` (public). Site files in `site/`.
- **Hosting:** Cloudflare (Workers serves `site/`); every push to `main` publishes within a few minutes.
  `.html` addresses redirect to extensionless ones (`/w/Q123`, `/week/2026-W48`, `/report/2026-11`).
- **Nightly run:** GitHub Actions `.github/workflows/radar.yml`, 2 a.m. Pacific. Two cron lines (09:00 and
  10:00 UTC) cover daylight saving; a gate job lets only the right one do the work. GitHub often starts it
  up to an hour late. The main step takes ~60 minutes (2 hours on 2026-11-26 because Wikidata was slow).
- **Business plan:** Claude doc https://claude.ai/artifact/871TVez4bTz6A1SdQezwy2 (sections include What's free
  and what's paid, Budget, Marketing plan, Security and resilience, Implementation plan, Risks).
- **Accounts list:** a private file the owner keeps (not in this public repo): GitHub, Cloudflare (domain,
  hosting, DNS, email routing), Gmail (receives hello@therallyback.com), Beehiiv (newsletter), Google Forms
  (tips/contact), Google Search Console, Bing Webmaster Tools, Google Cloud (YouTube key), Bluesky,
  Currents, Claude.

## 2. How the owner likes to work (important)

- Plain, non-technical language. Short answers; lead with the result.
- **Preview before anything readers would see changes** (layout, wording, pictures, new pages): build it on a
  `preview-<name>` branch, screenshot desktop and phone (Playwright), and wait for "publish". Invisible fixes
  (wrong reasons, bugs, data fields) can go straight to `main`.
- The owner deletes GitHub branches (this environment can't). After publishing a preview, tell them which
  branch to delete.
- Commits end with the session's attribution lines; never put model names in commits, code or docs.
- Privacy: never put the owner's name or email in the repo, requests to outside services, or the site.
- Never work around a site that blocks automated access (no spoofed user agents, no bypassing blocks).
- Check a data source's terms before adding it: commercial use must be allowed (see section 5).
- Before saying something is live, check the live site.

## 3. The nightly pipeline (radar.py and friends)

1. **Discover**: Wikipedia pageviews (English + bulk files for ~51,000 watched works), early risers, and
   "confirm elsewhere" signals (`signals.py`: iTunes charts, Open Library trending, Gutenberg via Gutendex,
   ListenBrainz weekly charts, Steam players).
2. **Classify** titles via Wikidata (creative works at least 10 years old).
3. **Measure** attention (lift vs usual level, 3-day rise).
4. **Find reasons** (`radar.py` triggers from Wikidata: deaths, sequels/adaptations, same creator,
   anniversaries, honors, Public Domain Day; then `explain.py` for the unexplained: news, Wikipedia, TVmaze,
   MusicBrainz, YouTube, Bluesky). Up to **100** unexplained comebacks researched a night (`--explain-max`).
5. **Write** `site/data/latest.json` + `site/data/runs/<date>.json`, title pages (`site/w/`), weekly pages
   (`site/week/`), the monthly Comeback Report (`site/report/`), feeds, sitemap, homepage static block.
6. After commit: **IndexNow** ping (`tools/indexnow.py`), **Bluesky post** (`bluesky_post.py`), health check
   (opens a GitHub issue only when something needs a person).

Verdicts: death, derivative (sequel/remake/adaptation), same-creator, anniversary, public domain, honor,
editor / editor-release / editor-death (editor's notes in `annotations.json`), ripple (a connected page jumped),
coverage (reason read from news/edits), common thread (several titles sharing a person), unexplained,
weak link, lookup failed; set aside: seasonal, automated?, front page.

## 4. The site today

- **Menu:** Today, This week, Unexplained, Coming up, Track record, About us, and a red **Subscribe** button
  (pinned right on phones). Subscribe page explains the Friday newsletter + Beehiiv form; it says "The first
  issue goes out soon" (remove after the first issue: `subscribePage` in `site/app.js`). Every newsletter link
  points to `?tab=subscribe`.
- **Today page (changes every morning):** lead = best comeback new today or yesterday (`days_on <= 2`);
  Top 10 with NEW / ▲▼ score marks (one line per story/reason); "New today: N comebacks · M still going" row;
  then the streamgraph ("The month in comebacks"); then sections (In the news, New releases, In memoriam,
  Unexplained). Each edition records `days_on` and `prev_score` per comeback (`mark_freshness` in radar.py).
- **Phones:** cards sit inside collapsed sections; links open the section before scrolling (`openAround`).
- **Logo:** wordmark in masthead, footer and title-page headers (inverted in dark mode); yellow "Rb" icon for
  favicon/apple-touch/Google logo; share card `site/og.png` = wordmark on yellow #F3C716. Files in `site/logo/`.
- **Fonts:** Playfair Display (serif) + Libre Franklin (sans), Google Fonts, OFL.
- **Pages for search/press:** title pages `/w/<qid>` (thin ones noindexed), weekly `/week/`, monthly
  **Comeback Report** `/report/<YYYY-MM>` (top 10 by reason, "why things came back" bars, mysteries, quote
  invitation). Linked from This week, footer, journalists page, weekly pages.
- **Security:** only http(s)/mailto links from data (`safeUrl`); headers in `site/_headers` (nosniff,
  referrer policy, permissions policy, HSTS; no frame blocking because `embed.html` is embeddable).

### Pictures (rules, in order; learned the hard way)
1. A story whose **headline names a person** shows that person (death, honor, person ripple; group stories
   for a person in the news or who died). `headline_person` in radar.py, `personPic` in app.js.
2. **Films and TV:** the **top-billed** star (first 3 of Wikidata's cast list, which is in billing order) with a
   free photo. Ranking by fame picked cameos (Kevin Bacon in Planes, Trains and Automobiles). Films before
   **1970 keep their own picture** (usually the original public-domain poster), at the owner's request.
3. Otherwise the work's own Commons image (P18 / poster / logo).
4. Then the **series or franchise logo** (Grand Theft Auto's), before a person.
5. Then a person behind it (performer, author, director...).
Only Wikimedia Commons images (free to reuse). Cover art, posters, YouTube thumbnails, Apple artwork, Steam
images are copyrighted: crediting the owner is NOT permission. Apple artwork becomes usable only through the
Apple affiliate program, next to an Apple badge.

## 5. Data sources: what we use, what we dropped, and why

**The rule that matters:** whose terms you accept is decided by who you connect to. Reading a publisher's own
feed binds us to their terms (most forbid automated/commercial use). Going through a middleman (GDELT,
a news API) means only the middleman's terms bind us; we keep only a headline-free link, and copyright on a
headline + link is low risk. Not legal advice; the planned lawyer review should confirm.

**In use (commercial use allowed):**
| Source | Use | Notes |
|---|---|---|
| Wikipedia / Wikimedia | pageviews, edits, Current events, Top 25 Report, other languages | CC BY-SA text |
| Wikidata | titles, credits, deaths, sequels, honors, IDs | CC0; can be slow (2026-11-26) |
| Wikimedia Commons | pictures | free licences |
| GDELT raw 15-min files | quoted headlines, 30 days kept in `store/gdelt/` | its search API refuses cloud IPs |
| Currents News API | headlines when GDELT finds nothing | free plan 250/day, 30 days back, 7-day max window; must show "Powered by Currents News API" beside its links; no permanent copies (we keep link, site, date, our reason word only); no published stats about its data. Good for people/general news, thin on entertainment trade press. Use `query` (exact phrase), not `keywords`. |
| YouTube Data API | trending chart (16 units/night) + up to 60 searches | key in `YOUTUBE_API_KEY`; nothing stored |
| TVmaze | new seasons/specials for TV series | CC BY-SA, credit on site |
| MusicBrainz (core data) | album reissues | CC0; 1 req/s |
| ListenBrainz | weekly listening charts (signal) | CC0; MetaBrainz asks businesses to support it (in business plan) |
| Bluesky | post counts for unexplained comebacks; weekly "chatter"; daily posting | signed in as therallyback.bsky.social; keep only counts, links, likes; never post text or handles |
| Apple iTunes RSS charts, Open Library, Gutendex, Steam players | confirm-elsewhere signals | Steam reviews blocked from GitHub (off) |

**Dropped or rejected (don't re-add without new terms):**
Deezer (private, non-commercial only); Google News (robots.txt disallows); BBC, Guardian, Penske Media
(Variety, Deadline, THR, IndieWire, Billboard, Rolling Stone) feeds (terms forbid automated/commercial use);
other publisher feeds (precaution); Netflix Top 10 (terms forbid commercial use and automated gathering);
Discogs data dumps (now block automated downloads); APITube (free plan testing-only; paid plans still push
publisher risk on us); NewsAPI.org/GNews/Mediastack free plans (non-commercial); TMDB, IGDB, Last.fm, Spotify,
Reddit, IMDb datasets, Google Trends, Box Office Mojo, JustWatch, FlixPatrol (non-commercial or paid);
Threads (Meta declined the account). The real gap is **entertainment trade news** (Variety/Deadline): only a
paid licence fixes it, later, once there is revenue.

**Secrets (GitHub → Settings → Secrets → Actions):** `YOUTUBE_API_KEY`, `CURRENTS_API_KEY`, `BLUEVIOLET`
(Bluesky app password; handle is in radar.yml). This environment cannot read or set GitHub secrets.

## 6. Reason-matching rules (each one fixed a real wrong reason)

- **News headlines:** a work's title must be in quotes, alone or as `Title: subtitle` ('May God forgive you'
  is not the film *May*); comparisons ("meets", "-style") don't count; people by full name.
- **Wikipedia added sentences:** skip infobox/template lines and citation fragments; sentences dated only in
  the past (full dates, or bare years like "In 1960") are old news; uncited sentences count only if they date
  themselves near the comeback; more than 3 added sentences (a rewrite) count only if dated near it; undated
  cited sentences are **background** (shown as sources, never read for a reason).
- **Edit summaries ignored:** reverts, typos, formatting, page protection, grammar, removals, "unsourced",
  "self-sourced", bots.
- **Cause words:** "legal" needs sentenced/sentencing, not "sentence".
- **Dated sentences anywhere in the article** are read only when nothing else explains a comeback.
- **YouTube:** the title must be a whole part of the video title or in quotes ("Shutter" ≠ "Shutter Island");
  hashtags ignored; big videos with no other reason count as "viral".
- **Bluesky:** a post about a work counts only if it also says film/song/book/watching...; a reason only when
  5+ popular posts agree; a Bluesky search page is never the link behind a reason.
- **Honors:** year-only dates moved to the usual month (Nobel → October); NFR stored as Jan 1 → allowed lead-in.
- **Title pages:** a comeback's reason comes from the latest day that found one.

Known remaining weak spots: plot or background text in edit summaries ("appears in" → sync placement),
ripples through an actor who isn't in the film, same-named different works (The Body 2001 vs a new Netflix
film), people with common names. Editor-note groups (e.g. the Bond casting) have no person photo yet.

## 7. Bluesky posting (`bluesky_post.py`, on since 2026-11-25)

- After each edition: one story post; Tue/Thu a mystery instead; Friday also the week's roundup.
- Follows the front page: new comebacks first. Quiet days skipped (story needs Rallyback Score 50+;
  mystery 45+ and 10x interest). Same title or reason not repeated within 14 days (`site/data/social.json`).
- **Every post has a picture**; stories without one are skipped; if a picture can't be fetched, up to three
  backup stories are tried; Friday roundup uses `og.png`.
- Two hashtags: kind (#Movies, #TV, #Music, #Books, #Gaming, #Comics) + #Nostalgia, as real tag facets.
- Release-day wording: "comes out today". To pause: set `BLUESKY_POST: "off"` in radar.yml.
- Preview: `python bluesky_post.py --dry-run --day YYYY-MM-DD` or `--week`.

## 8. Measuring quality: the morning report

- Scheduled task "Rallyback morning report" fires **into this session** at 4:47 a.m. Pacific
  (trigger `trig_01M2QwBJEEya6XthiqP6iDyv`). An older copy (`trig_01C85nXnZBrMYQF15uojBUnL`) that started
  fresh sessions is **paused**; those sessions had no repo access. Delete it from claude.ai's scheduled tasks.
- `python tools/nightly_report.py` prints the explained-share table (counted like the site: a same-person
  group with a reason counts as explained), evidence by source, every reason to check, and privacy checks.
- Recent explained share: 39–46% (Nov 19–25). Editor's notes have fallen 36 → 21 as old notes age out;
  new editor's notes are the quickest way up. Wrong reasons fell from ~20 of 41 (Nov 23) to 2–3 of 31 (Nov 25).

### How to test from this environment
This container can't reach most outside hosts (Wikipedia, Wikidata, Commons, news APIs). Test on GitHub:
write `.github/workflows/news-test.yml` (workflow_dispatch), push, run with
`gh api -X POST repos/inchurl2564/rally/actions/workflows/news-test.yml/dispatches -f ref=<branch>`, read logs
with `gh api .../actions/jobs/<id>/logs`, then delete the workflow. GraphQL is blocked; use REST via `gh api`.
YouTube's daily quota is shared with the nightly run (resets midnight Pacific); Currents' 250/day too (UTC).
Playwright + Chromium are pre-installed for screenshots; the chart library (cdnjs) doesn't load here.

## 9. Marketing and money (summary of the plan)

Order: owned channels (newsletter waiting on a PO box; Cloudflare Web Analytics not yet on; affiliate
sign-ups Apple + Bookshop.org) → search (title pages, IndexNow, Comeback Report) → Bluesky (automated) →
communities (Reddit OC days, Show HN, podcasts) → press (journalist query services, embeddable chart) →
newsletter growth. Revenue: affiliates first, newsletter sponsors from ~2,000 subscribers, pro alerts for
catalog owners (validate Apr–Sep 2027), chart licensing. Keep "comebacks" as the everyday word; "Rallyback"
for the name, score and an occasional wink. USPTO search for "The Rallyback": no matches (file in Class 41
after forming the LLC).

## 10. Suggested next steps

**Owner:** PO box → first Friday newsletter (then remove "first issue goes out soon"); Apple + Bookshop.org
affiliate applications; Cloudflare Web Analytics; two-factor on all accounts; SPF/DMARC records; restrict the
YouTube key; LLC → trademark; delete the paused old morning-report task; add editor's notes for big
unexplained comebacks.

**Engineering:**
1. Retry failed Wikidata batches (two derivative batches failed on 2026-11-26 → 18 "lookup failed").
2. Person photo for editor-note groups (e.g. Robert Pattinson for the Bond casting) and for same-creator
   stories (the creator's photo; the trigger qid is the new work, not the person).
3. Tighten "sync placement" from edit summaries; consider treating Hunger Games films and books as one reason
   for Bluesky repeats.
4. Update GitHub actions to Node 24 versions (deprecation warning in every run).
5. Chart library integrity hash (SRI) for d3 on cdnjs.
6. Written corrections policy (defamation risk from automated reasons) before sponsorships.
7. Once affiliates are approved: "Watch / Listen / Read / Play" buttons + Apple artwork next to Apple badges.
8. Mastodon cross-posting if Bluesky works well.
9. Monthly: export the business plan; check `WAITING.md`.

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
  "Always Use HTTPS" is on (2026-11-26): http:// forwards to https://; www forwards to the bare domain.
- **Nightly run:** GitHub Actions `.github/workflows/radar.yml`, 2 a.m. Pacific. Two cron lines (09:00 and
  10:00 UTC) cover daylight saving; a gate job lets only the right one do the work. GitHub often starts it
  up to an hour late. The main step takes ~60 minutes (2 hours on 2026-11-26 because Wikidata was slow).
- **Business plan:** Claude doc https://claude.ai/artifact/871TVez4bTz6A1SdQezwy2 (sections include Progress to
  date, What's free and what's paid, Budget, Marketing plan, Security and resilience, Implementation plan, Risks).
  Keep "Progress to date" (a dated log, newest first) and the Status column in the Step 0 table current.
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
- **Editor's notes are reader-visible:** write them, test them, but push to `main` only after the owner says
  so ("push it"). The session's permission check blocks an unapproved push of a note. A stop hook asks for
  every change to be committed and pushed: if the owner hasn't approved yet, push to a side branch (not
  `main`) and say so. Published notes need a `source` link; for a reason the owner supplies, find a primary
  source (the studio's announcement, Wikipedia) and mark it "(supplied by an editor)".

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
6. **Completeness check before saving** (`health.py --gate`, added 2026-11-26): edition files readable and
   consistent, comebacks not halved, title pages present, few "lookup failed". On a problem nothing is
   saved or published, yesterday's edition stays up, and an issue "tonight's edition was held back" emails
   the owner. To publish anyway after checking, rerun the workflow or loosen the threshold in `health.py`.
7. After commit: **IndexNow** ping (`tools/indexnow.py`), **Bluesky post** (`bluesky_post.py`, at most one a
   day), health warnings (`health.py`: a source down 3 nights, comebacks doubled, lookups or picture
   lookups failing (`picture_lookups_failed`), more comebacks than usual without a picture; issue only when
   something needs a person).
8. An extra run on the same day (Actions → Run workflow) works, but runs without YouTube and Currents once
   the nightly run has used their daily allowance (YouTube resets midnight Pacific, Currents midnight UTC),
   so news/YouTube reasons can be thinner until the next night.

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
- **Header and footer:** brand yellow #F3C716 (the icon's color) with the black logo, same in light and dark,
  on every page (since 2026-11-27). To undo: `git revert 685d6e77`, push, then run Quick fix (static pages).
- **Menu:** on its own band, black in light mode and off-white in dark mode; Subscribe is red (since 2026-11-27).
  To undo: `git revert f9f5e81b` and push.
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
Same-name spillover: people searching for a new release land on an older work with the same name (the 1977
film *Grand Theft Auto* during GTA VI). Fix with an editor's note on that title's `qids` plus `new_work`
(the new release's Wikidata ID) so it joins that story; leave `works` empty so other titles aren't caught.

## 7. Bluesky posting (`bluesky_post.py`, on since 2026-11-25)

- After each edition: one story post; Tue/Thu a mystery instead; Friday also the week's roundup.
- Follows the front page: new comebacks first. Quiet days skipped (story needs Rallyback Score 50+;
  mystery 45+ and 10x interest). Same title or reason not repeated within 14 days (`site/data/social.json`).
- **Every post has a picture**; stories without one are skipped; if a picture can't be fetched, up to three
  backup stories are tried; Friday roundup uses `og.png`.
- Two hashtags: kind (#Movies, #TV, #Music, #Books, #Gaming, #Comics) + #Nostalgia, as real tag facets.
- Release-day wording: "comes out today". To pause: set `BLUESKY_POST: "off"` in radar.yml.
- Preview: `python bluesky_post.py --dry-run --day YYYY-MM-DD` or `--week`.

## 7b. Fixing a live mistake fast (Quick fix, added 2026-11-27)

A full run takes ~90 minutes; a correction doesn't need one. **Quick fix** re-applies editor's notes and
corrections to the edition that's already live and rebuilds the pages, with no new data: ~2 minutes to run
plus 2-5 for Cloudflare, so live in under 10 minutes.
1. Add the fix: a wrong reason or headline → an editor's note in `annotations.json` (as usual); a story
   that must come down, or a wrong picture → an entry in `corrections.json` (format in `corrections.py`):
   `{"id": "...", "qid": "Q123", "action": "take down", "why": "...", "date": "YYYY-MM-DD"}` or
   `{"id": "...", "qid": "Q123", "action": "picture", "image": "Commons file.jpg" | null, "image_of": "...", ...}`.
2. Push, then run it: `gh api -X POST repos/inchurl2564/rally/actions/workflows/quickfix.yml/dispatches -f ref=main`
   (or Actions → Quick fix → Run workflow). Optional input `delete_bluesky`: a link to one of our posts to delete.
3. Check the live site. Corrections stay in force every night until the entry is removed.
Needs a full run: anything that needs new data (a new kind of reason, new numbers). `quickfix.py` locally:
`python quickfix.py --site site`.

## 8. Measuring quality: the morning report

- The report is also **emailed**: `.github/workflows/morning-report.yml` posts it as a comment on issue #1
  "Morning reports" as the GitHub bot (GitHub doesn't email you about your own actions).
- Scheduled task "Rallyback morning report" fires **into this session** at 4:47 a.m. Pacific
  (trigger `trig_01Gg1bCbduQmLTch2SiCpWaT`, moved here 2026-11-26). Two older copies are **paused**:
  `trig_01M2QwBJEEya6XthiqP6iDyv` (fired into the previous session) and `trig_01C85nXnZBrMYQF15uojBUnL`
  (started fresh sessions with no repo access). Delete both from claude.ai's scheduled tasks.
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
therallyback.com itself is unreachable from here too: to check the live site, use the same pattern with a
temporary `live-check.yml` that curls the pages (wait in a loop for a deploy), then delete it. To test the
archive locally, run `archive.build('site', ...)` with `sys.modules['radar'] = None` (skips the free-reading
lookup) on two copies (old and new code) and diff `site/`.

**Tests:** `tests/test_rules.py` (no network, under a second; `python -m pytest -q tests`) pins each matching
rule in section 6 that fixed a real wrong reason, plus the retry/carry-over, person photos, title bundles and
the check before publishing. GitHub runs them on every code push (`.github/workflows/tests.yml`). When you
fix a new wrong reason, add a test with the real example. Archive output is deterministic (identical data
gives identical files), so old/new diffs show only real changes.

### Google Search Console
"Not indexed" reasons that are intentional: **Excluded by 'noindex'** (thin title pages), **Page with
redirect** (`.html` and www addresses), **Alternate page with proper canonical tag** (the old GitHub address,
`?tab=`/`?work=` links). Every sitemap address was checked on 2026-11-26: all load directly (200), none noindex.
Search Console emails once per new reason; watch the indexed-pages count instead.

## 8b. Storage (measured 2026-11-26)

Where data lives: **GitHub repo** (source of truth, full history: code, `site/data`, title/weekly/report
pages, `store/gdelt`), **Cloudflare** (serves the current copy of `site/`), **GitHub Actions cache** (`.cache`,
temporary pageview/lookup caches, rebuilt if lost), **Beehiiv** (subscribers), **Google Forms/Sheets** (tips),
**Bluesky** (posts), **Claude** (business plan doc).
- Repo on GitHub: 22.6 MB. Each nightly data commit adds ~1.9 MB compressed (~12 MB raw), i.e. ~0.7 GB/year.
  GitHub recommends under 1 GB (reached around early 2028) and strongly under 5 GB; files over 100 MB are blocked.
- Site files: 1,516 after title data was bundled into 256 files on 2026-11-26 (was 2,467: one data file per
  title). Now growing ~80 a night (one `site/w/` page per new title). **Cloudflare Workers Free allows 20,000
  files per deploy** (Paid $5/month: 100,000) → at this pace the limit arrives around **July 2027**.
- Next options: serve thin (noindexed, ~43%) title pages from one shared page that fills itself in from the
  data (same address, so Share links keep working; needs a preview). Don't simply skip thin pages: Share
  buttons and new mysteries link to them. Or Workers Paid ($5/month). Later move old run archives out of
  git (Cloudflare R2 free tier) if the repo nears 1 GB.
- The morning report checks repo size and file count on Mondays.

## 9. Marketing and money (summary of the plan)

Order: owned channels (newsletter: PO box ready Nov 26, next is entering it in Beehiiv; Cloudflare Web Analytics not yet on; affiliate
sign-ups Apple + Bookshop.org) → search (title pages, IndexNow, Comeback Report) → Bluesky (automated) →
communities (Reddit OC days, Show HN, podcasts) → press (journalist query services, embeddable chart) →
newsletter growth. Revenue: affiliates first, newsletter sponsors from ~2,000 subscribers, pro alerts for
catalog owners (validate Apr–Sep 2027), chart licensing. Keep "comebacks" as the everyday word; "Rallyback"
for the name, score and an occasional wink. USPTO search for "The Rallyback": no matches (file in Class 41
after forming the LLC).

## 10. Suggested next steps

**Owner:** enter the PO box (Castle Bridge Media's mailing address) in Beehiiv → first Friday newsletter (then remove "first issue goes out soon"); Apple + Bookshop.org
affiliate applications; Cloudflare Web Analytics; two-factor on all accounts; SPF/DMARC records; restrict the
YouTube key; LLC → trademark; delete the two paused old morning-report tasks; delete the merged branches
`preview-monthly-report` and `note-blade-runner-2099`; add editor's notes for big unexplained comebacks.

**Engineering:**
1. ~~Retry failed Wikidata batches~~ Done 2026-11-26: failed trigger batches are retried in pieces of 3; if that
   fails too, the reason from the latest edition in the past week (same comeback) is kept (`carry_over_triggers`).
2. ~~Person photos~~ Done 2026-11-26: same-creator stories keep `person` (the creator, if a person or band,
   not a studio); editor's notes pass `entity_title`, and if that article is about a person with a free photo
   (`fetch_person_images_by_title`), the note's group story leads with them when the headline names them.
   A note needs `entity_title` for this (Wildwood's "Travis Knight" note has none). The site reads
   `site/data/runs/<date>.json`, not `latest.json`: test front-end changes against the runs file.
3. Tighten "sync placement" from edit summaries; consider treating Hunger Games films and books as one reason
   for Bluesky repeats.
4. Update GitHub actions to Node 24 versions (deprecation warning in every run).
5. Chart library integrity hash (SRI) for d3 on cdnjs.
6. Written corrections policy (defamation risk from automated reasons) before sponsorships.
7. Once affiliates are approved: "Watch / Listen / Read / Play" buttons + Apple artwork next to Apple badges.
8. Mastodon cross-posting if Bluesky works well.
8b. YouTube channel (plan from Nov 27, faceless, mostly text): a daily Short (45-60 s) from the daily list and a
   weekly 6-10 min video from the weekly roundup; 2-week trial at 5 Shorts + 1 weekly. Reads the data the site
   already publishes (`data/latest.json`, `data/runs/<date>.json`, `data/weekly/<week>.json`); script from the
   site's own headlines and reasons only (never Currents headlines or Bluesky text); Commons pictures with credit;
   music only from YouTube Audio Library or a licensed library; leave out or label "Possible" reasons; a person
   reviews every video before upload (a video can't be corrected like the site); check YouTube's AI labelling.
   Uploads manual at first (API uploads stay private until YouTube's compliance review). Vary formats (charts,
   mysteries, deep dives) to stay clear of YouTube's repetitive-content rules. Decide who builds it.
   **Sample reviewed (Nov 28):** a 64 s, 1080x1920 Short from the Nov 26 list (hook, 4 stories with animated
   charts counting up from "usual interest", 2 mysteries stamped "Reason: unknown", "Know why? Tell us in the
   comments"). All figures matched the site's `lift` exactly; keep it that way (use `lift`, not `peak_lift`).
   Before building: (1) Shorts safe zones: YouTube's title/caption covers ~the bottom fifth and its buttons the
   right edge; move the "WHY" box up and end charts ~15% in from the right; check in YouTube's preview.
   (2) Credit on each chart: "Data: Wikipedia page views · therallyback.com". (3) Use the site's specific reason,
   not a vague one ("A new adaptation of the game" for Ocarina of Time; the data says interest rose ahead of the
   release). (4) Brand: yellow title/end card with the black logo to match the site and icon; dark story screens
   can stay. (5) Don't let a "1.0x" starting frame become the thumbnail. Narration not yet reviewed.
9. Spring 2027 (before the July 2027 file limit): revisit thin title pages (no reason yet, on our list 2 days or
   less, ~43% of `site/w/`). Plan: serve them from one shared page that fills itself in from the title data, at
   the same address so Share links keep working (needs a preview). Alternative: Workers Paid ($5/month).
10. Monthly: export the business plan; check `WAITING.md`.

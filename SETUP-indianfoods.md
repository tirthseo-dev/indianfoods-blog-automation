# Setup notes for indianfoods.co.in

This repo is the generic Blog Engine (see `README.md` for the full walkthrough),
already configured for **indianfoods.co.in**. The only file that was changed is
`config.json`, plus a seeded `queue-template.csv`.

## What's already done for you

- **`config.json`** — filled in for Indian Foods: recipe categories as "services",
  Indian audience, vegetarian-first cooking, no health/nutrition claims, and
  keyword discovery set to **country `in`** (India) with recipe seed terms.
- **`queue-template.csv`** — seeded with 8 real recipe topics marked `To write`,
  so the first daily run produces a draft immediately. Review and replace these
  with your own before running at scale.

## Three things to check before you run

1. **Subscribe URL.** `cta_url` currently points to the homepage
   (`https://indianfoods.co.in`). If you have a dedicated newsletter/subscribe
   page, put it there so every draft's call-to-action links straight to it.
2. **Author byline.** Set to `Shashi, Indian Foods`. Change `author_name` and
   `author_bio` in `config.json` if you want a different byline or fuller
   credentials — a named author with real credentials helps E-E-A-T.
3. **The "US Volume" column.** Keep that exact column header in your Google
   Sheet `Queue` tab — the script reads it by name. The numbers in it are just
   India monthly search volume now; the label is cosmetic. Don't rename it.

## Quick start (full detail in README.md)

1. Create a **private GitHub repo** and upload every file. Create
   `.github/workflows/daily-blogs.yml` via *Add file → Create new file* so the
   nested folders are made.
2. New Google Sheet, first tab named exactly **`Queue`**, import
   `queue-template.csv`.
3. Create a Google **service account** (Sheets API + Drive API), download its
   JSON key, and give its `client_email` **Content manager** on a **Shared
   Drive** folder.
4. Add GitHub **Actions secrets**: `ANTHROPIC_API_KEY`,
   `GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEET_ID`, `DRIVE_FOLDER_ID`
   (and `AHREFS_API_KEY` only if you want weekly keyword discovery).
5. **Actions → Daily Blog Drafts → Run workflow** to test.

## Ahrefs is optional

The weekly keyword discovery (`discover.py` + `weekly-keywords.yml`) needs the
**paid Ahrefs API add-on**. If you don't have it, just skip it — the daily
drafting works fully on its own. Add topics to the `Queue` tab by hand.

## Publishing to WordPress

Drafts land in a Google Doc marked "Draft ready - needs human edit" — they are
**not** auto-published. For indianfoods.co.in (a WordPress site) the natural
flow is: review the draft, verify every source link and any factual claim, add
one genuine tip only your kitchen would know, then paste into a new WordPress
post. The JSON-LD block in the doc goes into the post's `<head>` (or your SEO
plugin's schema field). This human step is what keeps the site clear of
Google's scaled-content-abuse policy — see the last section of `README.md`.

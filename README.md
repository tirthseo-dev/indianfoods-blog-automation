# Blog Engine — automated SEO drafts for any website

Writes one long-form blog draft per day into a Google Doc, plus weekly keyword
discovery via Ahrefs. Runs free on GitHub Actions.

**To use it on a different website you edit ONE file: `config.json`.**
Every other file stays byte-identical.

---

## The files

| File | Edit per site? | What it does |
|---|---|---|
| `config.json` | **YES — this one** | Company name, services, audience, CTA, seed keywords, word counts |
| `generate.py` | No | Daily drafting → Google Doc |
| `discover.py` | No | Weekly Ahrefs keyword pull → Suggestions tab |
| `requirements.txt` | No | Python packages |
| `.github/workflows/daily-blogs.yml` | No | Daily scheduler |
| `.github/workflows/weekly-keywords.yml` | No | Monday scheduler |
| `queue-template.csv` | Starting point | Column headers for your Queue tab |

---

## What each draft contains

**The article** (1,500–2,000 words)
- Eyebrow category label, H1, byline
- **QUICK ANSWER** box (45–65 words — the block AI Overviews lift)
- **KEY TAKEAWAYS** box
- 7–9 question-phrased H2s, each 150–250 words, answer-first
- One data table, one H3-subdivided section, one "common mistakes" list
- Mid-article **CTA box**
- 6-question FAQ, sources with links, **ABOUT THE AUTHOR** box

**Plus a publishing pack**
- URL slug, keywords, meta title + description with character counts
- Feature image alt text, internal link suggestions
- **Valid Article + FAQPage JSON-LD** ready to paste into `<head>`
- AI Overview / LLM ranking checklist

---

## Setting it up for a NEW website

### 1. Fill in `config.json`

```json
"company": {
  "name": "Acme Plumbing",
  "site": "https://acmeplumbing.com",
  "location": "Denver, Colorado",
  "what_we_are": "a residential plumbing company",
  "services": "drain cleaning, water heaters, leak repair, repiping",
  "audience": "US homeowners, national",
  "reading_level": "a busy homeowner with no plumbing knowledge",
  "author_name": "The Acme Plumbing Team",
  "author_bio": "One or two sentences about the company.",
  "cta_url": "https://acmeplumbing.com/book",
  "cta_label": "Book a free estimate",
  "trusted_sources": "EPA, IAPMO, ICC, or a .edu/.gov source",
  "facts_to_respect": "Any domain facts the model must not get wrong."
}
```

Then the discovery seeds — one broad term per service area:

```json
"seeds": {
  "Drain Cleaning": "clogged drain",
  "Water Heaters": "water heater",
  "Leak Repair": "water leak"
}
```

Tune `min_volume`, `max_kd`, and `per_service` to taste. KD ≤ 30 suits a newer
site; raise it once you have authority.

### 2. Google Sheet

- New Sheet, first tab named exactly **`Queue`**
- Import `queue-template.csv`, then fill in your topics
- Copy the Sheet ID from the URL (between `/d/` and `/edit`)
- `Content` and `Suggestions` tabs are created automatically

### 3. Google service account

1. console.cloud.google.com → new project
2. Enable **Google Sheets API** and **Google Drive API**
3. APIs & Services → Credentials → Create Credentials → Service account
4. Open it → Keys → Add Key → JSON → download
5. Copy the `client_email` from that JSON

### 4. Shared Drive (required)

Service accounts have **no Drive storage of their own**, so a normal My Drive
folder fails with a quota error. Use a Shared Drive:

1. Drive → **Shared drives** → **+ New**
2. Add the `client_email` as a **Content manager**
3. Create a folder inside it, copy the folder ID from the URL

### 5. GitHub

Create a private repo, upload all files (create
`.github/workflows/daily-blogs.yml` via *Add file → Create new file* so the
nested folders get made), then add these secrets under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from console.anthropic.com (needs billing set up) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the whole JSON key file, `{` to `}` |
| `SHEET_ID` | from the Sheet URL |
| `DRIVE_FOLDER_ID` | the Shared Drive folder |
| `AHREFS_API_KEY` | only for keyword discovery |

### 6. Test

**Actions → Daily Blog Drafts → Run workflow.** Expect 60–120 seconds. The log
prints word counts at each stage:

```
draft: 1823 words
humanising...
humanised: 1654 words
building publishing pack...
done: https://docs.google.com/document/d/...
```

Under 20 seconds means it failed — check the Queue tab's Status column, where
the error is written in full.

---

## How keyword discovery works

Mondays, `discover.py`:

1. Calls Ahrefs `matching-terms` with `terms=questions` for each seed
2. Filters on `min_volume` and `max_kd`
3. Drops anything already in Queue, Content, or Suggestions
4. Writes the top `per_service` candidates into **`Suggestions`**

It never writes to Queue directly. You skim the suggestions, then copy the good
rows across with Status `To write`. Raw keyword pulls always contain off-topic
junk — the two-minute review is what keeps the queue clean.

**Note:** the Ahrefs *API* is a paid add-on billed in units, separate from a
normal Ahrefs subscription. If your plan lacks it, skip `discover.py` and the
weekly workflow entirely; the daily drafting works fine without them.

---

## Common failures

| Error | Fix |
|---|---|
| `credit balance is too low` | Add funds at console.anthropic.com; enable auto-reload |
| `storage quota has been exceeded` | Folder isn't in a Shared Drive |
| `The caller does not have permission` | Share the folder with the service account as Editor/Content manager |
| `Worksheet not found: Queue` | First tab must be named exactly `Queue` |
| `ModuleNotFoundError: markdown` | `requirements.txt` is missing `markdown>=3.5` |
| Green check but no output | A per-topic error was caught — read the Queue Status column |

---

## The part that isn't automated

Drafts land marked **"Draft ready - needs human edit"** and stop there. Before
publishing, every time:

1. **Click every source link.** Models occasionally produce URLs that look right
   and 404. This is the highest-value check.
2. **Verify factual specifics** — numbers, dates, policies.
3. **Add one insight only your company could write.** A pattern you actually see
   in your work. This is what makes the page non-replaceable.
4. **Use a named author with credentials** where you can, not just a team byline.

Google's scaled content abuse policy targets pages generated primarily to
manipulate rankings with little value added — the method doesn't matter, and
neither does the volume in isolation. Sites using AI inside a genuine editorial
process came through the March 2026 update fine. Sites publishing unreviewed
bulk did not. The ten-minute edit is the whole difference.

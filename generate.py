#!/usr/bin/env python3
"""
Blog draft generator -- config-driven, works for any website.

Reads the next N topics marked "To write" from the Queue tab, then per topic:
  1. Claude writes a structured long-form draft
  2. Claude rewrites it for human voice (without shortening)
  3. Word count is checked; a expansion pass runs if it came in short
  4. Claude produces a publishing pack (meta tags, internal links, checklist)
  5. Valid Article + FAQPage JSON-LD is built in Python
  6. It's all uploaded to Drive as a formatted Google Doc
  7. A row lands in the Content tab and the Queue row is marked done

ALL site-specific settings live in config.json. This file never changes
between websites.

Environment variables:
  ANTHROPIC_API_KEY            key from console.anthropic.com
  GOOGLE_SERVICE_ACCOUNT_JSON  service account key JSON
  SHEET_ID                     id from your Sheet URL
  DRIVE_FOLDER_ID              folder inside a SHARED DRIVE
"""
import argparse, datetime, io, json, os, re, sys
import urllib.request, urllib.error

import gspread
import markdown as md_lib
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
    CFG = json.load(f)

CO = CFG["company"]
ART = CFG["article"]
BANNED = ", ".join(f'"{p}"' for p in CFG["banned_phrases"])

MODEL = ART.get("model", "claude-sonnet-5")
MIN_WORDS = ART.get("min_words", 1500)
MAX_WORDS = ART.get("max_words", 2000)
SITE = CO["site"].rstrip("/")

API_URL = "https://api.anthropic.com/v1/messages"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
QUEUE_TAB, CONTENT_TAB = "Queue", "Content"
DONE = "Draft ready - needs human edit"
CELL_LIMIT = 49000

CONTENT_HEADERS = ["Date", "Service", "Blog Title", "Primary Keyword",
                   "US Volume", "KD", "Doc Link", "Full Content", "Status"]


# ------------------------------------------------------------------ Claude

def claude(prompt, max_tokens=8000):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ERROR: ANTHROPIC_API_KEY is not set.")
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Anthropic {e.code}: {detail}") from None
    return "".join(b["text"] for b in data["content"] if b["type"] == "text").strip()


def draft_prompt(row):
    return f"""Write a blog post for {CO['name']}, {'a ' if not CO['location'] else CO['location'] + '-based '}{CO['what_we_are']}
({CO['services']}). Audience: {CO['audience']}.

TOPIC BRIEF
- Title: {row['Blog Title']}
- Service area: {row['Service']}
- Primary keyword: {row['Primary Keyword']}
- Secondary keywords: {row.get('Secondary Keywords', '')}
- Search intent: {row.get('Search Intent', 'Informational')}

LENGTH: {MIN_WORDS}-{MAX_WORDS} words of body copy. This is a firm floor, not a
target to approach. A short draft is a failed draft. Reach the length by
covering the topic exhaustively -- never by padding or repeating yourself.

DEPTH REQUIREMENTS
- Cover EVERY question a reader would reasonably have about this topic.
- Each H2 section must run {ART['words_per_section']} words: the direct answer, then the
  explanation, then a concrete example or "what this looks like in practice".
- Anticipate the follow-up. State a rule, then address the common exception.
- Include practical specifics: timelines, sequences, what to do first.

Output EXACTLY this structure in markdown. Use the ::: block syntax verbatim
where shown -- those become callout boxes.

EYEBROW: <2-3 word ALL-CAPS category>

# {row['Blog Title']}

*By {CO['author_name']}  ·  Updated {datetime.date.today().strftime('%B %Y')}  ·  <N> min read*

:::quick-answer
QUICK ANSWER
<A direct 45-65 word answer to the core question. Self-contained, factual, and
liftable by AI Overviews. No preamble.>
:::

:::key-takeaways
KEY TAKEAWAYS
- <{ART['takeaway_count']} bold one-line takeaways, each a complete, useful statement>
:::

<One short intro paragraph, 60-90 words. No throat-clearing.>

## <Question-phrased H2, mirroring People Also Ask>

<Lead with a direct, extractable answer in the first sentence, key phrase in
bold. Then develop it properly to {ART['words_per_section']} words.>

<Repeat for {ART['sections']} H2 sections. Requirements across the article:>
- ONE markdown table organising something genuinely tabular (structure,
  timeline, comparison). GFM pipe syntax.
- At least one H2 broken into 2-4 H3 sub-sections for a topic with real parts.
- One H2 that is a bulleted "common mistakes" list, with a sentence of
  explanation under each -- not bare bullets.
- Cover the practical "how do I actually start" angle somewhere.

:::cta
**<Short question or hook relevant to this topic>**
<2 sentences on how {CO['name']} helps with THIS specific topic. Warm, not salesy.>
**→ {CO['cta_label']} at {CO['cta_url']}**
:::

## <One more H2 section after the CTA>

## Frequently asked questions

### <Question 1>

<1-3 sentence direct answer.>

<{ART['faq_count']} FAQs total, each phrased as a real search query.>

## Sources

- [<Descriptive link text>](<real, authoritative URL: {CO['trusted_sources']}>)
- <2-3 sources total. Only cite pages you are confident exist. Prefer the
  official organisation's main page over a deep link you are unsure about.>

:::author
ABOUT THE AUTHOR
{CO['author_bio']}
:::

RULES
- Every H2 must be a question a real person would type, except "Sources".
- Each section leads with the answer, then explains. Never bury it.
- NEVER invent statistics, studies, percentages, or research findings. To make
  a quantitative point, phrase it qualitatively instead.
- Facts must be accurate and current. {CO['facts_to_respect']}
- Write for {CO['reading_level']}. Second person. Contractions.
- Return ONLY the markdown. No preamble, no explanation, no code fences."""


def humanise_prompt(article, row):
    return f"""Rewrite the blog draft below so it reads like an experienced {CO['name']}
professional wrote it, not an AI. Keep the EXACT same structure: same headings,
same ::: blocks, same table, same FAQ questions, same sources, and the keyword
"{row['Primary Keyword']}".

LENGTH IS CRITICAL: the rewrite must be the SAME LENGTH OR LONGER than the
draft -- {MIN_WORDS}-{MAX_WORDS} words minimum. Do not condense, summarise, or
trim sections. Rewriting for voice usually shortens text; resist that. If a
section feels thin after rewriting, deepen it with a concrete example rather
than letting it shrink.

Fix these AI tells:
- DELETE entirely: {BANNED}.
- Kill the rule-of-three habit ("clear, concise, and compelling"). Real writers
  don't triple everything.
- Vary sentence length hard. Follow a 30-word sentence with a 4-word one.
  Fragments are fine. Start a sentence with "But" or "And" where it lands.
- Replace vague claims with concrete ones. Never fabricate statistics, studies,
  or named research.
- Cut hedging. Get to the point in the first six words of each section.
- Allow mild bluntness and a little opinion.
- Some sections should be plain prose, not everything bulleted.

Do NOT change: the EYEBROW line, the byline line, the ::: block markers, the
markdown table syntax, the source URLs, or the heading hierarchy.

Return ONLY the rewritten markdown. No preamble, no code fences.

DRAFT:
{article}"""


def expand_prompt(article, row, current):
    return f"""The article below is {current} words. It needs to be {MIN_WORDS}-{MAX_WORDS}.

Expand it to at least {MIN_WORDS} words WITHOUT changing its structure. Keep
every heading, every ::: block, the table, the FAQ questions, and the sources
exactly as they are, in the same order.

Add real substance only:
- Deepen thin H2 sections toward {ART['words_per_section']} words each with concrete examples
  or edge cases.
- Add practical specifics: sequences, timelines, what changes by situation.
- Answer follow-up questions a reader would have after each section.

Do NOT: add new headings, pad with filler, repeat points already made, or add
throat-clearing transitions. Do NOT invent statistics. Keep the same human
voice and avoid: {BANNED}.

Return ONLY the expanded markdown. No preamble, no code fences.

ARTICLE:
{article}"""


def pack_prompt(article, row):
    return f"""Below is a finished blog post for {CO['name']}. Produce a publishing pack for
whoever uploads it. Return ONLY markdown in exactly this shape:

### Page setup

**URL slug:** /blog/<kebab-case-slug-from-the-primary-keyword>

**Primary keyword:** {row['Primary Keyword']}

**Secondary keywords:** <4-5 comma-separated>

**Meta title:** <=60 characters, includes the primary keyword>  (<N> chars)

**Meta description:** <=155 characters, includes the primary keyword, ends with
a reason to click>  (<N> chars)

**Feature image alt text:** <descriptive, includes the topic and {CO['name']}>

### Internal links to add

- Anchor "<natural anchor phrase>" -> /blog/<related-slug>
- <3-4 suggestions relevant to this site's topics>

### AI Overview / LLM ranking checklist

- <6-8 bullets stating what this draft does that helps it get cited by AI
  Overviews, ChatGPT, and Perplexity. Be specific to THIS article.>

Count characters in the meta title and description accurately.

ARTICLE:
{article[:6000]}"""


# ------------------------------------------------- markdown -> HTML -> Doc

BOX_STYLES = {
    "quick-answer": ("#E8F0FE", "#1A73E8"),
    "key-takeaways": ("#F1F3F4", "#5F6368"),
    "cta": ("#FEF7E0", "#F9AB00"),
    "author": ("#F8F9FA", "#DADCE0"),
}
BOX_RE = re.compile(r"^:::([a-z-]+)\s*\n(.*?)\n:::\s*$", re.S | re.M)


def word_count(md_text):
    t = re.sub(r"^EYEBROW:.*$", "", md_text, flags=re.M)
    t = re.sub(r"^:::[a-z-]*$", "", t, flags=re.M)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[|#*_>`-]", " ", t)
    return len(t.split())


def _md(text):
    return md_lib.markdown(text, extensions=["tables", "sane_lists"])


def md_to_html(md_text, title):
    eyebrow = ""
    m = re.search(r"^EYEBROW:\s*(.+)$", md_text, re.M)
    if m:
        eyebrow = m.group(1).strip()
        md_text = md_text[: m.start()] + md_text[m.end():]

    boxes = []

    def stash(match):
        kind, inner = match.group(1), match.group(2).strip()
        bg, border = BOX_STYLES.get(kind, ("#F8F9FA", "#DADCE0"))
        lines = inner.split("\n")
        label = ""
        if lines and lines[0].isupper() and len(lines[0]) < 40:
            label, lines = lines[0], lines[1:]
        body = _md("\n".join(lines).strip())
        head = (f'<p style="margin:0 0 6pt 0;font-size:9pt;letter-spacing:1px;'
                f'color:{border};"><b>{label}</b></p>' if label else "")
        boxes.append(
            f'<table style="width:100%;border-collapse:collapse;border:1pt solid '
            f'{border};background-color:{bg};"><tr><td style="padding:10pt 12pt;">'
            f'{head}{body}</td></tr></table>')
        return f"\n\nBOXPLACEHOLDER{len(boxes) - 1}\n\n"

    md_text = BOX_RE.sub(stash, md_text)
    body_html = _md(md_text)
    for i, box in enumerate(boxes):
        body_html = body_html.replace(f"<p>BOXPLACEHOLDER{i}</p>", box)
        body_html = body_html.replace(f"BOXPLACEHOLDER{i}", box)

    eyebrow_html = (f'<p style="font-size:9pt;letter-spacing:2px;color:#5F6368;'
                    f'margin:0;"><b>{eyebrow}</b></p>' if eyebrow else "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.5; }}
h1 {{ font-size: 20pt; margin: 4pt 0 2pt 0; }}
h2 {{ font-size: 14pt; margin: 18pt 0 4pt 0; }}
h3 {{ font-size: 12pt; margin: 12pt 0 3pt 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; }}
th, td {{ border: 1pt solid #DADCE0; padding: 6pt 8pt; text-align: left;
          vertical-align: top; }}
th {{ background-color: #F1F3F4; }}
</style></head><body>
{eyebrow_html}
{body_html}
</body></html>"""


def faq_jsonld(md_text, title, slug):
    faqs = []
    m = re.search(r"^##\s*Frequently asked questions\s*$(.*?)(?=^##\s|\Z)",
                  md_text, re.S | re.M | re.I)
    if m:
        for q, a in re.findall(r"^###\s*(.+?)\s*$\n+(.*?)(?=^###\s|\Z)",
                               m.group(1), re.S | re.M):
            answer = " ".join(a.strip().split())
            answer = re.sub(r"[*_`\[\]]|\(https?://[^)]+\)", "", answer).strip()
            if answer:
                faqs.append({"@type": "Question", "name": q.strip().strip("*"),
                             "acceptedAnswer": {"@type": "Answer",
                                                "text": answer[:900]}})
    today = datetime.date.today().isoformat()
    article = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title[:110],
        "author": {"@type": "Organization", "name": CO["author_name"],
                   "url": SITE},
        "publisher": {"@type": "Organization", "name": CO["name"], "url": SITE},
        "datePublished": today, "dateModified": today,
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{SITE}/blog/{slug}"},
    }
    blocks = [json.dumps(article, indent=2)]
    if faqs:
        blocks.append(json.dumps({"@context": "https://schema.org",
                                  "@type": "FAQPage", "mainEntity": faqs},
                                 indent=2))
    return blocks


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70]


def create_doc(drive, title, html, folder_id):
    if not folder_id:
        sys.exit("ERROR: DRIVE_FOLDER_ID must be set.")
    media = MediaIoBaseUpload(io.BytesIO(html.encode("utf-8")),
                              mimetype="text/html", resumable=False)
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document",
            "parents": [folder_id]}
    f = drive.files().create(body=meta, media_body=media, fields="id",
                             supportsAllDrives=True).execute()
    return f"https://docs.google.com/document/d/{f['id']}/edit"


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1)
    args = ap.parse_args()

    sheet_id = os.environ.get("SHEET_ID")
    folder_id = os.environ.get("DRIVE_FOLDER_ID", "").strip()
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sheet_id or not raw:
        sys.exit("ERROR: SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON must be set.")

    print(f"Site: {CO['name']} ({SITE})")

    c = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    gc = gspread.authorize(c)
    drive = build("drive", "v3", credentials=c, cache_discovery=False)

    sh = gc.open_by_key(sheet_id)
    q = sh.worksheet(QUEUE_TAB)
    try:
        content = sh.worksheet(CONTENT_TAB)
    except gspread.exceptions.WorksheetNotFound:
        content = sh.add_worksheet(title=CONTENT_TAB, rows=300, cols=12)
    if not content.row_values(1):
        content.append_row(CONTENT_HEADERS, value_input_option="RAW")

    rows = q.get_all_records()
    headers = q.row_values(1)
    if "Status" not in headers:
        sys.exit("ERROR: The 'Queue' tab needs a 'Status' column.")
    status_col = headers.index("Status") + 1

    todo = [(i + 2, r) for i, r in enumerate(rows)
            if str(r.get("Status", "")).strip().lower() in ("", "to write")]
    if not todo:
        print("Nothing to write. Add rows to Queue with Status 'To write'.")
        return

    today = datetime.date.today().isoformat()
    made = 0

    for row_num, row in todo[: args.count]:
        title = str(row.get("Blog Title", "")).strip()
        if not title:
            continue
        print(f"\nDrafting: {title}")
        try:
            draft = claude(draft_prompt(row))
            print(f"  draft: {word_count(draft)} words")
            print("  humanising...")
            final = claude(humanise_prompt(draft, row))

            wc = word_count(final)
            print(f"  humanised: {wc} words")
            if wc < MIN_WORDS:
                print(f"  short of {MIN_WORDS} - expanding...")
                final = claude(expand_prompt(final, row, wc))
                wc = word_count(final)
                print(f"  expanded: {wc} words")
                if wc < MIN_WORDS:
                    print(f"  WARNING: still {wc} words, below the floor")

            print("  building publishing pack...")
            pack = claude(pack_prompt(final, row), max_tokens=2000)

            slug = slugify(row.get("Primary Keyword") or title)
            jsonld = faq_jsonld(final, title, slug)

            article_html = md_to_html(final, title)
            pack_html = md_to_html(
                "# AI Overview & LLM Optimization Pack\n\n"
                "*Implementation reference for whoever publishes this post.*\n\n"
                + pack + "\n\n### Structured data to embed in &lt;head&gt;\n", title)
            body_pack = pack_html.split("<body>", 1)[1].rsplit("</body>", 1)[0]
            schema_html = "".join(
                f'<pre style="font-family:Consolas,monospace;font-size:8pt;'
                f'background:#F8F9FA;border:1pt solid #DADCE0;padding:8pt;'
                f'white-space:pre-wrap;">&lt;script type="application/ld+json"&gt;\n'
                f'{b.replace("<", "&lt;").replace(">", "&gt;")}\n'
                f'&lt;/script&gt;</pre>' for b in jsonld)

            full_html = article_html.replace(
                "</body>",
                f'<hr style="margin:24pt 0;">{body_pack}{schema_html}</body>')

            link = create_doc(drive, title, full_html, folder_id)
        except Exception as e:
            q.update_cell(row_num, status_col, f"ERROR: {e}"[:300])
            print(f"  FAILED: {e}")
            continue

        content.append_row(
            [today, row.get("Service", ""), title, row.get("Primary Keyword", ""),
             str(row.get("US Volume", "")), str(row.get("KD", "")),
             link, final[:CELL_LIMIT], DONE],
            value_input_option="RAW")
        q.update_cell(row_num, status_col, DONE)
        made += 1
        print(f"  done: {link}")

    print(f"\nFinished. {made} draft(s) written.")


if __name__ == "__main__":
    main()

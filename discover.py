#!/usr/bin/env python3
"""
Weekly keyword discovery via the Ahrefs API -- config-driven.

For each seed term in config.json, pulls question-style keyword ideas, filters
them on volume and difficulty, drops anything already in your Queue/Content/
Suggestions tabs, and writes the survivors into a "Suggestions" tab.

Nothing goes into the Queue automatically. You review, then copy the good rows
across with Status "To write". This is deliberate -- raw keyword pulls contain
off-topic terms, duplicates, and things you have already covered.

Environment variables:
  AHREFS_API_KEY               Ahrefs API token (paid API add-on)
  GOOGLE_SERVICE_ACCOUNT_JSON  service account key JSON
  SHEET_ID                     your Sheet id
"""
import json, os, sys, urllib.request, urllib.parse, urllib.error, datetime

import gspread
from google.oauth2.service_account import Credentials

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
    CFG = json.load(f)

DISC = CFG["discovery"]
SEEDS = DISC["seeds"]
COUNTRY = DISC.get("country", "us")
MIN_VOLUME = DISC.get("min_volume", 150)
MAX_KD = DISC.get("max_kd", 30)
PER_SERVICE = DISC.get("per_service", 4)

AHREFS_URL = "https://api.ahrefs.com/v3/keywords-explorer/matching-terms"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SUGGEST_TAB = "Suggestions"

HEADERS = ["Found", "Service", "Suggested Title", "Primary Keyword",
           "Volume", "KD", "Traffic Potential", "Approve?"]


def ahrefs(seed):
    token = os.environ.get("AHREFS_API_KEY")
    if not token:
        sys.exit("ERROR: AHREFS_API_KEY is not set.")
    params = urllib.parse.urlencode({
        "country": COUNTRY,
        "keywords": seed,
        "select": "keyword,volume,difficulty,traffic_potential",
        "terms": "questions",
        "match_mode": "terms",
        "order_by": "volume:desc",
        "limit": 60,
    })
    req = urllib.request.Request(
        f"{AHREFS_URL}?{params}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r).get("keywords", [])
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"Ahrefs {e.code}: {detail}") from None


def title_case(kw):
    t = kw.strip()
    t = t[0].upper() + t[1:]
    if t.lower().startswith(("how ", "what ", "when ", "why ", "should ",
                             "can ", "do ", "does ", "is ", "are ", "which ")):
        t += "?"
    return t


def main():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.environ.get("SHEET_ID")
    if not raw or not sheet_id:
        sys.exit("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON and SHEET_ID must be set.")

    print(f"Site: {CFG['company']['name']} | country={COUNTRY} "
          f"| filters: volume>={MIN_VOLUME}, KD<={MAX_KD}")

    gc = gspread.authorize(
        Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES))
    sh = gc.open_by_key(sheet_id)

    seen = set()
    for tab in ("Queue", "Content", SUGGEST_TAB):
        try:
            for r in sh.worksheet(tab).get_all_records():
                kw = str(r.get("Primary Keyword", "")).strip().lower()
                if kw:
                    seen.add(kw)
        except gspread.exceptions.WorksheetNotFound:
            pass
    print(f"Already covered: {len(seen)} keyword(s)")

    try:
        ws = sh.worksheet(SUGGEST_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=SUGGEST_TAB, rows=500, cols=10)
    if not ws.row_values(1):
        ws.append_row(HEADERS, value_input_option="RAW")

    today = datetime.date.today().isoformat()
    new_rows = []

    for service, seed in SEEDS.items():
        try:
            results = ahrefs(seed)
        except Exception as e:
            print(f"{service}: FAILED - {e}")
            continue

        picked = 0
        for k in results:
            kw = (k.get("keyword") or "").strip()
            vol = k.get("volume") or 0
            kd = k.get("difficulty")
            tp = k.get("traffic_potential") or 0
            if not kw or kw.lower() in seen:
                continue
            if vol < MIN_VOLUME or kd is None or kd > MAX_KD:
                continue
            seen.add(kw.lower())
            new_rows.append([today, service, title_case(kw), kw, vol, kd, tp, ""])
            picked += 1
            if picked >= PER_SERVICE:
                break
        print(f"{service}: {picked} new candidate(s)")

    if not new_rows:
        print("\nNo new candidates passed the filters this run.")
        return

    ws.append_rows(new_rows, value_input_option="RAW")
    print(f"\nAdded {len(new_rows)} suggestions to '{SUGGEST_TAB}'.")
    print("Review them, then copy good rows into Queue with Status 'To write'.")


if __name__ == "__main__":
    main()

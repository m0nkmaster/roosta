"""Public feeds for the Office lounge TV: BBC headlines and the daily Bamboozle! quiz."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from roosta import paths

log = logging.getLogger(__name__)

NEWS_FEEDS = {"news": "https://feeds.bbci.co.uk/news/rss.xml", "sport": "https://feeds.bbci.co.uk/sport/rss.xml"}
NEWS_TTL = 900


def parse_rss(xml_bytes: bytes, limit: int = 10) -> list[dict]:
    """Headline + standfirst pairs from an RSS 2.0 feed."""
    import xml.etree.ElementTree as ET
    out = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        title = (item.findtext("title") or "").strip()
        if title:
            out.append({"title": title, "summary": (item.findtext("description") or "").strip(),
                        "link": (item.findtext("link") or "").strip()})
        if len(out) >= limit:
            break
    return out


def lead_paragraphs(page_html: str, limit: int = 2) -> list[str]:
    """The opening paragraphs of a BBC article: the <p>s inside its text-block components."""
    import html as html_lib
    out = []
    for block in re.findall(r'data-component="text-block".*?</div>', page_html, re.S):
        for p in re.findall(r"<p\b[^>]*>(.*?)</p>", block, re.S):
            text = html_lib.unescape(re.sub(r"<[^>]+>", "", p)).strip()
            if text:
                out.append(text)
            if len(out) >= limit:
                return out
    return out


def _fetch(url: str, limit: int) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "office-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read(limit)


def _article_body(item: dict) -> None:
    try:
        item["body"] = lead_paragraphs(_fetch(item["link"], 2_000_000).decode("utf-8", "replace")) if item.get("link") else []
    except Exception:  # no body is fine: the page falls back to the RSS standfirst
        item["body"] = []


def fetch_news() -> dict:
    from concurrent.futures import ThreadPoolExecutor
    sections = {}
    for name, url in NEWS_FEEDS.items():
        try:
            sections[name] = parse_rss(_fetch(url, 1_000_000))
        except Exception as exc:  # a dead feed shows as "not in transmission", never breaks the page
            log.info("news feed %s failed: %s", name, exc)
            sections[name] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_article_body, [it for items in sections.values() for it in items]))
    return {"source": "BBC", "fetched": datetime.now(timezone.utc).isoformat(), "sections": sections}


# Bamboozle! (the Teletext quiz) on the lounge TV: ten fresh questions a day, easiest first.
BAMBOOZLE_FILE = paths.CACHE_DIR / "bamboozle.json"
BAMBOOZLE_SOURCES = (
    ("The Trivia API", "https://the-trivia-api.com/v2/questions?limit=10&region=GB"),
    ("Open Trivia DB", "https://opentdb.com/api.php?amount=10&type=multiple&encode=url3986"),
)
BAMBOOZLE_MIN = 5


def parse_quiz(source: str, payload) -> list[dict]:
    """Normalise either trivia API into {question, category, difficulty, correct, wrong}."""
    out = []
    if source == "Open Trivia DB":
        rows = (payload or {}).get("results") or []
        get = lambda r: (unquote(r.get("question") or ""), unquote(r.get("category") or ""), r.get("difficulty"),
                         unquote(r.get("correct_answer") or ""), [unquote(a) for a in r.get("incorrect_answers") or []])
    else:
        rows = payload if isinstance(payload, list) else []
        get = lambda r: (((r.get("question") or {}).get("text") or ""), (r.get("category") or "").replace("_", " "),
                         r.get("difficulty"), r.get("correctAnswer") or "", list(r.get("incorrectAnswers") or []))
    for row in rows:
        try:
            q, cat, diff, right, wrong = get(row)
        except (AttributeError, TypeError):
            continue
        q, right, wrong = str(q).strip(), str(right).strip(), [str(a).strip() for a in wrong][:3]
        if not q or not right or len(wrong) != 3 or len({right, *wrong}) != 4 or not all(wrong):
            continue  # every question needs four distinct answers, one per coloured key
        out.append({"question": q, "category": str(cat).strip().upper(), "difficulty": diff if diff in ("easy", "medium", "hard") else "medium",
                    "correct": right, "wrong": wrong})
    return out


def build_quiz(day: str, source: str, questions: list[dict]) -> dict:
    """Order easiest first and shuffle answers reproducibly for the day."""
    import random
    rank = {"easy": 0, "medium": 1, "hard": 2}
    rng = random.Random(day)
    out = []
    for q in sorted(questions, key=lambda q: rank[q["difficulty"]])[:10]:
        options = [q["correct"], *q["wrong"]]
        rng.shuffle(options)
        out.append({"question": q["question"], "category": q["category"], "difficulty": q["difficulty"],
                    "options": options, "answer": options.index(q["correct"])})
    return {"date": day, "source": source, "questions": out}


def fetch_quiz_questions() -> tuple[str, list[dict]] | None:
    import urllib.request
    for source, url in BAMBOOZLE_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "office-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                questions = parse_quiz(source, json.loads(resp.read(1_000_000)))
            if len(questions) >= BAMBOOZLE_MIN:
                return source, questions
        except Exception as exc:  # try the next source; no source means an off-air page, not an error
            log.info("quiz source %s failed: %s", source, exc)
    return None


def daily_quiz(day: str, cache_file: Path = BAMBOOZLE_FILE, fetch=fetch_quiz_questions) -> dict | None:
    """Today's quiz, fetched once a day; yesterday's set (marked stale) if every source is down."""
    try:
        cached = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cached = None
    if cached and cached.get("date") == day:
        return cached
    got = fetch()
    if got:
        quiz = build_quiz(day, *got)
        paths.write_json(cache_file, quiz)
        return quiz
    return {**cached, "stale": True} if cached else None

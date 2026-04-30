#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_LIMIT_PER_SOURCE = 50
USER_AGENT = "trade-bot-news-research/0.1"

DEFAULT_SOURCES = [
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
    ("fed_monetary", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("sec_press", "https://www.sec.gov/news/pressreleases.rss"),
]

SYMBOL_TERMS: dict[str, list[str]] = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ether", "ethereum"],
    "SOL": ["sol", "solana"],
    "XRP": ["xrp", "ripple"],
    "BNB": ["bnb", "binance coin"],
    "TON": ["toncoin", "the open network"],
    "ZEC": ["zec", "zcash"],
    "TRX": ["trx", "tron"],
    "SUI": ["sui"],
    "ADA": ["ada", "cardano"],
    "AAVE": ["aave"],
    "LINK": ["chainlink"],
    "AXS": ["axs", "axie"],
    "AVAX": ["avax", "avalanche"],
    "LTC": ["ltc", "litecoin"],
    "APT": ["aptos"],
    "NEAR": ["near protocol"],
    "LDO": ["ldo", "lido"],
    "XLM": ["xlm", "stellar"],
    "HBAR": ["hbar", "hedera"],
    "ARB": ["arbitrum"],
    "UNI": ["uniswap"],
    "INJ": ["inj", "injective"],
    "DOT": ["polkadot"],
    "BCH": ["bch", "bitcoin cash"],
}

EVENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("security_incident", ["hack", "hacked", "exploit", "exploited", "stolen", "breach", "drain", "phishing"]),
    ("regulatory", ["sec", "cftc", "lawsuit", "sues", "sued", "settlement", "regulator", "regulatory", "court", "judge"]),
    ("macro_policy", ["federal reserve", "fed ", "fomc", "rate cut", "rate hike", "interest rates", "inflation", "cpi", "pce", "gdp"]),
    ("listing", ["listing", "lists ", "listed on", "launchpool"]),
    ("delisting", ["delist", "delisted", "suspends trading", "trading halt"]),
    ("token_unlock", ["unlock", "vesting", "token release"]),
    ("protocol_upgrade", ["upgrade", "hard fork", "mainnet", "halving", "fork", "proposal", "governance"]),
    ("fund_flow", ["etf", "inflow", "outflow", "treasury", "reserve", "buys", "bought", "accumulates"]),
    ("market_structure", ["liquidation", "open interest", "funding", "short squeeze", "long squeeze"]),
    ("partnership", ["partnership", "integrates", "integration", "collaboration", "adopts", "adoption"]),
]

NEGATIVE_WORDS = {
    "hack",
    "hacked",
    "exploit",
    "stolen",
    "breach",
    "sues",
    "sued",
    "lawsuit",
    "delist",
    "delisted",
    "outflow",
    "plunge",
    "falls",
    "crash",
    "liquidation",
    "bankrupt",
    "fraud",
}

POSITIVE_WORDS = {
    "approval",
    "approves",
    "approved",
    "etf",
    "inflow",
    "buys",
    "bought",
    "adopts",
    "adoption",
    "partnership",
    "upgrade",
    "mainnet",
    "rally",
    "surges",
    "record",
}

HIGH_SEVERITY_WORDS = {
    "hack",
    "exploit",
    "stolen",
    "sec",
    "lawsuit",
    "etf",
    "fed",
    "fomc",
    "cpi",
    "halving",
    "delist",
}


@dataclass(frozen=True)
class FeedItem:
    source: str
    source_url: str
    title: str
    url: str | None
    published_at: int | None
    summary: str | None


@dataclass(frozen=True)
class ClassifiedEvent:
    event_key: str
    source: str
    source_url: str
    title: str
    url: str | None
    published_at: int | None
    fetched_at: int
    event_type: str
    scope: str
    sentiment: str
    severity: int
    confidence: float
    symbols: list[str]
    bases: list[str]
    tags: list[str]
    summary: str | None
    classification: dict[str, Any]


def normalize_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def lower_words(value: str) -> str:
    return f" {normalize_text(value).lower()} "


def parse_timestamp(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def child_text(element: ET.Element, names: set[str]) -> str | None:
    for child in list(element):
        if tag_name(child) in names and child.text:
            return normalize_text(child.text)
    return None


def child_link(element: ET.Element) -> str | None:
    for child in list(element):
        name = tag_name(child)
        if name == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
            if child.text:
                return normalize_text(child.text)
        if name == "guid" and child.text:
            return normalize_text(child.text)
    return None


def parse_feed(source: str, source_url: str, payload: bytes, limit: int) -> list[FeedItem]:
    root = ET.fromstring(payload.decode("utf-8-sig", errors="replace"))
    items: list[ET.Element] = []
    for element in root.iter():
        if tag_name(element) in {"item", "entry"}:
            items.append(element)

    parsed: list[FeedItem] = []
    for item in items[:limit]:
        title = child_text(item, {"title"})
        if not title:
            continue
        published_at = parse_timestamp(
            child_text(item, {"pubdate", "published", "updated", "date"})
        )
        parsed.append(
            FeedItem(
                source=source,
                source_url=source_url,
                title=title,
                url=child_link(item),
                published_at=published_at,
                summary=child_text(item, {"description", "summary", "content"}),
            )
        )
    return parsed


def term_matches(text: str, term: str, base: str) -> bool:
    if base == "BTC" and term == "bitcoin" and " bitcoin cash " in text:
        return False
    if len(term) <= 5 and term.isalnum():
        return f" {term.lower()} " in text or f"${term.lower()} " in text
    return term.lower() in text


def detect_symbols(title: str, summary: str | None) -> tuple[list[str], list[str]]:
    text = lower_words(f"{title} {summary or ''}")
    bases = []
    for base, terms in SYMBOL_TERMS.items():
        if any(term_matches(text, term, base) for term in terms):
            bases.append(base)
    if " bitcoin cash " in text and "BCH" not in bases:
        bases.append("BCH")
    bases = sorted(set(bases))
    return [f"{base}USDT" for base in bases], bases


def detect_event_type(title: str, summary: str | None) -> tuple[str, list[str]]:
    text = lower_words(f"{title} {summary or ''}")
    tags = []
    for event_type, keywords in EVENT_KEYWORDS:
        matched = [keyword.strip() for keyword in keywords if keyword.lower() in text]
        if matched:
            tags.extend(matched)
            return event_type, sorted(set(tags))
    return "general_news", tags


def classify_sentiment(title: str, summary: str | None, event_type: str) -> str:
    text = lower_words(f"{title} {summary or ''}")
    negative = sum(1 for word in NEGATIVE_WORDS if f" {word} " in text or word in text)
    positive = sum(1 for word in POSITIVE_WORDS if f" {word} " in text or word in text)
    if event_type in {"security_incident", "delisting"}:
        negative += 2
    if event_type in {"listing", "partnership", "protocol_upgrade"}:
        positive += 1
    if negative and positive:
        return "mixed"
    if negative:
        return "negative"
    if positive:
        return "positive"
    return "neutral"


def classify_severity(title: str, summary: str | None, event_type: str, bases: list[str]) -> int:
    text = lower_words(f"{title} {summary or ''}")
    severity = 1
    if event_type not in {"general_news"}:
        severity += 1
    if event_type in {"security_incident", "regulatory", "macro_policy"}:
        severity += 1
    if any(word in text for word in HIGH_SEVERITY_WORDS):
        severity += 1
    if bases:
        severity += 1
    return min(severity, 5)


def classify_item(item: FeedItem, fetched_at: int) -> ClassifiedEvent:
    symbols, bases = detect_symbols(item.title, item.summary)
    event_type, tags = detect_event_type(item.title, item.summary)
    sentiment = classify_sentiment(item.title, item.summary, event_type)
    severity = classify_severity(item.title, item.summary, event_type, bases)
    scope = "symbol" if symbols else ("macro" if event_type == "macro_policy" else "market")
    confidence = 0.45
    if event_type != "general_news":
        confidence += 0.2
    if symbols:
        confidence += 0.2
    if item.published_at is not None:
        confidence += 0.1
    confidence = min(confidence, 0.95)
    event_key = hashlib.sha256(
        "|".join(
            [
                item.source,
                item.title,
                item.url or "",
                str(item.published_at or ""),
            ]
        ).encode("utf-8")
    ).hexdigest()
    classification = {
        "event_type": event_type,
        "scope": scope,
        "sentiment": sentiment,
        "severity": severity,
        "confidence": confidence,
        "symbols": symbols,
        "bases": bases,
        "tags": tags,
        "classifier": "deterministic_news_v1",
    }
    return ClassifiedEvent(
        event_key=event_key,
        source=item.source,
        source_url=item.source_url,
        title=item.title,
        url=item.url,
        published_at=item.published_at,
        fetched_at=fetched_at,
        event_type=event_type,
        scope=scope,
        sentiment=sentiment,
        severity=severity,
        confidence=confidence,
        symbols=symbols,
        bases=bases,
        tags=tags,
        summary=item.summary,
        classification=classification,
    )


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_news_events (
            event_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_url TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            published_at INTEGER,
            fetched_at INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            scope TEXT NOT NULL,
            sentiment TEXT NOT NULL,
            severity INTEGER NOT NULL,
            confidence REAL NOT NULL,
            symbols_json TEXT NOT NULL,
            bases_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            summary TEXT,
            classification_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_telemetry_news_events_published_at ON telemetry_news_events(published_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_telemetry_news_events_event_type ON telemetry_news_events(event_type)"
    )


def upsert_events(connection: sqlite3.Connection, events: list[ClassifiedEvent]) -> int:
    initialize_database(connection)
    changed = 0
    for event in events:
        cursor = connection.execute(
            """
            INSERT INTO telemetry_news_events (
                event_key, source, source_url, title, url, published_at, fetched_at,
                event_type, scope, sentiment, severity, confidence,
                symbols_json, bases_json, tags_json, summary, classification_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                event_type = excluded.event_type,
                scope = excluded.scope,
                sentiment = excluded.sentiment,
                severity = excluded.severity,
                confidence = excluded.confidence,
                symbols_json = excluded.symbols_json,
                bases_json = excluded.bases_json,
                tags_json = excluded.tags_json,
                summary = excluded.summary,
                classification_json = excluded.classification_json
            """,
            (
                event.event_key,
                event.source,
                event.source_url,
                event.title,
                event.url,
                event.published_at,
                event.fetched_at,
                event.event_type,
                event.scope,
                event.sentiment,
                event.severity,
                event.confidence,
                json.dumps(event.symbols),
                json.dumps(event.bases),
                json.dumps(event.tags),
                event.summary,
                json.dumps(event.classification, sort_keys=True),
            ),
        )
        changed += cursor.rowcount
    connection.commit()
    return changed


def collect_events(
    sources: list[tuple[str, str]],
    limit_per_source: int,
    timeout: int,
) -> tuple[list[ClassifiedEvent], list[str]]:
    fetched_at = int(time.time() * 1000)
    events: list[ClassifiedEvent] = []
    errors = []
    for source, url in sources:
        try:
            payload = fetch_url(url, timeout)
            items = parse_feed(source, url, payload, limit_per_source)
            events.extend(classify_item(item, fetched_at) for item in items)
        except Exception as error:  # noqa: BLE001 - collector should continue across flaky feeds.
            errors.append(f"{source}: {error}")
    return events, errors


def event_to_json(event: ClassifiedEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["symbols_json"] = json.dumps(event.symbols)
    payload["bases_json"] = json.dumps(event.bases)
    payload["tags_json"] = json.dumps(event.tags)
    payload["classification_json"] = json.dumps(event.classification, sort_keys=True)
    return payload


def render_summary(events: list[ClassifiedEvent], errors: list[str], changed: int | None) -> str:
    event_counts = Counter(event.event_type for event in events)
    symbol_counts = Counter(symbol for event in events for symbol in event.symbols)
    lines = [
        "# News Event Collection",
        "",
        f"- Fetched events: `{len(events)}`",
        f"- Database rows changed: `{changed if changed is not None else 'dry-run'}`",
        f"- Feed errors: `{len(errors)}`",
        "",
        "## Event Types",
        "",
    ]
    if event_counts:
        for name, count in event_counts.most_common():
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- No events collected.")
    lines.extend(["", "## Symbols", ""])
    if symbol_counts:
        for symbol, count in symbol_counts.most_common(20):
            lines.append(f"- `{symbol}`: `{count}`")
    else:
        lines.append("- No symbol-specific events classified.")
    lines.extend(["", "## Recent Classified Events", ""])
    for event in sorted(events, key=lambda item: item.published_at or item.fetched_at, reverse=True)[:20]:
        lines.append(
            f"- `{event.source}` `{event.event_type}` `{event.sentiment}` severity `{event.severity}` "
            f"symbols `{','.join(event.symbols) or 'market'}`: {event.title}"
        )
    if errors:
        lines.extend(["", "## Feed Errors", ""])
        for error in errors:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"


def parse_source(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("Sources must use name=url format.")
    name, url = raw.split("=", 1)
    name = name.strip()
    url = url.strip()
    if not name or not url:
        raise argparse.ArgumentTypeError("Sources must use non-empty name=url values.")
    return name, url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and classify public news events into SQLite telemetry.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--source", action="append", type=parse_source, help="Override/add source in name=url format.")
    parser.add_argument("--limit-per-source", type=int, default=DEFAULT_LIMIT_PER_SOURCE)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = args.source if args.source else DEFAULT_SOURCES
    events, errors = collect_events(sources, args.limit_per_source, args.timeout)
    changed: int | None = None
    if not args.dry_run:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(args.db) as connection:
            changed = upsert_events(connection, events)

    payload = {
        "generated_at": int(time.time() * 1000),
        "sources": [{"name": name, "url": url} for name, url in sources],
        "events": [event_to_json(event) for event in events],
        "errors": errors,
        "rows_changed": changed,
    }
    markdown = render_summary(events, errors, changed)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(markdown, end="")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

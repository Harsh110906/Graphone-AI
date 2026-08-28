"""
Date extraction waterfall and 24-hour freshness verification engine.

Waterfall Priority Order:
1. JSON-LD structured data (datePublished, dateCreated, dateModified)
2. OpenGraph / HTML Meta tags (article:published_time, publish_date, og:updated_time, date)
3. <time datetime="..."> HTML tags
4. Visible relative text expressions ("X hours ago", "yesterday", "just now")
5. RSS / Atom / Sitemap feed timestamps
6. Last-seen / HTTP Last-Modified header (only if confident and explicitly supplied)

Hard Rule:
If no confident publication timestamp can be extracted, the date extractor returns None.
Records without a confident date are REJECTED — freshness is never assumed or defaulted to "now".
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple
from bs4 import BeautifulSoup
import structlog

logger = structlog.get_logger(__name__)

# Common ISO-8601 and RFC 2822 date formats
ISO_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%d %b %Y %H:%M:%S %z",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
]


def parse_datetime_to_utc(date_str: str | None) -> datetime | None:
    """
    Parse a date string in various formats into a UTC-aware datetime.
    Handles ISO-8601, RFC 2822, and standard web date formats.
    If date_str lacks timezone info, it is assumed to be UTC.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    cleaned = date_str.strip()
    if not cleaned:
        return None

    # Try standard strptime formats
    for fmt in ISO_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except ValueError:
            continue

    # Fallback to dateutil if installed
    try:
        from dateutil import parser
        dt = parser.parse(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass

    return None


class DateExtractionWaterfall:
    """
    6-step waterfall date extraction engine.
    """

    @classmethod
    def extract_from_json_ld(cls, html: str) -> Tuple[Optional[datetime], Optional[str]]:
        """Step 1: Extract date from JSON-LD schema.org script blocks."""
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

        for match in matches:
            try:
                data = json.loads(match.strip())
                items = data if isinstance(data, list) else [data]

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Direct dates on root or @graph elements
                    nodes = [item]
                    if "@graph" in item and isinstance(item["@graph"], list):
                        nodes.extend(item["@graph"])

                    for node in nodes:
                        if not isinstance(node, dict):
                            continue
                        for field in ["datePublished", "dateCreated", "dateModified", "uploadDate"]:
                            val = node.get(field)
                            if val and isinstance(val, str):
                                dt = parse_datetime_to_utc(val)
                                if dt:
                                    return dt, f"json_ld:{field}"
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

        return None, None

    @classmethod
    def extract_from_meta_tags(cls, html: str) -> Tuple[Optional[datetime], Optional[str]]:
        """Step 2: Extract date from OpenGraph, Twitter, and standard HTML meta tags."""
        meta_patterns = [
            (r'<meta\s+property=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']', "og:article:published_time"),
            (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']article:published_time["\']', "og:article:published_time"),
            (r'<meta\s+property=["\']og:published_time["\']\s+content=["\']([^"\']+)["\']', "og:published_time"),
            (r'<meta\s+property=["\']og:updated_time["\']\s+content=["\']([^"\']+)["\']', "og:updated_time"),
            (r'<meta\s+name=["\']publish[_-]?date["\']\s+content=["\']([^"\']+)["\']', "meta:publish_date"),
            (r'<meta\s+name=["\']pubdate["\']\s+content=["\']([^"\']+)["\']', "meta:pubdate"),
            (r'<meta\s+name=["\']date["\']\s+content=["\']([^"\']+)["\']', "meta:date"),
            (r'<meta\s+name=["\']parsely-pub-date["\']\s+content=["\']([^"\']+)["\']', "meta:parsely-pub-date"),
            (r'<meta\s+name=["\']sailthru.date["\']\s+content=["\']([^"\']+)["\']', "meta:sailthru.date"),
        ]

        for pattern, source_label in meta_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                dt = parse_datetime_to_utc(match.group(1))
                if dt:
                    return dt, source_label

        return None, None

    @classmethod
    def extract_from_time_element(cls, html: str) -> Tuple[Optional[datetime], Optional[str]]:
        """Step 3: Extract date from HTML5 <time datetime="..."> tags."""
        pattern = r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>"
        matches = re.findall(pattern, html, re.IGNORECASE)

        for dt_str in matches:
            dt = parse_datetime_to_utc(dt_str)
            if dt:
                return dt, "html5:time_element"

        return None, None

    @classmethod
    def extract_from_relative_text(
        cls,
        text: str,
        now: datetime | None = None,
    ) -> Tuple[Optional[datetime], Optional[str]]:
        """
        Step 4: Parse human relative date expressions from visible text.
        Handles expressions like: '2 hours ago', '45 minutes ago', 'yesterday', 'just now'.
        """
        ref_now = now or datetime.now(timezone.utc)
        text_lower = text.lower().strip()

        if "just now" in text_lower or "moments ago" in text_lower:
            return ref_now, "relative_text:just_now"

        if "yesterday" in text_lower:
            return ref_now - timedelta(days=1), "relative_text:yesterday"

        # Regex: \b(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago\b
        match = re.search(
            r"\b(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago\b",
            text_lower,
        )
        if match:
            val = int(match.group(1))
            unit = match.group(2)

            unit_map = {
                "second": timedelta(seconds=val),
                "minute": timedelta(minutes=val),
                "hour": timedelta(hours=val),
                "day": timedelta(days=val),
                "week": timedelta(weeks=val),
                "month": timedelta(days=val * 30),
                "year": timedelta(days=val * 365),
            }

            delta = unit_map.get(unit)
            if delta:
                return ref_now - delta, f"relative_text:{val}_{unit}s_ago"

        return None, None

    @classmethod
    def extract_from_feed_timestamp(cls, feed_date: str | None) -> Tuple[Optional[datetime], Optional[str]]:
        """Step 5: Extract timestamp from RSS / Atom / Sitemap entry."""
        if not feed_date:
            return None, None
        dt = parse_datetime_to_utc(feed_date)
        if dt:
            return dt, "feed_metadata"
        return None, None

    @classmethod
    def extract_from_last_seen_header(
        cls,
        last_modified_header: str | None,
    ) -> Tuple[Optional[datetime], Optional[str]]:
        """Step 6: Last-seen heuristic (HTTP Last-Modified header if present)."""
        if not last_modified_header:
            return None, None
        dt = parse_datetime_to_utc(last_modified_header)
        if dt:
            return dt, "http_header:last_modified"
        return None, None

    @classmethod
    def extract_date(
        cls,
        html: str = "",
        feed_timestamp: str | None = None,
        last_modified_header: str | None = None,
        now: datetime | None = None,
    ) -> Tuple[Optional[datetime], Optional[str]]:
        """
        Execute full 6-step waterfall in strict priority order.
        Returns (extracted_datetime_utc, extraction_method_label).
        Returns (None, None) if all steps fail -> Record must be REJECTED.
        """
        # Step 1: JSON-LD
        if html:
            dt, method = cls.extract_from_json_ld(html)
            if dt:
                return dt, method

        # Step 2: OpenGraph / Meta tags
        if html:
            dt, method = cls.extract_from_meta_tags(html)
            if dt:
                return dt, method

        # Step 3: <time> elements
        if html:
            dt, method = cls.extract_from_time_element(html)
            if dt:
                return dt, method

        # Step 4: Relative text
        if html:
            try:
                soup = BeautifulSoup(html, "lxml")
                visible_text = soup.get_text(separator=" ", strip=True)
                dt, method = cls.extract_from_relative_text(visible_text, now=now)
                if dt:
                    return dt, method
            except Exception:
                pass

        # Step 5: RSS / Atom / Sitemap feed timestamp
        if feed_timestamp:
            dt, method = cls.extract_from_feed_timestamp(feed_timestamp)
            if dt:
                return dt, method

        # Step 6: HTTP Last-Modified Header
        if last_modified_header:
            dt, method = cls.extract_from_last_seen_header(last_modified_header)
            if dt:
                return dt, method

        # Rejection: No confident date found
        return None, None


def check_24h_freshness(
    pub_date: datetime | None,
    now: datetime | None = None,
    max_age_hours: float = 24.0,
) -> Tuple[bool, float]:
    """
    Check if a publication timestamp is strictly within the 24-hour freshness window.

    Returns:
        (is_fresh, age_in_hours)
    """
    if pub_date is None:
        return False, float("inf")

    ref_now = now or datetime.now(timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)

    # Compute age in hours
    age_seconds = (ref_now - pub_date).total_seconds()
    age_hours = age_seconds / 3600.0

    # Reject future dates beyond a 5-minute clock drift margin
    if age_seconds < -300:
        logger.warning("date_in_future_rejected", pub_date=pub_date.isoformat(), age_hours=age_hours)
        return False, age_hours

    # Fresh if within [0, max_age_hours]
    is_fresh = 0 <= age_hours <= max_age_hours
    return is_fresh, age_hours

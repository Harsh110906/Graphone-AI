"""
Tests for date parsing/extraction waterfall.

The date extraction waterfall order:
1. JSON-LD (structured data)
2. OpenGraph/meta tags
3. <time datetime> elements
4. Visible relative text ("2 hours ago", "yesterday")
5. RSS/sitemap timestamp
6. Last-seen heuristic

If no confident date can be extracted, the record is REJECTED.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest


# ═══════════════════════════════════════════════════════════════
# Date extraction utility functions (tested in isolation)
# ═══════════════════════════════════════════════════════════════

def extract_date_from_json_ld(html: str) -> datetime | None:
    """Extract publish date from JSON-LD structured data."""
    import json

    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

    for match in matches:
        try:
            data = json.loads(match)
            # Handle both single objects and lists
            if isinstance(data, list):
                data = data[0] if data else {}

            for field in ["datePublished", "dateCreated", "dateModified"]:
                if field in data and data[field]:
                    return _parse_iso_date(data[field])
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return None


def extract_date_from_meta_tags(html: str) -> datetime | None:
    """Extract date from OpenGraph or other meta tags."""
    meta_patterns = [
        r'<meta\s+property=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']article:published_time["\']',
        r'<meta\s+name=["\']publish[_-]?date["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+name=["\']date["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+property=["\']og:updated_time["\']\s+content=["\']([^"\']+)["\']',
    ]

    for pattern in meta_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            result = _parse_iso_date(match.group(1))
            if result:
                return result
    return None


def extract_date_from_time_element(html: str) -> datetime | None:
    """Extract date from <time datetime='...'> elements."""
    pattern = r"<time[^>]*datetime=[\"']([^\"']+)[\"'][^>]*>"
    matches = re.findall(pattern, html, re.IGNORECASE)

    for dt_str in matches:
        result = _parse_iso_date(dt_str)
        if result:
            return result
    return None


def extract_date_from_relative_text(text: str, now: datetime | None = None) -> datetime | None:
    """
    Parse relative date expressions.

    Handles: "2 hours ago", "3 days ago", "1 minute ago", "yesterday", "just now"
    """
    now = now or datetime.now(timezone.utc)
    text_lower = text.lower().strip()

    if "just now" in text_lower:
        return now

    if "yesterday" in text_lower:
        return now - timedelta(days=1)

    # Pattern: "X unit(s) ago"
    match = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", text_lower)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)

        delta_map = {
            "second": timedelta(seconds=amount),
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
            "month": timedelta(days=amount * 30),   # Approximate
            "year": timedelta(days=amount * 365),    # Approximate
        }

        delta = delta_map.get(unit)
        if delta:
            return now - delta

    return None


def _parse_iso_date(date_str: str) -> datetime | None:
    """Parse an ISO-8601 date string into a datetime."""
    if not date_str:
        return None

    # Common ISO-8601 formats
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None


def extract_date_waterfall(
    html: str,
    rss_date: str | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """
    Full date extraction waterfall.

    Returns the first successfully extracted date, or None if all methods fail.
    None means: REJECT the record — never assume freshness.
    """
    # 1. JSON-LD
    result = extract_date_from_json_ld(html)
    if result:
        return result

    # 2. Meta tags
    result = extract_date_from_meta_tags(html)
    if result:
        return result

    # 3. <time> elements
    result = extract_date_from_time_element(html)
    if result:
        return result

    # 4. Relative text (search the visible text)
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
        visible_text = soup.get_text(separator=" ", strip=True)
        result = extract_date_from_relative_text(visible_text, now=now)
        if result:
            return result
    except Exception:
        pass

    # 5. RSS/sitemap date
    if rss_date:
        result = _parse_iso_date(rss_date)
        if result:
            return result

    # 6. All methods failed — return None (record will be REJECTED)
    return None


# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

class TestIsoDateParsing:
    """Test ISO-8601 date string parsing."""

    def test_full_iso_with_timezone(self):
        result = _parse_iso_date("2024-01-15T10:30:00+05:30")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_iso_with_z_suffix(self):
        result = _parse_iso_date("2024-03-20T14:00:00Z")
        assert result is not None
        assert result.hour == 14

    def test_iso_with_microseconds(self):
        result = _parse_iso_date("2024-06-01T08:15:30.123456Z")
        assert result is not None
        assert result.microsecond == 123456

    def test_date_only(self):
        result = _parse_iso_date("2024-12-25")
        assert result is not None
        assert result.month == 12
        assert result.day == 25

    def test_empty_string(self):
        assert _parse_iso_date("") is None

    def test_none_input(self):
        assert _parse_iso_date(None) is None

    def test_garbage_string(self):
        assert _parse_iso_date("not-a-date-at-all") is None

    def test_partial_date(self):
        """Partial dates without time should still parse."""
        result = _parse_iso_date("2024-01-01")
        assert result is not None
        assert result.year == 2024


class TestJsonLdExtraction:
    """Test JSON-LD date extraction."""

    def test_valid_json_ld(self):
        html = '''
        <html><head>
        <script type="application/ld+json">
        {"@type": "Article", "datePublished": "2024-03-15T09:00:00Z"}
        </script>
        </head></html>
        '''
        result = extract_date_from_json_ld(html)
        assert result is not None
        assert result.year == 2024
        assert result.month == 3

    def test_json_ld_array(self):
        html = '''
        <script type="application/ld+json">
        [{"@type": "NewsArticle", "datePublished": "2024-06-01T12:00:00Z"}]
        </script>
        '''
        result = extract_date_from_json_ld(html)
        assert result is not None

    def test_invalid_json_ld(self):
        html = '<script type="application/ld+json">not valid json</script>'
        result = extract_date_from_json_ld(html)
        assert result is None

    def test_no_json_ld(self):
        html = "<html><head></head><body>Hello</body></html>"
        result = extract_date_from_json_ld(html)
        assert result is None


class TestMetaTagExtraction:
    """Test OpenGraph/meta tag date extraction."""

    def test_og_published_time(self):
        html = '<meta property="article:published_time" content="2024-04-10T18:30:00Z">'
        result = extract_date_from_meta_tags(html)
        assert result is not None
        assert result.month == 4

    def test_meta_publish_date(self):
        html = '<meta name="publish_date" content="2024-07-20T00:00:00Z">'
        result = extract_date_from_meta_tags(html)
        assert result is not None

    def test_reversed_attribute_order(self):
        """Content before property should still match."""
        html = '<meta content="2024-01-01T00:00:00Z" property="article:published_time">'
        result = extract_date_from_meta_tags(html)
        assert result is not None

    def test_no_meta_tags(self):
        html = "<html><head><title>No Dates</title></head></html>"
        result = extract_date_from_meta_tags(html)
        assert result is None


class TestTimeElementExtraction:
    """Test <time datetime> extraction."""

    def test_time_element(self):
        html = '<article><time datetime="2024-05-01T14:30:00Z">May 1</time></article>'
        result = extract_date_from_time_element(html)
        assert result is not None
        assert result.month == 5

    def test_multiple_time_elements(self):
        """Should return the first valid one."""
        html = '''
        <time datetime="2024-08-01T00:00:00Z">Aug 1</time>
        <time datetime="2024-07-15T00:00:00Z">Jul 15</time>
        '''
        result = extract_date_from_time_element(html)
        assert result is not None
        assert result.month == 8

    def test_no_time_element(self):
        html = "<p>No time elements here</p>"
        result = extract_date_from_time_element(html)
        assert result is None


class TestRelativeDateExtraction:
    """Test relative date text parsing with realistic edge cases."""

    def test_hours_ago(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("Published 3 hours ago", now=now)
        assert result is not None
        assert result.hour == 9

    def test_minutes_ago(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("5 minutes ago", now=now)
        assert result is not None
        expected = now - timedelta(minutes=5)
        assert abs((result - expected).total_seconds()) < 1

    def test_days_ago(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("2 days ago", now=now)
        assert result is not None
        assert result.day == 13

    def test_yesterday(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("yesterday", now=now)
        assert result is not None
        assert result.day == 14

    def test_just_now(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("just now", now=now)
        assert result is not None
        assert result == now

    def test_singular_unit(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("1 hour ago", now=now)
        assert result is not None
        assert result.hour == 11

    def test_ambiguous_text_no_match(self):
        """Text without a recognizable relative date should return None."""
        result = extract_date_from_relative_text("Last updated sometime")
        assert result is None

    def test_empty_string(self):
        assert extract_date_from_relative_text("") is None

    def test_weeks_ago(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = extract_date_from_relative_text("2 weeks ago", now=now)
        assert result is not None
        assert result.day == 1


class TestDateWaterfall:
    """Test the full date extraction waterfall."""

    def test_json_ld_takes_priority(self):
        """JSON-LD should be tried first and takes priority."""
        html = '''
        <html><head>
        <script type="application/ld+json">
        {"datePublished": "2024-01-01T00:00:00Z"}
        </script>
        <meta property="article:published_time" content="2024-06-15T00:00:00Z">
        </head><body><time datetime="2024-12-25T00:00:00Z">Dec 25</time></body></html>
        '''
        result = extract_date_waterfall(html)
        assert result is not None
        assert result.month == 1  # JSON-LD date wins

    def test_falls_through_to_meta(self):
        """If no JSON-LD, should use meta tags."""
        html = '''
        <html><head>
        <meta property="article:published_time" content="2024-06-15T00:00:00Z">
        </head></html>
        '''
        result = extract_date_waterfall(html)
        assert result is not None
        assert result.month == 6

    def test_falls_through_to_rss(self):
        """If HTML has no dates, RSS date should be used."""
        html = "<html><body>No dates here</body></html>"
        result = extract_date_waterfall(html, rss_date="2024-09-01T00:00:00Z")
        assert result is not None
        assert result.month == 9

    def test_all_fail_returns_none(self):
        """If all extraction methods fail, return None (REJECT the record)."""
        html = "<html><body>Completely dateless content</body></html>"
        result = extract_date_waterfall(html, rss_date=None)
        assert result is None  # Record should be REJECTED

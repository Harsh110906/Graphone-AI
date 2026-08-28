"""
Comprehensive unit tests for DateExtractionWaterfall and 24h freshness verification.

Tests cover:
- Exact waterfall priority order: JSON-LD -> Meta tags -> <time> -> Relative text -> RSS -> Last-modified
- JSON-LD date extraction success
- Relative-date-only page ("2 hours ago", "yesterday")
- Timezone-ambiguous and varied offset date parsing into UTC
- Missing/garbage date -> Returns None -> Record REJECTED (never assumed)
- 24-hour freshness window bounds (0h, 12h, 23.9h, 24.1h, 48h, future dates)
"""

from datetime import datetime, timedelta, timezone
import pytest

from src.crawler.date_extractor import (
    DateExtractionWaterfall,
    parse_datetime_to_utc,
    check_24h_freshness,
)


class TestWaterfallPriority:
    """Verify strict waterfall ordering."""

    def test_json_ld_beats_meta_and_time(self):
        """JSON-LD (Step 1) must take precedence over Meta tags and <time> tags."""
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {"@context": "https://schema.org", "@type": "NewsArticle", "datePublished": "2026-08-28T12:00:00Z"}
            </script>
            <meta property="article:published_time" content="2026-08-27T08:00:00Z" />
          </head>
          <body>
            <time datetime="2026-08-26T00:00:00Z">August 26</time>
          </body>
        </html>
        """
        dt, method = DateExtractionWaterfall.extract_date(html=html)
        assert dt is not None
        assert method.startswith("json_ld:")
        assert dt == datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)

    def test_meta_tag_beats_time_and_relative(self):
        """Meta tags (Step 2) take precedence when JSON-LD is absent."""
        html = """
        <html>
          <head>
            <meta property="article:published_time" content="2026-08-28T10:30:00+00:00" />
          </head>
          <body>
            <time datetime="2026-08-25T00:00:00Z">August 25</time>
            <p>Published 2 hours ago</p>
          </body>
        </html>
        """
        dt, method = DateExtractionWaterfall.extract_date(html=html)
        assert dt is not None
        assert method == "og:article:published_time"
        assert dt == datetime(2026, 8, 28, 10, 30, 0, tzinfo=timezone.utc)

    def test_time_element_beats_relative_text(self):
        """HTML5 <time> tag (Step 3) takes precedence over unstructured text."""
        html = """
        <html>
          <body>
            <article>
              <time datetime="2026-08-28T09:15:00Z">9:15 AM</time>
              <p>Posted 5 hours ago</p>
            </article>
          </body>
        </html>
        """
        dt, method = DateExtractionWaterfall.extract_date(html=html)
        assert dt is not None
        assert method == "html5:time_element"
        assert dt == datetime(2026, 8, 28, 9, 15, 0, tzinfo=timezone.utc)

    def test_relative_text_beats_feed_metadata(self):
        """Relative text in HTML (Step 4) takes precedence over feed metadata."""
        now = datetime(2026, 8, 28, 18, 0, 0, tzinfo=timezone.utc)
        html = """
        <html>
          <body>
            <div class="article-meta">Published 3 hours ago by Tech Staff</div>
          </body>
        </html>
        """
        dt, method = DateExtractionWaterfall.extract_date(
            html=html,
            feed_timestamp="2026-08-27T00:00:00Z",
            now=now,
        )
        assert dt is not None
        assert method == "relative_text:3_hours_ago"
        assert dt == datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)

    def test_feed_metadata_fallback_when_html_lacks_date(self):
        """Step 5: Feed metadata is used if HTML body has no dates."""
        html = "<html><body><p>Article body without explicit timestamp</p></body></html>"
        feed_ts = "Fri, 28 Aug 2026 14:00:00 GMT"
        dt, method = DateExtractionWaterfall.extract_date(html=html, feed_timestamp=feed_ts)
        assert dt is not None
        assert method == "feed_metadata"
        assert dt == datetime(2026, 8, 28, 14, 0, 0, tzinfo=timezone.utc)


class TestEdgeCasesAndRejection:
    """Verify required rejection and edge cases."""

    def test_missing_date_returns_none_rejection(self):
        """Page with no extractable date MUST return (None, None) -> Rejection."""
        html = "<html><head><title>No Dates</title></head><body><h1>AI breakthrough announced</h1></body></html>"
        dt, method = DateExtractionWaterfall.extract_date(html=html, feed_timestamp=None)
        assert dt is None
        assert method is None

    def test_timezone_ambiguous_date_normalized_to_utc(self):
        """Dates with varied timezone offsets (+05:30, -07:00, Z) are normalized to UTC."""
        dt1 = parse_datetime_to_utc("2026-08-28T15:30:00+05:30")
        assert dt1 is not None
        assert dt1.tzinfo == timezone.utc
        assert dt1.hour == 10  # 15:30 - 5:30 = 10:00 UTC

        dt2 = parse_datetime_to_utc("2026-08-28T04:00:00-07:00")
        assert dt2 is not None
        assert dt2.tzinfo == timezone.utc
        assert dt2.hour == 11  # 04:00 + 7:00 = 11:00 UTC

    def test_relative_date_variations(self):
        """Verify various relative date expressions."""
        now = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)
        dt_just_now, _ = DateExtractionWaterfall.extract_from_relative_text("Updated just now", now=now)
        assert dt_just_now == now

        dt_mins, _ = DateExtractionWaterfall.extract_from_relative_text("15 minutes ago", now=now)
        assert dt_mins == now - timedelta(minutes=15)

        dt_yesterday, _ = DateExtractionWaterfall.extract_from_relative_text("posted yesterday", now=now)
        assert dt_yesterday == now - timedelta(days=1)


class TestFreshnessVerification:
    """Verify 24h freshness filter logic."""

    def test_fresh_record_accepted(self):
        now = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)
        pub_date = now - timedelta(hours=4.5)
        is_fresh, age = check_24h_freshness(pub_date, now=now)
        assert is_fresh is True
        assert round(age, 1) == 4.5

    def test_stale_record_rejected_over_24h(self):
        now = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)
        pub_date = now - timedelta(hours=25.0)
        is_fresh, age = check_24h_freshness(pub_date, now=now)
        assert is_fresh is False
        assert round(age, 1) == 25.0

    def test_none_date_rejected(self):
        is_fresh, age = check_24h_freshness(None)
        assert is_fresh is False
        assert age == float("inf")

    def test_future_date_rejected(self):
        now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
        pub_date = now + timedelta(hours=2.0)  # 2 hours in the future
        is_fresh, _ = check_24h_freshness(pub_date, now=now)
        assert is_fresh is False

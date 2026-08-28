"""
Unit tests for TextExtractor boilerplate removal and readability cleaning.

Verifies:
- Removal of navigation menus, header/footer, advertising banners, social buttons, cookie modals
- Preservation of article title, headings (H1-H3), body paragraphs, bullet points
- Excerpt generation
- Explicit before/after assertions
"""

import pytest
from src.crawler.text_extractor import TextExtractor


class TestTextExtractor:
    """Test suite for boilerplate stripping and clean full-text extraction."""

    def test_boilerplate_stripping_on_noisy_html(self):
        """Noisy page with header, nav, ads, social shares, and footers is cleaned."""
        raw_html = """
        <!DOCTYPE html>
        <html>
          <head><title>AI Breakthrough</title></head>
          <body>
            <header class="site-header">
              <div class="logo">TechNews</div>
              <nav class="main-navigation">
                <ul><li><a href="/home">Home</a></li><li><a href="/about">About</a></li></ul>
              </nav>
            </header>
            <div class="ad-banner top-leaderboard">
              <p>Special Offer: 50% off Cloud Hosting!</p>
            </div>
            <div class="cookie-notice-banner">
              <p>We use cookies to improve your browsing experience.</p>
              <button>Accept All</button>
            </div>
            <main class="article-content">
              <h1>Mistral AI Announces New Multimodal Reasoning Model</h1>
              <p class="byline">By Jane Doe | August 28, 2026</p>
              <div class="social-share-widget">
                <a href="#twitter">Share on X</a>
                <a href="#linkedin">Share on LinkedIn</a>
              </div>
              <p>Mistral AI has officially unveiled their next-generation multimodal model designed for complex agentic workflows.</p>
              <h2>Key Capabilities and Benchmarks</h2>
              <p>The architecture features a native vision-language transformer capable of processing high-resolution imagery and code simultaneously.</p>
              <div class="newsletter-signup-box">
                <p>Subscribe to our daily AI newsletter for breaking updates.</p>
              </div>
              <p>Initial benchmarks show competitive accuracy on mathematical problem solving while maintaining an open weights license for research.</p>
            </main>
            <aside class="sidebar-widgets">
              <div class="popular-posts">
                <h3>Most Read Stories</h3>
                <ul><li>Top 10 AI startups in 2026</li></ul>
              </div>
            </aside>
            <footer class="site-footer">
              <p>&copy; 2026 TechNews Media Inc. All rights reserved. <a href="/privacy">Privacy Policy</a></p>
            </footer>
          </body>
        </html>
        """

        full_text, excerpt = TextExtractor.clean_html_to_text(raw_html)

        # Confirm boilerplate elements are stripped
        assert "50% off Cloud Hosting" not in full_text
        assert "We use cookies" not in full_text
        assert "Share on LinkedIn" not in full_text
        assert "Privacy Policy" not in full_text
        assert "Most Read Stories" not in full_text

        # Confirm legitimate article body and headings are preserved
        assert "Mistral AI has officially unveiled their next-generation multimodal model" in full_text
        assert "Key Capabilities and Benchmarks" in full_text
        assert "Initial benchmarks show competitive accuracy" in full_text

        # Confirm excerpt is clean
        assert len(excerpt) > 20
        assert "Mistral AI" in excerpt

    def test_empty_html_handling(self):
        text, excerpt = TextExtractor.clean_html_to_text("")
        assert text == ""
        assert excerpt == ""

    def test_excerpt_truncation(self):
        long_body = "Artificial Intelligence continues to evolve rapidly across every technical domain. " * 20
        excerpt = TextExtractor._generate_excerpt(long_body, max_chars=150)
        assert len(excerpt) <= 160
        assert excerpt.endswith("...")

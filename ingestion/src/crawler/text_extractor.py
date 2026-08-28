"""
Full-text extraction and boilerplate removal engine for news articles and web content.

Strips navigational menus, advertising iframes, header/footer elements, sidebars,
tracking pixels, cookie banners, and social sharing widgets.
Preserves the core readable article content, headings, and paragraphs.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple
from bs4 import BeautifulSoup, Comment
import structlog

logger = structlog.get_logger(__name__)

# CSS classes / IDs commonly used for junk / boilerplate / ads
BOILERPLATE_PATTERNS = [
    r"nav(bar)?",
    r"header",
    r"footer",
    r"sidebar",
    r"advert(isement)?",
    r"banner",
    r"cookie(-banner|-notice|-modal)?",
    r"share(-buttons|-widget|-bar)?",
    r"social(-media|-share|-icons)?",
    r"comment(s|-section|-form)?",
    r"related(-articles|-posts|-content)?",
    r"newsletter(-signup|-form)?",
    r"author(-bio|-card)?|byline",
    r"popup|modal|overlay",
    r"promo|sponsor",
    r"taboola|outbrain|disqus",
    r"breadcrumb",
]
BOILERPLATE_REGEX = re.compile("|".join(BOILERPLATE_PATTERNS), re.IGNORECASE)

# Tags to strip outright
STRIP_TAGS = [
    "script", "style", "noscript", "svg", "form", "iframe", "button",
    "nav", "header", "footer", "aside", "select", "option", "input",
]


class TextExtractor:
    """
    Readability-style HTML parser that strips boilerplate and extracts main article text.
    """

    @classmethod
    def clean_html_to_text(cls, html: str) -> Tuple[str, str]:
        """
        Extract clean full text and a short excerpt from raw HTML.

        Returns:
            (full_text, excerpt)
        """
        if not html or not html.strip():
            return "", ""

        # Try readability-lxml if available
        readable_html = None
        try:
            from readability import Document
            doc = Document(html)
            readable_html = doc.summary()
        except Exception:
            readable_html = html

        soup = BeautifulSoup(readable_html or html, "lxml")

        # 1. Remove non-content tags
        for tag in soup(STRIP_TAGS):
            tag.decompose()

        # 2. Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 3. Remove elements with boilerplate class or id
        for tag in soup.find_all(True):
            if not hasattr(tag, "attrs") or tag.attrs is None:
                continue

            classes = tag.get("class", [])
            class_str = " ".join(classes) if isinstance(classes, list) else str(classes)
            id_str = str(tag.get("id", "") or "")
            role_str = str(tag.get("role", "") or "")

            if role_str in ("navigation", "banner", "contentinfo", "complementary"):
                tag.decompose()
                continue

            if BOILERPLATE_REGEX.search(class_str) or BOILERPLATE_REGEX.search(id_str):
                # Only remove if it doesn't appear to be the main article wrapper
                combined = (class_str + " " + id_str).lower()
                if not any(k in combined for k in ["article-body", "post-content", "entry-content"]):
                    tag.decompose()

        # 4. Extract text from primary content containers if present
        target_elements = soup.find_all(["article", "main"])
        if not target_elements:
            target_elements = soup.find_all(
                "div",
                class_=re.compile(r"article[-_]?(body|content)|entry[-_]?content|post[-_]?content|story[-_]?content", re.I)
            )

        containers = target_elements if target_elements else ([soup.body] if soup.body else [soup])

        # 5. Extract and normalize paragraphs and headings
        blocks = []
        for container in containers:
            for element in container.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
                text = element.get_text(separator=" ", strip=True)
                if len(text) > 25 and not BOILERPLATE_REGEX.search(text[:60]):
                    blocks.append(text)

        if not blocks:
            # Fallback: full text of container
            for container in containers:
                raw_text = container.get_text(separator="\n", strip=True)
                for line in raw_text.splitlines():
                    cleaned_line = line.strip()
                    if len(cleaned_line) > 25 and not BOILERPLATE_REGEX.search(cleaned_line[:60]):
                        blocks.append(cleaned_line)

        # Deduplicate sequential repeated blocks
        deduped_blocks = []
        for b in blocks:
            if not deduped_blocks or deduped_blocks[-1] != b:
                deduped_blocks.append(b)

        full_text = "\n\n".join(deduped_blocks)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()

        # Excerpt: First 2-3 sentences or first ~300 chars
        excerpt = cls._generate_excerpt(full_text, max_chars=350)

        return full_text, excerpt

    @staticmethod
    def _generate_excerpt(text: str, max_chars: int = 350) -> str:
        """Create a clean excerpt from full article text."""
        if not text:
            return ""

        # Take first paragraph or up to max_chars
        paragraphs = text.split("\n\n")
        first_para = paragraphs[0] if paragraphs else text

        if len(first_para) <= max_chars:
            return first_para

        truncated = first_para[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > 200:
            return truncated[:last_space] + "..."
        return truncated + "..."

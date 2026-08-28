"""
Tests for the deduplication engine.

Covers:
- Exact key dedup (URL, arxiv_id)
- Normalized key dedup (case, unicode, legal suffix stripping)
- Blocked fuzzy match (near-duplicates within same block)
- Cross-type isolation (a startup named "Test" != a paper titled "Test")
- Stats tracking
"""

from datetime import datetime, timezone

import pytest

from src.storage.dedup import DeduplicationEngine


# ═══════════════════════════════════════════════════════════════
# Normalization Tests
# ═══════════════════════════════════════════════════════════════

class TestNormalization:
    """Test the normalize_key function."""

    def test_basic_lowercase(self):
        assert DeduplicationEngine.normalize_key("OpenAI") == "openai"

    def test_strip_inc(self):
        assert DeduplicationEngine.normalize_key("OpenAI Inc.") == "openai"

    def test_strip_ltd(self):
        assert DeduplicationEngine.normalize_key("DeepMind Ltd") == "deepmind"

    def test_strip_llc(self):
        assert DeduplicationEngine.normalize_key("Acme LLC") == "acme"

    def test_strip_pvt_ltd(self):
        result = DeduplicationEngine.normalize_key("TechCo Pvt Ltd")
        assert "pvt" not in result
        assert "ltd" not in result

    def test_unicode_normalization(self):
        """Unicode NFKD normalization should handle accented characters."""
        result = DeduplicationEngine.normalize_key("Café AI")
        # After NFKD normalization, accented characters may decompose
        assert "caf" in result

    def test_whitespace_collapse(self):
        assert DeduplicationEngine.normalize_key("  Open   AI  ") == "open ai"

    def test_empty_string(self):
        assert DeduplicationEngine.normalize_key("") == ""

    def test_strip_corp(self):
        assert DeduplicationEngine.normalize_key("Microsoft Corp") == "microsoft"


# ═══════════════════════════════════════════════════════════════
# Exact Key Dedup Tests
# ═══════════════════════════════════════════════════════════════

class TestExactKeyDedup:
    """Test exact key deduplication."""

    def test_same_arxiv_id_is_duplicate(self):
        engine = DeduplicationEngine()
        paper1 = {
            "recordType": "RESEARCH_PAPER",
            "content": {"title": "Paper One", "paper_url": "https://arxiv.org/abs/2301.00001"},
            "_metadata": {"arxiv_id": "2301.00001"},
        }
        paper2 = {
            "recordType": "RESEARCH_PAPER",
            "content": {"title": "Paper One (updated)", "paper_url": "https://arxiv.org/abs/2301.00001"},
            "_metadata": {"arxiv_id": "2301.00001"},
        }

        result1 = engine.check_and_register(paper1)
        assert not result1.is_duplicate

        result2 = engine.check_and_register(paper2)
        assert result2.is_duplicate
        assert result2.match_type == "exact_key"

    def test_different_arxiv_ids_not_duplicate(self):
        engine = DeduplicationEngine()
        paper1 = {
            "recordType": "RESEARCH_PAPER",
            "content": {"title": "Attention Is All You Need: A Transformer Architecture"},
            "_metadata": {"arxiv_id": "2301.00001"},
        }
        paper2 = {
            "recordType": "RESEARCH_PAPER",
            "content": {"title": "Scaling Laws for Neural Language Models"},
            "_metadata": {"arxiv_id": "2301.00002"},
        }

        engine.check_and_register(paper1)
        result = engine.check_and_register(paper2)
        assert not result.is_duplicate

    def test_same_url_startup_is_duplicate(self):
        engine = DeduplicationEngine()
        s1 = {
            "recordType": "STARTUP",
            "source": {"url": "https://crunchbase.com/org/openai"},
            "content": {"entityName": "OpenAI"},
        }
        s2 = {
            "recordType": "STARTUP",
            "source": {"url": "https://crunchbase.com/org/openai"},
            "content": {"entityName": "Open AI"},
        }

        engine.check_and_register(s1)
        result = engine.check_and_register(s2)
        assert result.is_duplicate


# ═══════════════════════════════════════════════════════════════
# Normalized Key Dedup Tests
# ═══════════════════════════════════════════════════════════════

class TestNormalizedKeyDedup:
    """Test normalized key deduplication."""

    def test_case_insensitive_dedup(self):
        engine = DeduplicationEngine()
        s1 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source1.com/openai"},
            "content": {"entityName": "OpenAI"},
        }
        s2 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source2.com/openai"},
            "content": {"entityName": "openai"},
        }

        engine.check_and_register(s1)
        result = engine.check_and_register(s2)
        assert result.is_duplicate
        assert result.match_type == "normalized_key"

    def test_legal_suffix_dedup(self):
        engine = DeduplicationEngine()
        s1 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source1.com"},
            "content": {"entityName": "Anthropic"},
        }
        s2 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source2.com"},
            "content": {"entityName": "Anthropic PBC"},
        }

        engine.check_and_register(s1)
        result = engine.check_and_register(s2)
        assert result.is_duplicate


# ═══════════════════════════════════════════════════════════════
# Fuzzy Match Dedup Tests
# ═══════════════════════════════════════════════════════════════

class TestFuzzyMatchDedup:
    """Test blocked fuzzy matching."""

    def test_near_duplicate_names(self):
        """'OpenAI' vs 'Open AI' within same block should be caught."""
        engine = DeduplicationEngine(fuzzy_threshold=0.85)
        s1 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source1.com"},
            "content": {"entityName": "Deep Mind"},
        }
        s2 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source2.com"},
            "content": {"entityName": "DeepMind"},
        }

        engine.check_and_register(s1)
        result = engine.check_and_register(s2)
        # These should match due to fuzzy similarity
        assert result.is_duplicate or result.match_type == "normalized_key"

    def test_different_names_not_duplicate(self):
        """Clearly different names should not match."""
        engine = DeduplicationEngine()
        s1 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source1.com"},
            "content": {"entityName": "Anthropic"},
        }
        s2 = {
            "recordType": "STARTUP",
            "source": {"url": "https://source2.com"},
            "content": {"entityName": "Mistral AI"},
        }

        engine.check_and_register(s1)
        result = engine.check_and_register(s2)
        assert not result.is_duplicate


# ═══════════════════════════════════════════════════════════════
# Cross-Type Isolation Tests
# ═══════════════════════════════════════════════════════════════

class TestCrossTypeIsolation:
    """Different entity types should not cross-match on normalized keys."""

    def test_startup_vs_paper_same_name(self):
        engine = DeduplicationEngine()
        startup = {
            "recordType": "STARTUP",
            "source": {"url": "https://source1.com"},
            "content": {"entityName": "Attention"},
        }
        paper = {
            "recordType": "RESEARCH_PAPER",
            "content": {"title": "Attention"},
            "_metadata": {"arxiv_id": "2301.99999"},
        }

        engine.check_and_register(startup)
        result = engine.check_and_register(paper)
        assert not result.is_duplicate  # Different types, not duplicate


# ═══════════════════════════════════════════════════════════════
# Stats Tests
# ═══════════════════════════════════════════════════════════════

class TestDedupStats:
    """Test dedup statistics tracking."""

    def test_stats_tracking(self):
        engine = DeduplicationEngine()

        # Register 3 unique, 1 duplicate
        records = [
            {"recordType": "STARTUP", "source": {"url": "https://a.com"}, "content": {"entityName": "Alpha"}},
            {"recordType": "STARTUP", "source": {"url": "https://b.com"}, "content": {"entityName": "Beta"}},
            {"recordType": "STARTUP", "source": {"url": "https://c.com"}, "content": {"entityName": "Gamma"}},
            {"recordType": "STARTUP", "source": {"url": "https://d.com"}, "content": {"entityName": "alpha"}},  # dup
        ]

        for r in records:
            engine.check_and_register(r)

        stats = engine.stats
        assert stats["total_seen"] == 4
        assert stats["duplicates_found"] == 1

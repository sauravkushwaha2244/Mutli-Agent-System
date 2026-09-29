"""Unit tests for the evidence-first ResearchMind pipeline."""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import PageRecord, ClaimRecord, ClaimGroup
from evidence_tools import verify_quote, format_citations, calculate_credibility
from visualizer import generate_agreement_chart, generate_conflict_map, generate_credibility_chart


class TestQuoteVerification(unittest.TestCase):
    """Test suite for the deterministic quote verification function."""

    def setUp(self):
        self.sample_page_text = (
            "The international thermonuclear experimental reactor (ITER) project in southern France "
            "has reached 85 percent completion of its critical components as of early 2026. "
            "Scientists report that first plasma is slated for late 2028, overcoming previous coil alignment setbacks."
        )

    def test_exact_quote_passes(self):
        quote = "reached 85 percent completion of its critical components"
        self.assertTrue(verify_quote(quote, self.sample_page_text))

    def test_case_and_whitespace_normalized_quote_passes(self):
        # Different casing and extra spaces
        quote = "REACHED   85 percent   completion  of its critical components"
        self.assertTrue(verify_quote(quote, self.sample_page_text))

    def test_hallucinated_quote_rejected(self):
        # Fabricated quote not in source text
        quote = "commercial fusion power was connected to the French national electricity grid"
        self.assertFalse(verify_quote(quote, self.sample_page_text))

    def test_partially_altered_quote_rejected(self):
        # Quote with altered number (85% -> 95%)
        quote = "reached 95 percent completion of its critical components"
        self.assertFalse(verify_quote(quote, self.sample_page_text))

    def test_short_trivial_quote_rejected(self):
        # Too short (< 12 chars)
        self.assertFalse(verify_quote("reached 85", self.sample_page_text))
        self.assertFalse(verify_quote("", self.sample_page_text))

    def test_empty_inputs(self):
        self.assertFalse(verify_quote("", ""))
        self.assertFalse(verify_quote("Valid quote here", ""))


class TestCitationMarkerFormatting(unittest.TestCase):
    """Test suite for marker validation, ungrounded marker rejection, and link conversion."""

    def setUp(self):
        self.sources_by_id = {
            "s1": PageRecord(
                source_id="s1",
                source_name="nature.com",
                url="https://nature.com/articles/fusion-2026",
                raw_text="...",
                trimmed_text="...",
                published="2026",
                credibility=0.85,
                is_snippet_fallback=False
            ),
            "s2": PageRecord(
                source_id="s2",
                source_name="energy.gov",
                url="https://energy.gov/news/iter-milestone",
                raw_text="...",
                trimmed_text="...",
                published="2026",
                credibility=0.90,
                is_snippet_fallback=False
            ),
        }

    def test_valid_marker_converted_to_link(self):
        raw = "Fusion energy has achieved major magnetic confinement milestones [s1]."
        formatted, rejected = format_citations(raw, self.sources_by_id)
        self.assertEqual(len(rejected), 0)
        self.assertIn("[[s1: nature.com]](https://nature.com/articles/fusion-2026)", formatted)

    def test_multiple_valid_markers_converted(self):
        raw = "Recent tests show plasma stability [s1] while federal funding rose [s2]."
        formatted, rejected = format_citations(raw, self.sources_by_id)
        self.assertEqual(len(rejected), 0)
        self.assertIn("[[s1: nature.com]]", formatted)
        self.assertIn("[[s2: energy.gov]]", formatted)

    def test_unregistered_marker_rejected_and_stripped(self):
        # [s99] is not in the source registry
        raw = "The system achieved net energy gain [s99]."
        formatted, rejected = format_citations(raw, self.sources_by_id)
        self.assertIn("s99", rejected)
        self.assertNotIn("s99", formatted)
        self.assertNotIn("[s99]", formatted)

    def test_case_insensitive_markers(self):
        raw = "Component testing is complete [S1]."
        formatted, rejected = format_citations(raw, self.sources_by_id)
        self.assertEqual(len(rejected), 0)
        self.assertIn("[[s1: nature.com]]", formatted)


class TestCredibilityScoring(unittest.TestCase):
    """Test suite for deterministic, rule-based credibility scoring."""

    def test_government_domain_boost(self):
        score = calculate_credibility("https://www.energy.gov/reports/fusion")
        self.assertGreaterEqual(score, 0.85)

    def test_academic_domain_boost(self):
        score = calculate_credibility("https://plasma.mit.edu/research")
        self.assertGreaterEqual(score, 0.80)

    def test_known_outlet_boost(self):
        score = calculate_credibility("https://www.nature.com/articles/s41586-026")
        self.assertGreaterEqual(score, 0.75)

    def test_social_forum_penalty(self):
        score = calculate_credibility("https://www.reddit.com/r/fusion/comments/milestone")
        self.assertLessEqual(score, 0.35)

    def test_snippet_fallback_penalty(self):
        score = calculate_credibility("https://www.reuters.com/article", is_snippet_fallback=True)
        self.assertLessEqual(score, 0.35)


class TestVisualizerDataRules(unittest.TestCase):
    """Test suite ensuring visualizations respect data presence (hide empty charts)."""

    def test_conflict_map_hidden_when_no_disputes(self):
        # Only AGREE and SINGLE_SOURCE
        groups = [
            ClaimGroup(group_id="g1", topic="Plasma heating", consensus="AGREE", claim_ids=["c1", "c2"]),
            ClaimGroup(group_id="g2", topic="Magnet design", consensus="SINGLE_SOURCE", claim_ids=["c3"]),
        ]
        claims_by_id = {}
        conflict_map = generate_conflict_map(groups, claims_by_id)
        self.assertIsNone(conflict_map, "Conflict map must be hidden (None) when no disputed claims exist")

    def test_conflict_map_rendered_when_disputes_exist(self):
        groups = [
            ClaimGroup(group_id="g1", topic="Q-factor breakeven", consensus="DISPUTED", claim_ids=["c1", "c2"]),
        ]
        claims_by_id = {
            "c1": ClaimRecord("c1", "Net gain reached", "quote 1", "s1", "Source A", "http://a.com", "2026", 0.8),
            "c2": ClaimRecord("c2", "Net gain not yet reached", "quote 2", "s2", "Source B", "http://b.com", "2026", 0.7),
        }
        conflict_map = generate_conflict_map(groups, claims_by_id)
        self.assertIsNotNone(conflict_map)
        self.assertIn("flowchart TD", conflict_map)
        self.assertIn("Q-factor breakeven", conflict_map)

    def test_agreement_chart_counts(self):
        groups = [
            ClaimGroup("g1", "Topic A", "AGREE", ["c1"]),
            ClaimGroup("g2", "Topic B", "DISPUTED", ["c2"]),
            ClaimGroup("g3", "Topic C", "SINGLE_SOURCE", ["c3"]),
        ]
        chart = generate_agreement_chart(groups)
        self.assertIsNotNone(chart)
        self.assertEqual(chart["data"][0]["values"], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()

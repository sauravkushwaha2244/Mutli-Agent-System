"""Unit tests for ResearchMind API endpoints and Supabase integration."""

import unittest
from unittest.mock import patch, MagicMock
import json
from app import app
from supabase_client import save_research_run, get_history, is_supabase_configured
import supabase_client


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_status_endpoint(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["service"], "ResearchMind")
        self.assertIn("supabase_connected", data)
        self.assertIn("supabase_url", data)
        self.assertIn("supabase_key", data)

    def test_history_list_endpoint(self):
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("history", data)
        self.assertIsInstance(data["history"], list)

    def test_research_empty_topic_validation(self):
        response = self.client.post("/api/research", json={"topic": "   "})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("error", data)

    def test_save_research_run_with_user_context(self):
        dummy_result = {
            "topic": "Test Quantum Computing",
            "report_markdown": "# Quantum Report",
            "sources": [{"title": "Source 1", "credibility": 0.85}],
            "claims": [{"text": "Quantum claim", "quote": "verified", "credibility": 0.85, "source_id": "S1", "source_name": "Source 1", "status": "verified"}],
            "visuals": {"agreement_chart": {}, "credibility_chart": {}},
            "stats": {}
        }
        # Test save_research_run accepts user_id and user_email without error
        save_info = save_research_run(
            dummy_result,
            user_id="00000000-0000-0000-0000-000000000001",
            user_email="testuser@example.com"
        )
        self.assertIn("saved_to", save_info)

    @patch("supabase_client.requests.post")
    @patch("supabase_client.is_supabase_configured", return_value=True)
    def test_save_uses_supabase_bearer_authorization(self, _mock_configured, mock_post):
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: [{"id": "saved-record"}],
        )

        save_info = save_research_run({
            "topic": "Authorization regression",
            "report_markdown": "Report",
            "sources": [],
            "claims": [],
            "visuals": {},
        })

        self.assertEqual(save_info, {"saved_to": "supabase", "id": "saved-record"})
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer " + supabase_client.SUPABASE_KEY)


if __name__ == "__main__":
    unittest.main()

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.api_client import post_provider_json
from video_sottotitoli.config import (
    DEEPSEEK_FLASH,
    PROVIDER_DEEPSEEK,
    PROVIDER_MODELS,
    PROVIDER_OPENAI,
)
from video_sottotitoli.revision_worker import RevisionWorker


class ProviderTests(unittest.TestCase):
    def test_provider_catalog_has_separate_models(self):
        self.assertIn(PROVIDER_OPENAI, PROVIDER_MODELS)
        self.assertIn(DEEPSEEK_FLASH, PROVIDER_MODELS[PROVIDER_DEEPSEEK])

    def test_deepseek_uses_its_responses_endpoint(self):
        request = {}

        def fake_request(req, timeout=300):
            request["url"] = req.full_url
            request["body"] = json.loads(req.data.decode("utf-8"))
            return {"ok": True}

        with patch("video_sottotitoli.api_client._request", side_effect=fake_request):
            result = post_provider_json("secret", "/responses", {"model": "x"}, PROVIDER_DEEPSEEK)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request["url"], "https://api.deepseek.com/responses")
        self.assertEqual(request["body"]["model"], "x")

    def test_old_revision_job_defaults_to_openai(self):
        manifest = {"version": 4}
        RevisionWorker._migrate_manifest(manifest)
        self.assertEqual(manifest["provider"], PROVIDER_OPENAI)

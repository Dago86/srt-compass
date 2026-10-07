import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_sottotitoli.video_summary import (
    SummaryWorker,
    collect_sources,
    estimate_summary,
    render_summary,
    summary_output_path,
)


class VideoSummaryTests(unittest.TestCase):
    def test_french_original_uses_french_summary_language(self):
        rendered, _sources = render_summary(
            {"output_text": "RÉSUMÉ\nUn contenu.", "output": []},
            (0, 60),
            "fr",
        )
        self.assertIn("Lingua: Francese", rendered)

    def test_estimate_is_approximate_and_includes_search_reserve(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nUn testo breve.\n",
                encoding="utf-8",
            )
            estimate = estimate_summary(source, "it")
            self.assertTrue(estimate.approximate)
            self.assertEqual(estimate.search_calls, 2)
            self.assertGreater(estimate.cost_usd, 0.02)

    def test_summary_uses_only_valid_research_sources_and_keeps_interval(self):
        response = {
            "output_text": "TEMATICHE\n- Storia\n\nRIASSUNTO\nUna storia. https://invented.invalid",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "x", "annotations": [
                    {"type": "url_citation", "url": "https://example.org/topic", "title": "Fonte"},
                    {"type": "url_citation", "url": "file:///private", "title": "Privata"},
                ]}],
            }],
        }
        rendered, sources = render_summary(response, (2400, 3000), "it")
        self.assertIn("00:40:00 – 00:50:00", rendered)
        self.assertIn("https://example.org/topic", rendered)
        self.assertNotIn("invented.invalid", rendered)
        self.assertEqual(len(sources), 1)
        self.assertEqual(collect_sources(response), sources)

    def test_worker_saves_txt_usage_sources_and_parent_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            parent.mkdir()
            (parent / "job.json").write_text(json.dumps({
                "version": 4, "status": "completed", "duration": 3600,
                "output": str(root / "source.srt"), "final_output": str(root / "source.srt"),
            }), encoding="utf-8")
            source = root / "source.srt"
            source.write_text(
                "1\n00:40:00,000 --> 00:40:04,000\nUna lezione di storia.\n",
                encoding="utf-8",
            )
            output = root / "source.scheda.txt"
            response = {
                "output_text": "TEMATICHE\n- Storia\n\nRIASSUNTO\nUna lezione.",
                "usage": {"input_tokens": 1000, "output_tokens": 200},
                "output": [
                    {"type": "web_search_call", "action": {"type": "search", "sources": [
                        {"url": "https://example.org/", "title": "Approfondimento"},
                    ]}},
                    {"type": "message", "content": []},
                ],
            }
            calls = []
            worker = SummaryWorker(
                source, output, "test-key", parent, "it", (2400, 3000),
                request_fn=lambda payload: calls.append(payload) or response,
            )
            worker.run()
            self.assertEqual(len(calls), 1)
            self.assertTrue(output.is_file())
            self.assertIn("Approfondimento", output.read_text(encoding="utf-8"))
            saved = json.loads((parent / "summary" / "summary.json").read_text(encoding="utf-8"))
            parent_saved = json.loads((parent / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["actual_cost"]["web_search_calls"], 1)
            self.assertEqual(parent_saved["summary_state"], "completed")
            self.assertTrue(any(kind == "complete" for kind, _ in worker.events.queue))

    def test_output_name_avoids_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "film.srt"
            (Path(temporary) / "film.scheda.txt").write_text("keep", encoding="utf-8")
            self.assertEqual(summary_output_path(source).name, "film.scheda-2.txt")

    def test_resume_reuses_saved_response_without_another_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "parent"
            child = parent / "summary"
            child.mkdir(parents=True)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nUn testo breve.\n",
                encoding="utf-8",
            )
            output = root / "source.scheda.txt"
            (parent / "job.json").write_text(json.dumps({
                "version": 4, "status": "completed", "duration": 2,
                "output": str(source), "final_output": str(source),
            }), encoding="utf-8")
            from video_sottotitoli.jobs import fingerprint

            manifest = {
                "version": 1, "status": "response_received",
                "source_srt": str(source), "source_fingerprint": fingerprint(source),
                "output": str(output), "model": "gpt-6-sol", "language": "it",
                "interval": [0, 2], "pricing": {
                    "input_per_million": 2, "output_per_million": 10,
                    "web_search_call_usd": 0.01,
                },
            }
            (child / "summary.json").write_text(json.dumps(manifest), encoding="utf-8")
            (child / "response.json").write_text(json.dumps({
                "output_text": "TEMATICHE\n- Storia\n\nRIASSUNTO\nContenuto riassunto.",
                "usage": {"input_tokens": 100, "output_tokens": 40},
                "output": [{"type": "message", "content": []}],
            }), encoding="utf-8")
            worker = SummaryWorker(
                source, output, "test-key", parent, "it", (0, 2),
                request_fn=lambda _payload: self.fail("non deve ripetere la richiesta"),
            )
            worker.run()
            self.assertTrue(output.is_file())
            saved = json.loads((child / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")


if __name__ == "__main__":
    unittest.main()

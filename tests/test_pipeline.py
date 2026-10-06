import csv
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import lastfm_pipeline as pipeline

class PipelineTests(unittest.TestCase):
    def test_cleaning_preserves_missing_and_zero_counts(self):
        tracks = [
            {"name": " Song ", "artist": {"name": " Artist "}, "playcount": "0"},
            {"name": "Song", "artist": {"name": "Artist"}, "playcount": "100"},
            {"name": "Other", "artist": {"name": "Artist"}, "playcount": "bad"},
            {"name": "", "artist": {"name": "Artist"}},
        ]
        rows = pipeline.clean_tracks(tracks, "2026-10-06")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["playcount"], 0)
        self.assertIsNone(rows[1]["playcount"])

    def test_csv_unicode_commas_and_empty_results(self):
        rows = [{key: None for key in pipeline.COLUMNS}]
        rows[0]["track_name"] = "Música, live"
        decoded = pipeline.make_csv(rows).decode("utf-8")
        self.assertEqual(list(csv.DictReader(io.StringIO(decoded)))[0]["track_name"], "Música, live")
        self.assertEqual(list(csv.DictReader(io.StringIO(pipeline.make_csv([]).decode()))), [])

    def test_api_errors_fail_without_exposing_key(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"error":10}'
        with patch.object(pipeline, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "code 10"):
                pipeline.fetch_page("private-key", 1, 50)

if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from viewer.catalog import Catalog, write_json


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.runs = root / "runs"
        self.maestro = root / "maestro"
        self.output = root / "outputs"
        run = self.runs / "transcriber-one"
        (run / "1").mkdir(parents=True)
        (run / "model-100.pt").write_bytes(b"checkpoint")
        write_json(run / "1" / "config.json", {"batch_size": 8})
        (self.maestro / "2004").mkdir(parents=True)
        for name in ("one.wav", "one.midi", "two.wav", "two.midi"):
            (self.maestro / "2004" / name).write_bytes(b"data")
        write_json(self.maestro / "maestro-v3.0.0.json", {
            "split": {"1": "test", "2": "train", "3": "test"},
            "canonical_composer": {"1": "A", "2": "B", "3": "C"},
            "canonical_title": {"1": "One", "2": "Two", "3": "Three"},
            "year": {"1": 2004, "2": 2004, "3": 2004},
            "duration": {"1": 10, "2": 20, "3": 10},
            "audio_filename": {"1": "2004/one.wav", "2": "2004/two.wav", "3": "2004/two.wav"},
            "midi_filename": {"1": "2004/one.midi", "2": "2004/two.midi", "3": "2004/two.midi"},
        })
        self.catalog = Catalog(self.runs, self.maestro, self.output)

    def tearDown(self):
        self.temporary.cleanup()

    def test_only_known_checkpoint_and_test_tracks_can_be_selected(self):
        models = self.catalog.models()
        self.assertEqual([model["id"] for model in models], ["transcriber-one:100"])
        self.assertEqual(models[0]["config"]["batch_size"], 8)
        self.assertEqual([track["id"] for track in self.catalog.tracks()], ["1", "3"])
        self.assertEqual(self.catalog.source("maestro", "1")["title"], "One")
        for model_id in ("../secret:1", "transcriber-one:101", "transcriber-one:100/../../"):
            with self.assertRaises(ValueError):
                self.catalog.model(model_id)
        with self.assertRaises(ValueError):
            self.catalog.source("maestro", "2")

    def test_aggregate_uses_one_value_per_completed_track(self):
        model_id = "transcriber-one:100"
        key = self.catalog.cache_key(model_id, "maestro", "1")
        write_json(self.catalog.result_path(key), {
            "metrics": {"metric/frame/f1": 0.4, "metric/note/f1": 0.6}})
        partial = self.catalog.aggregate(model_id)
        self.assertEqual(partial["completed"], 1)
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["metrics"]["metric/frame/f1"], 0.4)
        second_key = self.catalog.cache_key(model_id, "maestro", "3")
        write_json(self.catalog.result_path(second_key), {
            "metrics": {"metric/frame/f1": 0.8, "metric/note/f1": 1.0}})
        full = self.catalog.aggregate(model_id)
        self.assertTrue(full["complete"])
        self.assertAlmostEqual(full["metrics"]["metric/frame/f1"], 0.6)
        self.assertAlmostEqual(full["metrics"]["metric/note/f1"], 0.8)


if __name__ == "__main__":
    unittest.main()

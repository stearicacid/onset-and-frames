import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import Mock

from viewer.catalog import Catalog, write_json
from viewer.server import ViewerHandler, ViewerServer


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        run = root / "runs" / "example"
        (run / "1").mkdir(parents=True)
        (run / "model-1.pt").write_bytes(b"checkpoint")
        write_json(run / "1" / "config.json", {})
        maestro = root / "maestro"
        maestro.mkdir()
        write_json(maestro / "maestro-v3.0.0.json", {
            "split": {}, "canonical_composer": {}, "canonical_title": {},
            "year": {}, "duration": {}, "audio_filename": {}, "midi_filename": {}})
        self.server = ViewerServer(("127.0.0.1", 0), Catalog(root / "runs", maestro, root / "outputs"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def test_audio_transfer_stops_when_browser_disconnects(self):
        # ブラウザが再生位置を変更して送信先を閉じても、HTTPスレッドを例外終了させない。
        audio_path = Path(self.temporary.name) / "audio.wav"
        audio_path.write_bytes(b"audio data")
        handler = ViewerHandler.__new__(ViewerHandler)
        handler.headers = {}
        handler.command = "GET"
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        for error in (BrokenPipeError, ConnectionResetError):
            handler.wfile = Mock()
            handler.wfile.write.side_effect = error
            handler._file(audio_path)
            handler.wfile.write.assert_called_once()

    def test_catalog_rejects_unknown_model_and_upload_range_works(self):
        with urllib.request.urlopen(self.base + "/api/catalog") as response:
            catalog = json.load(response)
        self.assertEqual(catalog["models"][0]["id"], "example:1")

        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 1600)
        boundary = "ViewerTestBoundary"
        payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"test.wav\"\r\n"
                   "Content-Type: audio/wav\r\n\r\n").encode() + output.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(self.base + "/api/upload", data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request) as response:
            uploaded = json.load(response)
        self.assertFalse(uploaded["has_gt"])
        request = urllib.request.Request(
            self.base + f"/api/audio?kind=upload&id={uploaded['id']}",
            headers={"Range": "bytes=0-15"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 16)

        invalid = json.dumps({"model_ids": ["../../etc/passwd:1"],
                              "source": {"kind": "upload", "id": uploaded["id"]}}).encode()
        request = urllib.request.Request(self.base + "/api/jobs", data=invalid,
                                         headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 400)

        # 不正なJSON形状やIDも、サーバーエラーにせず入力エラーとして返す。
        for invalid_spec in ([], {"model_ids": [[]],
                                  "source": {"kind": "upload", "id": uploaded["id"]}},
                             {"model_ids": ["example:1"],
                              "source": {"kind": "upload", "id": "0" * 32}}):
            request = urllib.request.Request(
                self.base + "/api/jobs", data=json.dumps(invalid_spec).encode(),
                headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()

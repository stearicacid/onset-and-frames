"""SSHトンネル専用の小さなHTTP APIと静的画面。"""

import argparse
import cgi
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import mido
import soundfile

from viewer.catalog import Catalog, read_json, write_json


STATIC_ROOT = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024


class JobManager:
    """HTTP要求を短く返し、GPUを使う子プロセスを一つずつ起動する。"""

    def __init__(self, catalog):
        self.catalog = catalog
        self.directory = catalog.output_root / "jobs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pending = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, model_ids, source):
        if not isinstance(model_ids, list) or not 1 <= len(model_ids) <= 8:
            raise ValueError("モデルは1〜8個を選択してください")
        if any(not isinstance(model_id, str) for model_id in model_ids):
            raise ValueError("Checkpoint IDが不正です")
        if len(set(model_ids)) != len(model_ids):
            raise ValueError("モデルIDが重複しています")
        for model_id in model_ids:
            self.catalog.model(model_id)
        if not isinstance(source, dict):
            raise ValueError("音源IDが不正です")
        kind, source_id = source.get("kind"), source.get("id")
        self.catalog.source(kind, source_id)
        job_id = uuid.uuid4().hex
        spec = {"id": job_id, "model_ids": model_ids,
                "source": {"kind": kind, "id": str(source_id)}}
        status = {"id": job_id, "state": "queued", "completed": 0,
                  "total": len(model_ids), "results": [], "error": None}
        write_json(self.directory / f"{job_id}.spec.json", spec)
        write_json(self.directory / f"{job_id}.status.json", status)
        self.pending.put(job_id)
        return status

    def status(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("ジョブIDが不正です")
        path = self.directory / f"{job_id}.status.json"
        if not path.is_file():
            raise ValueError("ジョブが見つかりません")
        return read_json(path)

    def _run(self):
        while True:
            job_id = self.pending.get()
            spec_path = self.directory / f"{job_id}.spec.json"
            status_path = self.directory / f"{job_id}.status.json"
            log_path = self.directory / f"{job_id}.log"
            command = [sys.executable, "-m", "viewer.worker", str(spec_path), str(status_path)]
            with open(log_path, "a", encoding="utf-8") as log:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                         cwd=Path(__file__).resolve().parents[2])
            if process.returncode != 0:
                status = read_json(status_path)
                if status["state"] != "error":
                    status["state"] = "error"
                    status["error"] = f"推論プロセスが終了コード{process.returncode}で停止しました"
                    write_json(status_path, status)
            self.pending.task_done()


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, catalog):
        super().__init__(address, ViewerHandler)
        self.catalog = catalog
        self.jobs = JobManager(catalog)


class ViewerHandler(BaseHTTPRequestHandler):
    server_version = "OnsetsFramesViewer/1.0"

    def _host_allowed(self):
        host = self.headers.get("Host", "").split(":")[0].lower()
        return host in {"localhost", "127.0.0.1", "[::1]"}

    def _origin_allowed(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "localhost", "127.0.0.1", "::1"}

    def _json(self, value, code=200):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _file(self, path, content_type=None, download=False):
        path = Path(path)
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = False
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            if not match:
                self.send_error(416)
                return
            start = int(match.group(1))
            end = min(size - 1, int(match.group(2))) if match.group(2) else end
            if start > end or start >= size:
                self.send_error(416)
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    break
                try:
                    self.wfile.write(block)
                except (BrokenPipeError, ConnectionResetError):
                    # 再生位置の変更などでブラウザが転送を中止した場合は、残りの送信だけ終了する。
                    return
                remaining -= len(block)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_allowed():
            self.send_error(403, "localhost経由で接続してください")
            return
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/":
                self._file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            elif path in {"/static/app.js", "/static/style.css"}:
                self._file(STATIC_ROOT / path.rsplit("/", 1)[1])
            elif path == "/api/catalog":
                self._json({"models": self.server.catalog.models(),
                            "tracks": self.server.catalog.tracks()})
            elif path.startswith("/api/job/"):
                self._json(self.server.jobs.status(path.rsplit("/", 1)[1]))
            elif path.startswith("/api/result/"):
                result_path = self.server.catalog.result_path(path.rsplit("/", 1)[1])
                self._json(read_json(result_path))
            elif path == "/api/aggregate":
                self._json(self.server.catalog.aggregate(query["model_id"][0]))
            elif path in {"/api/audio", "/api/midi"}:
                source = self.server.catalog.source(query["kind"][0], query["id"][0])
                file_path = source["audio"] if path == "/api/audio" else source["midi"]
                if file_path is None:
                    raise ValueError("GT MIDIがありません")
                self._file(file_path, download=path == "/api/midi")
            elif path.startswith("/api/artifact/"):
                parts = path.split("/")
                if len(parts) != 5 or parts[4] != "prediction.mid":
                    raise ValueError("成果物IDが不正です")
                result_path = self.server.catalog.result_path(parts[3])
                if not result_path.is_file():
                    raise FileNotFoundError
                self._file(result_path.parent / "prediction.mid", "audio/midi", download=True)
            else:
                self.send_error(404)
        except (KeyError, IndexError, ValueError) as error:
            self._json({"error": str(error)}, 400)
        except FileNotFoundError:
            self._json({"error": "見つかりません"}, 404)

    def do_POST(self):
        if not self._host_allowed() or not self._origin_allowed():
            self.send_error(403, "localhost経由で接続してください")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path == "/api/jobs":
                if not 0 < length <= MAX_JSON_BYTES:
                    raise ValueError("リクエストが大きすぎます")
                spec = json.loads(self.rfile.read(length))
                if not isinstance(spec, dict):
                    raise ValueError("ジョブ指定はJSONオブジェクトにしてください")
                status = self.server.jobs.submit(spec.get("model_ids"), spec.get("source"))
                self._json(status, 202)
            elif self.path == "/api/upload":
                if not 0 < length <= MAX_UPLOAD_BYTES:
                    raise ValueError("WAVとMIDIの合計は512 MB以下にしてください")
                content_type = self.headers.get("Content-Type", "")
                if not content_type.startswith("multipart/form-data"):
                    raise ValueError("multipart/form-dataが必要です")
                cgi.maxlen = MAX_UPLOAD_BYTES
                form = cgi.FieldStorage(
                    fp=self.rfile, headers=self.headers,
                    environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type,
                             "CONTENT_LENGTH": str(length)}, keep_blank_values=True)
                audio = form["audio"] if "audio" in form else None
                gt = form["gt"] if "gt" in form else None
                if isinstance(audio, list) or audio is None or not audio.filename:
                    raise ValueError("WAVを1ファイル選択してください")
                if not audio.filename.lower().endswith(".wav"):
                    raise ValueError("WAVファイルのみ受け付けます")
                audio.file.seek(0)
                info = soundfile.info(audio.file)
                if info.format != "WAV" or info.samplerate < 8000 or info.samplerate > 192000:
                    raise ValueError("対応外のWAV形式です")
                if not 0 < info.duration <= 1800 or not 1 <= info.channels <= 8:
                    raise ValueError("音声は30分以内・8チャンネル以内にしてください")
                if gt is not None:
                    if isinstance(gt, list) or not gt.filename or not gt.filename.lower().endswith((".mid", ".midi")):
                        raise ValueError("GTはMIDIファイルを1つ選択してください")
                    gt.file.seek(0)
                    mido.MidiFile(file=gt.file)
                upload_id = uuid.uuid4().hex
                directory = self.server.catalog.output_root / "uploads" / upload_id
                directory.mkdir(parents=True, exist_ok=False)
                audio.file.seek(0)
                with open(directory / "audio.wav", "wb") as stream:
                    shutil.copyfileobj(audio.file, stream)
                if gt is not None:
                    gt.file.seek(0)
                    with open(directory / "ground_truth.mid", "wb") as stream:
                        shutil.copyfileobj(gt.file, stream)
                name = re.sub(r"[\x00-\x1f\x7f]", "", Path(audio.filename).name)[:100]
                write_json(directory / "manifest.json", {
                    "name": name, "duration": info.duration, "has_gt": gt is not None})
                self._json({"kind": "upload", "id": upload_id, "name": name,
                            "duration": info.duration, "has_gt": gt is not None}, 201)
            else:
                self.send_error(404)
        except (ValueError, KeyError, json.JSONDecodeError, soundfile.LibsndfileError) as error:
            self._json({"error": str(error)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ViewerServer((args.host, args.port), Catalog())
    print(f"Viewer listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Checkpointと評価曲を、許可済みディレクトリから列挙する。"""

import hashlib
import json
import os
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src" / "onsets-and-frames"
OUTPUT_ROOT = Path(os.environ.get("VIEWER_OUTPUT_ROOT", REPO_ROOT / "outputs" / "viewer"))
MAESTRO_ROOT = Path(os.environ.get("MAESTRO_PATH", "/mlnas/rin/datasets/MAESTRO"))
MAESTRO_METADATA = os.environ.get("MAESTRO_METADATA_FILENAME", "maestro-v3.0.0.json")
MODEL_ID_PATTERN = re.compile(r"^([A-Za-z0-9_-]+):(\d+)$")
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
TRACK_ID_PATTERN = re.compile(r"^\d+$")
CACHE_VERSION = "viewer-v1-evaluate-full-track-20261025"


def read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    """Viewerの出力だけを原子的に更新する。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
    os.replace(temporary, path)


class Catalog:
    def __init__(self, runs_root=None, maestro_root=None, output_root=None):
        self.runs_root = Path(runs_root or SOURCE_ROOT / "runs").resolve()
        self.maestro_root = Path(maestro_root or MAESTRO_ROOT).resolve()
        self.output_root = Path(output_root or OUTPUT_ROOT).resolve()
        self._tracks = None

    def models(self):
        """存在するCheckpointだけを表示し、runのSacred設定を添える。"""
        models = []
        for run_dir in sorted(self.runs_root.iterdir()) if self.runs_root.exists() else []:
            if not run_dir.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]+", run_dir.name):
                continue
            config_files = sorted(run_dir.glob("*/config.json"))
            config = read_json(config_files[0]) if config_files else {}
            for checkpoint in run_dir.glob("model-*.pt"):
                match = re.fullmatch(r"model-(\d+)\.pt", checkpoint.name)
                if match and checkpoint.is_file():
                    models.append({
                        "id": f"{run_dir.name}:{int(match.group(1))}",
                        "run": run_dir.name,
                        "step": int(match.group(1)),
                        "config": config,
                    })
        return sorted(models, key=lambda item: (item["run"], item["step"]))

    def model(self, model_id):
        match = MODEL_ID_PATTERN.fullmatch(str(model_id))
        if not match:
            raise ValueError("Checkpoint IDが不正です")
        run, step = match.groups()
        path = (self.runs_root / run / f"model-{int(step)}.pt").resolve()
        if self.runs_root not in path.parents or not path.is_file():
            raise ValueError("Checkpointが見つかりません")
        config_files = sorted((self.runs_root / run).glob("*/config.json"))
        return {
            "id": f"{run}:{int(step)}", "run": run, "step": int(step),
            "path": path,
            "config": read_json(config_files[0]) if config_files else {},
        }

    def tracks(self):
        """MAESTRO v3の列指向JSONからtest splitだけを取り出す。"""
        if self._tracks is None:
            metadata = read_json(self.maestro_root / MAESTRO_METADATA)
            split = metadata["split"]
            self._tracks = {}
            for track_id, value in split.items():
                if value != "test":
                    continue
                self._tracks[str(track_id)] = {
                    "id": str(track_id),
                    "composer": metadata["canonical_composer"][track_id],
                    "title": metadata["canonical_title"][track_id],
                    "year": metadata["year"][track_id],
                    "duration": metadata["duration"][track_id],
                    "audio_filename": metadata["audio_filename"][track_id],
                    "midi_filename": metadata["midi_filename"][track_id],
                }
        return [self._tracks[key] for key in sorted(self._tracks, key=int)]

    def source(self, kind, source_id):
        """HTTP入力のIDを検証し、登録済み音声・MIDIだけに解決する。"""
        if kind == "maestro":
            if not TRACK_ID_PATTERN.fullmatch(str(source_id)):
                raise ValueError("曲IDが不正です")
            if self._tracks is None:
                self.tracks()
            track = self._tracks.get(str(source_id))
            if track is None:
                raise ValueError("test splitの曲ではありません")
            audio = (self.maestro_root / track["audio_filename"]).resolve()
            if not audio.is_file():
                audio = audio.with_suffix(".flac")
            midi = (self.maestro_root / track["midi_filename"]).resolve()
            if self.maestro_root not in audio.parents or self.maestro_root not in midi.parents:
                raise ValueError("データセットのパスが不正です")
            if not audio.is_file() or not midi.is_file():
                raise ValueError("曲の音声またはMIDIが見つかりません")
            return {"kind": kind, "id": str(source_id), "audio": audio,
                    "midi": midi, "title": track["title"], "duration": track["duration"]}
        if kind == "upload":
            if not UPLOAD_ID_PATTERN.fullmatch(str(source_id)):
                raise ValueError("アップロードIDが不正です")
            directory = self.output_root / "uploads" / source_id
            if not (directory / "manifest.json").is_file():
                raise ValueError("アップロードIDが見つかりません")
            manifest = read_json(directory / "manifest.json")
            audio = (directory / "audio.wav").resolve()
            midi = (directory / "ground_truth.mid").resolve() if manifest["has_gt"] else None
            if directory.resolve() not in audio.parents or not audio.is_file():
                raise ValueError("アップロード音声が見つかりません")
            if midi is not None and (directory.resolve() not in midi.parents or not midi.is_file()):
                raise ValueError("アップロードMIDIが見つかりません")
            return {"kind": kind, "id": source_id, "audio": audio,
                    "midi": midi, "title": manifest["name"], "duration": manifest["duration"]}
        raise ValueError("音源の種類が不正です")

    def cache_key(self, model_id, kind, source_id):
        """Checkpointと入力ファイルが変わった場合だけ推論をやり直す。"""
        model = self.model(model_id)
        source = self.source(kind, source_id)
        files = [model["path"], source["audio"]]
        if source["midi"] is not None:
            files.append(source["midi"])
        fingerprint = [CACHE_VERSION, model["id"], kind, str(source_id)]
        fingerprint += [(str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in files]
        return hashlib.sha256(json.dumps(fingerprint).encode("utf-8")).hexdigest()

    def result_path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", str(key)):
            raise ValueError("結果IDが不正です")
        return self.output_root / "cache" / key / "result.json"

    def aggregate(self, model_id):
        """評価済みtest曲だけを平均する。全177曲が揃ったかも返す。"""
        keys = []
        values = {}
        for track in self.tracks():
            key = self.cache_key(model_id, "maestro", track["id"])
            path = self.result_path(key)
            if not path.is_file():
                continue
            result = read_json(path)
            if not result.get("metrics"):
                continue
            keys.append(track["id"])
            for name, value in result["metrics"].items():
                if value is not None:
                    values.setdefault(name, []).append(value)
        return {"model_id": model_id, "completed": len(keys), "total": len(self.tracks()),
                "complete": len(keys) == len(self.tracks()),
                "metrics": {name: sum(items) / len(items) for name, items in values.items()}}

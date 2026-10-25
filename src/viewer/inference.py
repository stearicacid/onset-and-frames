"""既存の推論・評価関数を単曲単位で呼び出す。"""

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch
from mir_eval.util import midi_to_hz

from evaluate import evaluate
from onsets_and_frames import (
    HOP_LENGTH, HOPS_IN_OFFSET, HOPS_IN_ONSET, MAX_MIDI, MIN_MIDI,
    SAMPLE_RATE, extract_notes, melspectrogram, save_midi, save_pianoroll,
)
from onsets_and_frames.midi import parse_midi
from transcribe import transcribe
from viewer.catalog import read_json, write_json


def decode_audio(path):
    """既存のデータセットと同じffmpeg設定で16 kHz/mono/int16にする。"""
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar",
         str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    return torch.from_numpy(np.frombuffer(decoded, dtype="<i2").copy())


def midi_labels(audio_length, midi_path):
    """dataset.loadと同じ32 msラベルを、データセットへ書かずに作る。"""
    steps = (audio_length - 1) // HOP_LENGTH + 1
    keys = MAX_MIDI - MIN_MIDI + 1
    label = torch.zeros(steps, keys, dtype=torch.uint8)
    velocity = torch.zeros(steps, keys, dtype=torch.uint8)
    tsv_path = Path(midi_path).with_suffix(".tsv")
    if tsv_path.is_file():
        notes = np.loadtxt(tsv_path, delimiter="\t", skiprows=1)
    else:
        notes = parse_midi(midi_path)
    if np.asarray(notes).size == 0:
        return label, velocity
    for onset, offset, note, strength in np.asarray(notes).reshape(-1, 4):
        pitch = int(note) - MIN_MIDI
        if pitch < 0 or pitch >= keys:
            continue
        left = int(round(onset * SAMPLE_RATE / HOP_LENGTH))
        onset_right = min(steps, left + HOPS_IN_ONSET)
        frame_right = min(steps, int(round(offset * SAMPLE_RATE / HOP_LENGTH)))
        offset_right = min(steps, frame_right + HOPS_IN_OFFSET)
        label[left:onset_right, pitch] = 3
        label[onset_right:frame_right, pitch] = 2
        label[frame_right:offset_right, pitch] = 1
        velocity[left:frame_right, pitch] = strength
    return label, velocity


def load_sample(source, device):
    """既存.ptがあれば読み取り専用で使い、アップロード時はメモリ内で作る。"""
    audio_path = source["audio"]
    cached_path = audio_path.with_suffix(".pt") if source["kind"] == "maestro" else None
    if cached_path is not None and cached_path.is_file():
        # 学習時のキャッシュはTensorと文字列のみなので安全な読み込みを使う。
        data = torch.load(cached_path, map_location="cpu", weights_only=True)
        audio = data["audio"]
        label = data["label"]
        velocity = data["velocity"]
    else:
        audio = decode_audio(audio_path)
        if source["midi"] is not None:
            label, velocity = midi_labels(len(audio), source["midi"])
        else:
            label = velocity = None

    sample = {"path": str(audio_path), "audio": audio.to(device).float().div_(32768.0)}
    if label is not None:
        label = label.to(device)
        sample.update({
            "label": label,
            "onset": (label == 3).float(),
            "offset": (label == 1).float(),
            "frame": (label > 1).float(),
            "velocity": velocity.to(device).float().div_(128.0),
        })
    return sample


def midi_notes(path):
    if path is None:
        return []
    notes = np.asarray(parse_midi(str(path)))
    if notes.size == 0:
        return []
    return [{"start": float(onset), "end": float(offset),
             "pitch": int(pitch), "velocity": int(strength)}
            for onset, offset, pitch, strength in notes.reshape(-1, 4)]


def metric_values(metrics):
    """evaluate()の曲別リストをJSONの単一数値にする。"""
    values = {}
    for name, samples in metrics.items():
        if name.startswith("metric/") and samples:
            number = float(samples[0])
            values[name] = number if math.isfinite(number) else None
    return values


def infer_one(catalog, model_id, source_kind, source_id, device=None, loaded_model=None):
    """許可済みCheckpointだけを読み、既存評価関数で単曲を評価する。"""
    model_info = catalog.model(model_id)
    source = catalog.source(source_kind, source_id)
    key = catalog.cache_key(model_id, source_kind, source_id)
    result_path = catalog.result_path(key)
    if result_path.is_file():
        return read_json(result_path), True

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    output_dir = result_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # mel変換器は既存コードでモジュール全体に作られるため、モデルと同じデバイスへ合わせる。
    melspectrogram.to(device)
    sample = load_sample(source, device)
    # weights_only=Falseは、runs/から列挙した自身のCheckpointにだけ使う。
    model = loaded_model
    if model is None:
        model = torch.load(model_info["path"], map_location=device, weights_only=False).eval()
    prediction_midi = output_dir / "prediction.mid"
    with torch.no_grad():
        if source["midi"] is not None:
            metrics = metric_values(evaluate([sample], model, save_path=str(output_dir)))
            generated = output_dir / (source["audio"].name + ".pred.mid")
            shutil.copyfile(generated, prediction_midi)
        else:
            predictions = transcribe(model, sample["audio"])
            pitches, intervals, velocities = extract_notes(
                predictions["onset"], predictions["frame"], predictions["velocity"])
            seconds = (intervals * HOP_LENGTH / SAMPLE_RATE).reshape(-1, 2)
            frequencies = np.array([midi_to_hz(MIN_MIDI + int(pitch)) for pitch in pitches])
            save_midi(str(prediction_midi), frequencies, seconds, velocities)
            save_pianoroll(str(output_dir / "prediction.png"),
                           predictions["onset"], predictions["frame"])
            metrics = None

    result = {
        "key": key, "model_id": model_id,
        "source": {"kind": source_kind, "id": str(source_id), "title": source["title"]},
        "duration": float(source["duration"]),
        "metrics": metrics,
        "ground_truth_notes": midi_notes(source["midi"]),
        "prediction_notes": midi_notes(prediction_midi),
        "prediction_midi": "prediction.mid",
    }
    write_json(result_path, result)
    del sample
    if loaded_model is None:
        del model
    if loaded_model is None and device == "cuda":
        torch.cuda.empty_cache()
    return result, False

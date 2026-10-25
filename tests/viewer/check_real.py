"""既存Dataset.__getitem__とevaluate()を使ってViewerのF1を照合する。"""

import argparse
import math

import torch

from evaluate import evaluate
from onsets_and_frames import melspectrogram
from onsets_and_frames.dataset import PianoRollAudioDataset
from viewer.catalog import Catalog, read_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--track-id", required=True)
    args = parser.parse_args()
    catalog = Catalog()
    source = catalog.source("maestro", args.track_id)
    cached_audio = source["audio"].with_suffix(".pt")
    if not cached_audio.is_file():
        parser.error("既存データセットの.ptキャッシュが必要です")
    result = read_json(catalog.result_path(catalog.cache_key(
        args.model, "maestro", args.track_id)))
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # 既存Datasetが行う正規化とラベル生成を、そのまま1曲だけに適用する。
    dataset = PianoRollAudioDataset.__new__(PianoRollAudioDataset)
    dataset.data = [torch.load(cached_audio, map_location="cpu", weights_only=True)]
    dataset.sequence_length = None
    dataset.device = device
    melspectrogram.to(device)
    model_path = catalog.model(args.model)["path"]
    model = torch.load(model_path, map_location=device, weights_only=False).eval()
    with torch.no_grad():
        reference = evaluate([dataset[0]], model)
    for name, values in reference.items():
        if not name.startswith("metric/"):
            continue
        expected = float(values[0])
        actual = result["metrics"][name]
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-7):
            raise AssertionError(f"{name}: Viewer={actual}, evaluate={expected}")
    print(f"F1一致: {args.model}, MAESTRO test曲ID {args.track_id}")


if __name__ == "__main__":
    main()

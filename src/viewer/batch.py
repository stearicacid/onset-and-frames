"""MAESTRO v3 testの177曲を、未評価分だけ順次評価するCLI。"""

import argparse
import sys

import torch

from onsets_and_frames import melspectrogram
from viewer.catalog import Catalog
from viewer.inference import infer_one


def main():
    parser = argparse.ArgumentParser(description="MAESTRO v3 testを未評価分だけ処理します")
    parser.add_argument("--model", action="append", required=True,
                        help="run名:step。複数回指定できます")
    parser.add_argument("--track-id", action="append", help="単曲確認用。省略時は全177曲")
    parser.add_argument("--limit", type=int, help="先頭から指定曲数だけ処理します")
    args = parser.parse_args()
    catalog = Catalog()
    tracks = catalog.tracks()
    if args.track_id:
        requested = set(args.track_id)
        tracks = [track for track in tracks if track["id"] in requested]
        if len(tracks) != len(requested):
            parser.error("test splitにない曲IDが含まれています")
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limitは1以上にしてください")
        tracks = tracks[:args.limit]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    errors = 0
    for model_id in args.model:
        model_info = catalog.model(model_id)
        pending = [track for track in tracks if not catalog.result_path(
            catalog.cache_key(model_id, "maestro", track["id"])).is_file()]
        print(f"{model_id}: {len(tracks) - len(pending)}曲をキャッシュから再利用、{len(pending)}曲を評価")
        if pending:
            melspectrogram.to(device)
            # モデルを曲ごとに再読込しない。GPU上には同時に1モデルだけ置く。
            model = torch.load(model_info["path"], map_location=device,
                               weights_only=False).eval()
            for index, track in enumerate(pending, 1):
                try:
                    infer_one(catalog, model_id, "maestro", track["id"],
                              device=device, loaded_model=model)
                    print(f"[{index}/{len(pending)}] {track['id']} {track['title']}", flush=True)
                except Exception as error:
                    errors += 1
                    print(f"[{index}/{len(pending)}] {track['id']}: {error}",
                          file=sys.stderr, flush=True)
            del model
            if device == "cuda":
                torch.cuda.empty_cache()
        summary = catalog.aggregate(model_id)
        print(f"{model_id}: {summary['completed']}/{summary['total']}曲が完了")
        for name in ("metric/frame/f1", "metric/note/f1", "metric/note-with-offsets/f1"):
            if name in summary["metrics"]:
                print(f"  {name}: {summary['metrics'][name]:.4f}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

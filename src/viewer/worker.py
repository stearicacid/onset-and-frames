"""WebジョブをHTTPサーバーとは別のGPUプロセスで逐次実行する。"""

import argparse
import traceback
from pathlib import Path

from viewer.catalog import Catalog, read_json, write_json
from viewer.inference import infer_one


def run_job(spec_path, status_path):
    catalog = Catalog()
    spec = read_json(spec_path)
    model_ids = spec["model_ids"]
    source = spec["source"]
    status = {"id": spec["id"], "state": "running", "completed": 0,
              "total": len(model_ids), "results": [], "error": None}
    write_json(status_path, status)
    try:
        for model_id in model_ids:
            status["current_model"] = model_id
            write_json(status_path, status)
            result, cache_hit = infer_one(catalog, model_id, source["kind"], source["id"])
            status["results"].append({"key": result["key"], "model_id": model_id,
                                      "cache_hit": cache_hit})
            status["completed"] += 1
            write_json(status_path, status)
        status["state"] = "done"
        status.pop("current_model", None)
        write_json(status_path, status)
    except Exception as error:
        status["state"] = "error"
        status["error"] = f"{type(error).__name__}: {error}"
        status.pop("current_model", None)
        write_json(status_path, status)
        Path(status_path).with_suffix(".traceback.txt").write_text(
            traceback.format_exc(), encoding="utf-8")
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("status")
    args = parser.parse_args()
    run_job(args.spec, args.status)


if __name__ == "__main__":
    main()

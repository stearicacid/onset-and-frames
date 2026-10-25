"""起動中Viewerへ実WAVを送り、別プロセス推論とキャッシュを確認する。"""

import argparse
import json
import time
import urllib.request
import uuid

from viewer.catalog import Catalog, read_json


def request_json(url, body=None, content_type=None):
    headers = {"Content-Type": content_type} if content_type else {}
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def wait_job(base, job_id):
    for _ in range(300):
        status = request_json(f"{base}/api/job/{job_id}")
        if status["state"] == "done":
            return status
        if status["state"] == "error":
            raise RuntimeError(status["error"])
        time.sleep(1)
    raise TimeoutError("推論ジョブが5分以内に終わりませんでした")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, action="append")
    parser.add_argument("--track-id", default="92")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--without-gt", action="store_true")
    args = parser.parse_args()
    catalog = Catalog()
    source = catalog.source("maestro", args.track_id)
    audio = source["audio"].read_bytes()
    gt = source["midi"].read_bytes()
    boundary = "ViewerSmoke" + uuid.uuid4().hex
    payload = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"sample.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n".encode() + audio
    )
    if not args.without_gt:
        payload += (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"gt\"; filename=\"sample.mid\"\r\n"
            "Content-Type: audio/midi\r\n\r\n".encode() + gt
        )
    payload += f"\r\n--{boundary}--\r\n".encode()
    upload = request_json(args.url + "/api/upload", payload,
                          f"multipart/form-data; boundary={boundary}")
    assert upload["has_gt"] is (not args.without_gt)
    spec = {"model_ids": args.model,
            "source": {"kind": "upload", "id": upload["id"]}}
    body = json.dumps(spec).encode()
    submitted = request_json(args.url + "/api/jobs", body, "application/json")
    finished = wait_job(args.url, submitted["id"])
    assert finished["completed"] == len(args.model)
    results = [request_json(args.url + "/api/result/" + item["key"])
               for item in finished["results"]]
    for model_id, result in zip(args.model, results):
        assert result["model_id"] == model_id and result["prediction_notes"]
        if args.without_gt:
            assert not result["ground_truth_notes"] and result["metrics"] is None
        else:
            assert result["ground_truth_notes"]
            assert result["metrics"]["metric/note/f1"] > 0
        with urllib.request.urlopen(args.url + "/api/artifact/" + result["key"] + "/prediction.mid") as response:
            assert response.read(4) == b"MThd"
    if not args.without_gt:
        with urllib.request.urlopen(args.url + "/api/midi?kind=upload&id=" + upload["id"]) as response:
            assert response.read(4) == b"MThd"
    with urllib.request.urlopen(urllib.request.Request(
            args.url + "/api/audio?kind=upload&id=" + upload["id"],
            headers={"Range": "bytes=0-31"})) as response:
        assert response.status == 206 and len(response.read()) == 32

    # 同じ入力・Checkpointで再要求し、GPU計算が省略されたことをジョブ結果で確認する。
    repeated = request_json(args.url + "/api/jobs", body, "application/json")
    reused = wait_job(args.url, repeated["id"])
    assert all(item["cache_hit"] for item in reused["results"])
    if args.without_gt:
        print("GTなしWAV HTTP推論完了", args.model)
    else:
        for model_id, result in zip(args.model, results):
            baseline = read_json(catalog.result_path(catalog.cache_key(
                model_id, "maestro", args.track_id)))
            difference = abs(result["metrics"]["metric/note/f1"] -
                             baseline["metrics"]["metric/note/f1"])
            print("WAV+GT HTTP推論完了", model_id, "note F1", result["metrics"]["metric/note/f1"])
            print("MAESTRO読込とのnote F1差", difference)
            assert difference < 1e-7
    print("再要求キャッシュ再利用", all(item["cache_hit"] for item in reused["results"]))


if __name__ == "__main__":
    main()

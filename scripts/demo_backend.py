"""Live HTTP demonstration; run while uvicorn is listening on localhost:8000."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, help="optional JSON evidence artifact")
    args = parser.parse_args()

    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(args.url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as response:
            return json.load(response)

    catalog = request("/catalog")
    body = {"versions": catalog["versions"], "selections": [
        {"measureId": "M7", "districtId": "nura"},
        {"measureId": "M8", "districtId": "nura"},
        {"measureId": "M10", "districtId": "nura"},
        {"measureId": "M12", "districtId": None},
        {"measureId": "M5", "districtId": "saryarka"},
    ]}
    evaluation = request("/v1/evaluate", body)
    assert evaluation["valid"] and abs(evaluation["score"] - 56.54307) < 1e-8
    invalid = request("/v1/evaluate", {"selections": []})
    assert not invalid["valid"] and invalid["score"] is None
    alternatives = request("/v1/alternatives", body)
    assert all(r["evaluation"]["valid"] and r["evaluation"]["score"] > evaluation["score"]
               for r in alternatives["results"])
    analysis = request("/v1/analysis", body)
    assert analysis["claims"]
    output = json.dumps({
        "versions": catalog["versions"], "score": evaluation["score"], "cost": evaluation["cost"],
        "delta": evaluation["decomposition"]["total"]["delta"], "invalidScore": invalid["score"],
        "alternatives": [{"score": item["evaluation"]["score"], "cost": item["evaluation"]["cost"]}
                         for item in alternatives["results"]],
        "analysisMode": analysis["mode"], "analysisStatus": analysis["status"],
        "claimCount": len(analysis["claims"]),
    }, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

"""Test 5: monitors lifecycle - create, run, list runs, list changes, delete."""
from __future__ import annotations

import time
from typing import Any

from common import client, record_credits, save_json

TARGET_URL = "https://lemmy.world/c/memes?dataType=Post&sort=New"


def create_monitor(c: Any) -> dict[str, Any]:
    body = {
        "name": "meme-genealogy spike - lemmy memes",
        "target": {"type": "page", "url": TARGET_URL},
        "schedule": {"type": "interval", "frequency": 10, "unit": "minutes"},
    }
    t0 = time.time()
    resp = c.post("/monitors", json=body)
    latency = time.time() - t0
    record_credits("monitor_create", resp, latency)
    data = resp.json()
    save_json("monitor_create_raw.json", data)
    return {"request_body": body, "status": resp.status_code, "response": data, "latency_s": round(latency, 2)}


def run_monitor(c: Any, monitor_id: str) -> dict[str, Any]:
    t0 = time.time()
    resp = c.post(f"/monitors/{monitor_id}/run")
    latency = time.time() - t0
    record_credits("monitor_run", resp, latency)
    data = resp.json()
    save_json("monitor_run_raw.json", data)
    return {"status": resp.status_code, "response": data, "latency_s": round(latency, 2)}


def list_runs(c: Any, monitor_id: str) -> dict[str, Any]:
    t0 = time.time()
    resp = c.get(f"/monitors/{monitor_id}/runs")
    latency = time.time() - t0
    record_credits("monitor_list_runs", resp, latency)
    data = resp.json()
    save_json("monitor_runs_raw.json", data)
    return {"status": resp.status_code, "response": data, "latency_s": round(latency, 2)}


def list_changes(c: Any, monitor_id: str) -> dict[str, Any]:
    t0 = time.time()
    resp = c.get(f"/monitors/{monitor_id}/changes")
    latency = time.time() - t0
    record_credits("monitor_list_changes", resp, latency)
    data = resp.json()
    save_json("monitor_changes_raw.json", data)
    return {"status": resp.status_code, "response": data, "latency_s": round(latency, 2)}


def delete_monitor(c: Any, monitor_id: str) -> dict[str, Any]:
    t0 = time.time()
    resp = c.delete(f"/monitors/{monitor_id}")
    latency = time.time() - t0
    record_credits("monitor_delete", resp, latency)
    data = resp.json()
    save_json("monitor_delete_raw.json", data)
    return {"status": resp.status_code, "response": data, "latency_s": round(latency, 2)}


def confirm_gone(c: Any, monitor_id: str) -> dict[str, Any]:
    resp = c.get(f"/monitors/{monitor_id}")
    return {"status": resp.status_code, "body": resp.text[:500]}


def main() -> None:
    c = client()
    results: dict[str, Any] = {}
    results["create"] = create_monitor(c)
    monitor_id = (results["create"]["response"] or {}).get("id")
    if not monitor_id:
        print("No monitor id returned, aborting further steps.")
        save_json("test5_summary.json", results)
        return
    print("monitor_id:", monitor_id)

    # Give the baseline run a moment before triggering an on-demand run.
    time.sleep(5)
    results["run"] = run_monitor(c, monitor_id)

    print("waiting 20s for run to complete...")
    time.sleep(20)

    results["list_runs"] = list_runs(c, monitor_id)
    results["list_changes"] = list_changes(c, monitor_id)

    results["delete"] = delete_monitor(c, monitor_id)
    results["confirm_gone"] = confirm_gone(c, monitor_id)

    save_json("test5_summary.json", results)
    import json as _json

    print(_json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()

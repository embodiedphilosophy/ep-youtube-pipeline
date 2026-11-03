"""Pick up work queued in Ops (approved picks, re-cuts, new thumbnails, Push to YouTube) and run it.
Runs every 30 minutes from GitHub Actions, or straight away when Ops nudges it. Usage: python queue_runner.py [--peek]"""
import os
import subprocess
import sys

from common import ops

HERE = os.path.dirname(os.path.abspath(__file__))


def run(args):
    p = subprocess.run([sys.executable, *args], cwd=HERE, capture_output=True, text=True)
    sys.stdout.write(p.stdout[-20000:])
    sys.stderr.write(p.stderr[-20000:])
    return p.returncode, (p.stderr or p.stdout).strip().splitlines()[-1:] or ["unknown error"]


def args_for(j):
    kind = j["kind"]
    if kind == "publish":
        return ["publish_youtube.py", "--cut-id", j["id"]]
    a = ["produce.py", "--vimeo-id", str(j["vimeo_id"])]
    if kind == "thumb":
        a += ["--thumb-only", j["id"]]
    else:
        a += ["--proposal-id", j["id"]]
        for k in ("teacher", "series"):
            if j.get(k):
                a += [f"--{k}", str(j[k])]
        if j.get("start") is not None and j.get("end") is not None:
            a += ["--start", str(j["start"]), "--end", str(j["end"])]
    for k in ("headline", "accent"):
        if j.get(k):
            a += [f"--{k}", str(j[k])]
    return a


def main():
    if "--peek" in sys.argv:
        n = ops("GET", "/queue", params={"peek": "1"}).get("waiting", 0)
        print(f"{n} job(s) waiting")
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
            f.write(f"waiting={n}\n")
        return
    jobs = ops("GET", "/queue").get("jobs", [])
    print(f"Running {len(jobs)} job(s)")
    failed = 0
    for j in jobs:
        print(f"\n=== {j['kind']} · item {j['id']} · Vimeo {j['vimeo_id']} ===", flush=True)
        try:
            code, last = run(args_for(j))
        except Exception as e:  # noqa: BLE001
            code, last = 1, [str(e)]
        if code:
            failed += 1
            msg = f"{j['kind']} stopped: {last[0][:400]}"
            print("FAILED:", msg)
            try:
                ops("POST", f"/cuts/{j['id']}/failed", json={"error": msg})
            except Exception as e:  # noqa: BLE001
                print("Could not report the failure to Ops:", e)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""Measure the captcha solver against live portal challenges, without logging in.

The portal rate-limits bursts: fetching many challenges back to back makes the
endpoint answer with an empty body for several minutes. This tool therefore
paces every request and stops as soon as the endpoint stops answering.

Two steps, so the ground truth stays human-owned:

    python packaging/captcha_accuracy.py collect --rounds 10 --interval 30 --out build/captcha-accuracy
    # read every image, fill the label column of build/captcha-accuracy/labels.tsv
    python packaging/captcha_accuracy.py score --out build/captcha-accuracy

`collect` records the image, the solver text, the backend and the latency. `score`
compares against the labels and prints exact / case-insensitive accuracy, which
tells whether the model's lowercase output is a real risk for this portal.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

CAPTCHA_URL = "https://cer.ysu.edu.cn/authserver/getCaptcha.htl"
MIN_INTERVAL = 20.0


def _session():
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 YSU-Net/accuracy-check"
    return session


def _fetch(session) -> bytes:
    response = session.get(f"{CAPTCHA_URL}?ts={int(time.time() * 1000)}", timeout=15)
    if response.status_code != 200 or not response.content:
        raise SystemExit(
            f"验证码接口没有返回图片（HTTP {response.status_code}），通常是请求过密被临时限流；稍后重试并加大 --interval"
        )
    return response.content


def collect(args) -> int:
    from ysu_net.auth import captcha

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    session = _session()
    interval = max(args.interval, MIN_INTERVAL)
    rows, records = [], []
    for index in range(1, args.rounds + 1):
        image = _fetch(session)
        started = time.monotonic()
        solution = captcha.solve(image)
        elapsed = time.monotonic() - started
        name = f"{index:02d}.jpg"
        (out / name).write_bytes(image)
        text = solution.text if solution else ""
        backend = solution.backend if solution else "none"
        rows.append(f"{name}\t{text}\t{backend}\t{elapsed * 1000:.0f}\t")
        records.append({"image": name, "solved": text, "backend": backend, "ms": round(elapsed * 1000)})
        print(f"{name} -> {text or '<未识别>'} ({backend}, {elapsed * 1000:.0f} ms)")
        if index < args.rounds:
            time.sleep(interval)
    labels = out / "labels.tsv"
    if not labels.exists():
        labels.write_text(
            "# 逐行填写最后一列：图片中的实际文字\n" + "\n".join(rows) + "\n", encoding="utf-8"
        )
    (out / "predictions.json").write_text(
        json.dumps({"url": CAPTCHA_URL, "rounds": records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n图片与预测已写入 {out}；填写 labels.tsv 后运行 score。")
    return 0


def score(args) -> int:
    out = Path(args.out)
    labels = out / "labels.tsv"
    if not labels.is_file():
        raise SystemExit(f"缺少标签文件：{labels}")
    exact = insensitive = total = 0
    misses = []
    for line in labels.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5 or not parts[4].strip():
            continue
        name, solved, truth = parts[0], parts[1], parts[4].strip()
        total += 1
        exact += solved == truth
        insensitive += solved.lower() == truth.lower()
        if solved.lower() != truth.lower():
            misses.append(f"{name}: 模型 {solved!r} / 实际 {truth!r}")
    if not total:
        raise SystemExit("labels.tsv 还没有已填写的行")
    print(f"样本 {total}；完全一致 {exact}/{total}；忽略大小写一致 {insensitive}/{total}")
    for miss in misses:
        print(f"  未命中 {miss}")
    if insensitive > exact:
        print("模型输出的大小写与图片不一致：门户若区分大小写，识别会因此失败。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    grab = sub.add_parser("collect", help="按节奏抓取验证码并记录识别结果")
    grab.add_argument("--rounds", type=int, default=10)
    grab.add_argument("--interval", type=float, default=30.0, help="两次抓取之间的秒数；实测低于 20 秒会被临时限流")
    grab.add_argument("--out", default="build/captcha-accuracy")
    run = sub.add_parser("score", help="按 labels.tsv 计算识别率")
    run.add_argument("--out", default="build/captcha-accuracy")
    args = parser.parse_args()
    return collect(args) if args.command == "collect" else score(args)


if __name__ == "__main__":
    raise SystemExit(main())

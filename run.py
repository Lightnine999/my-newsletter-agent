# run.py — 로컬과 GitHub Actions가 같은 진입점을 쓴다
import json, os, sys, time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import graph

METRICS_PATH = Path(__file__).resolve().parent / "store" / "metrics.jsonl"
# gpt-4.1-mini 100만 토큰당 가격(USD, 입력·출력) — 비용 감시용 추정치라 요금표가 바뀌면 고친다
PRICE_PER_M = {"prompt": 0.40, "completion": 1.60}

def already_sent(sent_path, today):            # 예비 실행(07:50·08:10)이 두 번 보내지 않게
    path = Path(sent_path)
    if not path.exists():
        return False
    return any(json.loads(l).get("date") == today for l in path.read_text(encoding="utf-8").splitlines() if l.strip())

def publish_result(log):
    last = next((l for l in reversed(log) if l.startswith("⑤")), "")
    return next((r for r in ("보냄", "dry-run", "실패") if last.endswith(r)), "알 수 없음")

def dropped(log):                               # 어디서 왜 빠졌는지
    stage = {"   취재 제외": "report", "   검수 제외": "verify"}
    return [{"stage": s, "detail": l.strip()[6:]} for l in log for p, s in stage.items() if l.startswith(p)]

def metrics_row(out, today, started, duration, env):
    tokens = dict(graph.USAGE)
    cost = sum(tokens.get(k, 0) * p / 1_000_000 for k, p in PRICE_PER_M.items())
    return {"date": today, "run_id": env.get("GITHUB_RUN_ID", "local"), "trigger": env.get("GITHUB_EVENT_NAME", "manual"),
            "started_at": started, "duration_s": round(duration),
            "collected": len(out["collected"]), "source_counts": dict(Counter(c["source"] for c in out["collected"])),
            "picked": dict(Counter(p["part"] for p in out["picked"])), "verified": len(out["verified"]),
            "dropped": dropped(out["log"]), "publish_result": publish_result(out["log"]),
            "tokens": sum(tokens.values()), "cost_usd": round(cost, 4)}

def write_metrics(row):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

def main(argv, env):
    dry = "--dry-run" in argv or env.get("DRY_RUN", "1") != "0"   # 기본은 보내지 않는다
    os.environ["DRY_RUN"] = "1" if dry else "0"                    # publish가 같은 값을 보게
    today = graph.today_kst()
    if not dry and already_sent(graph.SENT_PATH, today):
        print(f"오늘({today})은 이미 보냈어요. 예비 실행이라 건너뛰어요.")
        return 0
    started, t0 = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S"), time.time()
    try:
        out = graph.run()
    except graph.ConfigError as e:              # audience.yaml이 틀리면 수집 전에 멈춘다
        print(e)
        return 2
    for line in out["log"]:
        print(line)                             # 이 출력이 Actions 로그에 그대로 남는다
    if dry:
        return 0
    row = metrics_row(out, today, started, time.time() - t0, env)
    write_metrics(row)
    print(f"   기록 store/metrics.jsonl · {row['duration_s']}초 · 토큰 {row['tokens']} · ${row['cost_usd']}")
    # Discord가 거절해도 실행이 '성공'으로 끝나면 알 수가 없다 → 보내야 하는데 '보냄'이 아니면 exit 1 (Actions 빨간불)
    if row["publish_result"] != "보냄":
        print("발행 실패: Discord로 보내지 못했어요. 위의 '⑤ 발행' 줄을 확인하세요.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv, os.environ))

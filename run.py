# run.py — 로컬과 GitHub Actions가 같은 진입점을 쓴다
import json, os, sys, time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord_review
import graph
import hitl
import hitl_store

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
    if last.startswith("⑤ 발행   보류"):          # 사람이 보류한 호
        return "보류"
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
    if "--check" in argv:
        return check(env)
    dry = "--dry-run" in argv or env.get("DRY_RUN", "1") != "0"   # 기본은 보내지 않는다
    os.environ["DRY_RUN"] = "1" if dry else "0"                    # publish가 같은 값을 보게
    today = graph.today_kst()
    if not dry and already_sent(graph.SENT_PATH, today):
        print(f"오늘({today})은 이미 보냈어요. 예비 실행이라 건너뛰어요.")
        return 0
    if today in {r["date"] for r in hitl_store.waiting()}:   # 07:30 실행이 이미 승인 요청을 올렸다
        print(f"오늘({today}) 호는 승인 대기 중이에요. 확인 실행(run.py --check)이 이어 가요.")
        return 0
    started, t0 = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S"), time.time()
    try:
        with hitl_store.saver(env) as saver:    # 걸리면 approve에서 멈춘 지점이 여기에 남는다
            out = graph.run(checkpointer=saver, thread_id=today)
            if "__interrupt__" not in out:
                saver.delete_thread(today)      # 다 끝난 호는 지운다 — 암호화 파일이 커지지 않게
    except graph.ConfigError as e:              # audience.yaml이 틀리면 수집 전에 멈춘다
        print(e)
        return 2
    except hitl_store.StateKeyError as e:
        print(e)
        return 1
    for line in out["log"]:
        print(line)                             # 이 출력이 Actions 로그에 그대로 남는다
    # 실행마다 한 줄 — publish_result가 보냄 / dry-run / 실패로 나뉘어 dry-run도 품질 추적에 쓴다
    row = metrics_row(out, today, started, time.time() - t0, env)
    if "__interrupt__" in out:
        return wait_for_review(out["__interrupt__"][0].value, row, dry, env)
    write_metrics(row)
    print(f"   기록 store/metrics.jsonl · {row['duration_s']}초 · 토큰 {row['tokens']} · ${row['cost_usd']}")
    if dry:
        return 0
    # Discord가 거절해도 실행이 '성공'으로 끝나면 알 수가 없다 → 보내야 하는데 '보냄'이 아니면 exit 1 (Actions 빨간불)
    if row["publish_result"] != "보냄":
        print("발행 실패: Discord로 보내지 못했어요. 위의 '⑤ 발행' 줄을 확인하세요.")
        return 1
    return 0

# ── HITL: 승인 대기 · 확인 실행 (docs/hitl-plan.md "구현 설계") ──────────
def wait_for_review(review, row, dry, env):     # 걸린 기사가 있어 approve에서 멈췄다
    print(f"   승인 대기 · 걸린 기사 {len(review['flagged'])}건 / {review['total']}건")
    write_metrics({**row, "publish_result": "승인 대기"})
    date = review["date"]
    if env.get("GITHUB_ACTIONS") and not hitl_store.can_seal(env):
        # 키가 없으면 멈춘 지점을 저장소에 남길 수 없다 → 확인 실행이 이어 갈 수 없으니 카드도 올리지 않는다
        print("HITL_STATE_KEY가 없어 승인 대기 건을 저장하지 못했어요. Actions Secrets에 등록하세요.")
        return 1
    cfg, mid, code = discord_review.config(env), None, 0
    if cfg:
        try:
            mid = discord_review.post_review(cfg, review, dry_run=dry)
            print("   디스코드 #검토 채널에 승인 요청을 올렸어요")
        except discord_review.DiscordError as e:
            print(f"   승인 요청을 올리지 못했어요 · {e}")
            code = 1
    else:
        print("   디스코드 봇 설정(DISCORD_BOT_TOKEN·DISCORD_REVIEW_CHANNEL_ID·DISCORD_REVIEWER_ID)이 없어 알리지 못했어요")
        code = 0 if dry else 1                  # 보내는 날인데 아무도 모르면 빨간불
    hitl_store.save_review({"date": date, "status": "waiting", "message_id": mid, "dry_run": dry, "seen": "0",
                            "flagged": len(review["flagged"]), "total": review["total"]})
    print("   정오까지 응답이 없으면 걸린 기사만 빼고 발송돼요")
    return code

def check(env, now=None):                       # 30분마다: 담당자 응답을 읽어 이어 간다
    rows = hitl_store.waiting()
    if not rows:
        print("승인을 기다리는 호가 없어요.")
        return 0
    cfg, now, code = discord_review.config(env), now or datetime.now(hitl.KST), 0
    try:
        with hitl_store.saver(env) as saver:
            for row in rows:
                code = max(code, check_one(saver, row, cfg, now, env))
    except hitl_store.StateKeyError as e:
        print(e)
        return 1
    return code

def read_answer(row, review, cfg):              # 디스코드 응답 → (Decision|None, 갱신한 기록, 오류 여부)
    if not (cfg and row.get("message_id")):
        return None, row, False
    try:
        got = discord_review.read_response(cfg, row["message_id"], review["flagged"], row.get("seen", "0"))
        row = {**row, "seen": got.seen}
        if got.problem and got.problem != row.get("asked"):   # 같은 말을 30분마다 되풀이하지 않는다
            discord_review.reply(cfg, row["message_id"], got.problem)
            row = {**row, "asked": got.problem}
        return got.decision, row, False
    except discord_review.DiscordError as e:
        print(f"{row['date']} · 디스코드 응답을 읽지 못했어요 · {e}")
        return None, row, True

def check_one(saver, row, cfg, now, env):
    date, t0 = row["date"], time.time()
    review = graph.pending(saver, date)
    if review is None:                          # 이미 이어 갔거나 지워진 호
        hitl_store.save_review({**row, "status": "done", "result": "대기 건 없음"})
        return 0
    d, new_row, failed = read_answer(row, review, cfg)
    source = "디스코드"
    if d is None and hitl.past_deadline(date, now):
        d, source = hitl.timeout_decision(review["flagged"]), "정오 규칙"
    if d is None:
        if new_row != row:
            hitl_store.save_review(new_row)
        print(f"{date} · 아직 응답이 없어요")
        return 1 if failed else 0
    os.environ["DRY_RUN"] = "1" if row.get("dry_run") else "0"   # 처음 실행과 같은 모드로 발행한다
    out = graph.resume(saver, date, d.model_dump())
    saver.delete_thread(date)
    for line in out["log"][-3:]:
        print(line)
    result = publish_result(out["log"])
    hitl_store.save_review({**new_row, "status": "done", "result": result, "decision": d.action, "source": source})
    write_metrics({**metrics_row(out, date, datetime.now(hitl.KST).strftime("%H:%M:%S"), time.time() - t0, env),
                   "publish_result": result, "review": {"decision": d.action, "source": source}})
    if cfg and row.get("message_id"):
        try:
            discord_review.close_card(cfg, row["message_id"], f"{hitl.ACTION_LABEL[d.action]} ({source}) · 결과 {result}")
        except discord_review.DiscordError as e:
            print(f"   처리 표시를 못 했어요 · {e}")
    return 1 if result == "실패" else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv, os.environ))

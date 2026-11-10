# hitl_store — 승인을 기다리는 호의 '멈춘 지점'을 실행과 실행 사이에 남긴다 (docs/hitl-plan.md "구현 설계")
# 비유: Actions는 아침에 잠깐 출근하는 직원이다. 멈춘 지점은 자물쇠 채운 서랍(암호화 파일)에 넣어 저장소에 커밋하고,
#       다음 확인 실행이 같은 열쇠(HITL_STATE_KEY)로 열어 이어 간다. 서버는 없다
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from langgraph.checkpoint.sqlite import SqliteSaver

ROOT = Path(__file__).resolve().parent
PLAIN = ROOT / "store" / "hitl" / "checkpoints.sqlite"   # 풀어 둔 파일 — 기사 본문이 있어 커밋하지 않는다 (.gitignore)
SEALED = ROOT / "store" / "checkpoints.enc"              # 암호화한 파일 — 공개 저장소에 커밋한다
REVIEWS = ROOT / "store" / "reviews.jsonl"               # 승인 대기 기록 — 날짜·상태·디스코드 메시지 번호만 (본문 없음)


class StateKeyError(Exception):
    """HITL_STATE_KEY가 틀려서 저장된 대기 건을 열 수 없을 때."""


def _fernet(env):
    key = (env.get("HITL_STATE_KEY") or "").strip()
    return Fernet(key.encode()) if key else None


@contextmanager
def saver(env, seal=True):                      # with saver(os.environ) as s: graph.run(checkpointer=s, ...)
    # seal=False: 읽기만 한다 (로컬 승인 화면) — 암호화 파일을 다시 쓰지 않는다
    f = _fernet(env)
    PLAIN.parent.mkdir(parents=True, exist_ok=True)
    if f and SEALED.exists():                   # 저장소에 있는 것이 정본 — 풀어서 덮어쓴다
        try:
            PLAIN.write_bytes(f.decrypt(SEALED.read_bytes()))
        except InvalidToken:
            raise StateKeyError("HITL_STATE_KEY가 store/checkpoints.enc를 만든 키와 달라요") from None
    conn = sqlite3.connect(PLAIN, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
        conn.commit()
    finally:
        conn.close()
    if f and seal:                              # 키가 없으면(로컬 시험) 풀어 둔 파일만 쓴다
        SEALED.parent.mkdir(parents=True, exist_ok=True)
        SEALED.write_bytes(f.encrypt(PLAIN.read_bytes()))


def can_seal(env):
    return _fernet(env) is not None


# ── 승인 대기 기록 (reviews.jsonl) ──────────────────────────
def reviews():                                  # 날짜 → 마지막 줄
    if not REVIEWS.exists():
        return {}
    rows = [json.loads(l) for l in REVIEWS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["date"]: r for r in rows}


def waiting():
    return [r for r in reviews().values() if r.get("status") == "waiting"]


def save_review(row):
    REVIEWS.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")}
    with REVIEWS.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row

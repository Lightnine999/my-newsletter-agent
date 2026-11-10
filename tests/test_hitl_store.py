"""hitl_store — 멈춘 지점(SQLite 체크포인트)을 암호화해 저장소에 두고, 다음 실행이 풀어서 이어 간다."""
import pytest
from cryptography.fernet import Fernet

import graph
import hitl_store
from tests.test_approve import RISKY, SAFE, pipeline  # noqa: F401  (픽스처 재사용)

KEY = Fernet.generate_key().decode()


def test_암호화한_파일로_다음_실행이_이어_간다(pipeline):
    pipeline([SAFE, RISKY])
    env = {"HITL_STATE_KEY": KEY}
    with hitl_store.saver(env) as s:                       # 1번째 실행 (07:30)
        graph.run(checkpointer=s, thread_id="2026-11-10")
    assert hitl_store.SEALED.exists()
    assert b"cholesterol" not in hitl_store.SEALED.read_bytes()      # 공개 저장소에 올라가도 본문이 안 보인다
    hitl_store.PLAIN.unlink()                              # Actions 컴퓨터가 사라진 것과 같다
    with hitl_store.saver(env) as s:                       # 2번째 실행 (확인)
        assert graph.pending(s, "2026-11-10")["flagged"][0]["url"] == "u-risk"
        out = graph.resume(s, "2026-11-10", {"action": "approve"})
    assert len(out["verified"]) == 2


def test_키가_없으면_암호화_파일을_만들지_않는다(pipeline):
    pipeline([RISKY])
    with hitl_store.saver({}) as s:
        graph.run(checkpointer=s, thread_id="t")
    assert hitl_store.PLAIN.exists() and not hitl_store.SEALED.exists()


def test_키가_틀리면_분명하게_멈춘다(pipeline):
    pipeline([RISKY])
    with hitl_store.saver({"HITL_STATE_KEY": KEY}) as s:
        graph.run(checkpointer=s, thread_id="t")
    with pytest.raises(hitl_store.StateKeyError):
        with hitl_store.saver({"HITL_STATE_KEY": Fernet.generate_key().decode()}):
            pass


def test_승인_대기_기록은_날짜마다_마지막_줄이_이긴다():
    hitl_store.save_review({"date": "2026-11-10", "status": "waiting", "message_id": "1"})
    hitl_store.save_review({"date": "2026-11-09", "status": "done"})
    assert [r["date"] for r in hitl_store.waiting()] == ["2026-11-10"]
    hitl_store.save_review({**hitl_store.reviews()["2026-11-10"], "status": "done"})
    assert hitl_store.waiting() == []
    assert hitl_store.reviews()["2026-11-10"]["message_id"] == "1"


def test_읽기만_할_때는_암호화_파일을_다시_쓰지_않는다(pipeline):   # 로컬 화면이 열 때마다 git 변경이 생기지 않게
    pipeline([RISKY])
    env = {"HITL_STATE_KEY": KEY}
    with hitl_store.saver(env) as s:
        graph.run(checkpointer=s, thread_id="t")
    before = hitl_store.SEALED.read_bytes()
    with hitl_store.saver(env, seal=False) as s:
        assert graph.pending(s, "t")
    assert hitl_store.SEALED.read_bytes() == before

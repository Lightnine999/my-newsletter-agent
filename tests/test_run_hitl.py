"""run.py × HITL — 매일 실행은 걸리면 카드를 올리고 멈추고, --check가 응답을 읽어 이어 간다."""
import json
from datetime import datetime

import pytest

import discord_review as dr
import graph
import hitl
import hitl_store
import run
from tests.test_approve import RISKY, SAFE, pipeline  # noqa: F401

TODAY = "2026-11-10"
BOT = {"DISCORD_BOT_TOKEN": "t", "DISCORD_REVIEW_CHANNEL_ID": "100", "DISCORD_REVIEWER_ID": "7"}
MORNING, AFTERNOON = (datetime(2026, 11, 10, h, 30, tzinfo=hitl.KST) for h in (9, 12))


@pytest.fixture
def day(monkeypatch, tmp_path, pipeline):
    monkeypatch.setattr(run, "METRICS_PATH", tmp_path / "store" / "metrics.jsonl")
    monkeypatch.setattr(graph, "today_kst", lambda: TODAY)
    monkeypatch.setenv("DRY_RUN", "1")
    posted, closed, replies = [], [], []
    monkeypatch.setattr(dr, "post_review", lambda cfg, review, dry_run, **kw: posted.append((review, dry_run)) or "555")
    monkeypatch.setattr(dr, "close_card", lambda cfg, mid, text, **kw: closed.append(text))
    monkeypatch.setattr(dr, "reply", lambda cfg, mid, text, **kw: replies.append(text))
    pipeline([SAFE, RISKY])
    return {"posted": posted, "closed": closed, "replies": replies}


def answer(monkeypatch, decision=None, problem=None):
    monkeypatch.setattr(dr, "read_response",
                        lambda cfg, mid, flagged, seen="0", **kw: dr.Response(decision, "901", problem))


def metrics():
    return [json.loads(l) for l in run.METRICS_PATH.read_text(encoding="utf-8").splitlines()]


def test_걸리면_카드를_올리고_승인_대기로_끝낸다(day):
    assert run.main(["run.py", "--dry-run"], BOT) == 0
    review, dry = day["posted"][0]
    assert [a["url"] for a in review["flagged"]] == ["u-risk"] and dry is True
    row = hitl_store.reviews()[TODAY]
    assert (row["status"], row["message_id"], row["dry_run"]) == ("waiting", "555", True)
    assert metrics()[-1]["publish_result"] == "승인 대기"
    assert not graph.OUTPUT_DIR.exists()                               # 아직 아무것도 발행하지 않았다


def test_오늘_호가_승인_대기면_예비_실행은_건너뛴다(day, monkeypatch):
    run.main(["run.py", "--dry-run"], BOT)
    monkeypatch.setattr(graph, "run", lambda **kw: pytest.fail("다시 돌리면 안 돼요"))
    assert run.main(["run.py", "--dry-run"], BOT) == 0


def test_Actions에서_키가_없으면_대기_건을_잃으니_빨간불(day):
    assert run.main(["run.py", "--dry-run"], {**BOT, "GITHUB_ACTIONS": "true"}) == 1
    assert day["posted"] == []                                          # 저장 못 한 건은 카드도 올리지 않는다


def test_보내야_하는데_봇_설정이_없으면_빨간불(day):
    assert run.main(["run.py"], {"DRY_RUN": "0"}) == 1
    assert hitl_store.reviews()[TODAY]["status"] == "waiting"           # 정오 규칙이 나중에 처리할 수 있게 남긴다


def test_확인_실행이_답을_읽어_이어서_발행한다(day, monkeypatch):
    run.main(["run.py", "--dry-run"], BOT)
    answer(monkeypatch, hitl.Decision(action="approve_without", exclude=["u-risk"]))
    assert run.check(BOT, now=MORNING) == 0
    row = hitl_store.reviews()[TODAY]
    assert (row["status"], row["result"], row["decision"]) == ("done", "dry-run", "approve_without")
    assert "u-risk" not in (graph.OUTPUT_DIR / f"{TODAY}.md").read_text(encoding="utf-8").replace("u-safe", "")
    assert day["closed"] and "dry-run" in day["closed"][0]


def test_응답이_없으면_정오_전에는_기다리고_정오가_지나면_걸린_기사만_빼고_보낸다(day, monkeypatch):
    run.main(["run.py", "--dry-run"], BOT)
    answer(monkeypatch, None)
    assert run.check(BOT, now=MORNING) == 0
    assert hitl_store.reviews()[TODAY]["status"] == "waiting"
    assert run.check(BOT, now=AFTERNOON) == 0
    row = hitl_store.reviews()[TODAY]
    assert (row["status"], row["source"]) == ("done", "정오 규칙")


def test_보류면_보내지_않고_처리됨(day, monkeypatch):
    run.main(["run.py", "--dry-run"], BOT)
    answer(monkeypatch, hitl.Decision(action="hold", reason="수치 확인"))
    assert run.check(BOT, now=MORNING) == 0
    assert hitl_store.reviews()[TODAY]["result"] == "보류"
    assert not graph.OUTPUT_DIR.exists()


def test_되물을_말은_한_번만_단다(day, monkeypatch):
    run.main(["run.py", "--dry-run"], BOT)
    answer(monkeypatch, None, problem="반응이 여러 개예요")
    run.check(BOT, now=MORNING)
    run.check(BOT, now=MORNING)
    assert day["replies"] == ["반응이 여러 개예요"]


def test_기다리는_호가_없으면_조용히_끝난다(day):
    assert run.check(BOT, now=MORNING) == 0

"""approve 노드 — 기준에 걸리면 interrupt로 멈추고, 담당자 응답(Command resume)으로 이어 간다."""
import pytest
from langgraph.checkpoint.memory import InMemorySaver

import graph

SAFE = {"url": "u-safe", "part": "menswear", "source": "GQ", "title": "T", "headline": "가을 코트 고르기",
        "summary": "울 코트 세 벌을 비교합니다.", "why": "출근룩", "body": "We compare three wool coats."}
RISKY = {**SAFE, "url": "u-risk", "part": "sports", "headline": "콜레스테롤 낮추는 식단",
         "summary": "LDL 콜레스테롤을 낮추는 음식", "body": "LDL cholesterol can drop with oats."}


@pytest.fixture
def pipeline(monkeypatch):                      # 수집~검수는 건너뛰고, 검수 결과만 정해 준다
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(graph, "collect", lambda s, cfg: {"log": ["① 수집   가짜"]})
    monkeypatch.setattr(graph, "select", lambda s, cfg: {"picked": [], "log": ["② 선별   가짜"]})
    def use(arts):
        monkeypatch.setattr(graph, "verify", lambda s, cfg: {"verified": arts, "log": ["④ 검수   가짜"]})
    return use


def test_걸린_기사가_없으면_멈추지_않고_발행한다(pipeline):
    pipeline([SAFE])
    out = graph.run(checkpointer=InMemorySaver(), thread_id="2026-11-10")
    assert "__interrupt__" not in out
    assert out["log"][-1].endswith("dry-run")


def test_걸리면_발행_전에_멈추고_승인_화면_내용을_넘긴다(pipeline):
    pipeline([SAFE, RISKY])
    out = graph.run(checkpointer=InMemorySaver(), thread_id="2026-11-10")
    review = out["__interrupt__"][0].value
    assert [a["url"] for a in review["flagged"]] == ["u-risk"]
    assert review["date"] == "2026-11-10" and review["total"] == 2
    assert not any(l.startswith("⑤") for l in out["log"])             # 아직 아무것도 안 보냈다


def test_응답으로_이어_가면_응답대로_발행한다(pipeline):
    pipeline([SAFE, RISKY])
    saver = InMemorySaver()
    graph.run(checkpointer=saver, thread_id="t1")
    out = graph.resume(saver, "t1", {"action": "approve_without", "exclude": ["u-risk"]})
    assert [a["url"] for a in out["verified"]] == ["u-safe"]
    assert out["log"][-1].endswith("dry-run")
    assert graph.pending(saver, "t1") is None                          # 더 기다리는 게 없다


def test_보류면_아무것도_보내지_않는다(pipeline, tmp_path):
    pipeline([SAFE, RISKY])
    saver = InMemorySaver()
    graph.run(checkpointer=saver, thread_id="t1")
    out = graph.resume(saver, "t1", {"action": "hold", "reason": "수치 확인"})
    assert out["log"][-1] == "⑤ 발행   보류 · 수치 확인"
    assert not graph.OUTPUT_DIR.exists()                                # 사본도 만들지 않는다


def test_대기_중인_호의_승인_화면_내용을_다시_꺼낸다(pipeline):
    pipeline([RISKY])
    saver = InMemorySaver()
    graph.run(checkpointer=saver, thread_id="t1")
    assert graph.pending(saver, "t1")["flagged"][0]["url"] == "u-risk"

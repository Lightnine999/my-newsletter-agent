"""모든 테스트에서 실제 OpenAI·네트워크 호출을 막아요. 필요한 테스트만 가짜로 갈아 끼워요."""
import pytest
import requests

import graph
import hitl_store


def _blocked(*args, **kwargs):
    raise RuntimeError("테스트에서 실제 네트워크·API 호출을 했어요. 가짜로 바꿔 끼우세요.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    # 파일도 진짜 issues/·output/·store/에 쓰지 않게 임시 폴더로 돌린다
    monkeypatch.setattr(graph, "SENT_PATH", tmp_path / "store" / "sent.jsonl")
    monkeypatch.setattr(graph, "ISSUES_DIR", tmp_path / "issues")
    monkeypatch.setattr(graph, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(graph, "llm", _blocked)
    monkeypatch.setattr(graph, "fetch_feed", _blocked)
    monkeypatch.setattr(graph, "extract_body", _blocked)
    monkeypatch.setattr(graph.requests, "post", _blocked)   # Discord 발송도 막는다
    for name in ("get", "put", "patch", "delete", "request"):  # 디스코드 봇 호출도 막는다
        monkeypatch.setattr(requests, name, _blocked)
    # 승인 대기 체크포인트·기록도 임시 폴더로
    monkeypatch.setattr(hitl_store, "PLAIN", tmp_path / "store" / "hitl" / "checkpoints.sqlite")
    monkeypatch.setattr(hitl_store, "SEALED", tmp_path / "store" / "checkpoints.enc")
    monkeypatch.setattr(hitl_store, "REVIEWS", tmp_path / "store" / "reviews.jsonl")

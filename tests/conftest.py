"""모든 테스트에서 실제 OpenAI·네트워크 호출을 막아요. 필요한 테스트만 가짜로 갈아 끼워요."""
import pytest

import graph


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

"""ask — 구조화 출력이 같은 항목을 끝없이 되풀이해 길이 한도에 걸린 경우 (2026-11-10 실측: select에서 32,768토큰)"""
from types import SimpleNamespace as NS

import pytest
from openai import LengthFinishReasonError
from pydantic import BaseModel

import graph


class Out(BaseModel):
    ok: bool


def usage(prompt, completion):
    return NS(prompt_tokens=prompt, completion_tokens=completion)


def length_error():
    return LengthFinishReasonError(completion=NS(usage=usage(100, graph.MAX_OUT)))


class FakeLLM:                                  # 정해 둔 순서대로 예외를 던지거나 답을 돌려준다
    def __init__(self, *results):
        self.results, self.calls = list(results), []
        self.chat = NS(completions=NS(parse=self.parse))

    def parse(self, **kw):
        self.calls.append(kw)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return NS(usage=usage(10, 5), choices=[NS(message=NS(parsed=r))])


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(graph, "USAGE", graph.Counter())
    def install(*results):
        llm = FakeLLM(*results)
        monkeypatch.setattr(graph, "llm", lambda: llm)
        return llm
    return install


def test_출력_길이에_상한을_둔다(fake):
    llm = fake(Out(ok=True))
    graph.ask("sys", "user", Out)
    assert llm.calls[0]["max_completion_tokens"] == graph.MAX_OUT


def test_길이_초과면_seed를_바꿔_한_번_더_묻는다(fake):
    llm = fake(length_error(), Out(ok=True))
    assert graph.ask("sys", "user", Out) == Out(ok=True)
    assert [c["seed"] for c in llm.calls] == [graph.SEED, graph.SEED + 1]   # 같은 seed면 같은 반복에 빠질 수 있다


def test_다시_물어도_넘치면_예외를_그대로_던진다(fake):
    fake(length_error(), length_error())
    with pytest.raises(LengthFinishReasonError):
        graph.ask("sys", "user", Out)


def test_실패한_호출의_토큰도_비용에_센다(fake):
    fake(length_error(), Out(ok=True))
    graph.ask("sys", "user", Out)
    assert graph.USAGE["completion"] == graph.MAX_OUT + 5
    assert graph.USAGE["prompt"] == 100 + 10

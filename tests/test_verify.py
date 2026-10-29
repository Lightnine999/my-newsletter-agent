"""5부 verify 테스트 — 검수 LLM과 교체용 report는 가짜로 바꿔 끼워요."""
import graph

CFG = graph.load_config()
BODY = "본문 문장입니다. " * 80


def draft(i, source=None, part="sports"):
    return {"url": f"https://x/{i}", "title": f"t{i}", "source": source or f"S{i}", "part": part,
            "event": f"e{i}", "slot": "base", "body": BODY,
            "headline": f"제목{i}", "summary": f"요약{i}입니다.", "why": f"이유{i}예요."}


def spare(i, source=None, part="sports"):
    d = draft(i, source, part)
    return {k: v for k, v in d.items() if k not in ("body", "headline", "summary", "why")}


def fake_check(bad=()):
    def check(d, cfg):
        if d["url"] in bad:
            return graph.Verdict(supported=False, problems=["원문에 없는 수치"])
        return graph.Verdict(supported=True, problems=[])
    return check


def run_verify(monkeypatch, drafted, spares=(), bad=(), picked=None):
    monkeypatch.setattr(graph, "check_draft", fake_check(bad))
    monkeypatch.setattr(graph, "extract_body", lambda url: BODY)
    monkeypatch.setattr(graph, "write_draft",
                        lambda text, cfg, a, korean_only=False: graph.Draft(headline="교체 제목", summary="교체 요약입니다.", why="교체 이유예요."))
    s = {"drafted": drafted, "spares": list(spares), "picked": picked if picked is not None else drafted}
    return graph.verify(s, CFG)


def test_모두_통과하면_그대로_남긴다(monkeypatch):
    out = run_verify(monkeypatch, [draft(i) for i in range(3)])
    assert [d["url"] for d in out["verified"]] == [f"https://x/{i}" for i in range(3)]
    assert out["log"][-1].startswith("④ 검수   3 → 3건")


def test_불합격은_빼고_이유를_로그에_남긴다(monkeypatch):
    out = run_verify(monkeypatch, [draft(0), draft(1, source="GQ 코리아")], bad={"https://x/1"})
    assert [d["url"] for d in out["verified"]] == ["https://x/0"]
    assert any("검수 제외 GQ 코리아" in l and "원문에 없는 수치" in l for l in out["log"])


def test_빠진_자리는_예비_후보를_취재하고_검수해서_채운다(monkeypatch):
    out = run_verify(monkeypatch, [draft(0), draft(1)], spares=[spare(9)], bad={"https://x/1"})
    urls = [d["url"] for d in out["verified"]]
    assert urls == ["https://x/0", "https://x/9"]
    assert out["verified"][1]["slot"] == "spare"
    assert any("교체" in l for l in out["log"])


def test_report에서_빠진_기사_자리도_예비로_채운다(monkeypatch):
    picked = [spare(0), spare(1)]                  # 2건 골랐는데 report가 1건만 넘김(본문 부족 등)
    out = run_verify(monkeypatch, [draft(0)], spares=[spare(9)], picked=picked)
    assert len(out["verified"]) == 2


def test_예비도_불합격이면_다음_예비로_넘어가지_않고_한_번만_시도한다(monkeypatch):
    out = run_verify(monkeypatch, [draft(0), draft(1)], spares=[spare(8), spare(9)], bad={"https://x/1", "https://x/8"})
    assert [d["url"] for d in out["verified"]] == ["https://x/0"]


def test_예비가_매체_상한을_넘기면_건너뛴다(monkeypatch):
    drafted = [draft(i, source="GQ 코리아") for i in range(3)] + [draft(3)]
    out = run_verify(monkeypatch, drafted, spares=[spare(8, source="GQ 코리아"), spare(9)], bad={"https://x/3"})
    assert [d["url"] for d in out["verified"]][-1] == "https://x/9"


def test_검수_호출이_실패하면_통과시키지_않는다(monkeypatch):
    def boom(d, cfg):
        raise RuntimeError("API 오류")
    monkeypatch.setattr(graph, "check_draft", boom)
    out = graph.verify({"drafted": [draft(0)], "spares": [], "picked": [draft(0)]}, CFG)
    assert out["verified"] == []
    assert any("검수 오류" in l for l in out["log"])

"""4부 report 테스트 — 본문 추출과 LLM은 가짜로 바꿔 끼워요."""
import graph

CFG = graph.load_config()
ART = {"url": "https://x/1", "title": "t", "source": "GQ 코리아", "part": "grooming", "slot": "base", "event": "e"}
BODY = "본문 문장입니다. " * 80                    # 600자 넘는 본문


def ko(headline="각질 제거는 주 2~3회", summary="피부과 전문의는 주 2~3회를 권합니다.", why="면도 자극이 줄어요."):
    return graph.Draft(headline=headline, summary=summary, why=why)


def en():
    return graph.Draft(headline="Exfoliate twice a week", summary="Dermatologists suggest it.", why="Less irritation.")


def run_report(monkeypatch, body=BODY, drafts=None, boom=False):
    calls = []

    def fake_extract(url):
        if boom:
            raise RuntimeError("403")
        return body

    def fake_draft(text, cfg, article, korean_only=False):
        calls.append(korean_only)
        return drafts[len(calls) - 1]

    monkeypatch.setattr(graph, "extract_body", fake_extract)
    monkeypatch.setattr(graph, "write_draft", fake_draft)
    return graph.report({"article": ART}, CFG), calls


def test_세_칸을_채우고_기사_정보와_본문을_넘긴다(monkeypatch):
    out, calls = run_report(monkeypatch, drafts=[ko()])
    d = out["drafted"][0]
    assert (d["headline"], d["why"]) == ("각질 제거는 주 2~3회", "면도 자극이 줄어요.")
    assert d["part"] == "grooming" and d["url"] == ART["url"]
    assert d["body"].startswith("본문 문장입니다.")      # verify가 원문과 대조할 재료
    assert calls == [False]


def test_본문이_600자_미만이면_빼고_로그에_남긴다(monkeypatch):
    out, calls = run_report(monkeypatch, body="짧은 본문")
    assert out["drafted"] == [] and calls == []
    assert "취재 제외" in out["log"][0] and "본문 5자" in out["log"][0]


def test_본문을_못_가져오면_빼고_로그에_남긴다(monkeypatch):
    out, _ = run_report(monkeypatch, boom=True)
    assert out["drafted"] == []
    assert "취재 제외" in out["log"][0] and "본문 0자" in out["log"][0]


def test_영어로_나오면_한국어_지시를_붙여_한_번_다시_쓴다(monkeypatch):
    out, calls = run_report(monkeypatch, drafts=[en(), ko()])
    assert calls == [False, True]
    assert out["drafted"][0]["headline"] == "각질 제거는 주 2~3회"


def test_다시_써도_영어면_뺀다(monkeypatch):
    out, calls = run_report(monkeypatch, drafts=[en(), en()])
    assert out["drafted"] == [] and len(calls) == 2
    assert "한국어 아님" in out["log"][0]


def test_why가_비면_한국어가_아닌_것으로_본다(monkeypatch):
    out, _ = run_report(monkeypatch, drafts=[ko(why=""), ko(why="")])
    assert out["drafted"] == []


def test_그래프에서_고른_기사_수만큼_report가_돌아_drafted에_모인다(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(graph, "fetch_feed", lambda url: [])
    monkeypatch.setattr(graph, "extract_body", lambda url: BODY)
    monkeypatch.setattr(graph, "write_draft", lambda text, cfg, article, korean_only=False: ko())
    picked = [{**ART, "url": f"https://x/{i}"} for i in range(3)]
    monkeypatch.setattr(graph, "select", lambda s, cfg: {"picked": picked, "log": ["② 선별 (가짜)"]})
    out = graph.run()
    assert len(out["drafted"]) == 3
    assert {d["url"] for d in out["drafted"]} == {p["url"] for p in picked}

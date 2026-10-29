"""2부 collect 테스트 — 피드 요청은 가짜로 바꿔 끼워요."""
import json
from datetime import datetime, timedelta, timezone

import graph

NOW = datetime.now(timezone.utc)


def cfg_with(sources):
    cfg = graph.load_config()
    return cfg.model_copy(update={"sources": [graph.Source(**s) for s in sources]})


def entry(url, hours_ago=1, title="t"):
    at = NOW - timedelta(hours=hours_ago) if hours_ago is not None else None
    return {"title": title, "url": url, "at": at, "summary": "", "cats": []}


def run_collect(sources, feeds, sent_path=None, tmp_path=None):
    def fake_fetch(url):
        result = feeds[url]
        if isinstance(result, Exception):
            raise result
        return result
    sent_path = sent_path or (tmp_path / "sent.jsonl")
    return graph.collect({"hours": 24}, cfg_with(sources), fetch=fake_fetch, sent_path=sent_path)


def test_url_key는_추적_꼬리표만_뗀다():
    assert graph.url_key("https://a.com/x/?utm_source=rss&id=3") == "https://a.com/x?id=3"
    # 골프매거진코리아는 기사 번호가 ? 뒤에 있어요 — 통째로 떼면 전부 한 건이 돼요
    a = graph.url_key("https://golfmagazinekorea.com/LIFESTYLE/?idx=1&bmode=view")
    b = graph.url_key("https://golfmagazinekorea.com/LIFESTYLE/?idx=2&bmode=view")
    assert a != b


def test_24시간_밖과_날짜_없는_글은_버린다(tmp_path):
    src = [{"name": "A", "url": "u1", "part": "sports"}]
    out = run_collect(src, {"u1": [entry("https://a.com/1", 2),
                                   entry("https://a.com/2", 30),
                                   entry("https://a.com/3", None)]}, tmp_path=tmp_path)
    assert [i["url"] for i in out["collected"]] == ["https://a.com/1"]
    assert out["collected"][0]["part"] == "sports"
    assert out["collected"][0]["source"] == "A"


def test_같은_글은_한_번만_남기고_카테고리_피드의_파트를_쓴다(tmp_path):
    src = [{"name": "GQ", "url": "all", "part": "mixed"},
           {"name": "GQ", "url": "style", "part": "menswear"}]
    out = run_collect(src, {"all": [entry("https://gq.kr/1?utm_medium=rss")],
                            "style": [entry("https://gq.kr/1")]}, tmp_path=tmp_path)
    assert len(out["collected"]) == 1
    assert out["collected"][0]["part"] == "menswear"


def test_한_소스가_실패해도_나머지는_모으고_로그에_남긴다(tmp_path):
    src = [{"name": "죽은곳", "url": "dead", "part": "sports"},
           {"name": "산곳", "url": "ok", "part": "grooming"}]
    out = run_collect(src, {"dead": RuntimeError("403"), "ok": [entry("https://b.com/1")]},
                      tmp_path=tmp_path)
    assert len(out["collected"]) == 1
    assert "응답 없음" in out["log"][0] and "죽은곳" in out["log"][0]


def test_이미_보낸_주소는_뺀다(tmp_path):
    sent = tmp_path / "sent.jsonl"
    sent.write_text(json.dumps({"url": "https://c.com/1", "date": "2026-10-28"}) + "\n", encoding="utf-8")
    src = [{"name": "C", "url": "u", "part": "sports"}]
    out = run_collect(src, {"u": [entry("https://c.com/1"), entry("https://c.com/2")]}, sent_path=sent)
    assert [i["url"] for i in out["collected"]] == ["https://c.com/2"]
    assert "이미 보냄 1" in out["log"][0]


def test_소스별_건수를_로그에_남긴다(tmp_path):
    src = [{"name": "A", "url": "u1", "part": "sports"},
           {"name": "B", "url": "u2", "part": "grooming"}]
    out = run_collect(src, {"u1": [entry("https://a.com/1"), entry("https://a.com/2")],
                            "u2": []}, tmp_path=tmp_path)
    assert "A 2" in out["log"][0] and "B 0" in out["log"][0]
    assert out["log"][0].startswith("① 수집   24시간 · 2건")

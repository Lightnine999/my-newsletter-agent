"""6부 publish 테스트 — Discord 요청은 가짜로 바꿔 끼우고, 파일은 임시 폴더에 써요."""
import json

import pytest

import graph

CFG = graph.load_config()
TODAY = "2026-10-30"


def art(i, part, summary="요약입니다. " * 5):
    return {"url": f"https://x/{part}/{i}", "title": f"t{i}", "source": f"매체{i}", "part": part,
            "headline": f"제목 {i}", "summary": summary, "why": "40대에게 쓸모 있어요."}


TEN = [art(i, p) for p, n in (("menswear", 3), ("sports", 4), ("grooming", 3)) for i in range(n)]


class FakePost:
    def __init__(self, status=204):
        self.status, self.calls = status, []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append(json)
        return type("R", (), {"status_code": self.status, "text": "err"})()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(graph, "SENT_PATH", tmp_path / "store" / "sent.jsonl")
    monkeypatch.setattr(graph, "ISSUES_DIR", tmp_path / "issues")
    monkeypatch.setattr(graph, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(graph, "today_kst", lambda: TODAY)
    monkeypatch.setattr(graph, "PAUSE", 0)
    return tmp_path


def size(payload):
    return len(payload.get("content", "")) + sum(
        len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
        for e in payload.get("embeds", []))


# ── 메시지 만들기 ─────────────────────────────────────────

def test_첫_메시지는_오늘_배분이고_파트마다_한_메시지에_기사_카드가_붙는다():
    msgs = graph.build_messages(TEN, CFG, TODAY)
    assert "👔 3 · 🏃 4 · 🧴 3" in msgs[0]["content"] and TODAY in msgs[0]["content"]
    assert [len(m["embeds"]) for m in msgs[1:]] == [3, 4, 3]
    card = msgs[2]["embeds"][0]
    assert card["url"] == "https://x/sports/0" and "💡" in card["description"]
    assert card["footer"]["text"].startswith("매체0")


def test_디스코드_한도를_넘지_않는다():
    long = [art(i, "sports", summary="아주 긴 요약. " * 600) for i in range(5)]
    for m in graph.build_messages(long, CFG, TODAY):
        assert len(m.get("embeds", [])) <= 10 and size(m) <= 6000
        assert all(len(e["title"]) <= 256 and len(e["description"]) <= 4096 for e in m.get("embeds", []))


def test_0건이면_조용합니다_한_장():
    msgs = graph.build_messages([], CFG, TODAY)
    assert len(msgs) == 1 and "조용합니다" in msgs[0]["content"]


def test_마크다운_사본에_파트와_원문_링크가_들어간다():
    md = graph.render_markdown(TEN, CFG, TODAY)
    assert md.startswith(f"# 40대 남성 아침 브리핑 · {TODAY}")
    assert "## 👔 남성복" in md and "](https://x/grooming/2)" in md


# ── publish 노드 ──────────────────────────────────────────

def test_dry_run이면_보내지_않고_output에만_사본을_쓴다(paths, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    fake = FakePost()
    out = graph.publish({"verified": TEN}, CFG, post=fake)
    assert fake.calls == [] and out["log"][-1].endswith("dry-run")
    assert (paths / "output" / f"{TODAY}.md").exists()
    assert not (paths / "issues").exists() and not graph.SENT_PATH.exists()


def test_보내면_issues에_사본을_쓰고_보낸_주소를_쌓는다(paths, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    fake = FakePost(204)
    out = graph.publish({"verified": TEN}, CFG, post=fake)
    assert len(fake.calls) == 4 and out["log"][-1].endswith("보냄")
    assert (paths / "issues" / f"{TODAY}.md").exists()
    rows = [json.loads(l) for l in graph.SENT_PATH.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 10 and rows[0]["date"] == TODAY
    assert graph.load_sent(graph.SENT_PATH) >= {graph.url_key(a["url"]) for a in TEN}   # 2부가 다음 날 뺀다


def test_디스코드가_거절하면_실패로_적고_보낸_주소는_쌓지_않는다(paths, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    out = graph.publish({"verified": TEN}, CFG, post=FakePost(400))
    assert out["log"][-1].endswith("실패")
    assert not graph.SENT_PATH.exists()


def test_보내야_하는데_웹훅이_없으면_실패(paths, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    fake = FakePost()
    out = graph.publish({"verified": TEN}, CFG, post=fake)
    assert fake.calls == [] and out["log"][-1].endswith("실패")


def test_로그에_웹훅_주소가_찍히지_않는다(paths, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook/SECRET")
    out = graph.publish({"verified": TEN}, CFG, post=FakePost(400))
    assert all("SECRET" not in l for l in out["log"])

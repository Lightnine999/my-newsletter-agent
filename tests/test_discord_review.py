"""discord_review — 봇 REST 호출만 (켜 둘 필요 없음). 가짜 HTTP로 무엇을 보내고 어떻게 읽는지 확인한다."""
import pytest

import discord_review as dr

CFG = dr.Config(token="tok", channel_id="100", reviewer_id="7")
FLAGGED = [{"url": "a", "headline": "콜레스테롤 식단", "summary": "요약 A", "why": "w", "source": "MH", "title": "T",
            "reasons": ["건강·의학 키워드: 콜레스테롤"], "evidence": ["LDL cholesterol drops."]}]
REVIEW = {"date": "2026-11-10", "total": 9, "flagged": FLAGGED, "auto": [], "on_approve": "9건이 Discord 구독 채널로 발송됩니다"}


class Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}
        self.content = b"x" if data is not None else b""
    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self, routes=None):
        self.calls, self.routes = [], routes or {}
    def request(self, method, url, **kw):
        path = url.removeprefix(dr.API)
        self.calls.append((method, path, kw))
        for (m, prefix), resp in self.routes.items():
            if m == method and path.startswith(prefix):
                return resp(kw) if callable(resp) else resp
        return Resp(200, {"id": "555"})


def test_환경변수가_하나라도_없으면_설정_없음():
    assert dr.config({"DISCORD_BOT_TOKEN": "t", "DISCORD_REVIEW_CHANNEL_ID": "1"}) is None
    assert dr.config({"DISCORD_BOT_TOKEN": "t", "DISCORD_REVIEW_CHANNEL_ID": "1", "DISCORD_REVIEWER_ID": "2"}).reviewer_id == "2"


def test_카드는_담당자만_멘션하고_반응_세개와_스레드를_단다():
    http = FakeHTTP()
    mid = dr.post_review(CFG, REVIEW, dry_run=False, http=http)
    assert mid == "555"
    method, path, kw = http.calls[0]
    assert (method, path) == ("POST", "/channels/100/messages")
    body = kw["json"]
    assert "<@7>" in body["content"] and body["allowed_mentions"] == {"users": ["7"]}
    assert "9건이 Discord 구독 채널로 발송됩니다" in body["content"]
    assert len(body["content"]) <= 2000
    emb = body["embeds"][0]
    assert emb["title"].startswith("1. 콜레스테롤 식단") and "콜레스테롤" in emb["description"]
    assert "LDL cholesterol drops." in emb["description"]
    assert sum(c[0] == "PUT" and "/reactions/" in c[1] for c in http.calls) == 3
    assert ("POST", "/channels/100/messages/555/threads") in [(c[0], c[1]) for c in http.calls]
    assert all(kw["headers"]["Authorization"] == "Bot tok" for _, _, kw in http.calls)


def test_dry_run_카드는_표시가_붙는다():
    http = FakeHTTP()
    dr.post_review(CFG, REVIEW, dry_run=True, http=http)
    assert "dry-run" in http.calls[0][2]["json"]["content"]


def msg(mid, author, content):
    return {"id": mid, "author": {"id": author}, "content": content}


def test_담당자_답글이_반응보다_먼저고_마지막_답글이_이긴다():
    http = FakeHTTP({("GET", "/channels/555/messages"): Resp(200, [msg("903", "7", "보류: 다시 확인"),
                                                                   msg("902", "8", "승인"),       # 다른 사람
                                                                   msg("901", "7", "승인")])})
    got = dr.read_response(CFG, "555", FLAGGED, seen="0", http=http)
    assert got.decision.action == "hold" and got.decision.reason == "다시 확인"
    assert got.seen == "903"


def test_답글이_없으면_담당자가_누른_반응을_본다():
    def reactions(kw):
        return Resp(200, [{"id": "7"}, {"id": "999"}])
    http = FakeHTTP({("GET", "/channels/555/messages"): Resp(200, []),
                     ("GET", "/channels/100/messages/555/reactions/%E2%9E%96"): reactions,
                     ("GET", "/channels/100/messages/555/reactions/"): Resp(200, [{"id": "999"}])})  # 봇만 누름
    got = dr.read_response(CFG, "555", FLAGGED, seen="0", http=http)
    assert got.decision.action == "approve_without" and got.decision.exclude == ["a"]


def test_알아듣지_못한_새_답글은_한_번만_되묻는다():
    http = FakeHTTP({("GET", "/channels/555/messages"): Resp(200, [msg("901", "7", "음 글쎄요")]),
                     ("GET", "/channels/100/messages/555/reactions/"): Resp(200, [])})
    got = dr.read_response(CFG, "555", FLAGGED, seen="0", http=http)
    assert got.decision is None and "이해하지 못했어요" in got.problem
    again = dr.read_response(CFG, "555", FLAGGED, seen=got.seen, http=http)
    assert again.problem is None                                         # 같은 답글로 또 묻지 않는다


def test_반응을_여러_개_누르면_승인으로_치지_않고_묻는다():
    http = FakeHTTP({("GET", "/channels/555/messages"): Resp(200, []),
                     ("GET", "/channels/100/messages/555/reactions/"): Resp(200, [{"id": "7"}])})  # 셋 다 누름
    got = dr.read_response(CFG, "555", FLAGGED, seen="0", http=http)
    assert got.decision is None and "하나만" in got.problem


def test_속도_제한이면_기다렸다_다시_보낸다():
    tries = []
    def limited(kw):
        tries.append(1)
        return Resp(429, {"retry_after": 0.01}) if len(tries) == 1 else Resp(204)
    http = FakeHTTP({("PUT", "/channels/"): limited})
    dr.react(CFG, "555", "✅", http=http, sleep=lambda s: None)
    assert len(tries) == 2


def test_거절되면_토큰_없이_오류를_낸다():
    http = FakeHTTP({("POST", "/channels/"): Resp(403, {"message": "Missing Access"})})
    with pytest.raises(dr.DiscordError) as e:
        dr.reply(CFG, "555", "안녕", http=http)
    assert "403" in str(e.value) and "tok" not in str(e.value)

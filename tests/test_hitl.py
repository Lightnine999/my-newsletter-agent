"""hitl — 멈춤 기준 · 승인 화면 데이터 · 담당자 응답"""
import pytest
from pydantic import ValidationError

import hitl


def art(url="u1", headline="제목", summary="요약", body=""):
    return {"url": url, "headline": headline, "summary": summary, "body": body, "source": "S", "title": "T"}


# ── 기준 ① 원문에 없는 수치 ──
def test_원문에_없는_숫자를_찾는다():
    a = art(summary="가격은 45,000원입니다.", body="It costs 39,000 won.")
    assert hitl.missing_numbers(a) == ["45000"]

def test_영어_숫자_단어와_연대는_원문에_있는_것으로_본다():
    a = art(headline="향수 3종", summary="1920~30년대 스타일", body="Three ways. In the 1920s and 1930s.")
    assert hitl.missing_numbers(a) == []

def test_40대는_독자_표현이라_수치로_보지_않는다():
    assert hitl.missing_numbers(art(summary="40대에게 좋습니다.", body="good")) == []

def test_만_단위를_펴서_비교한다():
    assert hitl.missing_numbers(art(summary="3만 원", body="30,000 won")) == []


# ── 기준 ② 건강·의학 조언 ──
def test_건강_키워드를_찾는다():
    a = art(headline="LDL 콜레스테롤 줄이기", summary="혈압도 함께")
    assert hitl.health_words(a) == ["콜레스테롤", "혈압"]

def test_부상_예방과_치료_기사는_통과시킨다():   # 2026-11-10 사용자 결정 — 운동 기사마다 걸려 헛멈춤만 만들었다
    a = art(headline="마라톤 부상 없이 준비하기", summary="부상 치료와 회복 루틴을 소개합니다.")
    assert hitl.health_words(a) == []
    assert not hitl.CRITERIA["①+②"](a)


# ── 승인 화면 데이터 ──
def test_걸린_기사만_flagged에_이유와_원문_근거를_붙인다():
    arts = [art("a", summary="혈압을 낮춥니다.", body="Lowers blood pressure.\nOther line."),
            art("b", summary="코트 추천", body="Coat.")]
    r = hitl.build_review(arts, hitl.CRITERIA["①+②"])
    assert r["total"] == 2
    assert [a["url"] for a in r["flagged"]] == ["a"]
    assert r["flagged"][0]["reasons"] == ["건강·의학 키워드: 혈압"]
    assert r["flagged"][0]["evidence"]                  # 원문 발췌가 비어 있지 않다
    assert [a["url"] for a in r["auto"]] == ["b"]
    assert r["on_approve"] == "2건이 Discord 구독 채널로 발송됩니다"

def test_근거_문장은_걸린_숫자가_나오는_문장을_고른다():
    a = art(summary="12주 프로그램", body="Intro text. A 10-week plan works. End.")
    assert hitl.evidence(a) == ["Intro text.", "A 10-week plan works.", "End."]   # 못 찾으면 앞 문장
    b = art(summary="10주 프로그램", body="Intro text. A 10-week plan works. End.")
    assert hitl.evidence(b) == ["A 10-week plan works."]

def test_건강_키워드는_영어_원문에서도_근거_문장을_찾는다():
    a = art(summary="콜레스테롤을 낮추는 식단", body="Eat oats. LDL Cholesterol drops. End.")
    assert hitl.evidence(a) == ["LDL Cholesterol drops."]


# ── 담당자 응답 ──
def test_응답별로_필요한_값이_없으면_막는다():
    with pytest.raises(ValidationError):
        hitl.Decision(action="approve_without")
    with pytest.raises(ValidationError):
        hitl.Decision(action="edit")
    with pytest.raises(ValidationError):
        hitl.Decision(action="hold", reason="  ")

def test_응답대로_보낼_기사를_만든다():
    arts = [art("a"), art("b"), art("c")]
    assert len(hitl.apply_decision(arts, hitl.Decision(action="approve"))) == 3
    assert [a["url"] for a in hitl.apply_decision(arts, hitl.Decision(action="approve_without", exclude=["b"]))] == ["a", "c"]
    edited = hitl.apply_decision(arts, hitl.Decision(action="edit", edits={"a": {"headline": "새 제목", "summary": "새 요약"}}))
    assert edited[0]["headline"] == "새 제목" and edited[1]["headline"] == "제목"
    assert arts[0]["headline"] == "제목"                # 원본은 그대로
    assert hitl.apply_decision(arts, hitl.Decision(action="hold", reason="확인 필요")) == []


# ── 디스코드 답글 문법 · 반응 · 정오 규칙 ──
from datetime import datetime
from zoneinfo import ZoneInfo

FLAGGED = [art("a", headline="콜레스테롤 식단", summary="원래 요약 A"), art("b", headline="혈압 관리", summary="원래 요약 B")]

def test_답글_승인_빼고_보류를_읽는다():
    assert hitl.parse_reply("승인", FLAGGED).action == "approve"
    assert hitl.parse_reply("빼고", FLAGGED).exclude == ["a", "b"]           # 번호가 없으면 걸린 기사 전부
    assert hitl.parse_reply("빼고 2", FLAGGED).exclude == ["b"]
    d = hitl.parse_reply("보류: 수치 재확인 필요", FLAGGED)
    assert (d.action, d.reason) == ("hold", "수치 재확인 필요")

def test_답글로_제목과_요약을_고친다():
    d = hitl.parse_reply("수정 1: 새 요약\n제목 2: 새 제목", FLAGGED)
    assert d.action == "edit"
    assert d.edits["a"].summary == "새 요약" and d.edits["a"].headline == "콜레스테롤 식단"   # 안 고친 칸은 원래 값
    assert d.edits["b"].headline == "새 제목" and d.edits["b"].summary == "원래 요약 B"

def test_알아들을_수_없는_답글은_None():
    for text in ["좋아요", "빼고 3", "수정 9: x", "승인해 주세요 그런데 수정 1: x", ""]:
        assert hitl.parse_reply(text, FLAGGED) is None, text

def test_응답을_답글로_바꾸면_다시_같은_응답으로_읽힌다():   # Streamlit이 스레드에 대신 다는 글
    for d in [hitl.Decision(action="approve"),
              hitl.Decision(action="approve_without", exclude=["b"]),
              hitl.Decision(action="hold", reason="수치 확인"),
              hitl.Decision(action="edit", edits={"a": {"headline": "새 제목", "summary": "새 요약"}})]:
        assert hitl.parse_reply(hitl.reply_text(d, FLAGGED), FLAGGED) == d

def test_반응은_하나만_골랐을_때만_응답이_된다():
    assert hitl.from_reactions(["✅"], FLAGGED).action == "approve"
    assert hitl.from_reactions(["➖"], FLAGGED).exclude == ["a", "b"]
    assert hitl.from_reactions(["⏸️"], FLAGGED).action == "hold"
    assert hitl.from_reactions([], FLAGGED) is None
    assert hitl.from_reactions(["✅", "⏸️"], FLAGGED) is None              # 모호하면 승인으로 치지 않는다

def test_정오가_지나면_걸린_기사만_빼고_보낸다():
    kst = ZoneInfo("Asia/Seoul")
    assert not hitl.past_deadline("2026-11-10", datetime(2026, 11, 10, 11, 59, tzinfo=kst))
    assert hitl.past_deadline("2026-11-10", datetime(2026, 11, 10, 12, 0, tzinfo=kst))
    assert hitl.past_deadline("2026-11-10", datetime(2026, 11, 11, 8, 0, tzinfo=kst))
    d = hitl.timeout_decision(FLAGGED)
    assert (d.action, d.exclude) == ("approve_without", ["a", "b"]) and d.reason


# ── 기사별 답글: '번호 - 승인 / 보류 / 교체' (2026-11-11 사용자 요청) ──
def test_기사별로_승인_보류_교체를_읽는다():
    d = hitl.parse_reply("1 - 승인\n2 - 교체", FLAGGED)
    assert (d.action, d.exclude, d.replace) == ("per_article", [], ["b"])
    d = hitl.parse_reply("1,2 - 보류", FLAGGED)
    assert (d.action, d.exclude, d.replace) == ("per_article", ["a", "b"], [])
    assert hitl.parse_reply("1-승인\n2 – 보류", FLAGGED).exclude == ["b"]          # 띄어쓰기·대시 모양이 달라도

def test_걸린_기사_번호가_빠지면_응답으로_치지_않고_빠진_번호를_묻는다():
    d, problem = hitl.parse_reply_detail("1 - 승인", FLAGGED)
    assert d is None and "2번" in problem

def test_같은_번호에_다른_답이면_되묻는다():
    d, problem = hitl.parse_reply_detail("1 - 승인\n1 - 보류\n2 - 승인", FLAGGED)
    assert d is None and "1번" in problem

def test_없는_번호는_되묻는다():
    d, problem = hitl.parse_reply_detail("1 - 승인\n2 - 승인\n3 - 보류", FLAGGED)
    assert d is None and "3번" in problem

def test_기사별_응답도_답글로_바꾸면_같은_응답으로_읽힌다():
    d = hitl.Decision(action="per_article", exclude=["a"], replace=["b"])
    assert hitl.parse_reply(hitl.reply_text(d, FLAGGED), FLAGGED) == d

def test_기사별_응답은_보류와_교체를_빼고_나머지를_보낸다():
    arts = [art("a"), art("b"), art("c")]
    sent = hitl.apply_decision(arts, hitl.Decision(action="per_article", exclude=["a"], replace=["b"]))
    assert [a["url"] for a in sent] == ["c"]                                       # 교체 자리는 graph가 채운다
    with pytest.raises(ValidationError):
        hitl.Decision(action="per_article", exclude=["a"], replace=["a"])           # 한 기사에 두 가지 답

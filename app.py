# 발송 승인 화면 — streamlit run app.py
# 두 가지 보기 (docs/hitl-plan.md):
#   실제 승인 대기 — 07:30 실행이 approve에서 멈춘 호. 응답은 디스코드 스레드에 답글로 남기고, 확인 실행(30분마다)이 이어 간다
#   샘플(기준 시험) — store/hitl/samples.jsonl로 기준을 바꿔 보며 시험. 응답은 decisions.jsonl에만 적는다
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

import discord_review
import graph
import hitl
import hitl_store

load_dotenv(Path(__file__).resolve().parent / ".env")

HITL_DIR = Path(__file__).resolve().parent / "store" / "hitl"
SAMPLES, DECISIONS = HITL_DIR / "samples.jsonl", HITL_DIR / "decisions.jsonl"
ACTIONS = {"approve": "✅ 승인 — 그대로 발송", "approve_without": "➖ 걸린 기사 빼고 발송",
           "edit": "✏️ 문구 수정 후 발송", "hold": "⏸️ 발송 보류", "per_article": "🧩 기사별로 정하기"}
PER = {"승인": None, "보류": "exclude", "교체": "replace"}  # 기사별 응답 — 교체는 예비 기사로 바꿔 넣기
DEFAULT_RULE = "①+②"                           # 확정한 두 기준 (docs/hitl-plan.md)


def md(text):                                   # 기사 글을 마크다운으로 찍을 때 — '20~25마일'의 물결표 둘이 취소선으로, '$45'가 수식으로 바뀐다
    return (text or "").replace("~", r"\~").replace("$", r"\$")


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_issues():                              # 날짜 → 그날 기사 (호 단위 승인)
    issues = defaultdict(list)
    for a in read_jsonl(SAMPLES):
        if a.get("verify_passed"):              # 실제로 발송될 것은 검수를 통과한 기사뿐이다
            issues[a["date"]].append(a)
    return dict(sorted(issues.items(), reverse=True))


def latest_decisions():                         # 날짜마다 마지막 응답
    return {d["date"]: d for d in read_jsonl(DECISIONS)}


def save_decision(date, rule, decision, sent):
    HITL_DIR.mkdir(parents=True, exist_ok=True)
    row = {"date": date, "rule": rule, **decision.model_dump(), "sent_count": len(sent),
           "decided_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")}
    with DECISIONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def status(review, decision):
    if decision:
        return f"처리됨 · {ACTIONS[decision['action']].split(' — ')[0]}"
    return f"승인 대기 · {len(review['flagged'])}건 걸림" if review["flagged"] else "자동 발송 대상"


def sidebar():
    view = st.sidebar.radio("보기", ["실제 승인 대기", "샘플 (기준 시험)"])
    if view == "실제 승인 대기":
        st.sidebar.caption(f"기준은 실행과 같은 `{graph.STOP_RULE}`로 고정이에요.")
        return view, graph.STOP_RULE
    st.sidebar.header("멈춤 기준")
    names = list(hitl.CRITERIA)
    rule = st.sidebar.selectbox("어떤 기준으로 멈출까요?", names, index=names.index(DEFAULT_RULE))
    st.sidebar.caption("① 요약의 숫자가 원문에 없으면 · ② 요약에 건강·의학 키워드가 있으면 멈춰요. "
                       "기준을 바꾸면 대기 목록이 바로 달라져요.")
    return view, rule


def issue_list(issues, reviews, decisions):
    st.subheader("승인 대기 목록")
    rows = [{"발행일": d, "기사": r["total"], "걸린 기사": len(r["flagged"]), "상태": status(r, decisions.get(d))}
            for d, r in reviews.items()]
    st.dataframe(rows, hide_index=True, width="stretch")
    waiting = [d for d, r in reviews.items() if r["flagged"] and d not in decisions]
    options = waiting + [d for d in issues if d not in waiting]
    label = lambda d: f"{d} · {status(reviews[d], decisions.get(d))}"
    return st.selectbox("확인할 호", options, format_func=label) if options else None


def flagged_card(a):
    with st.container(border=True):
        st.markdown(f"#### {md(a['headline'])}")
        st.caption(f"{md(a['source'])} · [{md(a['title'])}]({a['url']})")
        for r in a["reasons"]:
            st.error(f"멈춘 이유 — {r}", icon="⚠️")
        st.markdown(f"**AI 요약** {md(a['summary'])}")
        st.markdown(f"**40대에게** {md(a['why'])}")
        st.markdown("**원문 근거** — 요약의 숫자·키워드가 나오는 문장")
        for s in a["evidence"]:
            st.markdown(f"> {md(s[:300])}")
        st.caption("AI 원문 대조 검수: 통과 (이 기사는 검수를 통과했지만 기준에 걸려 사람에게 왔어요)")


def response_form(date, rule, articles, review, submit_fn=None):
    st.subheader("응답")
    # 기본 선택을 두지 않는다 — 기준을 바꾸는 등 화면이 다시 그려질 때 선택이 '승인'으로 돌아가 실수로 승인한 적이 있다
    action = st.radio("어떻게 할까요?", list(ACTIONS), format_func=ACTIONS.get, key=f"act-{date}", index=None)
    flagged = review["flagged"]
    exclude, edits, reason, replace = [], {}, "", []
    if action == "approve_without":
        exclude = st.multiselect("뺄 기사", [a["url"] for a in flagged], default=[a["url"] for a in flagged],
                                 format_func=lambda u: next(a["headline"] for a in flagged if a["url"] == u))
    if action == "per_article":
        for i, a in enumerate(flagged, 1):
            pick = st.radio(f"{i}. {a['headline']}", list(PER), horizontal=True, key=f"p-{date}-{a['url']}")
            if PER[pick] == "exclude":
                exclude.append(a["url"])
            elif PER[pick] == "replace":
                replace.append(a["url"])
        st.caption("교체는 예비 기사를 새로 요약·검수해 그 자리에 넣어요. 그 기사도 기준에 걸리면 빼고 보내요.")
    if action == "edit":
        for a in flagged:
            h = st.text_input("제목", a["headline"], key=f"h-{a['url']}")
            s = st.text_area("요약", a["summary"], key=f"s-{a['url']}")
            if (h, s) != (a["headline"], a["summary"]):
                edits[a["url"]] = {"headline": h, "summary": s}
    reason = st.text_area("사유" + (" (필수)" if action == "hold" else " (선택)"), key=f"r-{date}",
                          placeholder="예: 콜레스테롤 수치를 원문에서 다시 확인해야 함")
    if st.button("응답 보내기", type="primary", key=f"go-{date}", disabled=action is None):
        (submit_fn or submit)(date, rule, articles, action, exclude, edits, reason, replace)


def submit(date, rule, articles, action, exclude, edits, reason, replace=()):
    try:
        d = hitl.Decision(action=action, exclude=exclude, edits=edits, reason=reason, replace=list(replace))
    except ValidationError as e:
        st.warning(e.errors()[0]["msg"].removeprefix("Value error, "))
        return
    sent = hitl.apply_decision(articles, d)
    save_decision(date, rule, d, sent)
    # 목록 상태가 바로 바뀌도록 다시 그린다 — 안내는 다시 그린 화면 위쪽에 띄운다
    st.session_state["flash"] = (f"{date} 호 기록했어요 · {'발송 보류' if d.action == 'hold' else f'{len(sent)}건 발송 예정'}"
                                 " (테스트라 실제 발송은 없어요)")
    st.rerun()


def issue_detail(date, rule, articles, review, decision, submit_fn=None):
    c1, c2, c3 = st.columns(3)
    c1.metric("전체 기사", review["total"])
    c2.metric("사람 확인 필요", len(review["flagged"]))
    c3.metric("자동 통과", len(review["auto"]))
    st.warning(f"**통과시키면:** {review['on_approve']}", icon="📨")
    if decision:
        st.info(f"이미 처리한 호예요 — {ACTIONS[decision['action']]} · {decision['decided_at']}"
                + (f" · 사유: {decision['reason']}" if decision["reason"] else ""))
    for a in review["flagged"]:
        flagged_card(a)
    with st.expander(f"자동 통과 기사 {len(review['auto'])}건"):
        for a in review["auto"]:
            st.markdown(f"- **{md(a['headline'])}** · {md(a['source'])}")
    if review["flagged"]:
        response_form(date, rule, articles, review, submit_fn)
    else:
        st.success("이 기준에서는 걸린 기사가 없어요. 사람을 거치지 않고 그대로 발송돼요.")


# ── 실제 승인 대기 ───────────────────────────────────────────
def load_waiting():                             # 날짜 → (기록, 승인 화면 내용). 암호화 파일은 읽기만 한다
    rows = hitl_store.waiting()
    if not rows:
        return {}
    with hitl_store.saver(os.environ, seal=False) as s:
        return {r["date"]: (r, review) for r in sorted(rows, key=lambda r: r["date"], reverse=True)
                if (review := graph.pending(s, r["date"]))}


def reply_to_discord(row, review):              # Streamlit 응답 → 디스코드 스레드 답글 (응답 창구는 스레드 하나)
    def submit_fn(date, rule, articles, action, exclude, edits, reason, replace=()):
        try:
            d = hitl.Decision(action=action, exclude=exclude, edits=edits, reason=reason, replace=list(replace))
        except ValidationError as e:
            st.warning(e.errors()[0]["msg"].removeprefix("Value error, "))
            return
        cfg = discord_review.config(os.environ)
        if not (cfg and row.get("message_id")):
            st.error("디스코드 봇 설정(.env의 DISCORD_BOT_TOKEN·DISCORD_REVIEW_CHANNEL_ID·DISCORD_REVIEWER_ID)이 없어 답글을 달 수 없어요.")
            return
        text = hitl.reply_text(d, review["flagged"])
        try:
            discord_review.reply(cfg, row["message_id"], text)
        except discord_review.DiscordError as e:
            st.error(f"디스코드가 거절했어요 · {e}")
            return
        st.session_state["flash"] = (f"{date} 호 · 디스코드 스레드에 답글 \"{md(text.splitlines()[0])}\"을 남겼어요. "
                                     "다음 확인 실행(30분마다) 때 반영돼요.")
        st.rerun()
    return submit_fn


def real_view():
    st.info("07:30 실행이 걸린 기사 때문에 멈춘 호예요. 여기서 응답하면 디스코드 #검토 스레드에 같은 답글을 남겨요. "
            "최신 대기 건을 보려면 먼저 `git pull` 하세요.")
    try:
        waiting = load_waiting()
    except hitl_store.StateKeyError as e:
        st.error(str(e))
        return
    if not waiting:
        st.success("승인을 기다리는 호가 없어요.")
        return
    st.subheader("승인 대기 목록")
    st.dataframe([{"발행일": d, "걸린 기사": len(rv["flagged"]), "전체": rv["total"],
                   "모드": "dry-run" if r.get("dry_run") else "실제 발송"} for d, (r, rv) in waiting.items()],
                 hide_index=True, width="stretch")
    date = st.selectbox("확인할 호", list(waiting))
    row, review = waiting[date]
    st.divider()
    st.subheader(f"{date} 호")
    articles = review["flagged"] + review["auto"]
    issue_detail(date, graph.STOP_RULE, articles, review, None, reply_to_discord(row, review))


def main():
    st.set_page_config(page_title="발송 승인", page_icon="📰", layout="wide")
    st.title("📰 40대 아침 브리핑 · 발송 승인")
    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    view, rule = sidebar()
    if view == "실제 승인 대기":
        real_view()
        return
    st.info("샘플 시험 화면이에요. Discord로 보내지 않고, 응답은 store/hitl/decisions.jsonl에만 기록해요.")
    issues = load_issues()
    if not issues:
        st.warning("샘플이 없어요. 먼저 `.venv/bin/python scripts/hitl_samples.py`를 실행하세요.")
        return
    stop = hitl.CRITERIA[rule]
    reviews = {d: hitl.build_review(arts, stop) for d, arts in issues.items()}
    decisions = latest_decisions()
    date = issue_list(issues, reviews, decisions)
    if date:
        st.divider()
        st.subheader(f"{date} 호")
        issue_detail(date, rule, issues[date], reviews[date], decisions.get(date))


main()

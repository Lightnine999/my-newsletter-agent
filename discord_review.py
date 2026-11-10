# discord_review — 디스코드 봇의 REST 호출만 모았다 (docs/hitl-plan.md "구현 설계")
# 봇을 켜 둘 필요는 없다: Actions가 돌 때만 토큰으로 카드를 올리고, 반응·답글을 읽고, 답글을 단다
# 판단은 하지 않는다 — 답글 해석은 hitl.parse_reply, 이어 가기는 graph.resume
import time
from dataclasses import dataclass
from urllib.parse import quote

import requests

import hitl

API = "https://discord.com/api/v10"
GRAMMAR = ("반응: ✅ 승인 · ➖ 걸린 기사 빼고 발송 · ⏸️ 보류\n"
           "기사별 답글 (걸린 번호를 모두, 줄마다): `1 - 승인` · `2 - 보류` · `3,4 - 교체` (교체 = 예비 기사로 바꿔 넣기)\n"
           "호 전체 답글: `승인` · `빼고 1,2` · `보류: 사유` · `수정 1: 새 요약` · `제목 1: 새 제목`")


class DiscordError(Exception):
    """디스코드가 요청을 거절했을 때 — 메시지에 토큰은 넣지 않는다."""


@dataclass(frozen=True)
class Config:
    token: str
    channel_id: str                             # 비공개 #검토 채널
    reviewer_id: str                            # 이 사람의 반응·답글만 응답으로 인정한다


@dataclass(frozen=True)
class Response:
    decision: hitl.Decision | None
    seen: str                                   # 마지막으로 읽은 담당자 답글 번호 — 같은 답글로 두 번 되묻지 않게
    problem: str | None = None                  # 담당자에게 되물을 말


def config(env):                                # 셋 중 하나라도 없으면 None (디스코드 검토 꺼짐)
    vals = [(env.get(k) or "").strip() for k in ("DISCORD_BOT_TOKEN", "DISCORD_REVIEW_CHANNEL_ID", "DISCORD_REVIEWER_ID")]
    return Config(*vals) if all(vals) else None


def _call(cfg, method, path, http=None, sleep=time.sleep, **kw):
    http = http or requests
    headers = {"Authorization": f"Bot {cfg.token}", "User-Agent": "DiscordBot (my-newsletter-agent, 1.0)"}
    for _ in range(3):
        r = http.request(method, API + path, headers=headers, timeout=20, **kw)
        if r.status_code == 429:                # 속도 제한 — 알려 준 만큼 쉬고 다시
            sleep(float((r.json() or {}).get("retry_after", 1)))
            continue
        if r.status_code >= 400:
            raise DiscordError(f"{method} {path} → {r.status_code}")
        return r.json() if r.content else None
    raise DiscordError(f"{method} {path} → 429 (속도 제한이 풀리지 않음)")


def _clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def card(review, cfg, dry_run):                 # 교안 4장: 원문 · 판단과 근거 · 멈춘 이유 · 통과시키면 일어나는 일
    flagged = review["flagged"][:10]            # 디스코드 카드(embed)는 메시지당 10장까지
    head = (f"<@{cfg.reviewer_id}> 📝 **{review['date']} 호 발송 승인 요청**{' · dry-run (구독 채널로는 안 나가요)' if dry_run else ''}\n"
            f"걸린 기사 {len(review['flagged'])}건 / 전체 {review['total']}건 · AI 원문 대조 검수는 모두 통과했어요\n"
            f"**승인하면:** {review['on_approve']}\n"
            f"**정오까지 응답이 없으면:** 걸린 기사만 빼고 발송돼요\n\n{GRAMMAR}")
    per = min(1500, 5000 // max(len(flagged), 1))   # 메시지 합계 6000자 한도 안에서 나눠 쓴다
    embeds = []
    for i, a in enumerate(flagged, 1):
        desc = ("⚠️ " + "\n⚠️ ".join(a["reasons"]) + f"\n\n**AI 요약** {a['summary']}\n\n**원문 근거**\n"
                + "\n".join(f"> {_clip(s, 300)}" for s in a["evidence"]))
        embeds.append({"title": _clip(f"{i}. {a['headline']}", 256), "url": a["url"], "description": _clip(desc, per),
                       "color": 0xC0392B, "footer": {"text": _clip(f"{a['source']} · {a['title']}", 200)}})
    return {"content": _clip(head, 2000), "embeds": embeds, "allowed_mentions": {"users": [cfg.reviewer_id]}}


def react(cfg, message_id, emoji, http=None, sleep=time.sleep):
    _call(cfg, "PUT", f"/channels/{cfg.channel_id}/messages/{message_id}/reactions/{quote(emoji, safe='')}/@me",
          http, sleep)


def reply(cfg, thread_id, text, http=None):     # 스레드에 글 — 아무도 멘션하지 않는다
    return _call(cfg, "POST", f"/channels/{thread_id}/messages", http,
                 json={"content": _clip(text, 2000), "allowed_mentions": {"parse": []}})


def post_review(cfg, review, dry_run, http=None, sleep=time.sleep):   # 카드 → 반응 세 개 → 스레드. 메시지 번호를 돌려준다
    mid = _call(cfg, "POST", f"/channels/{cfg.channel_id}/messages", http, json=card(review, cfg, dry_run))["id"]
    for emoji in hitl.REACTIONS:
        react(cfg, mid, emoji, http, sleep)
    _call(cfg, "POST", f"/channels/{cfg.channel_id}/messages/{mid}/threads", http,
          json={"name": f"{review['date']} 호 승인", "auto_archive_duration": 1440})
    return mid                                  # 메시지에서 연 스레드는 번호가 메시지와 같다


def _reviewer_reactions(cfg, mid, http):
    chosen = []
    for emoji in hitl.REACTIONS:
        users = _call(cfg, "GET", f"/channels/{cfg.channel_id}/messages/{mid}/reactions/{quote(emoji, safe='')}",
                      http, params={"limit": 100}) or []
        if any(u["id"] == cfg.reviewer_id for u in users):
            chosen.append(emoji)
    return chosen


def read_response(cfg, mid, flagged, seen="0", http=None):
    # 1) 담당자의 가장 최근 답글 하나가 응답이다. 알아들을 수 없으면 승인으로 치지 않고 (처음 한 번만) 되묻는다
    try:
        msgs = _call(cfg, "GET", f"/channels/{mid}/messages", http, params={"limit": 50}) or []
    except DiscordError:                        # 스레드를 못 열었으면 반응만 본다
        msgs = []
    mine = sorted((m for m in msgs if m["author"]["id"] == cfg.reviewer_id), key=lambda m: int(m["id"]))
    if mine:
        last, new_seen = mine[-1], str(max(int(seen), int(mine[-1]["id"])))
        d, why = hitl.parse_reply_detail(last["content"], flagged)
        if d:
            return Response(d, new_seen)
        ask = None if int(last["id"]) <= int(seen) else f"{why or '이해하지 못했어요.'} 이렇게 답해 주세요.\n{GRAMMAR}"
        return Response(None, new_seen, ask)
    # 2) 답글이 없으면 카드에 담당자가 누른 반응
    chosen = _reviewer_reactions(cfg, mid, http)
    if len(chosen) > 1:
        return Response(None, seen, f"반응이 {' '.join(chosen)} 여러 개예요. 하나만 남겨 주세요.")
    return Response(hitl.from_reactions(chosen, flagged), seen)


def close_card(cfg, mid, text, http=None):      # 처리 결과를 스레드에 남기고 카드 첫 줄에도 표시
    reply(cfg, mid, text, http)
    _call(cfg, "PATCH", f"/channels/{cfg.channel_id}/messages/{mid}", http,
          json={"content": _clip(f"✅ **처리됨** · {text}", 2000), "allowed_mentions": {"parse": []}})

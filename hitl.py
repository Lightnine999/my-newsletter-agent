# HITL — 발송 전 사람 승인에 쓰는 규칙과 데이터 (docs/hitl-plan.md)
# 비교 스크립트(scripts/hitl_compare.py)와 승인 화면(app.py)이 같은 기준을 쓴다. 나중에 graph의 approve 노드도 이것을 부른다
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── 멈춤 기준 ────────────────────────────────────────────────
# '부상'·'치료'는 뺐다 (2026-11-10 사용자 결정): 샘플 12건에서 부상으로 걸린 4건이 모두 헛멈춤이었고,
# 부상 예방·치료 기사는 통과시키기로 했다. 질환 치료는 혈압·질환·처방 같은 다른 키워드가 계속 잡는다
HEALTH = ["콜레스테롤", "혈압", "혈당", "질환", "효능", "복용", "의사", "피부과", "통증", "약물", "보충제", "처방"]
# 원문은 대부분 영어라 근거 문장을 찾을 때는 영어 어간으로도 찾는다
HEALTH_EN = {"콜레스테롤": ["cholesterol"], "혈압": ["blood pressure"], "혈당": ["blood sugar", "glucose"],
             "질환": ["disease", "condition"], "효능": ["benefit", "effect"],
             "복용": ["dose", "dosage"], "의사": ["doctor", "physician"], "피부과": ["dermatolog"], "통증": ["pain"],
             "약물": ["drug", "medication"], "보충제": ["supplement"], "처방": ["prescri"]}
NUM = re.compile(r"\d+(?:[.,]\d+)*")
# 영어 원문은 숫자를 글자로 쓰기도 한다 — 'Three ways'가 요약에서 '3종'이 된다
WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
DECADE = re.compile(r"\b\d{2}(\d0)s\b")         # '1930s' → 요약에서는 '30년대'

def numbers(text, korean=False):                # 쉼표를 지우고, '3만'은 30000으로 편다. '40대'는 독자 표현이라 뺀다
    text = text or ""
    out = set()
    if not korean:
        out |= {WORDS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in WORDS}
        out |= set(DECADE.findall(text))
    for m in NUM.finditer(text):
        tail = text[m.end():m.end() + 1]
        if korean and tail == "대":
            continue
        n = m.group().replace(",", "")
        if korean and tail == "만":
            n = str(int(float(n) * 10000))
        out.add(n)
    return out

def summary_text(a):
    return f"{a['headline']} {a['summary']}"

def missing_numbers(a):                         # 기준 ① 원문에 없는 수치
    return sorted(numbers(summary_text(a), korean=True) - numbers(a.get("body")))

def health_words(a, words=HEALTH):              # 기준 ② 건강·의학 조언
    return [w for w in words if w in summary_text(a)]

CRITERIA = {                                    # 이름 → 멈추면 True
    "기준 없음":              lambda a: False,
    "전부 멈춤":              lambda a: True,
    "숫자가 있으면":          lambda a: bool(numbers(summary_text(a), korean=True)),
    "① 원문에 없는 수치":     lambda a: bool(missing_numbers(a)),
    "② 건강·의학 조언":       lambda a: bool(health_words(a)),
    "①+②":                  lambda a: bool(missing_numbers(a) or health_words(a)),
}

def reasons(a, words=HEALTH):                   # 승인 화면의 '멈춘 이유' — 기준마다 한 줄
    nums, hw = missing_numbers(a), health_words(a, words)
    return ([f"원문에 없는 수치: {', '.join(nums)}"] if nums else []) + \
           ([f"건강·의학 키워드: {', '.join(hw)}"] if hw else [])

# ── 승인 화면에 보여 줄 것 (교안 4장: 원문 · 판정과 근거 · 멈춘 이유 · 통과시키면 일어나는 일) ──
def evidence(a, limit=3):                       # 요약의 숫자·건강 키워드가 원문에서 나오는 문장 — 담당자가 원문을 따로 열지 않게
    # 원문에 없는 수치는 원문에서 찾을 수 없으니, 요약에 나온 숫자 전체로 원문이 실제로 뭐라고 했는지 보여 준다
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", a.get("body") or "") if s.strip()]
    pats = [re.compile(rf"(?<![\d,]){re.escape(n)}(?![\d,])") for n in numbers(summary_text(a), korean=True)]
    words = [x for w in health_words(a) for x in [w, *HEALTH_EN.get(w, [])]]
    hits = [s for s in sentences
            if any(p.search(s.replace(",", "")) for p in pats) or any(w in s.lower() for w in words)]
    return hits[:limit] or sentences[:limit]

def build_review(articles, stop, words=HEALTH):  # 호 하나 → 승인 대기 건 (interrupt에 담을 내용과 같은 모양)
    flagged = [a for a in articles if stop(a)]
    return {
        "total": len(articles),
        "flagged": [{**a, "reasons": reasons(a, words) or ["선택한 기준에 걸림"], "evidence": evidence(a)}
                    for a in flagged],
        "auto": [a for a in articles if not stop(a)],
        "on_approve": f"{len(articles)}건이 Discord 구독 채널로 발송됩니다",
    }

# ── 담당자 응답 (교안 4장: 승인 / 수정 후 승인 / 반려 / 다시 판정 → 뉴스레터에 맞게 네 가지) ──
class Edit(BaseModel):
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)

class Decision(BaseModel):                      # 나중에 Command(resume=Decision)로 그래프에 넣는다
    action: Literal["approve", "approve_without", "edit", "hold", "per_article"]
    exclude: list[str] = []                     # 빼고 보낼 기사 url (per_article에서는 '보류'한 기사)
    replace: list[str] = []                     # per_article: 예비 기사로 바꿔 넣을 기사 url (graph의 approve가 채운다)
    edits: dict[str, Edit] = {}                 # url → 고친 제목·요약
    reason: str = ""

    @model_validator(mode="after")
    def check(self):
        if self.action == "approve_without" and not self.exclude:
            raise ValueError("뺄 기사를 하나 이상 고르세요")
        if self.action == "edit" and not self.edits:
            raise ValueError("고친 기사가 없어요")
        if self.action == "hold" and not self.reason.strip():
            raise ValueError("보류 사유를 적어 주세요 — 나중에 기준을 고칠 재료가 돼요")
        if set(self.exclude) & set(self.replace):
            raise ValueError("한 기사에 보류와 교체를 함께 고를 수 없어요")
        return self

def apply_decision(articles, d: Decision):      # 응답대로 실제로 보낼 기사 목록을 만든다. 보류면 빈 목록
    if d.action == "hold":
        return []
    kept = [a for a in articles if a["url"] not in set(d.exclude) | set(d.replace)]   # 교체 자리는 graph가 채운다
    return [{**a, **d.edits[a["url"]].model_dump()} if a["url"] in d.edits else a for a in kept]

# ── 디스코드 응답 (docs/hitl-plan.md "구현 설계") ───────────────────
# 카드 반응 하나 또는 스레드 답글 하나가 응답이 된다. Streamlit도 같은 답글을 대신 달아서 응답 창구를 하나로 모은다
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
DEADLINE = dtime(12, 0)                          # 이 시각이 지나도 응답이 없으면 timeout_decision
ACTION_LABEL = {"approve": "승인", "approve_without": "걸린 기사 빼고 발송", "edit": "문구 수정 후 발송", "hold": "보류",
                "per_article": "기사별 처리"}
REACTIONS = {"✅": "approve", "➖": "approve_without", "⏸️": "hold"}
HOLD_DEFAULT = "디스코드에서 보류 (사유 없음)"
EDIT_LINE = re.compile(r"^(수정|제목)\s*(\d+)\s*[:：]\s*(.+)$")

def _all_urls(flagged):
    return [a["url"] for a in flagged]

def _pick(nums, flagged):                       # '1,2' → url들. 범위를 벗어나면 None
    idx = [int(n) for n in re.findall(r"\d+", nums)]
    if any(not 1 <= i <= len(flagged) for i in idx):
        return None
    return [flagged[i - 1]["url"] for i in idx] or _all_urls(flagged)

def _parse_edits(lines, flagged):
    edits = {}
    for line in lines:
        m = EDIT_LINE.match(line)
        if not m or not 1 <= int(m.group(2)) <= len(flagged):
            return None
        a = flagged[int(m.group(2)) - 1]
        cur = edits.get(a["url"], {"headline": a["headline"], "summary": a["summary"]})
        edits[a["url"]] = {**cur, ("summary" if m.group(1) == "수정" else "headline"): m.group(3).strip()}
    return edits

# 기사별 답글 (2026-11-11 사용자 요청): '1 - 승인' · '2 - 보류' · '3,4 - 교체'를 줄마다. 걸린 기사 번호를 빠짐없이 적어야 한다
PER_LINE = re.compile(r"^([\d\s,]+?)\s*[-–—]\s*(승인|보류|교체)$")
PER_ACTION = {"승인": "approve", "보류": "exclude", "교체": "replace"}

def _parse_per_article(lines, flagged):         # → (Decision|None, 되물을 말|None)
    picked = {}
    for line in lines:
        m = PER_LINE.match(line)
        if not m:
            return None, f"'{line}'를 이해하지 못했어요. 줄마다 `번호 - 승인`·`번호 - 보류`·`번호 - 교체`로 써 주세요."
        for n in (int(x) for x in re.findall(r"\d+", m.group(1))):
            if not 1 <= n <= len(flagged):
                return None, f"{n}번 기사는 없어요. 걸린 기사는 1~{len(flagged)}번이에요."
            if picked.get(n, m.group(2)) != m.group(2):
                return None, f"{n}번에 답이 두 개예요({picked[n]}·{m.group(2)}). 하나만 남겨 주세요."
            picked[n] = m.group(2)
    missing = [str(n) for n in range(1, len(flagged) + 1) if n not in picked]
    if missing:
        return None, f"{', '.join(missing)}번은 어떻게 할까요? 걸린 기사 번호를 모두 적어 주세요."
    urls = lambda what: [flagged[n - 1]["url"] for n, w in sorted(picked.items()) if PER_ACTION[w] == what]
    return Decision(action="per_article", exclude=urls("exclude"), replace=urls("replace")), None

def parse_reply_detail(text, flagged):          # 스레드 답글 → (Decision|None, 되물을 말|None)
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    if any(PER_LINE.match(l) for l in lines):
        return _parse_per_article(lines, flagged)
    return parse_reply(text, flagged), None

def parse_reply(text, flagged):                 # 스레드 답글 → Decision. 알아들을 수 없으면 None (승인으로 치지 않는다)
    text = (text or "").strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if any(PER_LINE.match(l) for l in lines):
        return _parse_per_article(lines, flagged)[0]
    if text == "승인":
        return Decision(action="approve")
    if m := re.fullmatch(r"빼고([\d,\s]*)", text):
        urls = _pick(m.group(1), flagged)
        return Decision(action="approve_without", exclude=urls) if urls else None
    if m := re.fullmatch(r"보류\s*[:：]?\s*(.*)", text, re.S):
        return Decision(action="hold", reason=m.group(1).strip() or HOLD_DEFAULT)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    edits = _parse_edits(lines, flagged) if lines else None
    return Decision(action="edit", edits=edits) if edits else None

def reply_text(d: Decision, flagged):           # Decision → 스레드 답글 (parse_reply의 반대)
    num = {a["url"]: i for i, a in enumerate(flagged, 1)}
    flat = lambda s: " ".join(s.split())
    if d.action == "approve":
        return "승인"
    if d.action == "approve_without":
        return "빼고 " + ",".join(str(num[u]) for u in d.exclude)
    if d.action == "hold":
        return f"보류: {flat(d.reason)}"
    if d.action == "per_article":
        word = lambda u: "보류" if u in d.exclude else ("교체" if u in d.replace else "승인")
        groups = {}
        for a in flagged:
            groups.setdefault(word(a["url"]), []).append(str(num[a["url"]]))
        return "\n".join(f"{','.join(ns)} - {w}" for w, ns in groups.items())
    return "\n".join(line for u, e in d.edits.items()
                     for line in (f"제목 {num[u]}: {flat(e.headline)}", f"수정 {num[u]}: {flat(e.summary)}"))

def from_reactions(chosen, flagged):            # 담당자가 누른 반응 → Decision. 없거나 둘 이상이면 None
    picked = [REACTIONS[e] for e in chosen if e in REACTIONS]
    if len(picked) != 1:
        return None
    return {"approve": lambda: Decision(action="approve"),
            "approve_without": lambda: Decision(action="approve_without", exclude=_all_urls(flagged)),
            "hold": lambda: Decision(action="hold", reason=HOLD_DEFAULT)}[picked[0]]()

def past_deadline(date, now):                   # 발행일 정오(KST)가 지났나
    return now.astimezone(KST) >= datetime.combine(datetime.fromisoformat(date).date(), DEADLINE, KST)

def timeout_decision(flagged):                  # 정오까지 응답이 없으면: 걸린 기사만 빼고 보낸다
    return Decision(action="approve_without", exclude=_all_urls(flagged),
                    reason="정오까지 응답이 없어 걸린 기사만 빼고 자동 발송")

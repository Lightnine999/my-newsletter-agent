import operator
import os
from functools import partial
from pathlib import Path
from typing import Annotated, Literal, TypedDict

import yaml
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field, ValidationError, model_validator

class Brief(TypedDict):
    hours:     int                              # 수집 time window(시간)
    collected: list                             # ① 수집한 기사
    picked:    list                             # ② 파트 표시를 붙여 고른 10건
    spares:    list                             # ② 고르지 않은 다음 순위 — 빠진 자리를 verify가 채운다
    drafted:   Annotated[list, operator.add]    # ③ 세 칸 요약 — 워커들이 나눠 채운다
    verified:  list                             # ④ 검수를 통과한 것 — 줄이는 결과라 리듀서 없음
    log:       Annotated[list, operator.add]    # 무슨 일이 있었는지

# ── 설정 · audience.yaml ──────────────────────────────────────
AUDIENCE_PATH = Path(__file__).resolve().parent / "audience.yaml"

class ConfigError(Exception):
    """audience.yaml이 없거나 틀렸을 때 — 실행 시작 단계에서 바로 멈춘다."""

class Part(BaseModel):
    title: str
    emoji: str
    about: str
    keywords: list[str]

class Allocation(BaseModel):
    total: int = Field(gt=0)
    base_per_part: int = Field(ge=0)
    max_per_part: int = Field(gt=0)
    max_per_source_in_part: int = Field(gt=0)
    max_per_source_total: int = Field(gt=0)
    bonus: str                                  # best 또는 파트 이름 — 파트 목록을 알아야 해서 Config에서 검사

class Source(BaseModel):
    name: str
    url: str
    part: str                                   # 파트 이름 또는 mixed — Config에서 검사

class Config(BaseModel):
    audience: str
    editor: str                                 # 판단하는 사람 (페르소나)
    window_hours: int = Field(gt=0)
    min_body_chars: int = Field(gt=0)
    allocation: Allocation
    parts: dict[str, Part]
    criteria: list[str]
    exclude: list[str]
    style: dict[str, str]
    sources: list[Source] = Field(min_length=1)

    @model_validator(mode="after")
    def check_parts(self):
        names, a = set(self.parts), self.allocation
        if a.bonus != "best" and a.bonus not in names:
            raise ValueError(f"allocation.bonus는 best 또는 {sorted(names)} 중 하나여야 해요: {a.bonus}")
        if a.base_per_part * len(names) > a.total:
            raise ValueError(f"allocation.base_per_part × 파트 수({a.base_per_part}×{len(names)})가 total({a.total})보다 커요")
        if a.max_per_part < a.base_per_part:
            raise ValueError("allocation.max_per_part가 base_per_part보다 작아요")
        bad = [s.name for s in self.sources if s.part not in names | {"mixed"}]
        if bad:
            raise ValueError(f"sources의 part는 {sorted(names)} 또는 mixed여야 해요: {bad}")
        return self

def load_config(path=AUDIENCE_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"설정 파일이 없어요: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"설정 파일 형식이 틀렸어요: {path}\n{e}") from e
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"설정 값이 틀렸어요: {path}\n{e}") from e

# ── 2부 · collect ─────────────────────────────────────────────
import calendar, json, re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser, requests

UA = {"User-Agent": "my-newsletter-agent/0.1 (RSS reader; personal study)"}  # 이름을 밝히고 막히면 우회하지 않는다
SENT_PATH = Path(__file__).resolve().parent / "store" / "sent.jsonl"
TRACKING = {"fbclid", "gclid", "ref"}           # 추적용 꼬리표로 보는 이름 (정확히 일치)

def is_tracking(key):
    k = key.lower()
    return k.startswith("utm_") or k in TRACKING   # utm_* 만 접두어로, 나머지는 이름이 같을 때만

def url_key(url):
    # ? 뒤를 통째로 떼면 골프매거진코리아(?idx=번호)처럼 주소의 핵심이 사라진다
    # → 추적용 꼬리표만 떼고 나머지 쿼리는 남긴다
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not is_tracking(k)]
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), urlencode(query), ""))

def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()

def published_at(entry):                        # feedparser의 *_parsed는 UTC 기준 struct_time
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc) if t else None

def fetch_feed(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()                        # 403·404도 '응답 없음'으로 잡는다
    return [{"title": strip_tags(e.get("title", "")), "url": e.get("link", ""), "at": published_at(e),
             "summary": strip_tags(e.get("summary", ""))[:300],
             "cats": [t.get("term", "") for t in e.get("tags", [])]}
            for e in feedparser.parse(r.content).entries if e.get("link")]

def load_sent(path=SENT_PATH):                  # 이미 보낸 주소 — 6부 publish가 한 줄씩 쌓는다
    path = Path(path)
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {url_key(json.loads(l)["url"]) for l in lines if l.strip()}

def merge(items, item):
    # 같은 글이 전체 피드(mixed)와 카테고리 피드에 다 있으면 카테고리 쪽 파트를 쓴다
    return [{**old, "part": item["part"]} if old["key"] == item["key"] and old["part"] == "mixed" else old
            for old in items]

def collect(s: dict, cfg: Config, fetch=None, sent_path=SENT_PATH) -> dict:  # ① 자료 수집
    fetch = fetch or fetch_feed                 # 테스트가 fetch_feed를 갈아 끼울 수 있게 부를 때 찾는다
    cutoff = datetime.now(timezone.utc) - timedelta(hours=s["hours"])
    sent = load_sent(sent_path)
    items, dead, counts, skipped = [], [], Counter(), 0
    for src in cfg.sources:
        counts[src.name] += 0                   # 0건인 소스도 로그에 보이게
        try:
            entries = fetch(src.url)
        except Exception:
            dead.append(f"{src.name}({urlsplit(src.url).path or '/'})")  # 한 곳이 죽어도 나머지는 계속
            continue
        for e in entries:
            if not e["at"] or e["at"] < cutoff:  # 날짜가 없거나 time window 밖이면 버린다
                continue
            key = url_key(e["url"])
            if key in sent:
                skipped += 1
                continue
            item = {**e, "key": key, "source": src.name, "part": src.part}
            if any(i["key"] == key for i in items):
                items = merge(items, item)
                continue
            items = [*items, item]
            counts[src.name] += 1
    per_source = " · ".join(f"{n} {c}" for n, c in counts.items())
    return {"collected": items,
            "log": [f"① 수집   {s['hours']}시간 · {len(items)}건 ({per_source})"
                    + (f" · 이미 보냄 {skipped}" if skipped else "")
                    + (f" · 응답 없음 {dead}" if dead else "")]}

# ── 3부 · select ─────────────────────────────────────────────
from openai import OpenAI

try:                                            # 키는 .env에서 읽는다 (Actions에서는 Secrets가 환경변수로 들어온다)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

MODEL = "gpt-4.1-mini"
SEED = 40
BATCH = 40                                      # 한 번에 보여 줄 후보 수 (lost in the middle)
PRELIM_KEEP = 8                                 # 후보가 BATCH보다 많을 때 묶음마다 남길 수
SPARES = 6                                      # verify에 넘길 예비 후보 수

_client = None
def llm():                                      # 테스트는 LLM을 갈아 끼우므로 처음 부를 때만 만든다
    global _client
    if _client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY가 없어요. .env나 GitHub Secrets를 확인하세요.")
        _client = OpenAI()
    return _client

import threading
USAGE = Counter()                               # 실행 한 번의 토큰 수 — run.py가 metrics에 적는다
_usage_lock = threading.Lock()                  # report·verify가 여러 스레드에서 동시에 부른다

def ask(system, user, schema):                  # 구조화 출력 — 형식이 틀리면 openai가 예외를 던진다
    r = llm().chat.completions.parse(
        model=MODEL, temperature=0, seed=SEED,   # temperature 0이어도 결과가 흔들려서 seed까지 고정 (완전 보장은 아님)
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema)
    if r.usage:
        with _usage_lock:
            USAGE["prompt"] += r.usage.prompt_tokens
            USAGE["completion"] += r.usage.completion_tokens
    return r.choices[0].message.parsed

PartName = Literal["menswear", "sports", "grooming", "none"]

class Assign(BaseModel):
    index: int = Field(description="목록 번호")
    part: PartName
    reason: str = Field(description="한 줄 이유")

class Assignments(BaseModel):
    items: list[Assign]

class Ranked(BaseModel):
    index: int = Field(description="목록 번호")
    # 처음엔 사건 라벨을 받았는데 '남성 그루밍'처럼 뭉뚱그린 라벨이 나와 다른 기사까지 같은 사건으로 지워졌다
    # → 같은 사건(같은 제품 출시·같은 발표·같은 연구)을 다룬 앞 순위 기사의 번호만 받는다
    same_as: int | None = Field(description="앞 순위에 같은 사건을 다룬 기사가 있으면 그 목록 번호, 주제만 비슷하면 null")
    reason: str = Field(description="순위 이유 한 줄")

class Ranking(BaseModel):
    items: list[Ranked]

def persona(cfg):                               # 판단하는 사람 — audience.yaml의 editor
    return f"{cfg.editor}\n독자: {cfg.audience}\n"

def listing(batch):
    return "\n".join(f"{i}. [{it['source']} · 피드:{it['part']}] {it['title']}"
                     + (f" | {', '.join(it.get('cats', [])[:4])}" if it.get("cats") else "")
                     + (f" | {it['summary'][:120]}" if it.get("summary") else "")
                     for i, it in enumerate(batch))

def assign_once(batch, cfg):
    parts = "\n".join(f"- {k}: {p.about}" for k, p in cfg.parts.items())
    system = (persona(cfg) + f"아래 {len(batch)}건 전부에 파트를 하나씩 붙이세요. 고르는 단계가 아니라 분류하는 단계라, "
              f"0번부터 {len(batch) - 1}번까지 빠짐없이 답하세요.\n" + parts
              + "\n- none: 위에 해당하지 않음\nnone으로 보낼 것: " + ", ".join(cfg.exclude)
              + "\n'피드:'는 기사가 들어온 피드의 분류라 틀릴 수 있어요. 내용으로 판단하세요.")
    out = ask(system, listing(batch), Assignments)
    return {a.index: a.part for a in out.items if 0 <= a.index < len(batch)}

def ask_assign(batch, cfg):                     # ① 파트 배정 — 피드 파트는 힌트일 뿐 다시 정한다
    got = assign_once(batch, cfg)
    # 실측: 페르소나를 넣자 40건 중 3건에만 답해서 나머지가 전부 '제외'가 됐다 → 빠진 기사만 한 번 더 묻는다
    missing = [i for i in range(len(batch)) if i not in got]
    if missing:
        again = assign_once([batch[i] for i in missing], cfg)
        got = {**got, **{missing[j]: p for j, p in again.items()}}
    # 그래도 빠진 기사는 피드 파트를 쓰고, 섞인 피드라 모르면 뺀다
    return {it["key"]: got.get(i, it["part"] if it["part"] in cfg.parts else "none")
            for i, it in enumerate(batch)}

def ask_rank(cands, cfg, part=None):            # ② 본선 순위 / 결승 순위 — 후보를 모두 순서대로 돌려준다
    scope = f"{cfg.parts[part].title} 파트 후보입니다." if part else "여러 파트의 남은 후보입니다. 파트를 가리지 말고 비교하세요."
    system = (persona(cfg) + scope + " 40대 독자가 오늘 바로 쓸 수 있는 순서로 전부 순위를 매기세요.\n기준:\n"
              + "\n".join(f"- {c}" for c in cfg.criteria)
              + "\n같은 사건(같은 제품 출시·같은 발표·같은 연구)을 다룬 기사만 same_as로 묶으세요. 주제가 비슷한 것은 묶지 마세요.")
    out = ask(system, listing(cands), Ranking)
    seen, ranked = set(), []
    for r in out.items:
        if 0 <= r.index < len(cands) and r.index not in seen:   # 없는 번호·중복 번호는 버린다
            seen.add(r.index)
            root = r.same_as if r.same_as in seen and r.same_as != r.index else r.index
            ranked.append({**cands[r.index], "event": cands[root]["url"]})   # 사건 = 그 사건을 처음 다룬 기사 주소
    # 순위에서 빠진 후보는 원래 순서대로 뒤에 붙인다 — 자리를 못 채우는 일을 막는다
    return ranked + [{**c, "event": c.get("event", c["url"])} for i, c in enumerate(cands) if i not in seen]

def rank_part(cands, cfg, part, rank):          # 후보가 많으면 예선으로 줄이고 본선
    if len(cands) <= BATCH:
        return rank(cands, cfg, part)
    survivors = [it for i in range(0, len(cands), BATCH)
                 for it in rank(cands[i:i + BATCH], cfg, part)[:PRELIM_KEEP]]
    return rank(survivors, cfg, part)

def allocate(ranked, alloc, final_rank):        # 하루 10건 배분 — LLM 없이 규칙만 (PRD 0장)
    picked, events, src_total, src_part, part_n = [], set(), Counter(), Counter(), Counter()
    taken = set()

    def ok(it):
        p, s = it["part"], it["source"]
        return (it["url"] not in taken and it["event"] not in events
                and src_part[(p, s)] < alloc.max_per_source_in_part
                and src_total[s] < alloc.max_per_source_total and part_n[p] < alloc.max_per_part)

    def take(it, slot):
        taken.add(it["url"]); events.add(it["event"])
        src_total[it["source"]] += 1; src_part[(it["part"], it["source"])] += 1; part_n[it["part"]] += 1
        picked.append({**it, "slot": slot})

    # ① 기본 몫 — 한 파트씩 다 채우면 앞 파트가 매체 상한을 먼저 써 버린다(실측: 화장품의 GQ 기사가 막힘)
    # → 후보가 적은 파트부터 한 건씩 돌아가며 채운다
    order = sorted(ranked, key=lambda p: len(ranked[p]))
    progress = True
    while progress:
        progress = False
        for part in order:
            if part_n[part] >= alloc.base_per_part:
                continue
            nxt = next((it for it in ranked[part] if ok(it)), None)
            if nxt:
                take(nxt, "base"); progress = True
    notes = [f"부족: {p} {part_n[p]}/{alloc.base_per_part}" for p in ranked if part_n[p] < alloc.base_per_part]

    slots = alloc.total - len(picked)
    if slots > 0 and alloc.bonus in ranked:     # bonus를 파트로 고정했으면 그 파트가 먼저 1건
        first = next((it for it in ranked[alloc.bonus] if ok(it)), None)
        if first:
            take(first, "final"); slots -= 1
    if slots > 0:                               # ② 결승 — 파트마다 다음 후보를 모아 한 번 더 순위
        pool = [it for cands in ranked.values() for it in [c for c in cands if ok(c)][:slots]]
        final_order = final_rank(pool, slots) if pool else []
        by_url = {it["url"]: it for it in pool}
        ordered = [by_url[o["url"]] for o in final_order if o["url"] in by_url]
        ordered += [it for it in pool if it not in ordered]      # 결승이 빠뜨린 후보도 이어서 본다
        for it in ordered:
            if len(picked) >= alloc.total:
                break
            if ok(it):
                take(it, "final")
    # 결승 후보끼리 매체 상한에 막혀 자리가 남으면(실측: 9건에서 멈춤) 파트별 순위를 따라 돌아가며 끝까지 채운다
    progress = True
    while progress and len(picked) < alloc.total:
        progress = False
        for part in order:
            if len(picked) >= alloc.total:
                break
            nxt = next((it for it in ranked[part] if ok(it)), None)
            if nxt:
                take(nxt, "final"); progress = True
    if len(picked) < alloc.total:
        notes.append(f"부족: {len(picked)}/{alloc.total}")
    return picked, notes

def select(s: dict, cfg: Config, assign=None, rank=None) -> dict:   # ② 파트 배정 · 10건 배분
    assign, rank = assign or ask_assign, rank or ask_rank
    items = s["collected"]
    parts_of = {}
    for i in range(0, len(items), BATCH):
        parts_of.update(assign(items[i:i + BATCH], cfg))
    tagged = [{**it, "part": parts_of.get(it["key"], "none")} for it in items]
    by_part = {p: [it for it in tagged if it["part"] == p] for p in cfg.parts}
    ranked = {p: rank_part(c, cfg, p, rank) if c else [] for p, c in by_part.items()}
    picked, notes = allocate(ranked, cfg.allocation, lambda pool, n: rank(pool, cfg, None))

    emoji = {p: cfg.parts[p].emoji for p in cfg.parts}
    cands = " · ".join(f"{emoji[p]} {len(c)}" for p, c in by_part.items())
    dropped = sum(it["part"] == "none" for it in tagged)
    split = " · ".join(f"{emoji[p]} {sum(x['part'] == p for x in picked)}" for p in cfg.parts)
    taken = {p["url"] for p in picked}
    depth = max((len(c) for c in ranked.values()), default=0)
    spares = [c[i] for i in range(depth) for c in ranked.values()   # 파트별 순위를 번갈아 늘어놓는다
              if i < len(c) and c[i]["url"] not in taken][:SPARES]
    return {"picked": picked, "spares": spares,
            "log": [f"② 선별   {len(items)} → 후보 {cands} · 제외 {dropped} → {len(picked)}건 ({split})"
                    + (f" · {' / '.join(notes)}" if notes else "")]}

# ── 4부 · report ─────────────────────────────────────────────
class ReportIn(TypedDict):                      # 워커가 받는 것은 기사 하나뿐
    article: dict

def fan_report(s: dict):                        # 기사 수만큼 워커를 펼친다
    if not s["picked"]:
        return "verify"                         # 0건이어도 heartbeat까지 가야 멈춤과 구분된다
    return [Send("report", {"article": a}) for a in s["picked"]]

import trafilatura

BODY_LIMIT = 6000                               # LLM에 넘기는 본문 길이 (비용 · 앞부분에 핵심이 있다)

class Draft(BaseModel):                         # ← PRD 4부 세 칸
    headline: str = Field(description="25자 내외 한국어 제목, 과장 없이")
    summary: str = Field(description="두세 문장 한국어 요약, ~합니다체. 제품명·가격·수치·인명은 원문에 있는 것만")
    why: str = Field(description="40대 남성에게 왜 쓸모 있나 한국어 한 문장")

KO_ONLY = "\n본문이 영어여도 headline·summary·why는 모두 한국어로만 쓰세요. 제품명·브랜드명은 원문 표기를 써도 됩니다."

def extract_body(url):                          # 목록은 RSS, 본문만 원문 페이지에서 뽑는다 (다섯 길 ⑤)
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return trafilatura.extract(r.text) or ""

def write_draft(body, cfg, article, korean_only=False):
    style = "\n".join(f"- {k}: {v}" for k, v in cfg.style.items())
    system = (persona(cfg) + f"아래는 '{cfg.parts[article['part']].title}' 파트 기사 본문입니다. "
              "본문만 근거로 headline·summary·why 세 칸을 쓰세요.\n" + style
              + "\n원문에 없는 효능·수치를 더하지 마세요. 건강 조언은 원문 전문가 발언의 범위를 넘기지 말고, "
              "원문의 조건('~라면', '의료진과 상의')은 그대로 남기세요. '주목된다·기대를 모은다' 같은 기자체는 쓰지 마세요."
              + (KO_ONLY if korean_only else ""))
    return ask(system, body[:BODY_LIMIT], Draft)

def korean_ok(d):                               # 지켜졌는지는 출력만 보고 코드로 확인한다
    return all(re.search(r"[가-힣]", t or "") for t in (d.headline, d.summary, d.why))

def report(s: ReportIn, cfg: Config) -> dict:   # ③ 세 칸 요약 — 기사 한 건을 맡는다
    it = s["article"]
    try:
        body = extract_body(it["url"])
    except Exception:
        body = ""                               # 막히거나 끊기면 본문 0자로 보고 뺀다
    if len(body) < cfg.min_body_chars:          # G1과 같은 기준선
        return {"drafted": [], "log": [f"   취재 제외 {it['source']} · 본문 {len(body)}자 · {it['title'][:30]}"]}
    d = write_draft(body, cfg, it)
    if not korean_ok(d):                        # 영어로 나오면 한국어 지시를 덧붙여 한 번만 다시 쓴다
        d = write_draft(body, cfg, it, korean_only=True)
    if not korean_ok(d):                        # 그래도 영어면 버리고 로그에 남긴다
        return {"drafted": [], "log": [f"   취재 제외 {it['source']} · 한국어 아님 · {it['title'][:30]}"]}
    return {"drafted": [{**it, "body": body[:BODY_LIMIT], **d.model_dump()}]}

# ── 5부 · verify ─────────────────────────────────────────────
from concurrent.futures import ThreadPoolExecutor

class Verdict(BaseModel):
    supported: bool = Field(description="요약의 사실 진술이 모두 원문에서 확인되면 true")
    problems: list[str] = Field(description="원문과 맞지 않는 문장과 이유. 없으면 빈 목록")

VERIFY_SYS = ("당신은 뉴스레터 검수자입니다. 요약을 쓴 사람과 다른 사람으로서, 요약이 원문에 근거하는지만 판정하세요.\n"
              "fail(supported=false)로 볼 것:\n"
              "- 원문에 없는 제품·브랜드·수치·효능·인물이 있음\n"
              "- 가격·날짜·횟수·용량이 원문과 다름\n"
              "- 원문의 조건부 조언('~라면', '~해도 된다', '의료진과 상의')을 단정이나 금지로 바꿈.\n"
              "  예: 원문이 '면도하지 않는 날에 하라, 아침에 면도하면 밤에 해도 된다'인데 요약이 '면도하는 날엔 하지 말라'고 쓰면 fail\n"
              "- 원문 안에서 앞뒤가 안 맞는 건강 수치(예: 좋은·나쁜 콜레스테롤을 뒤바꿈)를 그대로 옮김\n"
              "번역·요약 표현 차이, 원문 내용을 줄여 쓴 것은 문제가 아닙니다. 문장마다 원문의 해당 부분을 찾아 대조하세요.")

def check_draft(d, cfg):                        # 요약을 쓴 호출과 따로 부른다
    # why는 '40대에게 왜'라는 우리 해석이라 원문에 없는 게 정상이다
    # → 넣었더니 멀쩡한 요약 2건이 '원문에 40대 언급 없음'으로 떨어져 사실 칸(headline·summary)만 대조한다
    user = f"[원문]\n{d['body']}\n\n[요약]\nheadline: {d['headline']}\nsummary: {d['summary']}"
    return ask(VERIFY_SYS, user, Verdict)

def judge(d, cfg):                              # 검수가 실패하면 통과시키지 않는다
    try:
        v = check_draft(d, cfg)
        return v.supported, "; ".join(v.problems)[:120]
    except Exception as e:
        return False, f"검수 오류 {type(e).__name__}"

def replace(spares, kept, need, cfg):           # 빠진 자리마다 예비 후보를 한 번씩만 취재·검수한다
    out, log, src = [], [], Counter(d["source"] for d in kept)
    queue = list(spares)
    for _ in range(need):
        cand = next((c for c in queue if src[c["source"]] < cfg.allocation.max_per_source_total), None)
        if cand is None:
            break
        queue = [c for c in queue if c is not cand]
        drafted = report({"article": {**cand, "slot": "spare"}}, cfg)
        log += drafted.get("log", [])
        if not drafted["drafted"]:
            continue
        d = drafted["drafted"][0]
        ok, why = judge(d, cfg)
        if ok:
            out.append(d); src[d["source"]] += 1
            log.append(f"   교체 {d['source']} · {d['title'][:30]}")
        else:
            log.append(f"   검수 제외 {d['source']} · {why}")
    return out, log

def verify(s: dict, cfg: Config) -> dict:       # ④ 원문 대조 검수
    drafted = s["drafted"]
    with ThreadPoolExecutor(5) as ex:
        verdicts = list(ex.map(lambda d: judge(d, cfg), drafted))
    kept = [d for d, (ok, _) in zip(drafted, verdicts) if ok]
    log = [f"   검수 제외 {d['source']} · {why}" for d, (ok, why) in zip(drafted, verdicts) if not ok]
    need = len(s.get("picked", drafted)) - len(kept)          # 검수 불합격 + report에서 빠진 자리
    extra, extra_log = replace(s.get("spares", []), kept, need, cfg) if need > 0 else ([], [])
    verified = kept + extra
    return {"verified": verified,
            "log": log + extra_log + [f"④ 검수   {len(drafted)} → {len(kept)}건"
                                      + (f" · 교체 {len(extra)} → {len(verified)}건" if extra else "")]}

# ── 6부 · publish ────────────────────────────────────────────
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ISSUES_DIR = ROOT / "issues"                    # 실제로 보낸 날의 사본 (저장소에 남긴다)
OUTPUT_DIR = ROOT / "output"                    # dry-run 사본 (.gitignore) — issues의 사람이 만든 0호를 덮지 않게
COLORS = {"menswear": 0x3A5A8C, "sports": 0x2E7D5B, "grooming": 0x8C5A3A}
TITLE_MAX, DESC_MAX, EMBED_MAX, TOTAL_MAX = 256, 4096, 10, 5800   # 합계 6000에서 여유를 둔다
PAUSE = 0.6                                     # 메시지 사이 쉬는 시간 (웹훅 속도 제한)

def today_kst():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

def split_line(verified, cfg):
    return " · ".join(f"{p.emoji} {sum(a['part'] == k for a in verified)}" for k, p in cfg.parts.items())

def card(a, n, cfg):
    desc = f"{a['summary']}\n\n💡 **{a['why']}**"
    return {"title": f"{cfg.parts[a['part']].emoji} {n}. {a['headline']}"[:TITLE_MAX],
            "description": desc[:DESC_MAX], "url": a["url"],
            "color": COLORS.get(a["part"], 0x5F7476), "footer": {"text": a["source"]}}

def fit(embeds):                                # 메시지 합계 한도를 넘으면 요약을 줄인다
    total = lambda es: sum(len(e["title"]) + len(e["description"]) + len(e["footer"]["text"]) for e in es)
    while total(embeds) > TOTAL_MAX:
        longest = max(range(len(embeds)), key=lambda i: len(embeds[i]["description"]))
        d = embeds[longest]["description"]
        embeds = [*embeds[:longest], {**embeds[longest], "description": d[:int(len(d) * 0.8)] + "…"}, *embeds[longest + 1:]]
    return embeds

def build_messages(verified, cfg, today):
    if not verified:                            # 조용한 날에도 한 장은 보낸다 (heartbeat)
        return [{"content": f"🗞️ {today} · 오늘은 조용합니다. 고를 만한 기사가 없었어요."}]
    msgs, n = [{"content": f"🗞️ **{today} · 40대 남성 아침 브리핑** — {split_line(verified, cfg)}"}], 0
    for key in cfg.parts:                       # 파트마다 한 메시지 · 기사마다 카드 한 장(제목이 원문 링크)
        arts = [a for a in verified if a["part"] == key]
        if not arts:
            continue
        cards = [card(a, n + i + 1, cfg) for i, a in enumerate(arts)][:EMBED_MAX]
        n += len(arts)
        msgs.append({"embeds": fit(cards)})
    return msgs

def render_markdown(verified, cfg, today):
    lines = [f"# 40대 남성 아침 브리핑 · {today}", "", f"> 오늘 배분 {split_line(verified, cfg)}", ""]
    if not verified:
        return "\n".join(lines + ["오늘은 조용합니다.", ""])
    for key, p in cfg.parts.items():
        arts = [a for a in verified if a["part"] == key]
        if arts:
            lines += [f"## {p.emoji} {p.title}", ""]
        for a in arts:
            lines += [f"### {a['headline']}", "", a["summary"], "", f"**40대에게:** {a['why']}", "",
                      f"{a['source']} · [{a['title']}]({a['url']})", ""]
    return "\n".join(lines)

def post_all(webhook, msgs, post):              # 하나라도 거절되면 실패
    for i, m in enumerate(msgs):
        r = post(webhook, json={"username": "40대 아침 브리핑", **m}, timeout=20)
        if r.status_code not in (200, 204):
            return False, f"{i + 1}/{len(msgs)}번째 메시지 {r.status_code}"   # 웹훅 주소는 로그에 남기지 않는다
        if i < len(msgs) - 1:
            time.sleep(PAUSE)
    return True, ""

def record_sent(verified, today):               # 2부 collect가 다음 날 이 주소를 뺀다
    SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SENT_PATH.open("a", encoding="utf-8") as f:
        for a in verified:
            f.write(json.dumps({"date": today, "url": a["url"], "part": a["part"], "source": a["source"]},
                               ensure_ascii=False) + "\n")

def publish(s: dict, cfg: Config, post=None) -> dict:   # ⑤ 발행
    post = post or requests.post
    verified, today = s["verified"], today_kst()
    msgs = build_messages(verified, cfg, today)
    dry_run = os.environ.get("DRY_RUN", "1") != "0"     # 기본은 보내지 않는다
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    label = f"{len(verified)}건 ({split_line(verified, cfg)}) · 메시지 {len(msgs)}개" if verified else "조용합니다"
    if dry_run:
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / f"{today}.md").write_text(render_markdown(verified, cfg, today), encoding="utf-8")
        return {"log": [f"   사본 output/{today}.md", f"⑤ 발행   {label} · dry-run"]}
    if not webhook:
        return {"log": ["   DISCORD_WEBHOOK_URL이 없어요", f"⑤ 발행   {label} · 실패"]}
    try:
        ok, why = post_all(webhook, msgs, post)
    except Exception as e:                      # 네트워크가 끊겨도 실패로 적고 끝낸다
        ok, why = False, type(e).__name__
    if not ok:
        return {"log": [f"   발송 거절 {why}", f"⑤ 발행   {label} · 실패"]}
    ISSUES_DIR.mkdir(exist_ok=True)
    (ISSUES_DIR / f"{today}.md").write_text(render_markdown(verified, cfg, today), encoding="utf-8")
    record_sent(verified, today)
    # sent가 False인 경우가 둘이라 나눠 적는다: 일부러 안 보냄(dry-run) / 보내려다 실패
    return {"log": [f"   사본 issues/{today}.md", f"⑤ 발행   {label} · 보냄"]}

def build(cfg: Config):                         # 노드를 이름으로 붙인다
    g = StateGraph(Brief)
    g.add_node("collect", partial(collect, cfg=cfg))
    g.add_node("select", partial(select, cfg=cfg))
    g.add_node("report", partial(report, cfg=cfg))
    g.add_node("verify", partial(verify, cfg=cfg))
    g.add_node("publish", partial(publish, cfg=cfg))
    g.add_edge(START, "collect")
    g.add_edge("collect", "select")
    g.add_conditional_edges("select", fan_report, ["report", "verify"])  # ← 팬아웃, 0건이면 verify로
    g.add_edge("report", "verify")
    g.add_edge("verify", "publish")
    g.add_edge("publish", END)
    return g

def run(config_path=AUDIENCE_PATH):            # 실행은 run.py에서만
    cfg = load_config(config_path)              # 설정이 틀리면 수집 전에 멈춘다
    init = {"hours": cfg.window_hours,
            "collected": [], "picked": [], "spares": [], "drafted": [], "verified": [], "log": []}
    return build(cfg).compile().invoke(init)

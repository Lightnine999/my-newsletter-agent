"""3부 select 테스트 — LLM은 가짜로 바꿔 끼워요. PRD 3부 검증표를 코드로 옮겼어요."""
from collections import Counter

import graph

ALLOC = graph.load_config().allocation          # total 10 · base 3 · max 5 · 매체 2/3 · bonus best


def items(part, n, source=None, prefix=None):
    prefix = prefix or part
    return [{"url": f"https://x/{prefix}/{i}", "title": f"{prefix} {i}", "part": part,
             "source": source or f"{prefix}-src{i}", "event": f"{prefix}-ev{i}"} for i in range(n)]


def keep_order(pool, n):                        # 가짜 결승: 받은 순서 그대로
    return pool


def parts_of(picked):
    return Counter(p["part"] for p in picked)


def test_후보가_충분하면_10건이고_파트마다_3건_이상이다():
    ranked = {"menswear": items("menswear", 6), "sports": items("sports", 6), "grooming": items("grooming", 6)}
    picked, notes = graph.allocate(ranked, ALLOC, keep_order)
    assert len(picked) == 10
    assert all(n >= 3 for n in parts_of(picked).values())
    assert notes == []


def test_결승_순위가_추가_1건의_파트를_정한다():
    ranked = {"menswear": items("menswear", 6), "sports": items("sports", 6), "grooming": items("grooming", 6)}
    prefer_grooming = lambda pool, n: sorted(pool, key=lambda it: it["part"] != "grooming")
    picked, _ = graph.allocate(ranked, ALLOC, prefer_grooming)
    assert parts_of(picked) == {"menswear": 3, "sports": 3, "grooming": 4}
    assert [p["slot"] for p in picked].count("final") == 1


def test_화장품이_1건뿐이면_남은_자리를_다른_파트가_채운다():
    ranked = {"menswear": items("menswear", 8), "sports": items("sports", 8), "grooming": items("grooming", 1)}
    picked, notes = graph.allocate(ranked, ALLOC, keep_order)
    c = parts_of(picked)
    assert len(picked) == 10 and c["grooming"] == 1
    assert c["menswear"] <= ALLOC.max_per_part and c["sports"] <= ALLOC.max_per_part
    assert "부족: grooming 1/3" in notes


def test_파트_안_같은_매체는_2건까지():
    ranked = {"menswear": items("menswear", 5, source="FB") + items("menswear", 3, prefix="mw2"),
              "sports": items("sports", 6), "grooming": items("grooming", 6)}
    picked, _ = graph.allocate(ranked, ALLOC, keep_order)
    assert Counter(p["source"] for p in picked if p["part"] == "menswear")["FB"] == 2


def test_전체_같은_매체는_3건까지():
    ranked = {p: items(p, 2, source="MH") + items(p, 4, prefix=f"{p}b") for p in ("menswear", "sports", "grooming")}
    picked, _ = graph.allocate(ranked, ALLOC, keep_order)
    assert Counter(p["source"] for p in picked)["MH"] == 3


def test_후보가_적은_파트가_매체_상한에_밀리지_않는다():
    # 실측에서 본 일: 남성복·스포츠가 GQ 3건을 먼저 써서 화장품의 GQ 기사가 막혔어요
    ranked = {"menswear": items("menswear", 2, source="GQ", prefix="m") + items("menswear", 4, prefix="m2"),
              "sports": items("sports", 1, source="GQ", prefix="s") + items("sports", 5, prefix="s2"),
              "grooming": items("grooming", 1, source="GQ", prefix="g") + items("grooming", 2, prefix="g2")}
    picked, _ = graph.allocate(ranked, ALLOC, keep_order)
    assert parts_of(picked)["grooming"] == 3
    assert any(p["part"] == "grooming" and p["source"] == "GQ" for p in picked)


def test_같은_사건은_파트가_달라도_한_번만():
    shared = {"event": "same"}
    ranked = {"menswear": [{**items("menswear", 1)[0], **shared}] + items("menswear", 4, prefix="m2"),
              "sports": [{**items("sports", 1)[0], **shared}] + items("sports", 4, prefix="s2"),
              "grooming": items("grooming", 5)}
    picked, _ = graph.allocate(ranked, ALLOC, keep_order)
    assert [p["event"] for p in picked].count("same") == 1


def test_bonus를_파트로_고정하면_그_파트가_추가_1건을_받는다():
    ranked = {"menswear": items("menswear", 6), "sports": items("sports", 6), "grooming": items("grooming", 6)}
    alloc = ALLOC.model_copy(update={"bonus": "sports"})
    prefer_menswear = lambda pool, n: sorted(pool, key=lambda it: it["part"] != "menswear")
    picked, _ = graph.allocate(ranked, alloc, prefer_menswear)
    assert parts_of(picked) == {"menswear": 3, "sports": 4, "grooming": 3}


def test_전체_후보가_모자라면_있는_만큼만_보내고_적는다():
    ranked = {"menswear": items("menswear", 2), "sports": items("sports", 3), "grooming": items("grooming", 2)}
    picked, notes = graph.allocate(ranked, ALLOC, keep_order)
    assert len(picked) == 7
    assert "부족: 7/10" in notes


def test_결승_후보가_매체_상한에_막혀도_뒤_순위로_끝까지_채운다():
    # 실측: 결승 후보를 파트마다 '남은 자리 수'만큼만 모았더니 서로 막혀서 9건에서 멈췄어요
    # 기본 몫에서 GQ 2건 → 결승 후보(파트마다 다음 2건)가 전부 GQ → 1건 뽑으면 GQ 상한 3에 걸려 나머지가 막힘
    gq = lambda p, n: items(p, n, source="GQ", prefix=f"{p}gq")
    ranked = {"menswear": items("menswear", 1, source="GQ", prefix="m0") + items("menswear", 2, prefix="m1") + gq("menswear", 2) + items("menswear", 3, prefix="m3"),
              "sports": items("sports", 1, source="GQ", prefix="s0") + items("sports", 2, prefix="s1") + gq("sports", 2) + items("sports", 3, prefix="s3"),
              "grooming": items("grooming", 3) + gq("grooming", 2)}
    alloc = ALLOC.model_copy(update={"total": 11})
    picked, notes = graph.allocate(ranked, alloc, keep_order)
    assert len(picked) == 11 and notes == []


def test_결승이_후보를_빠뜨려도_순위대로_이어서_채운다():
    ranked = {"menswear": items("menswear", 6), "sports": items("sports", 6), "grooming": items("grooming", 1)}
    picked, _ = graph.allocate(ranked, ALLOC, lambda pool, n: [])   # LLM이 빈 목록을 돌려줘도
    assert len(picked) == 10


# ── select 노드 ───────────────────────────────────────────

def test_select는_none을_빼고_파트별로_순위를_매겨_10건을_고른다():
    cfg = graph.load_config()
    collected = items("mixed", 30, prefix="c")
    parts = ["menswear", "sports", "grooming", "none", "sports"]

    def fake_assign(batch, cfg):
        return {it["key"]: parts[int(it["title"].split()[-1]) % 5] for it in batch}

    def fake_rank(cands, cfg, part=None):
        return [{**it, "event": it["url"]} for it in cands]

    out = graph.select({"collected": [{**c, "key": c["url"]} for c in collected]}, cfg,
                       assign=fake_assign, rank=fake_rank)
    assert len(out["picked"]) == 10
    assert all(p["part"] != "none" for p in out["picked"])
    assert out["log"][0].startswith("② 선별   30 →")
    assert "제외 6" in out["log"][0]

# HITL 기준 검증용 샘플 모으기 — 그래프를 dry-run으로 한 번 돌려 원문까지 담은 기사를 저장한다
# 실행: .venv/bin/python scripts/hitl_samples.py   (OpenAI 호출이 있어 1회 약 $0.03)
# 결과: store/hitl/samples.jsonl (본문 저작권 때문에 .gitignore로 저장소에서 뺀다)
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DRY_RUN"] = "1"                     # 절대 발송하지 않는다
import graph

OUT = ROOT / "store" / "hitl" / "samples.jsonl"
FIELDS = ("part", "source", "title", "url", "headline", "summary", "why", "body", "slot")

def main():
    out, today = graph.run(), graph.today_kst()
    kept = {a["url"] for a in out["verified"]}
    seen = set()
    if OUT.exists():                            # 같은 기사를 두 번 쌓지 않는다
        seen = {json.loads(l)["url"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = []
    for a in out["drafted"] + out["verified"]:  # verify에서 떨어진 기사도 모은다 (놓침 후보)
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        rows.append({"date": today, **{k: a.get(k) for k in FIELDS}, "verify_passed": a["url"] in kept})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"새 기사 {len(rows)}건 추가 → {OUT.relative_to(ROOT)} (검수 통과 {sum(r['verify_passed'] for r in rows)}건)")

if __name__ == "__main__":
    main()

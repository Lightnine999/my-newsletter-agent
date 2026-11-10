# HITL 멈춤 기준 비교표 — 같은 샘플에 여러 기준을 대고 개입률 · 놓침 · 헛멈춤을 센다 (교안 3장)
# 실행: .venv/bin/python scripts/hitl_compare.py
# 입력: store/hitl/samples.jsonl (hitl_samples.py가 만든다)
#       store/hitl/labels.csv   (url, 사람이 봐야 하나 y/n — 사람이 직접 채운다. 없으면 빈 양식을 만든다)
import csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hitl import CRITERIA, health_words, missing_numbers   # 기준은 승인 화면과 같은 곳에서 가져온다

HITL_DIR = Path(__file__).resolve().parent.parent / "store" / "hitl"
SAMPLES, LABELS = HITL_DIR / "samples.jsonl", HITL_DIR / "labels.csv"

def load_samples():
    return [json.loads(l) for l in SAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]

def load_labels(samples):                       # 양식이 없으면 만들고, 새 기사는 빈 칸으로 덧붙인다
    labels = {}
    if LABELS.exists():
        with LABELS.open(encoding="utf-8") as f:
            labels = {r["url"]: r["needs_review"].strip().lower() for r in csv.DictReader(f)}
    new = [a for a in samples if a["url"] not in labels]
    if new:
        fresh = not LABELS.exists()
        with LABELS.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if fresh:
                w.writerow(["url", "needs_review", "headline"])
            w.writerows([a["url"], "", a["headline"]] for a in new)
    return {u: v for u, v in labels.items() if v in ("y", "n")}

def table(samples, labels):
    labeled = [a for a in samples if a["url"] in labels]
    print(f"샘플 {len(samples)}건 · 정답 표시 {len(labeled)}건\n")
    print(f"{'기준':<18}{'멈춤':>6}{'개입률':>8}{'놓침':>6}{'헛멈춤':>7}")
    for name, stop in CRITERIA.items():
        hits = sum(stop(a) for a in samples)
        miss = sum(not stop(a) and labels[a["url"]] == "y" for a in labeled)
        false = sum(stop(a) and labels[a["url"]] == "n" for a in labeled)
        tail = f"{miss:>6}{false:>7}" if labeled else f"{'-':>6}{'-':>7}"
        print(f"{name:<18}{hits:>6}{hits / len(samples):>8.0%}{tail}")

def detail(samples):                            # 왜 멈췄는지 — 승인 화면의 '멈춘 이유'와 같은 내용
    print("\n기사별 멈춘 이유")
    for a in samples:
        nums, words = missing_numbers(a), health_words(a)
        reason = " · ".join(filter(None, [f"원문에 없는 수치 {nums}" if nums else "",
                                          f"건강 키워드 {words}" if words else ""])) or "자동 통과"
        print(f"- {a['headline'][:28]:<30} {reason}")

def main():
    samples = load_samples()
    labels = load_labels(samples)
    table(samples, labels)
    detail(samples)
    if len(labels) < len(samples):
        print(f"\n정답 표시: {LABELS} 의 needs_review 칸에 y/n을 채우면 놓침·헛멈춤이 계산돼요.")

if __name__ == "__main__":
    main()

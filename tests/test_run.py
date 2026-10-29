"""7부 run.py 테스트 — 예비 실행 중복 방지, 실패 시 exit 1, metrics 한 줄."""
import json

import pytest

import graph
import run

TODAY = "2026-10-30"


def fake_out(result="보냄", n=10):
    verified = [{"url": f"https://x/{i}", "part": ("menswear", "sports", "grooming")[i % 3], "source": f"S{i % 4}"}
                for i in range(n)]
    return {"collected": [{"source": "A"}] * 60 + [{"source": "B"}] * 5,
            "picked": verified, "verified": verified,
            "log": ["① 수집   ...", "   취재 제외 GQ 코리아 · 본문 300자 · 제목", "   검수 제외 MH · 원문에 없는 수치",
                    "② 선별   ...", "④ 검수   ...", f"⑤ 발행   {n}건 · {result}"]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "METRICS_PATH", tmp_path / "store" / "metrics.jsonl")
    monkeypatch.setattr(graph, "today_kst", lambda: TODAY)
    monkeypatch.setenv("DRY_RUN", "1")          # main이 os.environ을 바꾸므로 테스트가 끝나면 되돌린다
    return tmp_path


def sent_today(rows):
    graph.SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    graph.SENT_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_오늘_보낸_기록이_있으면_already_sent():
    assert not run.already_sent(graph.SENT_PATH, TODAY)                     # 파일이 없으면 아직
    sent_today([{"date": "2026-10-29", "url": "u"}])
    assert not run.already_sent(graph.SENT_PATH, TODAY)
    sent_today([{"date": "2026-10-29", "url": "u"}, {"date": TODAY, "url": "v"}])
    assert run.already_sent(graph.SENT_PATH, TODAY)


def test_예비_실행은_오늘_이미_보냈으면_그래프를_돌리지_않는다(env, monkeypatch):
    sent_today([{"date": TODAY, "url": "v"}])
    monkeypatch.setattr(graph, "run", lambda: pytest.fail("그래프를 돌리면 안 돼요"))
    assert run.main(["run.py"], {"DRY_RUN": "0"}) == 0
    assert not run.METRICS_PATH.exists()


def test_dry_run은_오늘_보냈어도_돌린다(env, monkeypatch):
    sent_today([{"date": TODAY, "url": "v"}])
    monkeypatch.setattr(graph, "run", lambda: fake_out("dry-run"))
    assert run.main(["run.py", "--dry-run"], {}) == 0


def test_보내야_하는데_못_보내면_exit_1이고_실패를_기록한다(env, monkeypatch):
    monkeypatch.setattr(graph, "run", lambda: fake_out("실패"))
    assert run.main(["run.py"], {"DRY_RUN": "0"}) == 1
    row = json.loads(run.METRICS_PATH.read_text(encoding="utf-8"))
    assert row["publish_result"] == "실패"


def test_보내면_metrics_한_줄을_쌓는다(env, monkeypatch):
    monkeypatch.setattr(graph, "run", lambda: fake_out("보냄"))
    actions_env = {"DRY_RUN": "0", "GITHUB_RUN_ID": "123", "GITHUB_EVENT_NAME": "schedule"}
    assert run.main(["run.py"], actions_env) == 0
    row = json.loads(run.METRICS_PATH.read_text(encoding="utf-8").splitlines()[-1])
    assert row["date"] == TODAY and row["run_id"] == "123" and row["trigger"] == "schedule"
    assert row["collected"] == 65 and row["source_counts"] == {"A": 60, "B": 5}
    assert row["picked"] == {"menswear": 4, "sports": 3, "grooming": 3}
    assert row["verified"] == 10 and row["publish_result"] == "보냄"
    assert [d["stage"] for d in row["dropped"]] == ["report", "verify"]
    assert {"tokens", "cost_usd", "duration_s", "started_at"} <= set(row)


def test_dry_run도_metrics에_dry_run으로_쌓는다(env, monkeypatch):
    # PRD 7부: publish_result는 보냄 / dry-run / 실패 — dry-run도 품질 추적에 쓴다
    monkeypatch.setattr(graph, "run", lambda: fake_out("dry-run"))
    assert run.main(["run.py", "--dry-run"], {}) == 0
    row = json.loads(run.METRICS_PATH.read_text(encoding="utf-8"))
    assert row["publish_result"] == "dry-run" and row["trigger"] == "manual"


def test_설정이_틀리면_exit_2(env, monkeypatch):
    def bad():
        raise graph.ConfigError("설정 파일이 없어요")
    monkeypatch.setattr(graph, "run", bad)
    assert run.main(["run.py"], {"DRY_RUN": "0"}) == 2

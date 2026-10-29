"""1부 뼈대 테스트 — 네트워크·API 키 없이 돌아가요."""
import pytest
import yaml

import graph

AUDIENCE = graph.AUDIENCE_PATH


def write_yaml(tmp_path, data):
    p = tmp_path / "audience.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def base_data():
    return yaml.safe_load(AUDIENCE.read_text(encoding="utf-8"))


# ── 설정 읽기 ─────────────────────────────────────────────

def test_실제_audience_yaml을_읽는다():
    cfg = graph.load_config(AUDIENCE)
    assert set(cfg.parts) == {"menswear", "sports", "grooming"}
    assert cfg.allocation.total == 10
    assert cfg.window_hours == 24
    assert len(cfg.sources) == 17


def test_파일이_없으면_바로_멈춘다(tmp_path):
    with pytest.raises(graph.ConfigError, match="없어요"):
        graph.load_config(tmp_path / "nope.yaml")


def test_yaml_문법이_틀리면_바로_멈춘다(tmp_path):
    p = tmp_path / "audience.yaml"
    p.write_text("parts: [menswear\n", encoding="utf-8")
    with pytest.raises(graph.ConfigError, match="형식"):
        graph.load_config(p)


def test_필수_칸이_빠지면_바로_멈춘다(tmp_path):
    data = base_data()
    del data["allocation"]
    with pytest.raises(graph.ConfigError, match="allocation"):
        graph.load_config(write_yaml(tmp_path, data))


def test_bonus는_best이거나_파트_이름이어야_한다(tmp_path):
    data = base_data()
    data["allocation"]["bonus"] = "golf"
    with pytest.raises(graph.ConfigError, match="bonus"):
        graph.load_config(write_yaml(tmp_path, data))
    data["allocation"]["bonus"] = "sports"
    assert graph.load_config(write_yaml(tmp_path, data)).allocation.bonus == "sports"


def test_기본_몫_합이_전체보다_크면_멈춘다(tmp_path):
    data = base_data()
    data["allocation"]["base_per_part"] = 4          # 4 × 3 = 12 > 10
    with pytest.raises(graph.ConfigError, match="base_per_part"):
        graph.load_config(write_yaml(tmp_path, data))


def test_소스_파트는_정해진_값만_쓴다(tmp_path):
    data = base_data()
    data["sources"][0]["part"] = "fashion"
    with pytest.raises(graph.ConfigError, match="part"):
        graph.load_config(write_yaml(tmp_path, data))


# ── 그래프 ───────────────────────────────────────────────

def test_그래프가_START부터_END까지_지나간다(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setattr(graph, "fetch_feed", lambda url: [])   # 네트워크 없이
    out = graph.run()
    steps = [line[0] for line in out["log"] if not line.startswith(" ")]   # 들여쓴 줄은 세부 기록
    assert steps == ["①", "②", "④", "⑤"]             # 0건이면 report를 건너뛰고 verify로
    assert out["log"][-1].endswith("dry-run")


def test_고른_기사가_있으면_기사_수만큼_report로_펼친다():
    sends = graph.fan_report({"picked": [{"title": "a"}, {"title": "b"}]})
    assert [s.node for s in sends] == ["report", "report"]
    assert graph.fan_report({"picked": []}) == "verify"

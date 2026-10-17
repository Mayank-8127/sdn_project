import csv

from ffr.experiments import run_suite
from ffr.experiments.runner import Case, run_case, run_cases
from ffr.experiments.suite import aggregate, srlg_pairs


def test_run_case_row():
    row = run_case(Case("ring6", "frr-link", [("link", "s1", "s2", 0.4, None, False)],
                        rate=200, start=0.25, stop=0.6, labels={"tag": "x"}))
    assert row["tag"] == "x" and row["app"] == "frr-link"
    assert row["affected"] > 0 and row["never_recovered"] == 0
    assert row["max_outage_ms"] <= 10 and row["stretch"] >= 1.0


def test_static_has_no_outage_statistics():
    row = run_case(Case("ring6", "static", [("link", "s1", "s2", 0.4, None, False)],
                        rate=200, start=0.25, stop=0.6))
    assert row["never_recovered"] > 0 and row["mean_outage_ms"] is None
    agg = aggregate([row])
    assert agg[0]["mean_outage_ms"] == "n/a" and agg[0]["survival_pct"] == 0.0


def test_parallel_equals_serial():
    cases = [Case("ring6", app, [("link", "s1", "s2", 0.4, None, False)], rate=100,
                  start=0.25, stop=0.5) for app in ("reactive", "frr-node")]
    serial = run_cases(cases, workers=1)
    par = run_cases(cases, workers=2, progress=False)
    strip = lambda rs: [{k: v for k, v in r.items() if k != "wall_s"} for r in rs]
    assert strip(serial) == strip(par)


def test_srlg_pairs_keep_network_connected():
    pairs = srlg_pairs("abilene", None)
    assert pairs and all(l1 != l2 for l1, l2 in pairs)


def test_suite_writes_report(tmp_path):
    run_suite(["risk_tradeoff", "timeline"], quick=True, out=str(tmp_path), workers=1)
    report = (tmp_path / "REPORT.md").read_text()
    assert "Risk-aware routing" in report and "What a failure looks like" in report
    rows = list(csv.DictReader(open(tmp_path / "risk_tradeoff.csv")))
    lam0 = [r for r in rows if r["topo"] == "abilene" and r["lam"] == "0"][0]
    lam50 = [r for r in rows if r["topo"] == "abilene" and r["lam"] == "50"][0]
    # more weight on risk => more reliable but slower paths
    assert float(lam50["mean_path_fail_prob_pct"]) < float(lam0["mean_path_fail_prob_pct"])
    assert float(lam50["mean_path_delay_ms"]) >= float(lam0["mean_path_delay_ms"])

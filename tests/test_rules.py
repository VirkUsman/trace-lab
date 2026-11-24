"""Structure checks on the rules file.

These parse the YAML and the PromQL text with regexes. They do not evaluate
PromQL: that is promtool's job (see test_promtool.py) and is skipped when
promtool is not installed.
"""

import re
from pathlib import Path

import pytest
import yaml

RULES = Path(__file__).parent.parent / "rules" / "slo.rules.yml"

BUDGET = {"availability": 0.001, "latency": 0.01}
# factor, long window, short window, severity: Google SRE Workbook, ch. 5.
AVAILABILITY_TABLE = [
    (14.4, "1h", "5m", "page"),
    (6, "6h", "30m", "page"),
    (3, "1d", "2h", "ticket"),
    (1, "3d", "6h", "ticket"),
]
SECONDS = {"m": 60, "h": 3600, "d": 86400}


def seconds(window: str) -> int:
    return int(window[:-1]) * SECONDS[window[-1]]


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(RULES.read_text())


@pytest.fixture(scope="module")
def alerts(doc):
    return [r for g in doc["groups"] for r in g["rules"] if "alert" in r]


@pytest.fixture(scope="module")
def records(doc):
    return [r for g in doc["groups"] for r in g["rules"] if "record" in r]


def parse_alert(rule):
    """(recorded series prefix, [windows], [thresholds]) from an alert's expr."""
    terms = re.findall(r"trace_lab:(\w+):rate(\w+) > \(([\d.]+) \* ([\d.]+)\)", rule["expr"])
    return terms


def test_file_has_the_two_groups(doc):
    assert [g["name"] for g in doc["groups"]] == ["trace_lab_slo_recording", "trace_lab_slo_alerts"]


def test_every_rule_has_an_expr(doc):
    for g in doc["groups"]:
        for r in g["rules"]:
            assert r["expr"].strip(), r


def test_recording_rule_names_follow_level_metric_operation(records):
    for r in records:
        assert re.fullmatch(r"trace_lab:[a-z_]+:rate\d+[mhd]", r["record"]), r["record"]


def test_both_ratios_are_recorded_over_all_seven_windows(records):
    names = {r["record"] for r in records}
    for kind in ("http_error_ratio", "http_slow_ratio"):
        for w in ("5m", "30m", "1h", "2h", "6h", "1d", "3d"):
            assert f"trace_lab:{kind}:rate{w}" in names


def test_recording_window_in_name_matches_the_range_in_expr(records):
    for r in records:
        in_name = r["record"].rsplit("rate", 1)[1]
        in_expr = set(re.findall(r"\[(\w+)\]", r["expr"]))
        assert in_expr == {in_name}, r["record"]


def test_error_ratio_counts_only_5xx_in_the_numerator(records):
    for r in records:
        if "error_ratio" in r["record"]:
            assert r["expr"].count('status="5xx"') == 1


def test_slow_ratio_reads_the_300ms_bucket(records):
    for r in records:
        if "slow_ratio" in r["record"]:
            assert 'le="0.3"' in r["expr"]


def test_alerts_exist_with_expected_names(alerts):
    names = {a["alert"] for a in alerts}
    assert {
        "TraceLabAvailabilityBurnFast",
        "TraceLabAvailabilityBurnSlow",
        "TraceLabAvailabilityBurnTicket",
        "TraceLabAvailabilityBurnDrift",
        "TraceLabLatencyBurnFast",
        "TraceLabLatencyBurnSlow",
    } <= names


def test_every_alert_uses_two_windows(alerts):
    for a in alerts:
        assert len(parse_alert(a)) == 2, a["alert"]


def test_availability_windows_and_factors_match_the_workbook_table(alerts):
    found = []
    for a in alerts:
        if a["labels"]["slo"] != "availability":
            continue
        (_, w1, f1, b1), (_, w2, f2, b2) = parse_alert(a)
        assert f1 == f2 and b1 == b2
        found.append((float(f1), w1, w2, a["labels"]["severity"]))
    assert sorted(found) == sorted((float(f), lo, sh, s) for f, lo, sh, s in AVAILABILITY_TABLE)


def test_short_window_is_a_twelfth_of_the_long_one(alerts):
    for a in alerts:
        (_, long_w, _, _), (_, short_w, _, _) = parse_alert(a)
        assert seconds(long_w) == 12 * seconds(short_w), a["alert"]


def test_both_windows_use_the_same_series_kind_and_threshold(alerts):
    for a in alerts:
        (k1, _, f1, b1), (k2, _, f2, b2) = parse_alert(a)
        assert (k1, f1, b1) == (k2, f2, b2), a["alert"]


def test_threshold_uses_the_budget_of_its_slo(alerts):
    for a in alerts:
        kind = a["labels"]["slo"]
        (_, _, _, budget), _ = parse_alert(a)
        assert float(budget) == BUDGET[kind], a["alert"]


def test_alert_reads_the_series_of_its_own_slo(alerts):
    series = {"availability": "http_error_ratio", "latency": "http_slow_ratio"}
    for a in alerts:
        (name, _, _, _), _ = parse_alert(a)
        assert name == series[a["labels"]["slo"]], a["alert"]


def test_pages_burn_fast_and_tickets_burn_slow(alerts):
    for a in alerts:
        (_, _, factor, _), _ = parse_alert(a)
        if a["labels"]["severity"] == "page":
            assert float(factor) >= 6
        else:
            assert float(factor) <= 3


def test_14_4x_for_an_hour_spends_two_percent_of_a_30_day_budget():
    assert round(14.4 * 1 / (30 * 24) * 100, 2) == 2.0


def test_6x_for_six_hours_spends_five_percent():
    assert round(6 * 6 / (30 * 24) * 100, 2) == 5.0


def test_alerts_carry_severity_and_annotations(alerts):
    for a in alerts:
        assert a["labels"]["severity"] in {"page", "ticket"}
        assert a["annotations"]["summary"] and a["annotations"]["description"]


def test_every_alert_reads_a_series_that_is_recorded(alerts, records):
    recorded = {r["record"] for r in records}
    for a in alerts:
        for name in re.findall(r"trace_lab:\w+:rate\w+", a["expr"]):
            assert name in recorded, (a["alert"], name)


def test_alert_names_are_unique(alerts):
    names = [a["alert"] for a in alerts]
    assert len(names) == len(set(names))

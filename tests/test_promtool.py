"""Run the real promtool when it is installed, skip when it is not.

go install github.com/prometheus/prometheus/cmd/promtool@v0.316.0
PROMTOOL=$(go env GOPATH)/bin/promtool uv run pytest tests/test_promtool.py
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROMTOOL = os.environ.get("PROMTOOL") or shutil.which("promtool")

needs_promtool = pytest.mark.skipif(not PROMTOOL, reason="promtool is not installed")


def run(*args):
    return subprocess.run([PROMTOOL, *args], cwd=ROOT, capture_output=True, text=True)


@needs_promtool
def test_promtool_accepts_the_rules():
    r = run("check", "rules", "rules/slo.rules.yml")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "20 rules found" in r.stdout


@needs_promtool
def test_promtool_accepts_the_prometheus_config():
    r = run("check", "config", "prometheus/prometheus.yml")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SUCCESS" in r.stdout


@needs_promtool
def test_rule_unit_tests_pass():
    r = run("test", "rules", "rules-tests/slo_test.yml")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SUCCESS" in r.stdout


def test_rule_unit_test_file_covers_both_slos():
    text = (ROOT / "rules-tests" / "slo_test.yml").read_text()
    assert "TraceLabAvailabilityBurnFast" in text
    assert "TraceLabLatencyBurnFast" in text
    assert "exp_alerts: []" in text

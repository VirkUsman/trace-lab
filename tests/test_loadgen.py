import re

from trace_lab.loadgen import plan


def test_plan_is_deterministic_for_a_seed():
    assert plan(50, seed=3) == plan(50, seed=3)


def test_plan_differs_between_seeds():
    assert plan(50, seed=3) != plan(50, seed=4)


def test_plan_length():
    assert len(plan(123)) == 123


def test_plan_has_no_unfilled_placeholders():
    assert not any("{" in p for p in plan(200))


def test_most_requests_are_orders():
    paths = plan(1000)
    orders = [p for p in paths if re.fullmatch(r"/orders/\d+", p)]
    assert 700 < len(orders) < 900

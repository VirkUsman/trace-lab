"""Send a mixed workload to a running service so the dashboard has something to show.

python -m trace_lab.loadgen http://127.0.0.1:8000 500
"""

import random
import sys
import time

import httpx

# (path template, weight). About 3 % of requests fail with a 500 and 5 % are slow.
MIX = [
    ("/orders/{n}", 80),
    ("/slow?ms=450", 5),
    ("/boom", 3),
    ("/slow?ms=0", 12),
]


def plan(count: int, seed: int = 1) -> list[str]:
    rng = random.Random(seed)
    paths = [p for p, _ in MIX]
    weights = [w for _, w in MIX]
    out = []
    for _ in range(count):
        path = rng.choices(paths, weights)[0]
        out.append(path.format(n=rng.randrange(1000)) if "{n}" in path else path)
    return out


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    with httpx.Client(base_url=base) as c:
        for path in plan(count):
            c.get(path)
            time.sleep(0.02)


if __name__ == "__main__":
    main()

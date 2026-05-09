"""
EZChess search engine benchmark.

Fixed-depth mode (default):
  .venv\\Scripts\\python.exe benchmark.py [label]
  depth=5, no time limit, 5 random boards — measures raw search time.

Time-limited mode:
  .venv\\Scripts\\python.exe benchmark.py [label] --time=N
  depth=50, N-second limit per position — measures max ID depth reached.
  Use --time=3 for a ~30s total run (5 boards × 3s × 2 versions).
"""
import sys
import os
import time
import statistics
import random
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.board import Board
from src.app import choose_minimax_move
import src.app as _app

RUNS = 5
SEED = 42

label = "baseline"
use_parallel = False
time_limit = None
depth = 5

idx = 1
while idx < len(sys.argv):
    arg = sys.argv[idx]
    if arg == '--parallel':
        use_parallel = True
    elif arg.startswith('--time='):
        time_limit = float(arg[7:])
        depth = 50
    elif arg == '--time' and idx + 1 < len(sys.argv):
        time_limit = float(sys.argv[idx + 1])
        depth = 50
        idx += 1
    else:
        label = arg
    idx += 1

random.seed(SEED)
boards = [Board.random_legal_board() for _ in range(RUNS)]

if __name__ == '__main__':
    multiprocessing.freeze_support()
    mode = "parallel" if use_parallel else "sequential"
    limit_str = f"{time_limit}s/pos" if time_limit else f"depth={depth} no-limit"
    print(f"\n=== {label} | {limit_str} | runs={RUNS} | {mode} ===")

    times = []
    depths = []
    for i, board in enumerate(boards):
        random.seed(SEED + i)
        t0 = time.perf_counter()
        move = choose_minimax_move(board, 'AB', depth=depth, time_limit=time_limit,
                                   use_nmp=False, use_parallel=use_parallel)
        elapsed = time.perf_counter() - t0
        d = getattr(_app, '_last_depth_reached', 0)
        times.append(elapsed)
        depths.append(d)
        depth_str = f"  depth_reached={d}" if time_limit else ""
        print(f"  [{i+1}] {elapsed:.3f}s{depth_str}  move={move}")

    print(f"\n  Mean time:   {statistics.mean(times):.3f}s")
    print(f"  Median time: {statistics.median(times):.3f}s")
    if len(times) > 1:
        print(f"  StdDev time: {statistics.stdev(times):.3f}s")
    if time_limit and depths:
        print(f"  Mean depth:  {statistics.mean(depths):.1f}")
        print(f"  Min/Max dep: {min(depths)} / {max(depths)}")
    print()

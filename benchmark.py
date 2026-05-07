"""
EZChess search engine benchmark.
Usage: .venv\\Scripts\\python.exe benchmark.py [label] [--parallel]
Runs choose_minimax_move at fixed depth=5, no time limit, 5 random boards.
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

DEPTH = 5
RUNS = 5
SEED = 42

label = "baseline"
use_parallel = False
for arg in sys.argv[1:]:
    if arg == '--parallel':
        use_parallel = True
    else:
        label = arg

random.seed(SEED)
boards = [Board.random_legal_board() for _ in range(RUNS)]

if __name__ == '__main__':
    multiprocessing.freeze_support()
    mode = "parallel" if use_parallel else "sequential"
    print(f"\n=== {label} | depth={DEPTH} | runs={RUNS} | {mode} ===")
    times = []
    for i, board in enumerate(boards):
        random.seed(SEED + i)
        t0 = time.perf_counter()
        move = choose_minimax_move(board, 'AB', depth=DEPTH, time_limit=None,
                                   use_nmp=False, use_parallel=use_parallel)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  [{i+1}] {elapsed:.3f}s  move={move}")

    print(f"\n  Mean:   {statistics.mean(times):.3f}s")
    print(f"  Median: {statistics.median(times):.3f}s")
    if len(times) > 1:
        print(f"  StdDev: {statistics.stdev(times):.3f}s")
    print()

# Artificial Intelligence Project 2026 — EZChess

A web-based board game program for a 2-player 8x8 strategy game.
See [RULE.md](RULE.md) for full game rules.

## Setup

**Requirements:** Python 3.10+, Git

```bash
# Clone and enter project
git clone <repo-url>
cd Artificial_Intelligence_Project_2026

# Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the web server
python run.py
```

Then open `http://localhost:5000` in your browser.

## Tech Stack

- **Backend:** Python 3 + Flask
- **Frontend:** HTML / CSS / JavaScript (browser-based board)
- **Input:** Mouse click on board
- **Coordinate format:** `(row, col)` 0-indexed, e.g. `B:(3,5)-(2,4)`

## Development Guidelines

- **Imports inside `src/`:** always use relative imports (e.g. `from .board import Board`), never `from src.board import Board`
- **Test files:** all tests go in `tests/`, never in the project root
- **Run tests (Windows):** `.venv\Scripts\python.exe -m pytest tests/ -v`
- **Run tests (macOS/Linux):** `.venv/bin/python -m pytest tests/ -v`

## AI Search Engine

### Search stack

| Layer | Technique | Effect | Default |
|---|---|---|---|
| L4 | Alpha-Beta pruning | ~2× deeper vs plain Minimax | always on |
| L5 | Iterative Deepening (ID) | Fills full time budget; returns best depth reached so far | always on |
| L6 | Move ordering | Tries captures and TT-best moves first; maximises cut rate | always on |
| L6 | Transposition Table (TT) | Caches evaluated positions with EXACT / LOWERBOUND / UPPERBOUND flags | always on |
| L6 | History Heuristic | Tracks which quiet moves caused beta-cutoffs; improves ordering | always on |
| L6 | Quiescence Search | Extends search at leaf nodes until no captures remain; avoids horizon effect | always on |
| L7 | Null Move Pruning (NMP) | Skips own turn at MAX nodes; if opponent still can't beat beta, prune the branch | on, R=2 |
| L7 | Late Move Reductions (LMR) | Searches quiet late moves at reduced depth first; re-searches only if promising | on, min-d=3, start=3 |
| L7 | Root Parallelization | Each root move evaluated by a separate worker with its own ID loop and TT | off by default |

**NMP guard:** only applied when own piece count > 2 (prevents Zugzwang misjudgement in endgame).  
**LMR re-search rule:** if reduced-depth value > alpha, re-search at full depth before updating best.  
**ID depth cap:** `depth=50` when time limit > 0 (fills budget); `depth=5` when no time limit.  
**Default time limit:** 60 s (main game and AI Battle).

### Evaluation function

Called at every leaf node. Components (in order of weight):

1. **Material** — weighted piece count: A/U=10, B/V=8, c/d/w/x=4, e/f/y/z=3 *(AI heuristic only; official scoring uses A/B/U/V=3, others=1)*
2. **Mobility** — number of legal moves available (encourages active pieces)
3. **Centre control** — bonus for pieces on the four central squares
4. **Threat penalty** — penalty for own pieces currently under attack

### Benchmark (depth=5, 5 random boards, no time limit)

| Config | Mean time | vs baseline |
|---|---|---|
| Baseline (no optimizations) | 12.6 s | — |
| + merge eval pass + board_key | 11.1 s | −12% |
| + LMR | 5.0 s | −60% |
| + Root parallelization | 1.0 s | −92% (12.8×) |

### AI Battle — batch testing UI

Run up to 200 automated games between two AI configurations and stream results in real time.

**Per-team controls:**

| Control | Description |
|---|---|
| Strategy | Random / Greedy / Minimax |
| d= | Max search depth (1–50). Ignored when time limit > 0; ID fills the budget automatically. |
| NMP ✓, R= | Enable Null Move Pruning; R=1 conservative → R=4 aggressive |
| LMR ✓, min-d=, start= | Enable Late Move Reductions; min-d = minimum depth to apply; start = first move index to reduce (0-based) |
| 平行 ✓ | Enable move-level root parallelisation for this team |

**Shared controls:**

| Control | Description |
|---|---|
| 先手 | Which team moves first: 隨機 (random) eliminates first-mover bias |
| 場次 | Number of games (1–200); 30+ recommended for statistical significance |
| 時限(s) | Per-move think time. 0 = no limit (use with fixed depth) |
| 多局並行 | Run N games simultaneously (1 = off, 2–8 = on). Disables move-level parallel automatically. |

**Parallelism modes (mutually exclusive):**

| Mode | When to use |
|---|---|
| Move-level parallel (平行 ✓) | Competition candidate; covers more root moves per move decision |
| Game-level parallel (多局並行 ≥ 2) | Batch testing only; ~2–4× faster; move-level parallel is forced off inside each worker |

### Benchmark script

```bash
# Sequential (default)
python benchmark.py sequential

# Move-level parallel
python benchmark.py parallel --parallel
```

## Development Batches

### Batch 1 — Environment Setup
- [x] Virtual environment (`venv`), `.gitignore`, `requirements.txt`
- [x] Project folder structure (`src/`, `static/`, `templates/`)

### Batch 2 — Board & Movement Core
- [x] 8x8 board data structure and piece placement
- [x] Move generation per piece type:
  - A, U — orthogonal (4 directions), 1–2 squares
  - B, V — diagonal (4 directions), 1–2 squares
  - c, d, w, x — orthogonal, 1 square
  - e, f, y, z — diagonal, 1 square
- [x] Path clearance check (no jumping over pieces)
- [x] Boundary check
- [x] Capture logic (land on opponent's square)

### Batch 3 — Game Flow
- [x] Game state: whose turn, round counter (max 20 rounds)
- [x] Turn alternation (AB first, UV second)
- [x] **Per-move response time + cumulative total time display** *(required for 4/28 demo)*
- [x] Move notation output (e.g. `B:(3,5)-(2,4)`)
- [x] Initial board input (manual entry via New Game modal)

### Batch 4 — Web Interface
- [x] Flask server with board state API
- [x] Board rendering with piece letters and bordered boxes
- [x] Click to select piece → highlight valid destination squares
- [x] Timer display (per-move elapsed + running total)
- [x] Move history log panel

### Batch 5A — AI Core (Minimax + Alpha-Beta)

Layered implementation — each level is independently deployable and stronger than the previous.

- [x] **L1** Random legal move (demo baseline)
- [x] **L2** Greedy — prioritise highest-value capture; else random
- [x] **L3** Minimax search, depth 2–3
- [x] **L4** Alpha-Beta pruning (same strength as L3, searches ~2× deeper in same time)
- [x] **L5** Iterative Deepening — fills the full 60 s budget, returns best move found so far
- [x] **L6** Move ordering + Transposition table (dramatically improves Alpha-Beta efficiency)
- [x] **L7** Evaluation function: piece-square tables, mobility, threat assessment, NMP, LMR

> **Evaluation function components (L3+):** material value (A/B/U/V=3, others=1),
> number of legal moves available, control of centre squares, pieces under attack.

### Batch 5B — AI Benchmarking (prerequisite for both 5A tuning and 5C)

- [x] AI vs AI battle mode: two AI agents play a full game automatically
- [x] Batch simulation: run N games (up to 200), streaming per-game results in real-time
- [x] Strategy comparison: select Random / Greedy / Minimax(depth) independently for AB and UV
- [x] Configurable NMP (per team, R value), LMR (per team, min-depth, start-index), parallel mode
- [x] First-team selection (random / AB / UV) to eliminate first-mover bias in testing
- [ ] Intra-team testing: play human or earlier AI version against current build to measure improvement

> Run this after each L3+ upgrade. Win rate vs the previous version is the only reliable
> strength signal — human intuition cannot substitute for actual game results.

### Batch 5C — Neural Network Path (experimental, parallel to 5A)

Requires 5B (self-play data generation) to be complete first.

- [ ] Self-play data collection via AI vs AI (board state → move → outcome)
- [ ] Simple policy network: input board tensor → output move probability distribution
- [ ] Simple value network: input board tensor → output win probability estimate
- [ ] MCTS guided by policy + value networks (AlphaZero-style)
- [ ] Compare 5C vs best 5A version via Batch 5B benchmark

> 5C is the stronger long-term ceiling but carries implementation risk.
> Ship 5A first; start 5C only after 5A reaches L5 and benchmarking is in place.

### Batch 6 — Wrap-up & Testing
- [ ] Game-end detection (20 rounds completed or disqualification triggered)
- [ ] Score calculation display (A/B/U/V = 3 pts, others = 1 pt)
- [ ] End-to-end full game test
- [ ] Extension time management (3 extensions per game, 60 s → 120 s)

## Competition Schedule

| Date | Event |
|------|-------|
| 2026-04-28 | 期中 Demo（助教驗收，每隊必到） ✅ |
| 2026-05-19 | 預賽截止（各組自行完成） |
| 2026-06-02 | 複賽 + 作業報告上傳截止（Word，含隊員貢獻度） |
| 2026-06-09 | 決賽 |

## 4/28 Demo Checklist

The TA will verify the following — UI and AI quality are not graded at this stage:

- [x] Game is playable including turn order
- [x] Program responds within the time limit
- [x] **Per-move response time is displayed**
- [x] **Cumulative response time is displayed**

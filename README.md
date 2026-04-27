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
- **Run tests:** `.venv\Scripts\pytest tests/ -v` from project root

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

- [X] **L1** Random legal move (demo baseline)
- [X] **L2** Greedy — prioritise highest-value capture; else random
- [X] **L3** Minimax search, depth 2–3
- [ ] **L4** Alpha-Beta pruning (same strength as L3, searches ~2× deeper in same time)
- [ ] **L5** Iterative Deepening — fills the full 60 s budget, returns best move found so far
- [ ] **L6** Move ordering + Transposition table (dramatically improves Alpha-Beta efficiency)
- [ ] **L7** Evaluation function tuning: piece-square tables, mobility score, threat assessment

> **Evaluation function components (L3+):** material value (A/B/U/V=3, others=1),
> number of legal moves available, control of centre squares, pieces under attack.

### Batch 5B — AI Benchmarking (prerequisite for both 5A tuning and 5C)

- [ ] AI vs AI battle mode: two AI agents play a full game automatically
- [ ] Batch simulation: run N games between two AI versions, report win rate and avg score
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
| 2026-04-28 | 期中 Demo（助教驗收，每隊必到） |
| 2026-05-19 | 預賽截止（各組自行完成） |
| 2026-06-02 | 複賽 + 作業報告上傳截止（Word，含隊員貢獻度） |
| 2026-06-09 | 決賽 |

## 4/28 Demo Checklist

The TA will verify the following — UI and AI quality are not graded at this stage:

- [ ] Game is playable including turn order
- [ ] Program responds within the time limit
- [ ] **Per-move response time is displayed**
- [ ] **Cumulative response time is displayed**

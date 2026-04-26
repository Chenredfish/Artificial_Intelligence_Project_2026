Batch 2 — Board & Movement Core ✅

Implemented in:

src/board.py

This module provides the complete board representation and legal move generation logic.

1. Board Data Structure

Implemented an 8×8 board using a 2D list:

self._grid = [[None] * 8 for _ in range(8)]

Supports:

piece placement
move execution
capture logic
board copy
2. Piece Classification

Pieces are separated into two teams:

Team	Pieces
AB	A B c d e f
UV	U V w x y z

Implemented helper function:

get_team(piece)

Returns:

AB / UV / None
3. Movement Rules per Piece Type

Movement rules implemented according to specification:

Piece	Movement
A / U	orthogonal, 1–2 squares
B / V	diagonal, 1–2 squares
c d w x	orthogonal, 1 square
e f y z	diagonal, 1 square

Defined using:

_PIECE_RULES
4. Boundary Checking

All generated moves ensure:

0 ≤ row < 8
0 ≤ col < 8

Out-of-board moves are automatically discarded.

5. Path Clearance Checking

Pieces cannot jump over other pieces.

Implemented inside:

legal_moves()

Logic:

stop if own piece encountered
capture if enemy encountered
terminate search after capture
6. Capture Logic

Enemy pieces can be captured if located at destination square:

elif get_team(target) != team:

Capture stops further movement along that direction.

7. Legal Move Generation

Implemented:

Single piece move generation
legal_moves(row, col)

Returns:

[(row, col), ...]
Team move generation
all_legal_moves(team)

Returns:

[((from_row, from_col), (to_row, to_col)), ...]
8. Move Execution

Implemented:

apply_move(from_pos, to_pos)

Performs:

piece movement
capture handling
returns captured piece
9. Move Notation Format

Supported notation:

B:(3,5)-(2,4)

Implemented:

format_move()
parse_move()
10. Board Validation System

Enhanced:

Board.from_grid()

Now validates:

Board size check
must be 8 × 8
Legal piece check

Allowed:

A B c d e f U V w x y z

Invalid symbols raise:

ValueError
11. Board Display Output

Implemented ASCII display:

+ + + + + + + +

Using:

display()

Supports debugging and console testing.

12. JSON-Compatible Board Export

Implemented:

to_dict()

Used for:

Flask API
frontend rendering
debugging output
13. Unit Testing (pytest)

Created:

test_board.py

Test coverage includes:

Feature	Verified
orthogonal movement	✅
diagonal movement	✅
1-step movement	✅
2-step movement	✅
boundary limits	✅
capture rules	✅
path blocking	✅
invalid board size	✅
invalid piece symbol	✅

Result:

10 passed
Batch 3 — Game Flow ✅

Implemented in:

src/game.py

Handles turn order, timing system, and match progression.

1. Turn Management System

Game starts with:

AB first
UV second

Turn alternation logic:

AB → UV → AB → UV

Implemented using:

switch_turn()
2. Round Counter System

Each full cycle:

AB + UV = 1 round

Maximum:

20 rounds

Implemented:

round_counter
max_rounds

Game ends automatically after limit reached.

3. Per-Move Response Time Tracking

Each move records elapsed thinking time:

get_elapsed_time()

Stored as:

move_time

Required for TA Demo validation ✅

4. Cumulative Time Tracking

Total time recorded separately for each team:

self.total_time = {
    "AB": 0.0,
    "UV": 0.0
}

Updated after every move.

Required for TA Demo validation ✅

5. Move History Recording

Each move stored as:

{
    team,
    round,
    move,
    move_time,
    total_time,
    captured
}

Example:

A:(3,3)-(3,4)

Supports:

replay system
UI history panel
debugging
competition logging
6. Illegal Move Detection

Implemented validation before execution:

is_legal_move()

Raises:

ValueError

if move invalid.

7. Game State Export API

Implemented:

get_state()

Returns:

board
current_team
round
elapsed_time
total_time
move_history
game_over

Designed for frontend integration (Flask API).

8. Game Over Detection

Game ends when:

round_counter > 20

Implemented:

is_game_over()
9. Unit Testing (pytest)

Created:

test_game.py

Test coverage includes:

Feature	Verified
AB first turn	✅
turn alternation	✅
round increment logic	✅
illegal move rejection	✅
move history recording	✅
time tracking structure	✅

All tests passed successfully.

---

Code Review & Fixes (2026-04-26)

After code review, 5 issues were identified and corrected.

Fix 1 — Relative import in src/game.py

Problem:
game.py used an absolute import: from src.board import Board
This requires the project root to always be in sys.path, and breaks if game.py is run standalone or the package structure changes.

Fix:
Changed to relative import: from .board import Board
Files changed: src/game.py line 3

Fix 2 — make_move returned next round instead of current round

Problem:
make_move() called switch_turn() before building its return dict.
switch_turn() increments round_counter when UV finishes a turn.
Result: the returned "round" value reflected the NEXT round, not the round the move was played in. move_history was unaffected (it saved round before switch), but the API return value was wrong.

Fix:
Saved current_round = self.round_counter before calling switch_turn(), then used current_round in the return dict.
Files changed: src/game.py make_move()

Fix 3 — Timer auto-started on switch_turn(), including at Game creation

Problem:
switch_turn() automatically called start_turn_timer(), and __init__ also started the timer immediately. This caused setup time and human input delay to count as AI thinking time. The intended design is that the timer starts only when the AI begins computing (user presses the infer/think button).

Fix:
- Initialized turn_start_time = None in __init__ (not started)
- switch_turn() now resets turn_start_time = None instead of calling start_turn_timer()
- get_elapsed_time() returns 0.0 when turn_start_time is None
- start_turn_timer() must now be called explicitly by the frontend when the user triggers AI inference
Files changed: src/game.py __init__, switch_turn(), get_elapsed_time()

Fix 4 — Test files in project root instead of tests/ directory

Problem:
test_board.py and test_game.py were placed in the project root, inconsistent with the README-specified tests/ directory. Deviations between documented structure and actual structure increase maintenance overhead and confuse new contributors.

Fix:
- Moved both files to tests/test_board.py and tests/test_game.py
- Deleted root-level test files
- Added conftest.py at project root to ensure pytest adds root to sys.path
Files changed: tests/test_board.py, tests/test_game.py, conftest.py (new), root test files deleted

Fix 5 — test_total_time_exists did not verify time accumulation

Problem:
The test only checked that "AB" and "UV" keys exist in game.total_time, which is trivially true from __init__ alone. The actual accumulation logic in make_move() was never exercised. The test would pass even if the accumulation line were deleted.

Fix:
Replaced with two meaningful tests:
- test_total_time_accumulates_on_move: calls start_turn_timer(), makes a move, verifies move_time >= 0, total_time["AB"] == move_time, total_time["UV"] == 0
- test_timer_not_started_returns_zero: verifies get_elapsed_time() returns 0.0 when start_turn_timer() has not been called
Files changed: tests/test_game.py

Result: 18 tests, 18 passed.
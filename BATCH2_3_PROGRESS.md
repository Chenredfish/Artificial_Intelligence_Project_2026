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
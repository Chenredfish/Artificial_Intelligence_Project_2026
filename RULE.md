# Game Rules

## Board & Pieces

8x8 board. Each side has 6 pieces.

**Team AB:** A B c d e f
**Team UV:** U V w x y z

### Movement

| Piece | Move Type | Range |
|-------|-----------|-------|
| A, U  | Orthogonal (4 directions) | 1–2 squares |
| B, V  | Diagonal (4 directions) | 1–2 squares |
| c, d, w, x | Orthogonal | 1 square |
| e, f, y, z | Diagonal | 1 square |

- A square can hold only one piece at a time.
- Moving onto an opponent's piece captures it.
- Pieces cannot jump over others (path must be clear).

## Game Flow

**Setup:** Initial board layout is drawn by lot, then modified per Rule (1) below. Both sides input the board state via keyboard / mouse / text file.

**Turn Order:** AB moves first, then UV alternates. Each turn, one piece must be moved.

**Input/Output:**
1. After inputting the initial board state, it counts as the first input — the program must compute and output a response immediately.
2. Each subsequent turn: input the opponent's last move, then output your response move and elapsed time.
3. Response must include:
   - Coordinate notation (e.g. `B:(3,5)-(2,4)`)
   - Board state diagram (text or graphical)

**Time Limit:** Response must be output within **60 seconds** per turn. Each game allows **3 extensions**, each extending that turn's limit to **120 seconds**.

---

## Supplementary Rules

### (1) Pre-game Setup
1. Referee reveals the board. Both sides rock-paper-scissors; winner chooses to be AB (first) or UV.
2. UV side may relocate any one piece (friend or foe) to any empty square.
3. Step 1 must be decided within 120 seconds; step 2 within the following 120 seconds.

### (2) Scoring (normal game completion)
1. Each game lasts at most **20 rounds (40 moves total)**; capture scores and elapsed time are recorded at the end.
2. Capture points: **A, B, U, V = 3 pts**; **c, d, e, f, w, x, y, z = 1 pt**. Higher total wins.
3. Tie in capture points → shorter total elapsed time wins. In multi-team ties, lowest average elapsed time advances.

### (3) Disqualification
A side that commits any of the following **forfeits the game** (that game's capture scores and elapsed time are voided):
1. Exceeds 60-second time limit for the **4th time**.
2. Exceeds **120 seconds** on any single turn.
3. Inputs the opponent's move incorrectly, disrupting normal play.
4. Outputs an **illegal move**, preventing the game from continuing.

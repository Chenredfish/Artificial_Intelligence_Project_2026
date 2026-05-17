import re
import random
import numpy as np

AB_PIECES = frozenset('ABcdef')
UV_PIECES = frozenset('UVwxyz')

PIECE_POINTS = {p: (3 if p in 'ABUV' else 1) for p in 'ABcdefUVwxyz'}

_ORTHOGONAL = ((0, 1), (0, -1), (1, 0), (-1, 0))
_DIAGONAL   = ((1, 1), (1, -1), (-1, 1), (-1, -1))

_PIECE_RULES = {
    'A': (_ORTHOGONAL, 2), 'U': (_ORTHOGONAL, 2),
    'B': (_DIAGONAL,   2), 'V': (_DIAGONAL,   2),
    'c': (_ORTHOGONAL, 1), 'd': (_ORTHOGONAL, 1),
    'w': (_ORTHOGONAL, 1), 'x': (_ORTHOGONAL, 1),
    'e': (_DIAGONAL,   1), 'f': (_DIAGONAL,   1),
    'y': (_DIAGONAL,   1), 'z': (_DIAGONAL,   1),
}

PIECE_TO_INT = {
    'A': 1,  'B': 2,  'c': 3,  'd': 4,  'e': 5,  'f': 6,
    'U': 7,  'V': 8,  'w': 9,  'x': 10, 'y': 11, 'z': 12,
}
INT_TO_PIECE = {v: k for k, v in PIECE_TO_INT.items()}
# INT_TO_PIECE[0] is not defined; 0 means empty


def get_team(piece):
    if piece in AB_PIECES:
        return 'AB'
    if piece in UV_PIECES:
        return 'UV'
    return None


class Board:
    def __init__(self):
        self._grid = np.zeros((8, 8), dtype=np.int8)

    # ── construction ───────────────────────────────────────────────────────

    @classmethod
    def from_grid(cls, grid):
        """Build from 8x8 list; use '.', '+', or None for empty squares."""
        if len(grid) != 8:
            raise ValueError("Board must have exactly 8 rows")

        for row in grid:
            if len(row) != 8:
                raise ValueError("Each row must have exactly 8 columns")

        board = cls()

        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                if cell in (None, '.', '+'):
                    board._grid[r, c] = 0
                elif cell in PIECE_TO_INT:
                    board._grid[r, c] = PIECE_TO_INT[cell]
                else:
                    raise ValueError(f"Invalid piece at ({r},{c}): {cell}")

        return board

    @classmethod
    def random_legal_board(cls, max_attempts=2000):
        pieces = list('ABcdef') + list('UVwxyz')
        all_positions = [(r, c) for r in range(8) for c in range(8)]

        for _ in range(max_attempts):
            board = cls()
            chosen_positions = random.sample(all_positions, len(pieces))
            for piece, pos in zip(pieces, chosen_positions):
                board.set(pos[0], pos[1], piece)

            if board.all_legal_moves('AB') and board.all_legal_moves('UV'):
                return board

        raise RuntimeError('Unable to generate a legal random board after many attempts')

    def copy(self):
        new = Board()
        new._grid = self._grid.copy()   # np.copy — faster than list deepcopy
        return new

    # ── accessors ──────────────────────────────────────────────────────────

    def get(self, row, col):
        v = int(self._grid[row, col])
        return INT_TO_PIECE[v] if v != 0 else None

    def set(self, row, col, piece):
        self._grid[row, col] = PIECE_TO_INT[piece] if piece is not None else 0

    def pieces(self, team):
        """Yield (row, col, piece) for every piece belonging to team."""
        lo, hi = (1, 6) if team == 'AB' else (7, 12)
        rs, cs = np.where((self._grid >= lo) & (self._grid <= hi))
        for r, c in zip(rs.tolist(), cs.tolist()):
            yield r, c, INT_TO_PIECE[int(self._grid[r, c])]

    # ── move generation ────────────────────────────────────────────────────

    def legal_moves(self, row, col):
        """Return list of (row, col) destinations for the piece at (row, col)."""
        piece_int = int(self._grid[row, col])
        if piece_int == 0:
            return []
        piece = INT_TO_PIECE[piece_int]
        team_lo, team_hi = (1, 6) if piece_int <= 6 else (7, 12)
        directions, max_steps = _PIECE_RULES[piece]
        moves = []
        for dr, dc in directions:
            for step in range(1, max_steps + 1):
                r, c = row + dr * step, col + dc * step
                if not (0 <= r < 8 and 0 <= c < 8):
                    break
                target = int(self._grid[r, c])
                if target == 0:
                    moves.append((r, c))
                elif not (team_lo <= target <= team_hi):
                    moves.append((r, c))   # capture — stop after
                    break
                else:
                    break                  # blocked by own piece
        return moves

    def all_legal_moves(self, team):
        """Return list of ((from_row, from_col), (to_row, to_col)) for team."""
        moves = []
        for r, c, _ in self.pieces(team):
            for dest in self.legal_moves(r, c):
                moves.append(((r, c), dest))
        return moves

    # ── mutation ───────────────────────────────────────────────────────────

    def apply_move(self, from_pos, to_pos):
        """Execute move; return captured piece or None."""
        r1, c1 = from_pos
        r2, c2 = to_pos
        piece_int    = int(self._grid[r1, c1])
        captured_int = int(self._grid[r2, c2])
        self._grid[r2, c2] = piece_int
        self._grid[r1, c1] = 0
        return INT_TO_PIECE[captured_int] if captured_int != 0 else None

    def is_legal_move(self, from_pos, to_pos, team):
        """Return True if from_pos belongs to team and to_pos is a legal destination."""
        r1, c1 = from_pos
        piece_int = int(self._grid[r1, c1])
        if piece_int == 0:
            return False
        piece = INT_TO_PIECE[piece_int]
        if get_team(piece) != team:
            return False
        return to_pos in self.legal_moves(r1, c1)

    # ── notation ──────────────────────────────────────────────────────────

    @staticmethod
    def format_move(piece, from_pos, to_pos):
        """Format as e.g. 'B:(3,5)-(2,4)'."""
        return f"{piece}:({from_pos[0]},{from_pos[1]})-({to_pos[0]},{to_pos[1]})"

    @staticmethod
    def parse_move(notation):
        """Parse 'B:(3,5)-(2,4)' → (piece, (3, 5), (2, 4)).  Raises ValueError on bad input."""
        m = re.fullmatch(r'([A-Za-z]):\((\d),(\d)\)-\((\d),(\d)\)', notation.strip())
        if not m:
            raise ValueError(f"Invalid move notation: {notation!r}")
        return (
            m.group(1),
            (int(m.group(2)), int(m.group(3))),
            (int(m.group(4)), int(m.group(5))),
        )

    # ── display ───────────────────────────────────────────────────────────

    def display(self):
        """Return ASCII board string matching the PDF layout ('+' for empty)."""
        lines = ["   " + " ".join(str(c) for c in range(8))]
        for r in range(8):
            cells = " ".join(
                INT_TO_PIECE[int(self._grid[r, c])] if self._grid[r, c] != 0 else "+"
                for c in range(8)
            )
            lines.append(f"{r}  {cells}")
        return "\n".join(lines)

    def to_dict(self):
        """JSON-serialisable 8×8 list; empty squares → '.'."""
        return [
            [INT_TO_PIECE[int(self._grid[r, c])] if self._grid[r, c] != 0 else "."
             for c in range(8)]
            for r in range(8)
        ]

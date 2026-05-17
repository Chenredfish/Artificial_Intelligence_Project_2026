import re
import random

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


def get_team(piece):
    if piece in AB_PIECES:
        return 'AB'
    if piece in UV_PIECES:
        return 'UV'
    return None


class Board:
    def __init__(self):
        self._grid = [[None] * 8 for _ in range(8)]
        self._ab_pieces = []   # [(r, c, piece), ...]  O(1) pieces() lookup
        self._uv_pieces = []

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
                    board._grid[r][c] = None
                elif cell in PIECE_POINTS:
                    board._grid[r][c] = cell
                    if cell in AB_PIECES:
                        board._ab_pieces.append((r, c, cell))
                    else:
                        board._uv_pieces.append((r, c, cell))
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
        new._grid = [row[:] for row in self._grid]
        new._ab_pieces = self._ab_pieces.copy()
        new._uv_pieces = self._uv_pieces.copy()
        return new

    def _rebuild_piece_lists(self):
        """Rebuild _ab_pieces/_uv_pieces from _grid (used after raw grid assignment)."""
        self._ab_pieces = []
        self._uv_pieces = []
        for r in range(8):
            for c in range(8):
                p = self._grid[r][c]
                if p:
                    if p in AB_PIECES:
                        self._ab_pieces.append((r, c, p))
                    else:
                        self._uv_pieces.append((r, c, p))

    # ── accessors ──────────────────────────────────────────────────────────

    def get(self, row, col):
        return self._grid[row][col]

    def set(self, row, col, piece):
        old = self._grid[row][col]
        if old is not None:
            lst = self._ab_pieces if old in AB_PIECES else self._uv_pieces
            lst.remove((row, col, old))
        self._grid[row][col] = piece
        if piece is not None:
            lst = self._ab_pieces if piece in AB_PIECES else self._uv_pieces
            lst.append((row, col, piece))

    def pieces(self, team):
        """Yield (row, col, piece) for every piece belonging to team — O(n_pieces)."""
        yield from (self._ab_pieces if team == 'AB' else self._uv_pieces)

    # ── move generation ────────────────────────────────────────────────────

    def legal_moves(self, row, col):
        """Return list of (row, col) destinations for the piece at (row, col)."""
        piece = self._grid[row][col]
        if piece is None:
            return []
        directions, max_steps = _PIECE_RULES[piece]
        team = get_team(piece)
        moves = []
        for dr, dc in directions:
            for step in range(1, max_steps + 1):
                r, c = row + dr * step, col + dc * step
                if not (0 <= r < 8 and 0 <= c < 8):
                    break
                target = self._grid[r][c]
                if target is None:
                    moves.append((r, c))
                elif get_team(target) != team:
                    moves.append((r, c))  # capture — stop after
                    break
                else:
                    break                 # blocked by own piece
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
        """Execute move; return captured piece or None. Updates piece lists."""
        r1, c1 = from_pos
        r2, c2 = to_pos
        piece    = self._grid[r1][c1]
        captured = self._grid[r2][c2]

        mover_list = self._ab_pieces if piece in AB_PIECES else self._uv_pieces
        mover_list.remove((r1, c1, piece))
        mover_list.append((r2, c2, piece))

        if captured is not None:
            cap_list = self._ab_pieces if captured in AB_PIECES else self._uv_pieces
            cap_list.remove((r2, c2, captured))

        self._grid[r2][c2] = piece
        self._grid[r1][c1] = None
        return captured

    def is_legal_move(self, from_pos, to_pos, team):
        """Return True if from_pos belongs to team and to_pos is a legal destination."""
        r1, c1 = from_pos
        piece = self._grid[r1][c1]
        if piece is None or get_team(piece) != team:
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
            cells = " ".join(self._grid[r][c] or "+" for c in range(8))
            lines.append(f"{r}  {cells}")
        return "\n".join(lines)

    def to_dict(self):
        """JSON-serialisable 8×8 list; empty squares → '.'."""
        return [
            [self._grid[r][c] or "." for c in range(8)]
            for r in range(8)
        ]

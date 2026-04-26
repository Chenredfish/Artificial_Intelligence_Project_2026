from src.board import Board


def empty_board():
    return [["." for _ in range(8)] for _ in range(8)]


def test_A_orthogonal_1_to_2_steps():
    grid = empty_board()
    grid[3][3] = "A"
    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    expected = {
        (3, 4), (3, 5),
        (3, 2), (3, 1),
        (4, 3), (5, 3),
        (2, 3), (1, 3),
    }

    assert moves == expected


def test_B_diagonal_1_to_2_steps():
    grid = empty_board()
    grid[3][3] = "B"
    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    expected = {
        (4, 4), (5, 5),
        (4, 2), (5, 1),
        (2, 4), (1, 5),
        (2, 2), (1, 1),
    }

    assert moves == expected


def test_c_orthogonal_1_step_only():
    grid = empty_board()
    grid[3][3] = "c"
    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    expected = {
        (3, 4),
        (3, 2),
        (4, 3),
        (2, 3),
    }

    assert moves == expected


def test_e_diagonal_1_step_only():
    grid = empty_board()
    grid[3][3] = "e"
    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    expected = {
        (4, 4),
        (4, 2),
        (2, 4),
        (2, 2),
    }

    assert moves == expected


def test_piece_cannot_jump_over_piece():
    grid = empty_board()
    grid[3][3] = "A"
    grid[3][4] = "c"

    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    assert (3, 4) not in moves
    assert (3, 5) not in moves


def test_piece_can_capture_enemy_but_stop_after_capture():
    grid = empty_board()
    grid[3][3] = "A"
    grid[3][4] = "w"

    board = Board.from_grid(grid)

    moves = set(board.legal_moves(3, 3))

    assert (3, 4) in moves
    assert (3, 5) not in moves


def test_out_of_boundary():
    grid = empty_board()
    grid[0][0] = "A"

    board = Board.from_grid(grid)

    moves = set(board.legal_moves(0, 0))

    expected = {
        (0, 1), (0, 2),
        (1, 0), (2, 0),
    }

    assert moves == expected


def test_invalid_board_row_count():
    grid = [["." for _ in range(8)] for _ in range(7)]

    try:
        Board.from_grid(grid)
        assert False
    except ValueError:
        assert True


def test_invalid_board_column_count():
    grid = empty_board()
    grid[0].append(".")

    try:
        Board.from_grid(grid)
        assert False
    except ValueError:
        assert True


def test_invalid_piece():
    grid = empty_board()
    grid[3][3] = "Q"

    try:
        Board.from_grid(grid)
        assert False
    except ValueError:
        assert True

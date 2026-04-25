from src.board import Board
from src.game import Game


def empty_board():
    return [["." for _ in range(8)] for _ in range(8)]


def test_ab_goes_first():
    game = Game()

    assert game.get_current_team() == "AB"


def test_turn_alternates_after_move():
    grid = empty_board()
    grid[3][3] = "A"
    board = Board.from_grid(grid)

    game = Game(board)

    game.make_move((3, 3), (3, 4))

    assert game.get_current_team() == "UV"


def test_round_increases_after_uv_move():
    grid = empty_board()
    grid[3][3] = "A"
    grid[4][4] = "U"

    board = Board.from_grid(grid)
    game = Game(board)

    game.make_move((3, 3), (3, 4))
    game.make_move((4, 4), (4, 5))

    assert game.get_current_team() == "AB"
    assert game.get_round_counter() == 2


def test_illegal_move_rejected():
    grid = empty_board()
    grid[3][3] = "A"

    board = Board.from_grid(grid)
    game = Game(board)

    try:
        game.make_move((3, 3), (4, 4))
        assert False
    except ValueError:
        assert True


def test_move_history_recorded():
    grid = empty_board()
    grid[3][3] = "A"

    board = Board.from_grid(grid)
    game = Game(board)

    game.make_move((3, 3), (3, 4))

    assert len(game.move_history) == 1
    assert game.move_history[0]["move"] == "A:(3,3)-(3,4)"


def test_total_time_exists():
    game = Game()

    assert "AB" in game.total_time
    assert "UV" in game.total_time
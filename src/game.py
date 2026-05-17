import time

from .board import Board, PIECE_POINTS  # relative import — always use within src/


class Game:
    def __init__(self, board=None):
        self.board = board if board is not None else Board()
        self.current_team = "AB"
        self.round_counter = 1
        self.max_rounds = 20

        self.move_history = []

        self.capture_score = {"AB": 0, "UV": 0}

        self.total_time = {
            "AB": 0.0,
            "UV": 0.0,
        }

        self.turn_start_time = None  # not started; call start_turn_timer() explicitly

    def get_current_team(self):
        return self.current_team

    def get_round_counter(self):
        return self.round_counter

    def start_turn_timer(self):
        """Call this when the AI begins computing (e.g. user presses the infer button)."""
        self.turn_start_time = time.time()

    def get_elapsed_time(self):
        if self.turn_start_time is None:
            return 0.0
        return time.time() - self.turn_start_time

    def switch_turn(self):
        if self.current_team == "AB":
            self.current_team = "UV"
        else:
            self.current_team = "AB"

        self.turn_start_time = None  # reset; frontend must call start_turn_timer() again

    def make_move(self, from_pos, to_pos):
        if self.is_game_over():
            raise ValueError("Game is already over")

        if not self.board.is_legal_move(from_pos, to_pos, self.current_team):
            raise ValueError("Illegal move")

        # A new round begins when AB is about to move (except the very first move).
        # This keeps round_counter == X for the entire Xth AB+UV pair.
        if self.current_team == "AB" and len(self.move_history) > 0:
            self.round_counter += 1

        r1, c1 = from_pos
        piece = self.board.get(r1, c1)

        elapsed = self.get_elapsed_time()
        self.total_time[self.current_team] += elapsed

        captured = self.board.apply_move(from_pos, to_pos)
        notation = Board.format_move(piece, from_pos, to_pos)

        current_round = self.round_counter
        current_team  = self.current_team

        if captured:
            self.capture_score[current_team] += PIECE_POINTS.get(captured, 0)

        self.move_history.append({
            "team": current_team,
            "round": current_round,
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time[self.current_team],
            "captured": captured,
        })

        self.switch_turn()

        return {
            "team": current_team,
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time,
            "captured": captured,
            "next_team": self.current_team,
            "round": current_round,
        }

    def is_game_over(self):
        # 20 rounds = 40 individual moves (AB + UV each round)
        return len(self.move_history) >= self.max_rounds * 2

    def get_state(self):
        return {
            "board": self.board.to_dict(),
            "current_team": self.current_team,
            "round": self.round_counter,
            "max_rounds": self.max_rounds,
            "elapsed_time": self.get_elapsed_time(),
            "total_time": self.total_time,
            "move_history": self.move_history,
            "game_over": self.is_game_over(),
            "capture_score": self.capture_score,
        }

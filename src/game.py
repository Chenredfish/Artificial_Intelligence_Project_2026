import time

from .board import Board  # relative import — always use within src/


class Game:
    def __init__(self, board=None):
        self.board = board if board is not None else Board()
        self.current_team = "AB"
        self.round_counter = 1
        self.max_rounds = 20

        self.move_history = []

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
            self.round_counter += 1

        self.turn_start_time = None  # reset; frontend must call start_turn_timer() again

    def make_move(self, from_pos, to_pos):
        if self.is_game_over():
            raise ValueError("Game is already over")

        if not self.board.is_legal_move(from_pos, to_pos, self.current_team):
            raise ValueError("Illegal move")

        r1, c1 = from_pos
        piece = self.board.get(r1, c1)

        elapsed = self.get_elapsed_time()
        self.total_time[self.current_team] += elapsed

        captured = self.board.apply_move(from_pos, to_pos)
        notation = Board.format_move(piece, from_pos, to_pos)

        current_round = self.round_counter  # save before switch_turn may increment it

        self.move_history.append({
            "team": self.current_team,
            "round": current_round,
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time[self.current_team],
            "captured": captured,
        })

        self.switch_turn()

        return {
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time,
            "captured": captured,
            "next_team": self.current_team,
            "round": current_round,  # the round this move was played in, not the next
        }

    def is_game_over(self):
        return self.round_counter > self.max_rounds

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
        }

import time

from src.board import Board


class Game:
    def __init__(self, board=None):
        self.board = board if board is not None else Board()
        self.current_team = "AB"
        self.round_counter = 1
        self.max_rounds = 20

        self.move_history = []

        self.total_time = {
            "AB": 0.0,
            "UV": 0.0
        }

        self.turn_start_time = time.time()

    def get_current_team(self):
        return self.current_team

    def get_round_counter(self):
        return self.round_counter

    def start_turn_timer(self):
        self.turn_start_time = time.time()

    def get_elapsed_time(self):
        return time.time() - self.turn_start_time

    def switch_turn(self):
        if self.current_team == "AB":
            self.current_team = "UV"
        else:
            self.current_team = "AB"
            self.round_counter += 1

        self.start_turn_timer()

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

        self.move_history.append({
            "team": self.current_team,
            "round": self.round_counter,
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time[self.current_team],
            "captured": captured
        })

        self.switch_turn()

        return {
            "move": notation,
            "move_time": elapsed,
            "total_time": self.total_time,
            "captured": captured,
            "next_team": self.current_team,
            "round": self.round_counter
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
            "game_over": self.is_game_over()
        }
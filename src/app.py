import os
import random
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import json
from flask import Flask, jsonify, request, render_template, Response, stream_with_context

from .game import Game
from .board import Board, PIECE_POINTS, get_team, _PIECE_RULES


class SearchTimeout(Exception):
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(_BASE, 'templates'),
    static_folder=os.path.join(_BASE, 'static'),
)

_game = Game()
_battle_stop = False
_last_depth_reached = 0
_move_pool = None
_board_history_hashes: list = []  # board_key after each game half-move
_repetition_hashes: set = set()   # recent N positions for repetition penalty


def _get_move_pool():
    global _move_pool
    if _move_pool is None:
        _move_pool = ProcessPoolExecutor()
    return _move_pool


# ── pages ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── read-only API ───────────────────────────────────────────────────────

@app.route('/api/state')
def api_state():
    return jsonify(_game.get_state())


@app.route('/api/legal_moves')
def api_legal_moves():
    row = int(request.args['row'])
    col = int(request.args['col'])
    moves = _game.board.legal_moves(row, col)
    return jsonify({'moves': moves})


@app.route('/api/random_board')
def api_random_board():
    board = Board.random_legal_board()
    return jsonify({'grid': board.to_dict()})


# ── action API ──────────────────────────────────────────────────────────

@app.route('/api/move', methods=['POST'])
def api_move():
    data = request.get_json()
    from_pos = tuple(data['from_pos'])
    to_pos   = tuple(data['to_pos'])
    try:
        result = _game.make_move(from_pos, to_pos)
        _board_history_hashes.append(board_key(_game.board))
        result['state'] = _game.get_state()
        return jsonify({'ok': True, **result})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/start_timer', methods=['POST'])
def api_start_timer():
    _game.start_turn_timer()
    return jsonify({'ok': True})


MINIMAX_DEPTH = 5
DEFAULT_NMP_R = 2          # null move reduction factor
DEFAULT_LMR_MIN_DEPTH = 3  # minimum depth to apply LMR
DEFAULT_LMR_MOVE_INDEX = 3 # start reducing moves at this index (0-based)
ASPIRATION_WINDOW = 50     # aspiration window half-width for iterative deepening
REPETITION_PENALTY = 25    # evaluate_board penalty for revisiting a recent game position
DEFAULT_STABILITY_DEPTH_COUNT = 3    # consecutive completed depths with same best move to declare convergence
DEFAULT_STABILITY_SCORE_THRESHOLD = 15  # max score variation across those depths
MAX_TT_SIZE = 400_000                # hard cap on transposition table entries to prevent OOM

# 評估函式：更細緻的 L7 版本，包含棋種價值差異、位置、中心控制、行動力與攻防交換
EVAL_PIECE_WEIGHTS = {
    'A': 10, 'U': 10,
    'B': 8,  'V': 8,
    'c': 4,  'w': 4,
    'd': 4,  'x': 4,
    'e': 3,  'y': 3,
    'f': 3,  'z': 3,
}

PIECE_PST_TYPE = {
    'A': 'A', 'U': 'A',
    'B': 'B', 'V': 'B',
    'c': 'P', 'w': 'P',
    'd': 'Q', 'x': 'Q',
    'e': 'R', 'y': 'R',
    'f': 'S', 'z': 'S',
}

PIECE_SQUARE_TABLES = {
    'A': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  2,  4,  4,  4,  4,  2,  0],
        [0,  2,  4,  6,  6,  4,  2,  0],
        [0,  2,  4,  6,  6,  4,  2,  0],
        [0,  2,  4,  4,  4,  4,  2,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'B': [
        [0,  0,  1,  2,  2,  1,  0,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [2,  3,  4,  5,  5,  4,  3,  2],
        [2,  3,  4,  5,  5,  4,  3,  2],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  0,  1,  2,  2,  1,  0,  0],
    ],
    'P': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'Q': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'R': [
        [0,  0,  0,  1,  1,  0,  0,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  1,  2,  2,  1,  1,  0],
        [0,  0,  0,  1,  1,  0,  0,  0],
    ],
    'S': [
        [0,  0,  0,  1,  1,  0,  0,  0],
        [0,  1,  1,  2,  2,  1,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  1,  2,  2,  1,  1,  0],
        [0,  0,  0,  1,  1,  0,  0,  0],
    ],
}

CENTER_SQUARES = {(3, 3), (3, 4), (4, 3), (4, 4)}
NEAR_CENTER_SQUARES = {
    (2, 2), (2, 3), (2, 4), (2, 5),
    (3, 2), (3, 5),
    (4, 2), (4, 5),
    (5, 2), (5, 3), (5, 4), (5, 5),
}


def piece_square_value(piece, row, col):
    base_type = PIECE_PST_TYPE.get(piece)
    if base_type is None:
        return 0
    table = PIECE_SQUARE_TABLES[base_type]
    return table[row][col]


def game_phase(board):
    total_pieces = len(board._ab_pieces) + len(board._uv_pieces)
    return max(0.0, min(1.0, total_pieces / 12.0))


def board_analysis(board, team):
    """Single pass over team pieces: returns all data previously split across
    moves_and_attacks() and influence_map(), reducing per-leaf work from 4
    traversals to 2 (one per team).

    Returns: (total_moves, captures, non_captures, attacks, piece_move_counts, influence)
      attacks   — squares the team can legally move to (empty + enemy)
      influence — all squares the team can "see" up to and including first blocker
    """
    moves_total = 0
    captures = 0
    non_captures = 0
    attacks = defaultdict(int)
    piece_move_counts = defaultdict(int)
    influence = defaultdict(int)

    for r, c, piece in board.pieces(team):
        directions, max_steps = _PIECE_RULES[piece]
        for dr, dc in directions:
            for step in range(1, max_steps + 1):
                nr, nc = r + dr * step, c + dc * step
                if not (0 <= nr < 8 and 0 <= nc < 8):
                    break
                target = board.get(nr, nc)
                influence[(nr, nc)] += 1          # count regardless (influence_map logic)
                if target is None:
                    attacks[(nr, nc)] += 1
                    piece_move_counts[(r, c)] += 1
                    moves_total += 1
                    non_captures += 1
                elif get_team(target) != team:
                    attacks[(nr, nc)] += 1
                    piece_move_counts[(r, c)] += 1
                    moves_total += 1
                    captures += 1
                    break
                else:
                    break                         # own piece blocks; influence already counted

    return moves_total, captures, non_captures, attacks, piece_move_counts, influence


def static_exchange_score(board, maximizing_team, own_attacks, opp_attacks, own_move_counts, opp_move_counts, own_influence, opp_influence):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_support = own_influence
    opp_support = opp_influence

    score = 0
    for r, c, piece in board.pieces(maximizing_team):
        attack_count = opp_attacks.get((r, c), 0)
        if attack_count:
            defense = own_support.get((r, c), 0)
            penalty = EVAL_PIECE_WEIGHTS[piece] * (0.26 * min(attack_count, 3) - 0.12 * min(defense, 3))
            if (r, c) in CENTER_SQUARES:
                penalty *= 1.12
            if own_move_counts.get((r, c), 0) == 0:
                penalty *= 1.2
            score -= max(0, penalty)

    for r, c, piece in board.pieces(opponent):
        attack_count = own_attacks.get((r, c), 0)
        if attack_count:
            defense = opp_support.get((r, c), 0)
            bonus = EVAL_PIECE_WEIGHTS[piece] * (0.22 * min(attack_count, 3) - 0.14 * min(defense, 3))
            if (r, c) in CENTER_SQUARES:
                bonus *= 1.1
            if opp_move_counts.get((r, c), 0) == 0:
                bonus *= 1.15
            score += max(0, bonus)

    return score


def mobility_score(board, maximizing_team, own_captures, own_non_capture, opp_captures, opp_non_capture, own_move_counts, opp_move_counts):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    piece_weights = {
        'A': 1.0, 'U': 1.0,
        'B': 0.9, 'V': 0.9,
        'c': 0.6, 'w': 0.6,
        'd': 0.6, 'x': 0.6,
        'e': 0.5, 'y': 0.5,
        'f': 0.5, 'z': 0.5,
    }
    mobility_value = 0
    for r, c, piece in board.pieces(maximizing_team):
        mobility_value += own_move_counts.get((r, c), 0) * piece_weights[piece]
    opp_value = 0
    for r, c, piece in board.pieces(opponent):
        opp_value += opp_move_counts.get((r, c), 0) * piece_weights[piece]
    score = 0.09 * (mobility_value - opp_value)
    score += 0.24 * (own_captures - opp_captures)
    score += 0.08 * (own_non_capture - opp_non_capture)
    return score


def activity_score(own_moves, own_captures, own_non_capture, opp_moves, opp_captures, opp_non_capture):
    score = 0.02 * (own_moves - opp_moves)
    score += 0.18 * (own_captures - opp_captures)
    score += 0.07 * (own_non_capture - opp_non_capture)
    return score


def control_score(board, maximizing_team, own_influence, opp_influence):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    score = 0
    for square, count in own_influence.items():
        piece = board.get(square[0], square[1])
        if piece is None:
            score += 0.015 * count
        elif get_team(piece) == opponent:
            score += 0.1 * min(count, 3)
    for square, count in opp_influence.items():
        piece = board.get(square[0], square[1])
        if piece is None:
            score -= 0.01 * count
        elif get_team(piece) == maximizing_team:
            score -= 0.12 * min(count, 3)
    return score


def threatened_score(board, maximizing_team, own_influence, opp_influence):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    score = 0
    for r, c, piece in board.pieces(maximizing_team):
        attack_count = opp_influence.get((r, c), 0)
        if attack_count:
            penalty = EVAL_PIECE_WEIGHTS[piece] * min(attack_count, 3) * 0.28
            if (r, c) in CENTER_SQUARES:
                penalty *= 1.10
            score -= penalty
    for r, c, piece in board.pieces(opponent):
        attack_count = own_influence.get((r, c), 0)
        if attack_count:
            bonus = EVAL_PIECE_WEIGHTS[piece] * min(attack_count, 3) * 0.20
            if (r, c) in CENTER_SQUARES:
                bonus *= 1.05
            score += bonus
    return score


def evaluate_board(board, maximizing_team):
    score = 0
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    phase = game_phase(board)

    own_moves, own_captures, own_non_capture, own_attacks, own_move_counts, own_influence = board_analysis(board, maximizing_team)
    opp_moves, opp_captures, opp_non_capture, opp_attacks, opp_move_counts, opp_influence = board_analysis(board, opponent)

    for r in range(8):
        for c in range(8):
            piece = board.get(r, c)
            if piece is None:
                continue
            material = EVAL_PIECE_WEIGHTS[piece]
            pst = piece_square_value(piece, r, c)
            piece_value = material + 0.35 * pst
            if get_team(piece) == maximizing_team:
                score += piece_value
                if (r, c) in CENTER_SQUARES:
                    score += 0.20
                elif (r, c) in NEAR_CENTER_SQUARES:
                    score += 0.09
            else:
                score -= piece_value
                if (r, c) in CENTER_SQUARES:
                    score -= 0.20
                elif (r, c) in NEAR_CENTER_SQUARES:
                    score -= 0.09

    score += mobility_score(board, maximizing_team, own_captures, own_non_capture, opp_captures, opp_non_capture, own_move_counts, opp_move_counts) * (0.40 + 0.50 * phase)
    score += activity_score(own_moves, own_captures, own_non_capture, opp_moves, opp_captures, opp_non_capture) * (0.20 + 0.20 * phase)
    score += control_score(board, maximizing_team, own_influence, opp_influence)
    score += threatened_score(board, maximizing_team, own_influence, opp_influence)
    score += static_exchange_score(board, maximizing_team, own_attacks, opp_attacks, own_move_counts, opp_move_counts, own_influence, opp_influence)
    if _repetition_hashes and board_key(board) in _repetition_hashes:
        score -= REPETITION_PENALTY
    return score


def terminal_eval(board, maximizing_team):
    """Score at true game end: PIECE_POINTS remaining differential × 200."""
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_pts = sum(PIECE_POINTS[p] for _, _, p in board.pieces(maximizing_team))
    opp_pts = sum(PIECE_POINTS[p] for _, _, p in board.pieces(opponent))
    return (own_pts - opp_pts) * 200


def board_key(board):
    return tuple(tuple(row) for row in board._grid)


def is_capture_move(board, move):
    _, to_pos = move
    return board.get(to_pos[0], to_pos[1]) is not None


def move_score(board, move, best_move=None, history_heuristic=None, use_mvv_lva=True):
    from_pos, to_pos = move
    captured = board.get(to_pos[0], to_pos[1])
    if captured is not None:
        if use_mvv_lva:
            # MVV-LVA: prefer high-value victim, break ties by low-value attacker
            mvv_lva = EVAL_PIECE_WEIGHTS[captured] * 100 - EVAL_PIECE_WEIGHTS[board.get(from_pos[0], from_pos[1])]
        else:
            mvv_lva = PIECE_POINTS.get(captured, 0) * 100
    else:
        mvv_lva = 0
    row, col = to_pos
    center_distance = abs(row - 3.5) + abs(col - 3.5)
    history_bonus = 0
    if history_heuristic is not None:
        history_bonus = history_heuristic.get(move, 0)
    best_bonus = 10000 if move == best_move else 0
    return (best_bonus, mvv_lva, history_bonus, -center_distance)


def order_moves(board, moves, transposition_table, history_heuristic, team, maximizing_team, use_mvv_lva=True):
    tt_entry = transposition_table.get((board_key(board), team, maximizing_team)) if transposition_table is not None else None
    best_move = tt_entry.get('best_move') if tt_entry else None
    scored_moves = []
    for move in moves:
        score = move_score(board, move, best_move=best_move, history_heuristic=history_heuristic, use_mvv_lva=use_mvv_lva)
        scored_moves.append((score, move))
    scored_moves.sort(reverse=True)
    return [move for _, move in scored_moves]


def quiescence_search(board, team, maximizing_team, alpha, beta, start_time=None, time_limit=None, history_heuristic=None, use_mvv_lva=True):
    if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
        raise SearchTimeout()

    stand_pat = evaluate_board(board, maximizing_team)
    opponent = 'UV' if team == 'AB' else 'AB'
    moves = [move for move in board.all_legal_moves(team) if is_capture_move(board, move)]
    moves = order_moves(board, moves, None, history_heuristic, team, maximizing_team, use_mvv_lva=use_mvv_lva)

    if team == maximizing_team:
        # MAX node: stand-pat raises the floor; capture must beat beta to prune.
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
        for from_pos, to_pos in moves:
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            score = quiescence_search(child, opponent, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic, use_mvv_lva=use_mvv_lva)
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha
    else:
        # MIN node: stand-pat lowers the ceiling; opponent's recaptures must beat alpha to prune.
        if stand_pat <= alpha:
            return alpha
        beta = min(beta, stand_pat)
        for from_pos, to_pos in moves:
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            score = quiescence_search(child, opponent, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic, use_mvv_lva=use_mvv_lva)
            if score <= alpha:
                return alpha
            beta = min(beta, score)
        return beta


def minimax(board, team, depth, maximizing_team, alpha=-float('inf'), beta=float('inf'), start_time=None, time_limit=None, transposition_table=None, history_heuristic=None, allow_null=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_pvs=True, use_mvv_lva=True, game_ml=None):
    if time_limit is not None and start_time is not None:
        if time.time() - start_time >= time_limit:
            raise SearchTimeout()

    if depth == 0:
        if game_ml is not None and game_ml <= 0:
            return terminal_eval(board, maximizing_team)
        return quiescence_search(board, team, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic, use_mvv_lva=use_mvv_lva)

    tt_key = (board_key(board), team, maximizing_team)
    tt_active = transposition_table is not None and (game_ml is None or game_ml > depth)
    if tt_active:
        entry = transposition_table.get(tt_key)
        if entry is not None and entry['depth'] >= depth:
            if entry['flag'] == 'EXACT':
                return entry['value']
            if entry['flag'] == 'LOWERBOUND':
                alpha = max(alpha, entry['value'])
            elif entry['flag'] == 'UPPERBOUND':
                beta = min(beta, entry['value'])
            if alpha >= beta:
                return entry['value']

    moves = board.all_legal_moves(team)
    if not moves:
        return evaluate_board(board, maximizing_team)

    moves = order_moves(board, moves, transposition_table, history_heuristic, team, maximizing_team, use_mvv_lva=use_mvv_lva)
    opponent = 'UV' if team == 'AB' else 'AB'
    alpha_orig, beta_orig = alpha, beta

    # Null Move Pruning — MAX nodes only, depth≥3, Zugzwang guard (own pieces > 2)
    if allow_null and depth >= nmp_r + 1 and team == maximizing_team:
        own_count = sum(1 for _ in board.pieces(team))
        if own_count > 2:
            try:
                null_val = minimax(board, opponent, depth - 1 - nmp_r, maximizing_team,
                                   alpha, beta, start_time, time_limit,
                                   transposition_table, history_heuristic,
                                   allow_null=False, nmp_r=nmp_r,
                                   use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                                   use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, game_ml=None)
                if null_val >= beta:
                    return beta
            except SearchTimeout:
                raise

    child_game_ml = game_ml - 1 if game_ml is not None else None
    _mm_kwargs = dict(start_time=start_time, time_limit=time_limit,
                      transposition_table=transposition_table, history_heuristic=history_heuristic,
                      allow_null=allow_null, nmp_r=nmp_r,
                      use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                      use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, game_ml=child_game_ml)

    if team == maximizing_team:
        best = -float('inf')
        best_move = None
        for move_idx, (from_pos, to_pos) in enumerate(moves):
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            lmr_ok = (use_lmr and depth >= lmr_min_depth and move_idx >= lmr_move_index
                      and not is_capture_move(board, (from_pos, to_pos)))
            if move_idx == 0:
                # First move: full-depth full-window (LMR never applies at idx 0)
                value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            elif lmr_ok:
                # LMR: reduced depth with full window only — no zero-window here to avoid stacking
                # two reductions (depth cut + window cut) on the same move, which makes the
                # scout result unreliable and corrupts the re-search decision.
                value = minimax(child, opponent, max(1, depth - 2), maximizing_team, alpha, beta, **_mm_kwargs)
                if value > alpha:
                    value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            else:
                if use_pvs:
                    # PVS: full depth with zero window — only window is narrowed, depth is not cut,
                    # so the scout is reliable and the re-search condition is trustworthy.
                    value = minimax(child, opponent, depth - 1, maximizing_team, alpha, alpha + 1, **_mm_kwargs)
                    if alpha < value < beta:
                        value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
                else:
                    value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            if value > best:
                best = value
                best_move = (from_pos, to_pos)
            alpha = max(alpha, best)
            if alpha >= beta:
                if history_heuristic is not None and best_move is not None:
                    history_heuristic[best_move] += depth * depth
                break
    else:
        best = float('inf')
        best_move = None
        for move_idx, (from_pos, to_pos) in enumerate(moves):
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            lmr_ok = (use_lmr and depth >= lmr_min_depth and move_idx >= lmr_move_index
                      and not is_capture_move(board, (from_pos, to_pos)))
            if move_idx == 0:
                value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            elif lmr_ok:
                # LMR at MIN node: reduced depth probe; re-search at full depth if still promising for MIN.
                value = minimax(child, opponent, max(1, depth - 2), maximizing_team, alpha, beta, **_mm_kwargs)
                if value < beta:
                    value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            else:
                if use_pvs:
                    # PVS at MIN: zero window just below beta.
                    value = minimax(child, opponent, depth - 1, maximizing_team, beta - 1, beta, **_mm_kwargs)
                    if alpha < value < beta:
                        value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
                else:
                    value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, **_mm_kwargs)
            if value < best:
                best = value
                best_move = (from_pos, to_pos)
            beta = min(beta, best)
            if beta <= alpha:
                break

    if tt_active:
        existing = transposition_table.get(tt_key)
        if existing is None or depth >= existing['depth']:
            if existing is None and len(transposition_table) >= MAX_TT_SIZE:
                pass  # TT full, skip new entries but allow updating existing ones
            else:
                if best <= alpha_orig:
                    flag = 'UPPERBOUND'
                elif best >= beta_orig:
                    flag = 'LOWERBOUND'
                else:
                    flag = 'EXACT'
                transposition_table[tt_key] = {
                    'depth': depth,
                    'value': best,
                    'flag': flag,
                    'best_move': best_move,
                }

    return best


def _root_move_worker(args):
    """Top-level worker for ProcessPoolExecutor — evaluates one root move with iterative deepening."""
    board_grid, from_pos, to_pos, max_depth, team, opponent, use_nmp, nmp_r, use_lmr, lmr_min_depth, lmr_move_index, start_time, time_limit, use_pvs, use_mvv_lva, moves_left, use_stability, stability_depth_count, stability_score_threshold = args
    child = Board()
    child._grid = [list(row) for row in board_grid]
    child._rebuild_piece_lists()
    child.apply_move(from_pos, to_pos)
    tt = {}
    hh = defaultdict(int)
    best_value = -float('inf')
    last_depth = 0
    # root move already applied — child has one fewer half-move remaining
    child_ml = moves_left - 1 if moves_left is not None else None
    eff_depth = max_depth  # horizon already baked into max_depth (= min(depth, moves_left)) by caller
    value_history = []
    for d in range(1, eff_depth + 1):
        if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
            break
        try:
            val = minimax(child, opponent, d - 1, team, -float('inf'), float('inf'),
                          start_time, time_limit, tt, hh,
                          allow_null=use_nmp, nmp_r=nmp_r,
                          use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                          use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, game_ml=child_ml)
            best_value = val
            last_depth = d
            if use_stability:
                value_history.append(val)
                if len(value_history) >= stability_depth_count:
                    recent = value_history[-stability_depth_count:]
                    if max(recent) - min(recent) < stability_score_threshold:
                        break
        except SearchTimeout:
            break
    return (best_value, from_pos, to_pos, last_depth)


def choose_minimax_move(board, team, depth=MINIMAX_DEPTH, time_limit=None, use_nmp=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_parallel=False, use_asp=True, asp_window=ASPIRATION_WINDOW, use_pvs=True, use_mvv_lva=True, moves_left=None, use_stability=False, stability_depth_count=DEFAULT_STABILITY_DEPTH_COUNT, stability_score_threshold=DEFAULT_STABILITY_SCORE_THRESHOLD):
    global _last_depth_reached
    moves = board.all_legal_moves(team)
    if not moves:
        return None

    if time_limit is not None and time_limit <= 0:
        time_limit = None

    start_time = time.time()
    effective_depth = min(depth, moves_left) if moves_left is not None else depth

    # Parallel root search: each worker does iterative deepening with the shared deadline
    if use_parallel and depth > 1:
        opponent = 'UV' if team == 'AB' else 'AB'
        board_grid = tuple(tuple(row) for row in board._grid)
        args_list = [
            (board_grid, fp, tp, effective_depth, team, opponent, use_nmp, nmp_r,
             use_lmr, lmr_min_depth, lmr_move_index, start_time, time_limit, use_pvs, use_mvv_lva,
             moves_left, use_stability, stability_depth_count, stability_score_threshold)
            for fp, tp in moves
        ]
        results = list(_get_move_pool().map(_root_move_worker, args_list))
        worker_depths = [d for _, _, _, d in results]
        _last_depth_reached = round(sum(worker_depths) / len(worker_depths)) if worker_depths else 0
        best_value = max(v for v, _, _, _ in results)
        best_moves = [(fp, tp) for v, fp, tp, _ in results if v == best_value]
        return random.choice(best_moves)
    opponent = 'UV' if team == 'AB' else 'AB'

    fallback_move = random.choice(moves)
    last_completed_moves = [fallback_move]
    transposition_table = {}
    history_heuristic = defaultdict(int)
    prev_best_value = None  # tracks last completed depth score for aspiration window
    _last_depth_reached = 0
    stability_history = []  # list of (best_move, best_value) per completed depth
    root_game_ml = moves_left - 1 if moves_left is not None else None

    for current_depth in range(1, effective_depth + 1):
        if time_limit is not None and time.time() - start_time >= time_limit:
            break

        # Aspiration window: use narrow bounds around previous depth's score
        if use_asp and prev_best_value is not None and current_depth > 2:
            asp_alpha = prev_best_value - asp_window
            asp_beta  = prev_best_value + asp_window
        else:
            asp_alpha, asp_beta = -float('inf'), float('inf')
        asp_alpha_orig = asp_alpha  # save original lower bound for failure detection

        ordered_moves = order_moves(board, moves, transposition_table, history_heuristic, team, team, use_mvv_lva=use_mvv_lva)
        best_value = -float('inf')
        current_moves = []

        try:
            for from_pos, to_pos in ordered_moves:
                if time_limit is not None and time.time() - start_time >= time_limit:
                    raise SearchTimeout()
                child = board.copy()
                child.apply_move(from_pos, to_pos)
                value = minimax(child, opponent, current_depth - 1, team, asp_alpha, asp_beta, start_time, time_limit, transposition_table, history_heuristic, allow_null=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, game_ml=root_game_ml)
                if value > best_value:
                    best_value = value
                    current_moves = [(from_pos, to_pos)]
                    asp_alpha = max(asp_alpha, value)  # tighten lower bound so later moves prune faster
                elif value == best_value:
                    current_moves.append((from_pos, to_pos))
        except SearchTimeout:
            break

        # Fail-low or fail-high: re-search with full window to get the correct score.
        # depth_reliable tracks whether we have a trustworthy result for this depth.
        depth_reliable = True
        if asp_alpha_orig != -float('inf') and (best_value <= asp_alpha_orig or best_value >= asp_beta):
            if time_limit is None or time.time() - start_time < time_limit:
                retry_value = -float('inf')
                retry_moves = []
                retry_timed_out = False
                try:
                    for from_pos, to_pos in ordered_moves:
                        if time_limit is not None and time.time() - start_time >= time_limit:
                            raise SearchTimeout()
                        child = board.copy()
                        child.apply_move(from_pos, to_pos)
                        value = minimax(child, opponent, current_depth - 1, team, -float('inf'), float('inf'), start_time, time_limit, transposition_table, history_heuristic, allow_null=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, game_ml=root_game_ml)
                        if value > retry_value:
                            retry_value = value
                            retry_moves = [(from_pos, to_pos)]
                        elif value == retry_value:
                            retry_moves.append((from_pos, to_pos))
                except SearchTimeout:
                    retry_timed_out = True
                if not retry_timed_out and retry_moves:
                    best_value = retry_value
                    current_moves = retry_moves
                else:
                    # Retry incomplete: aspiration results are unreliable.
                    # Keep last_completed_moves from the previous depth (ID safety guarantee).
                    depth_reliable = False
            else:
                depth_reliable = False  # aspiration failed but no time to retry

        if depth_reliable:
            prev_best_value = best_value
        if depth_reliable and current_moves:
            last_completed_moves = current_moves
            _last_depth_reached = current_depth
            if use_stability:
                stability_history.append((current_moves[0], best_value))
                if len(stability_history) >= stability_depth_count:
                    recent = stability_history[-stability_depth_count:]
                    same_move = all(m == recent[0][0] for m, _ in recent)
                    score_delta = max(v for _, v in recent) - min(v for _, v in recent)
                    if same_move and score_delta < stability_score_threshold:
                        break
            root_key = (board_key(board), team, team)
            transposition_table[root_key] = {
                'depth': current_depth,
                'value': best_value,
                'flag': 'EXACT',
                'best_move': current_moves[0],
            }

    return random.choice(last_completed_moves)


def choose_greedy_move(board, team):
    moves = board.all_legal_moves(team)
    best_value = -1
    best_moves = []

    for from_pos, to_pos in moves:
        target = board.get(to_pos[0], to_pos[1])
        value = PIECE_POINTS.get(target, 0) if target is not None else 0

        if value > best_value:
            best_value = value
            best_moves = [(from_pos, to_pos)]
        elif value == best_value:
            best_moves.append((from_pos, to_pos))

    if best_value > 0:
        return random.choice(best_moves)
    return random.choice(moves)


def _reloc_eval_worker(args):
    """Worker: evaluate one relocation candidate (or baseline) via minimax in a subprocess."""
    board_grid, from_pos, to_pos, first_mover, evaluating_team, depth, root_ml = args
    trial = Board()
    trial._grid = [list(row) for row in board_grid]
    trial._rebuild_piece_lists()
    if from_pos is not None:
        piece = trial.get(from_pos[0], from_pos[1])
        trial.set(from_pos[0], from_pos[1], None)
        trial.set(to_pos[0], to_pos[1], piece)
    tt = {}
    hh = defaultdict(int)
    score = minimax(trial, first_mover, depth, evaluating_team,
                    transposition_table=tt, history_heuristic=hh,
                    allow_null=False, use_lmr=False, use_pvs=True, use_mvv_lva=True,
                    game_ml=root_ml)
    return from_pos, to_pos, score


def suggest_relocation(board, evaluating_team='UV', depth=0, top_n=15, moves_left=None, use_parallel=False):
    """Return (from_pos, to_pos, score) of the best pre-game piece relocation for evaluating_team.
    depth=0: static evaluation only (fast).
    depth>0: static pre-filter to top_n candidates, then minimax re-ranking (slow but accurate).
    Returns (None, None, baseline_score) when no relocation improves the position."""
    first_mover = 'AB' if evaluating_team == 'UV' else 'UV'
    empty_squares = [(r, c) for r in range(8) for c in range(8) if board.get(r, c) is None]

    # Phase 1: static evaluation of every (piece × empty_square) combination
    candidates = []
    for r in range(8):
        for c in range(8):
            piece = board.get(r, c)
            if piece is None:
                continue
            for er, ec in empty_squares:
                trial = board.copy()
                trial.set(r, c, None)
                trial.set(er, ec, piece)
                score = evaluate_board(trial, evaluating_team)
                candidates.append(((r, c), (er, ec), score))

    if not candidates:
        return None, None, evaluate_board(board, evaluating_team)

    if depth == 0:
        baseline = evaluate_board(board, evaluating_team)
        best = max(candidates, key=lambda x: x[2])
        if best[2] <= baseline:
            return None, None, baseline
        return best[0], best[1], best[2]

    # Phase 2: minimax re-ranking of top_n static candidates
    candidates.sort(key=lambda x: x[2], reverse=True)
    top_candidates = candidates[:top_n]

    root_ml = (moves_left - 1) if moves_left is not None else None
    board_grid = [list(row) for row in board._grid]

    # baseline (from_pos=None means no relocation) + top candidates
    work_items = [(board_grid, None, None, first_mover, evaluating_team, depth, root_ml)]
    work_items += [(board_grid, fp, tp, first_mover, evaluating_team, depth, root_ml)
                   for fp, tp, _ in top_candidates]

    if use_parallel:
        results = list(_get_move_pool().map(_reloc_eval_worker, work_items))
    else:
        # Sequential with shared TT/HH for cross-candidate TT reuse
        tt = {}
        hh = defaultdict(int)
        results = []
        for item in work_items:
            bg, fp, tp, fm, et, d, rml = item
            trial = Board()
            trial._grid = [list(row) for row in bg]
            trial._rebuild_piece_lists()
            if fp is not None:
                piece = trial.get(fp[0], fp[1])
                trial.set(fp[0], fp[1], None)
                trial.set(tp[0], tp[1], piece)
            score = minimax(trial, fm, d, et,
                            transposition_table=tt, history_heuristic=hh,
                            allow_null=False, use_lmr=False, use_pvs=True, use_mvv_lva=True,
                            game_ml=rml)
            results.append((fp, tp, score))

    baseline_score = next(s for fp, tp, s in results if fp is None)
    best_from = None
    best_to = None
    best_score = baseline_score
    for fp, tp, score in results:
        if fp is not None and score > best_score:
            best_score = score
            best_from = fp
            best_to = tp

    return best_from, best_to, best_score


def choose_move_by_strategy(board, team, strategy, depth=MINIMAX_DEPTH, time_limit=None, use_nmp=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_parallel=False, use_asp=True, asp_window=ASPIRATION_WINDOW, use_pvs=True, use_mvv_lva=True, moves_left=None, use_stability=False, stability_depth_count=DEFAULT_STABILITY_DEPTH_COUNT, stability_score_threshold=DEFAULT_STABILITY_SCORE_THRESHOLD):
    if strategy == 'random':
        moves = board.all_legal_moves(team)
        return random.choice(moves) if moves else None
    if strategy == 'greedy':
        return choose_greedy_move(board, team)
    return choose_minimax_move(board, team, depth=depth, time_limit=time_limit, use_nmp=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_parallel=use_parallel, use_asp=use_asp, asp_window=asp_window, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, moves_left=moves_left, use_stability=use_stability, stability_depth_count=stability_depth_count, stability_score_threshold=stability_score_threshold)


def play_ai_battle_game(ab_depth, uv_depth, rounds=20, time_limit=None, ab_time_limit=None, uv_time_limit=None, ab_strategy='minimax', uv_strategy='minimax', ab_nmp=True, uv_nmp=True, ab_nmp_r=DEFAULT_NMP_R, uv_nmp_r=DEFAULT_NMP_R, first_team='random', ab_lmr=True, uv_lmr=True, ab_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, ab_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, uv_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, uv_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, ab_parallel=False, uv_parallel=False, ab_asp=True, uv_asp=True, ab_asp_window=ASPIRATION_WINDOW, uv_asp_window=ASPIRATION_WINDOW, ab_pvs=True, uv_pvs=True, ab_mvv_lva=True, uv_mvv_lva=True, ab_use_stability=False, ab_stability_depth_count=DEFAULT_STABILITY_DEPTH_COUNT, ab_stability_score_threshold=DEFAULT_STABILITY_SCORE_THRESHOLD, uv_use_stability=False, uv_stability_depth_count=DEFAULT_STABILITY_DEPTH_COUNT, uv_stability_score_threshold=DEFAULT_STABILITY_SCORE_THRESHOLD):
    global _last_depth_reached
    # Per-team time limits: explicit ab/uv_time_limit override the shared time_limit fallback
    _ab_tl = ab_time_limit if ab_time_limit is not None else time_limit
    _uv_tl = uv_time_limit if uv_time_limit is not None else time_limit
    board = Board.random_legal_board()
    game = Game(board=board)
    actual_first = random.choice(['AB', 'UV']) if first_team == 'random' else first_team
    second = 'UV' if actual_first == 'AB' else 'AB'
    game.current_team = actual_first
    game.turn_start_time = None

    ab_moves = []
    uv_moves = []
    round_number = 1
    ab_move_log = []
    uv_move_log = []
    battle_board_hashes: list = []

    for round_number in range(1, rounds + 1):
        any_move = False
        for team in (actual_first, second):
            if game.is_game_over():
                break
            game.current_team = team
            if not game.board.all_legal_moves(team):
                continue
            strategy  = ab_strategy if team == 'AB' else uv_strategy
            depth     = ab_depth    if team == 'AB' else uv_depth
            nmp       = ab_nmp      if team == 'AB' else uv_nmp
            nmp_r_val = ab_nmp_r    if team == 'AB' else uv_nmp_r
            lmr       = ab_lmr      if team == 'AB' else uv_lmr
            lmr_min   = ab_lmr_min_depth  if team == 'AB' else uv_lmr_min_depth
            lmr_idx   = ab_lmr_move_index if team == 'AB' else uv_lmr_move_index
            parallel  = ab_parallel if team == 'AB' else uv_parallel
            asp       = ab_asp      if team == 'AB' else uv_asp
            asp_w     = ab_asp_window if team == 'AB' else uv_asp_window
            pvs       = ab_pvs      if team == 'AB' else uv_pvs
            mvv_lva   = ab_mvv_lva  if team == 'AB' else uv_mvv_lva
            stability  = ab_use_stability           if team == 'AB' else uv_use_stability
            stab_n     = ab_stability_depth_count   if team == 'AB' else uv_stability_depth_count
            stab_t     = ab_stability_score_threshold if team == 'AB' else uv_stability_score_threshold
            tl        = _ab_tl if team == 'AB' else _uv_tl
            _last_depth_reached = 0
            game.start_turn_timer()
            moves_left = game.max_rounds * 2 - len(game.move_history)
            _repetition_hashes.clear()
            _own_cs = game.capture_score[team]
            _opp_cs = game.capture_score['UV' if team == 'AB' else 'AB']
            if _own_cs <= _opp_cs:
                _repetition_hashes.update(battle_board_hashes[-6:])
            move = choose_move_by_strategy(game.board, team, strategy, depth, tl, use_nmp=nmp, nmp_r=nmp_r_val, use_lmr=lmr, lmr_min_depth=lmr_min, lmr_move_index=lmr_idx, use_parallel=parallel, use_asp=asp, asp_window=asp_w, use_pvs=pvs, use_mvv_lva=mvv_lva, moves_left=moves_left, use_stability=stability, stability_depth_count=stab_n, stability_score_threshold=stab_t)
            depth_reached = _last_depth_reached
            if move is not None:
                from_pos, to_pos = move
                result = game.make_move(from_pos, to_pos)
                battle_board_hashes.append(board_key(game.board))
                move_time = result['move_time']
                move_entry = {
                    'round': round_number,
                    'move': result['move'],
                    'depth': depth_reached,
                    'time': round(move_time, 3),
                    'time_pct': round(move_time / tl * 100, 1) if tl else None,
                    'captured': result['captured'],
                }
                if team == 'AB':
                    ab_moves.append(f"R{round_number} AB: {result['move']}")
                    ab_move_log.append(move_entry)
                else:
                    uv_moves.append(f"R{round_number} UV: {result['move']}")
                    uv_move_log.append(move_entry)
                any_move = True
        if not any_move:
            break

    ab_score = game.capture_score['AB']
    uv_score = game.capture_score['UV']
    if ab_score > uv_score:
        winner = 'AB'
    elif uv_score > ab_score:
        winner = 'UV'
    else:
        winner = 'draw'

    _ab_d = [e['depth'] for e in ab_move_log if e['depth'] > 0]
    _uv_d = [e['depth'] for e in uv_move_log if e['depth'] > 0]
    _ab_t = [e['time'] for e in ab_move_log]
    _uv_t = [e['time'] for e in uv_move_log]
    _ab_p = [e['time_pct'] for e in ab_move_log if e['time_pct'] is not None]
    _uv_p = [e['time_pct'] for e in uv_move_log if e['time_pct'] is not None]
    return {
        'rounds': round_number,
        'winner': winner,
        'ab_score': ab_score,
        'uv_score': uv_score,
        'ab_moves': ab_moves,
        'uv_moves': uv_moves,
        'state': game.get_state(),
        'first_team': actual_first,
        'ab_move_log': ab_move_log,
        'uv_move_log': uv_move_log,
        'ab_avg_depth': round(sum(_ab_d) / len(_ab_d), 1) if _ab_d else 0,
        'ab_min_depth': min(_ab_d) if _ab_d else 0,
        'ab_max_depth': max(_ab_d) if _ab_d else 0,
        'ab_avg_time': round(sum(_ab_t) / len(_ab_t), 2) if _ab_t else 0.0,
        'ab_avg_time_pct': round(sum(_ab_p) / len(_ab_p), 1) if _ab_p else None,
        'uv_avg_depth': round(sum(_uv_d) / len(_uv_d), 1) if _uv_d else 0,
        'uv_min_depth': min(_uv_d) if _uv_d else 0,
        'uv_max_depth': max(_uv_d) if _uv_d else 0,
        'uv_avg_time': round(sum(_uv_t) / len(_uv_t), 2) if _uv_t else 0.0,
        'uv_avg_time_pct': round(sum(_uv_p) / len(_uv_p), 1) if _uv_p else None,
    }


def _game_worker(args):
    """Module-level worker for game-level parallelism. Move-level parallel is forced OFF."""
    (game_idx, ab_depth, uv_depth, ab_time_limit, uv_time_limit, ab_strategy, uv_strategy,
     ab_nmp, uv_nmp, ab_nmp_r, uv_nmp_r, first_team,
     ab_lmr, uv_lmr, ab_lmr_min_depth, ab_lmr_move_index,
     uv_lmr_min_depth, uv_lmr_move_index,
     ab_asp, uv_asp, ab_asp_window, uv_asp_window, ab_pvs, uv_pvs,
     ab_mvv_lva, uv_mvv_lva,
     ab_use_stability, ab_stability_depth_count, ab_stability_score_threshold,
     uv_use_stability, uv_stability_depth_count, uv_stability_score_threshold) = args
    gr = play_ai_battle_game(
        ab_depth, uv_depth, rounds=20, ab_time_limit=ab_time_limit, uv_time_limit=uv_time_limit,
        ab_strategy=ab_strategy, uv_strategy=uv_strategy,
        ab_nmp=ab_nmp, uv_nmp=uv_nmp, ab_nmp_r=ab_nmp_r, uv_nmp_r=uv_nmp_r,
        first_team=first_team, ab_lmr=ab_lmr, uv_lmr=uv_lmr,
        ab_lmr_min_depth=ab_lmr_min_depth, ab_lmr_move_index=ab_lmr_move_index,
        uv_lmr_min_depth=uv_lmr_min_depth, uv_lmr_move_index=uv_lmr_move_index,
        ab_parallel=False, uv_parallel=False,
        ab_asp=ab_asp, uv_asp=uv_asp, ab_asp_window=ab_asp_window, uv_asp_window=uv_asp_window,
        ab_pvs=ab_pvs, uv_pvs=uv_pvs,
        ab_mvv_lva=ab_mvv_lva, uv_mvv_lva=uv_mvv_lva,
        ab_use_stability=ab_use_stability, ab_stability_depth_count=ab_stability_depth_count, ab_stability_score_threshold=ab_stability_score_threshold,
        uv_use_stability=uv_use_stability, uv_stability_depth_count=uv_stability_depth_count, uv_stability_score_threshold=uv_stability_score_threshold,
    )
    return game_idx, gr


@app.route('/api/ask_ai', methods=['POST'])
def api_ask_ai():
    data = request.get_json() or {}
    auto_apply = data.get('auto_apply', True)
    time_limit = data.get('time_limit')
    use_nmp     = bool(data.get('use_nmp', True))
    use_lmr     = bool(data.get('use_lmr', True))
    use_pvs     = bool(data.get('use_pvs', True))
    use_mvv_lva = bool(data.get('use_mvv_lva', True))
    use_parallel = bool(data.get('use_parallel', False))
    use_asp     = bool(data.get('use_asp', True))

    try:
        time_limit     = None if time_limit is None else float(time_limit)
        nmp_r          = max(1, min(int(data.get('nmp_r',          DEFAULT_NMP_R)),          4))
        lmr_min_depth  = max(2, min(int(data.get('lmr_min_depth',  DEFAULT_LMR_MIN_DEPTH)),  10))
        lmr_move_index = max(1, min(int(data.get('lmr_move_index', DEFAULT_LMR_MOVE_INDEX)), 10))
        asp_window     = max(5, min(int(data.get('asp_window',     ASPIRATION_WINDOW)),      500))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Invalid parameter value.'}), 400

    use_stability = bool(data.get('use_stability', False))
    try:
        depth_req = data.get('depth')
        depth = max(1, min(int(depth_req), 50)) if depth_req is not None else (50 if (time_limit and time_limit > 0) else MINIMAX_DEPTH)
        stability_depth_count     = max(2, min(int(data.get('stability_depth_count',     DEFAULT_STABILITY_DEPTH_COUNT)),     10))
        stability_score_threshold = max(1, min(int(data.get('stability_score_threshold', DEFAULT_STABILITY_SCORE_THRESHOLD)), 500))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Invalid parameter value.'}), 400

    _game.start_turn_timer()

    moves = _game.board.all_legal_moves(_game.current_team)
    if not moves:
        return jsonify({'ok': False, 'error': 'No legal moves available'}), 400

    _repetition_hashes.clear()
    _own_score = _game.capture_score[_game.current_team]
    _opp_score = _game.capture_score['UV' if _game.current_team == 'AB' else 'AB']
    if _own_score <= _opp_score:  # behind or tied: penalise repeats to encourage breaking stalemate
        _repetition_hashes.update(_board_history_hashes[-6:])
    moves_left = _game.max_rounds * 2 - len(_game.move_history)
    move = choose_minimax_move(
        _game.board, _game.current_team,
        depth=depth, time_limit=time_limit,
        use_nmp=use_nmp, nmp_r=nmp_r,
        use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
        use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, use_parallel=use_parallel,
        use_asp=use_asp, asp_window=asp_window,
        moves_left=moves_left,
        use_stability=use_stability, stability_depth_count=stability_depth_count, stability_score_threshold=stability_score_threshold,
    )
    if move is None:
        return jsonify({'ok': False, 'error': 'No valid AI move found.'}), 400
    from_pos, to_pos = move
    piece = _game.board.get(from_pos[0], from_pos[1])
    notation = Board.format_move(piece, from_pos, to_pos)
    depth_reached = _last_depth_reached

    # 開關關閉：只回傳 AI 建議，不移動棋子
    if not auto_apply:
        # 記錄 AI 真正的計算耗時，然後立刻停止 timer
        # 這樣人類決策時間不會被計入 move_time
        ai_elapsed = _game.get_elapsed_time()
        _game.turn_start_time = None
        time_pct = round(ai_elapsed / time_limit * 100, 1) if (time_limit and time_limit > 0) else None
        return jsonify({
            'ok': True,
            'suggestion_only': True,
            'from_pos': from_pos,
            'to_pos': to_pos,
            'piece': piece,
            'move': notation,
            'ai_elapsed': ai_elapsed,
            'depth_reached': depth_reached,
            'time_pct': time_pct,
            'state': _game.get_state()
        })

    # 開關開啟：維持原本功能，AI 直接下棋
    try:
        result = _game.make_move(from_pos, to_pos)
        move_time = result['move_time']
        time_pct = round(move_time / time_limit * 100, 1) if (time_limit and time_limit > 0) else None
        result['state'] = _game.get_state()
        result['suggestion_only'] = False
        result['depth_reached'] = depth_reached
        result['time_pct'] = time_pct
        return jsonify({'ok': True, **result})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/stop_battle', methods=['POST'])
def api_stop_battle():
    global _battle_stop
    _battle_stop = True
    return jsonify({'ok': True})


@app.route('/api/ai_battle', methods=['POST'])
def api_ai_battle():
    data = request.get_json() or {}
    try:
        ab_depth = int(data.get('ab_depth', MINIMAX_DEPTH))
        uv_depth = int(data.get('uv_depth', MINIMAX_DEPTH))
        games = int(data.get('games', 10))
        _abt = data.get('ab_time_limit', data.get('time_limit'))
        _uvt = data.get('uv_time_limit', data.get('time_limit'))
        ab_time_limit = None if _abt is None else (None if float(_abt) <= 0 else float(_abt))
        uv_time_limit = None if _uvt is None else (None if float(_uvt) <= 0 else float(_uvt))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Depth, game count, and time limit must be numbers.'}), 400

    ab_depth = max(1, min(ab_depth, 50))
    uv_depth = max(1, min(uv_depth, 50))
    if games < 1 or games > 200:
        return jsonify({'ok': False, 'error': 'Game count must be between 1 and 200.'}), 400

    ab_strategy = data.get('ab_strategy', 'minimax')
    uv_strategy = data.get('uv_strategy', 'minimax')
    if ab_strategy not in {'random', 'greedy', 'minimax'} or uv_strategy not in {'random', 'greedy', 'minimax'}:
        return jsonify({'ok': False, 'error': 'Strategy must be random, greedy, or minimax.'}), 400

    ab_nmp = bool(data.get('ab_nmp', True))
    uv_nmp = bool(data.get('uv_nmp', True))
    try:
        ab_nmp_r = max(1, min(int(data.get('ab_nmp_r', DEFAULT_NMP_R)), 4))
        uv_nmp_r = max(1, min(int(data.get('uv_nmp_r', DEFAULT_NMP_R)), 4))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'nmp_r must be a number.'}), 400
    first_team = data.get('first_team', 'random')
    if first_team not in {'AB', 'UV', 'random'}:
        return jsonify({'ok': False, 'error': 'first_team must be AB, UV, or random.'}), 400

    ab_lmr = bool(data.get('ab_lmr', True))
    uv_lmr = bool(data.get('uv_lmr', True))
    try:
        ab_lmr_min_depth  = max(2, min(int(data.get('ab_lmr_min_depth',  DEFAULT_LMR_MIN_DEPTH)),  10))
        ab_lmr_move_index = max(1, min(int(data.get('ab_lmr_move_index', DEFAULT_LMR_MOVE_INDEX)), 10))
        uv_lmr_min_depth  = max(2, min(int(data.get('uv_lmr_min_depth',  DEFAULT_LMR_MIN_DEPTH)),  10))
        uv_lmr_move_index = max(1, min(int(data.get('uv_lmr_move_index', DEFAULT_LMR_MOVE_INDEX)), 10))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'lmr params must be numbers.'}), 400
    ab_parallel = bool(data.get('ab_parallel', False))
    uv_parallel = bool(data.get('uv_parallel', False))
    try:
        game_workers = max(1, min(int(data.get('game_workers', 1)), 8))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'game_workers must be a number.'}), 400
    ab_asp = bool(data.get('ab_asp', True))
    uv_asp = bool(data.get('uv_asp', True))
    ab_pvs = bool(data.get('ab_pvs', True))
    uv_pvs = bool(data.get('uv_pvs', True))
    ab_mvv_lva = bool(data.get('ab_mvv_lva', True))
    uv_mvv_lva = bool(data.get('uv_mvv_lva', True))
    try:
        ab_asp_window = max(5, min(int(data.get('ab_asp_window', ASPIRATION_WINDOW)), 500))
        uv_asp_window = max(5, min(int(data.get('uv_asp_window', ASPIRATION_WINDOW)), 500))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'asp_window must be a number.'}), 400
    ab_use_stability = bool(data.get('ab_use_stability', False))
    uv_use_stability = bool(data.get('uv_use_stability', False))
    try:
        ab_stability_depth_count     = max(2, min(int(data.get('ab_stability_depth_count',     DEFAULT_STABILITY_DEPTH_COUNT)),     10))
        ab_stability_score_threshold = max(1, min(int(data.get('ab_stability_score_threshold', DEFAULT_STABILITY_SCORE_THRESHOLD)), 500))
        uv_stability_depth_count     = max(2, min(int(data.get('uv_stability_depth_count',     DEFAULT_STABILITY_DEPTH_COUNT)),     10))
        uv_stability_score_threshold = max(1, min(int(data.get('uv_stability_score_threshold', DEFAULT_STABILITY_SCORE_THRESHOLD)), 500))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'stability params must be numbers.'}), 400

    global _battle_stop
    _battle_stop = False

    def generate():
        ab_wins = uv_wins = draws = 0
        ab_total = uv_total = total_rounds = 0
        ab_depth_sum = uv_depth_sum = 0.0
        ab_depth_count = uv_depth_count = 0
        game_log = []
        last_gr = None

        if game_workers > 1:
            # Game-level parallel: run multiple games simultaneously.
            # Move-level parallel is forced OFF inside _game_worker (no nested pools on Windows).
            _wargs = [
                (i, ab_depth, uv_depth, ab_time_limit, uv_time_limit, ab_strategy, uv_strategy,
                 ab_nmp, uv_nmp, ab_nmp_r, uv_nmp_r, first_team,
                 ab_lmr, uv_lmr, ab_lmr_min_depth, ab_lmr_move_index,
                 uv_lmr_min_depth, uv_lmr_move_index,
                 ab_asp, uv_asp, ab_asp_window, uv_asp_window, ab_pvs, uv_pvs,
                 ab_mvv_lva, uv_mvv_lva,
                 ab_use_stability, ab_stability_depth_count, ab_stability_score_threshold,
                 uv_use_stability, uv_stability_depth_count, uv_stability_score_threshold)
                for i in range(games)
            ]
            completed_count = 0
            with ProcessPoolExecutor(max_workers=game_workers) as executor:
                all_futures = [executor.submit(_game_worker, a) for a in _wargs]
                for fut in as_completed(all_futures):
                    try:
                        _, gr = fut.result()
                    except Exception:
                        continue
                    completed_count += 1
                    if gr['winner'] == 'AB':
                        ab_wins += 1
                    elif gr['winner'] == 'UV':
                        uv_wins += 1
                    else:
                        draws += 1
                    ab_total += gr['ab_score']
                    uv_total += gr['uv_score']
                    total_rounds += gr['rounds']
                    ab_depth_sum += gr.get('ab_avg_depth', 0)
                    uv_depth_sum += gr.get('uv_avg_depth', 0)
                    ab_depth_count += 1
                    uv_depth_count += 1
                    entry = {
                        'game': completed_count, 'winner': gr['winner'],
                        'ab_score': gr['ab_score'], 'uv_score': gr['uv_score'],
                        'rounds': gr['rounds'], 'first_team': gr['first_team'],
                        'ab_avg_depth': gr.get('ab_avg_depth', 0),
                        'uv_avg_depth': gr.get('uv_avg_depth', 0),
                        'ab_min_depth': gr.get('ab_min_depth', 0),
                        'ab_max_depth': gr.get('ab_max_depth', 0),
                        'uv_min_depth': gr.get('uv_min_depth', 0),
                        'uv_max_depth': gr.get('uv_max_depth', 0),
                        'ab_avg_time': gr.get('ab_avg_time', 0.0),
                        'uv_avg_time': gr.get('uv_avg_time', 0.0),
                        'ab_avg_time_pct': gr.get('ab_avg_time_pct'),
                        'uv_avg_time_pct': gr.get('uv_avg_time_pct'),
                        'ab_move_log': gr.get('ab_move_log', []),
                        'uv_move_log': gr.get('uv_move_log', []),
                    }
                    game_log.append({k: v for k, v in entry.items() if k not in ('ab_move_log', 'uv_move_log')})
                    last_gr = gr
                    yield json.dumps({
                        'type': 'progress',
                        'game': completed_count, 'total': games,
                        'ab_wins': ab_wins, 'uv_wins': uv_wins, 'draws': draws,
                        **entry,
                    }) + '\n'
                    if _battle_stop:
                        for f in all_futures:
                            f.cancel()
                        break
        else:
            for i in range(games):
                if _battle_stop:
                    break
                gr = play_ai_battle_game(
                    ab_depth, uv_depth, rounds=20, ab_time_limit=ab_time_limit, uv_time_limit=uv_time_limit,
                    ab_strategy=ab_strategy, uv_strategy=uv_strategy,
                    ab_nmp=ab_nmp, uv_nmp=uv_nmp,
                    ab_nmp_r=ab_nmp_r, uv_nmp_r=uv_nmp_r,
                    first_team=first_team,
                    ab_lmr=ab_lmr, uv_lmr=uv_lmr,
                    ab_lmr_min_depth=ab_lmr_min_depth, ab_lmr_move_index=ab_lmr_move_index,
                    uv_lmr_min_depth=uv_lmr_min_depth, uv_lmr_move_index=uv_lmr_move_index,
                    ab_parallel=ab_parallel, uv_parallel=uv_parallel,
                    ab_asp=ab_asp, uv_asp=uv_asp, ab_asp_window=ab_asp_window, uv_asp_window=uv_asp_window,
                    ab_pvs=ab_pvs, uv_pvs=uv_pvs,
                    ab_mvv_lva=ab_mvv_lva, uv_mvv_lva=uv_mvv_lva,
                    ab_use_stability=ab_use_stability, ab_stability_depth_count=ab_stability_depth_count, ab_stability_score_threshold=ab_stability_score_threshold,
                    uv_use_stability=uv_use_stability, uv_stability_depth_count=uv_stability_depth_count, uv_stability_score_threshold=uv_stability_score_threshold,
                )
                if gr['winner'] == 'AB':
                    ab_wins += 1
                elif gr['winner'] == 'UV':
                    uv_wins += 1
                else:
                    draws += 1
                ab_total += gr['ab_score']
                uv_total += gr['uv_score']
                total_rounds += gr['rounds']
                ab_depth_sum += gr.get('ab_avg_depth', 0)
                uv_depth_sum += gr.get('uv_avg_depth', 0)
                ab_depth_count += 1
                uv_depth_count += 1
                entry = {
                    'game': i + 1, 'winner': gr['winner'],
                    'ab_score': gr['ab_score'], 'uv_score': gr['uv_score'],
                    'rounds': gr['rounds'], 'first_team': gr['first_team'],
                    'ab_avg_depth': gr.get('ab_avg_depth', 0),
                    'uv_avg_depth': gr.get('uv_avg_depth', 0),
                    'ab_min_depth': gr.get('ab_min_depth', 0),
                    'ab_max_depth': gr.get('ab_max_depth', 0),
                    'uv_min_depth': gr.get('uv_min_depth', 0),
                    'uv_max_depth': gr.get('uv_max_depth', 0),
                    'ab_avg_time': gr.get('ab_avg_time', 0.0),
                    'uv_avg_time': gr.get('uv_avg_time', 0.0),
                    'ab_avg_time_pct': gr.get('ab_avg_time_pct'),
                    'uv_avg_time_pct': gr.get('uv_avg_time_pct'),
                    'ab_move_log': gr.get('ab_move_log', []),
                    'uv_move_log': gr.get('uv_move_log', []),
                }
                game_log.append({k: v for k, v in entry.items() if k not in ('ab_move_log', 'uv_move_log')})
                last_gr = gr
                yield json.dumps({
                    'type': 'progress',
                    'game': i + 1, 'total': games,
                    'ab_wins': ab_wins, 'uv_wins': uv_wins, 'draws': draws,
                    **entry,
                }) + '\n'

        played = ab_wins + uv_wins + draws
        n = played if played > 0 else 1
        summary = {
            'type': 'done', 'ok': True,
            'games': played, 'games_requested': games,
            'stopped': _battle_stop,
            'ab_wins': ab_wins, 'uv_wins': uv_wins, 'draws': draws,
            'ab_win_rate':  round(ab_wins / n * 100, 1),
            'uv_win_rate':  round(uv_wins / n * 100, 1),
            'draw_rate':    round(draws   / n * 100, 1),
            'avg_ab_score': round(ab_total / n, 1),
            'avg_uv_score': round(uv_total / n, 1),
            'avg_rounds':   round(total_rounds / n, 1),
            'ab_depth': ab_depth, 'uv_depth': uv_depth,
            'ab_strategy': ab_strategy, 'uv_strategy': uv_strategy,
            'ab_nmp': ab_nmp, 'uv_nmp': uv_nmp,
            'ab_nmp_r': ab_nmp_r, 'uv_nmp_r': uv_nmp_r,
            'ab_lmr': ab_lmr, 'uv_lmr': uv_lmr,
            'ab_lmr_min_depth': ab_lmr_min_depth, 'ab_lmr_move_index': ab_lmr_move_index,
            'uv_lmr_min_depth': uv_lmr_min_depth, 'uv_lmr_move_index': uv_lmr_move_index,
            'ab_parallel': ab_parallel, 'uv_parallel': uv_parallel,
            'game_workers': game_workers,
            'first_team': first_team,
            'game_log': game_log,
            'avg_ab_depth': round(ab_depth_sum / ab_depth_count, 1) if ab_depth_count > 0 else 0,
            'avg_uv_depth': round(uv_depth_sum / uv_depth_count, 1) if uv_depth_count > 0 else 0,
        }
        if last_gr:
            summary.update({
                'rounds': last_gr['rounds'], 'winner': last_gr['winner'],
                'ab_score': last_gr['ab_score'], 'uv_score': last_gr['uv_score'],
                'ab_moves': last_gr['ab_moves'], 'uv_moves': last_gr['uv_moves'],
                'state': last_gr['state'],
            })
        yield json.dumps(summary) + '\n'

    return Response(
        stream_with_context(generate()),
        mimetype='application/x-ndjson',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'},
    )


@app.route('/api/apply_ai_suggestion', methods=['POST'])
def api_apply_ai_suggestion():
    data = request.get_json()
    from_pos   = tuple(data['from_pos'])
    to_pos     = tuple(data['to_pos'])
    ai_elapsed = float(data.get('ai_elapsed', 0.0))

    # 用前端傳來的 AI 計算時間重建 timer，確保 move_time 只計 AI 思考耗時
    _game.turn_start_time = time.time() - ai_elapsed

    try:
        result = _game.make_move(from_pos, to_pos)
        _board_history_hashes.append(board_key(_game.board))
        result['state'] = _game.get_state()
        result['depth_reached'] = _last_depth_reached
        return jsonify({'ok': True, **result})
    except ValueError as e:
        _game.turn_start_time = None
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/suggest_relocation', methods=['POST'])
def api_suggest_relocation():
    if _game.move_history:
        return jsonify({'ok': False, 'error': 'Game already started'}), 400
    data = request.get_json() or {}
    try:
        depth = max(0, min(int(data.get('depth', 0)), 10))
    except (TypeError, ValueError):
        depth = 0
    moves_left = _game.max_rounds * 2  # no moves played yet — full 40 half-moves remain
    t0 = time.time()
    from_pos, to_pos, score = suggest_relocation(_game.board, 'UV', depth=depth, moves_left=moves_left, use_parallel=True)
    elapsed = round(time.time() - t0, 1)
    if from_pos is None:
        return jsonify({'ok': True, 'no_improvement': True,
                        'message': 'No relocation improves UV position', 'depth': depth, 'elapsed': elapsed})
    piece = _game.board.get(from_pos[0], from_pos[1])
    return jsonify({
        'ok': True,
        'no_improvement': False,
        'from_pos': list(from_pos),
        'to_pos': list(to_pos),
        'piece': piece,
        'score': round(score, 2),
        'depth': depth,
        'elapsed': elapsed,
    })


@app.route('/api/apply_relocation', methods=['POST'])
def api_apply_relocation():
    if _game.move_history:
        return jsonify({'ok': False, 'error': 'Game already started'}), 400
    data = request.get_json()
    from_pos = tuple(data['from_pos'])
    to_pos = tuple(data['to_pos'])
    r1, c1 = from_pos
    r2, c2 = to_pos
    piece = _game.board.get(r1, c1)
    if piece is None:
        return jsonify({'ok': False, 'error': 'No piece at source position'}), 400
    if _game.board.get(r2, c2) is not None:
        return jsonify({'ok': False, 'error': 'Destination is not empty'}), 400
    _game.board.set(r1, c1, None)
    _game.board.set(r2, c2, piece)
    return jsonify({'ok': True, 'state': _game.get_state()})


@app.route('/api/new_game', methods=['POST'])
def api_new_game():
    global _game
    _board_history_hashes.clear()
    _repetition_hashes.clear()
    data = request.get_json() or {}
    grid = data.get('grid')
    try:
        board = Board.from_grid(grid) if grid else Board()
        _game = Game(board=board)
        return jsonify({'ok': True, 'state': _game.get_state()})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

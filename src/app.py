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


# ── action API ──────────────────────────────────────────────────────────

@app.route('/api/move', methods=['POST'])
def api_move():
    data = request.get_json()
    from_pos = tuple(data['from_pos'])
    to_pos   = tuple(data['to_pos'])
    try:
        result = _game.make_move(from_pos, to_pos)
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
    total_pieces = sum(1 for r in range(8) for c in range(8) if board.get(r, c) is not None)
    return max(0.0, min(1.0, total_pieces / 24.0))


def moves_and_attacks(board, team):
    """Single pass: returns (total, captures, non_captures, attack_map, piece_move_counts) for team."""
    moves = board.all_legal_moves(team)
    capture_count = 0
    non_capture_count = 0
    attacks = defaultdict(int)
    piece_move_counts = defaultdict(int)
    for src, dest in moves:
        piece_move_counts[src] += 1
        attacks[dest] += 1
        if board.get(dest[0], dest[1]) is not None:
            capture_count += 1
        else:
            non_capture_count += 1
    return len(moves), capture_count, non_capture_count, attacks, piece_move_counts


def influence_map(board, team):
    counts = defaultdict(int)
    for r, c, piece in board.pieces(team):
        directions, max_steps = _PIECE_RULES[piece]
        for dr, dc in directions:
            for step in range(1, max_steps + 1):
                nr, nc = r + dr * step, c + dc * step
                if not (0 <= nr < 8 and 0 <= nc < 8):
                    break
                counts[(nr, nc)] += 1
                if board.get(nr, nc) is not None:
                    break
    return counts


def static_exchange_score(board, maximizing_team, own_attacks, opp_attacks, own_move_counts, opp_move_counts):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_support = own_attacks
    opp_support = opp_attacks

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

    own_moves, own_captures, own_non_capture, own_attacks, own_move_counts = moves_and_attacks(board, maximizing_team)
    opp_moves, opp_captures, opp_non_capture, opp_attacks, opp_move_counts = moves_and_attacks(board, opponent)
    own_influence = influence_map(board, maximizing_team)
    opp_influence = influence_map(board, opponent)

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
    score += static_exchange_score(board, maximizing_team, own_attacks, opp_attacks, own_move_counts, opp_move_counts)
    return score


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


def minimax(board, team, depth, maximizing_team, alpha=-float('inf'), beta=float('inf'), start_time=None, time_limit=None, transposition_table=None, history_heuristic=None, allow_null=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_pvs=True, use_mvv_lva=True):
    if time_limit is not None and start_time is not None:
        if time.time() - start_time >= time_limit:
            raise SearchTimeout()

    if depth == 0:
        return quiescence_search(board, team, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic, use_mvv_lva=use_mvv_lva)

    tt_key = (board_key(board), team, maximizing_team)
    if transposition_table is not None:
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
        own_count = sum(1 for r in range(8) for c in range(8)
                        if board.get(r, c) is not None and get_team(board.get(r, c)) == team)
        if own_count > 2:
            try:
                null_val = minimax(board, opponent, depth - 1 - nmp_r, maximizing_team,
                                   alpha, beta, start_time, time_limit,
                                   transposition_table, history_heuristic,
                                   allow_null=False, nmp_r=nmp_r,
                                   use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                                   use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)
                if null_val >= beta:
                    return beta
            except SearchTimeout:
                raise

    _mm_kwargs = dict(start_time=start_time, time_limit=time_limit,
                      transposition_table=transposition_table, history_heuristic=history_heuristic,
                      allow_null=allow_null, nmp_r=nmp_r,
                      use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                      use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)

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

    if transposition_table is not None:
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
    board_grid, from_pos, to_pos, max_depth, team, opponent, use_nmp, nmp_r, use_lmr, lmr_min_depth, lmr_move_index, start_time, time_limit, use_pvs, use_mvv_lva = args
    child = Board()
    child._grid = [list(row) for row in board_grid]
    child.apply_move(from_pos, to_pos)
    tt = {}
    hh = defaultdict(int)
    best_value = -float('inf')
    last_depth = 0
    for d in range(1, max_depth + 1):
        if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
            break
        try:
            val = minimax(child, opponent, d, team, -float('inf'), float('inf'),
                          start_time, time_limit, tt, hh,
                          allow_null=use_nmp, nmp_r=nmp_r,
                          use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
                          use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)
            best_value = val
            last_depth = d
        except SearchTimeout:
            break
    return (best_value, from_pos, to_pos, last_depth)


def choose_minimax_move(board, team, depth=MINIMAX_DEPTH, time_limit=None, use_nmp=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_parallel=False, use_asp=True, asp_window=ASPIRATION_WINDOW, use_pvs=True, use_mvv_lva=True):
    global _last_depth_reached
    moves = board.all_legal_moves(team)
    if not moves:
        return None

    if time_limit is not None and time_limit <= 0:
        time_limit = None

    start_time = time.time()

    # Parallel root search: each worker does iterative deepening with the shared deadline
    if use_parallel and depth > 1:
        opponent = 'UV' if team == 'AB' else 'AB'
        board_grid = tuple(tuple(row) for row in board._grid)
        args_list = [
            (board_grid, fp, tp, depth, team, opponent, use_nmp, nmp_r,
             use_lmr, lmr_min_depth, lmr_move_index, start_time, time_limit, use_pvs, use_mvv_lva)
            for fp, tp in moves
        ]
        with ProcessPoolExecutor() as executor:
            results = list(executor.map(_root_move_worker, args_list))
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

    for current_depth in range(1, depth + 1):
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
                value = minimax(child, opponent, current_depth - 1, team, asp_alpha, asp_beta, start_time, time_limit, transposition_table, history_heuristic, allow_null=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)
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
                        value = minimax(child, opponent, current_depth - 1, team, -float('inf'), float('inf'), start_time, time_limit, transposition_table, history_heuristic, allow_null=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)
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


def choose_move_by_strategy(board, team, strategy, depth=MINIMAX_DEPTH, time_limit=None, use_nmp=True, nmp_r=DEFAULT_NMP_R, use_lmr=True, lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, lmr_move_index=DEFAULT_LMR_MOVE_INDEX, use_parallel=False, use_asp=True, asp_window=ASPIRATION_WINDOW, use_pvs=True, use_mvv_lva=True):
    if strategy == 'random':
        moves = board.all_legal_moves(team)
        return random.choice(moves) if moves else None
    if strategy == 'greedy':
        return choose_greedy_move(board, team)
    return choose_minimax_move(board, team, depth=depth, time_limit=time_limit, use_nmp=use_nmp, nmp_r=nmp_r, use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index, use_parallel=use_parallel, use_asp=use_asp, asp_window=asp_window, use_pvs=use_pvs, use_mvv_lva=use_mvv_lva)


def play_ai_battle_game(ab_depth, uv_depth, rounds=20, time_limit=None, ab_strategy='minimax', uv_strategy='minimax', ab_nmp=True, uv_nmp=True, ab_nmp_r=DEFAULT_NMP_R, uv_nmp_r=DEFAULT_NMP_R, first_team='random', ab_lmr=True, uv_lmr=True, ab_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, ab_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, uv_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, uv_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, ab_parallel=False, uv_parallel=False, ab_asp=True, uv_asp=True, ab_asp_window=ASPIRATION_WINDOW, uv_asp_window=ASPIRATION_WINDOW, ab_pvs=True, uv_pvs=True, ab_mvv_lva=True, uv_mvv_lva=True):
    global _last_depth_reached
    board = Board.random_legal_board()
    game = Game(board=board)
    actual_first = random.choice(['AB', 'UV']) if first_team == 'random' else first_team
    second = 'UV' if actual_first == 'AB' else 'AB'
    game.current_team = actual_first
    game.turn_start_time = None

    ab_moves = []
    uv_moves = []
    ab_score = 0
    uv_score = 0
    round_number = 1
    ab_move_log = []
    uv_move_log = []

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
            _last_depth_reached = 0
            t0 = time.time()
            move = choose_move_by_strategy(game.board, team, strategy, depth, time_limit, use_nmp=nmp, nmp_r=nmp_r_val, use_lmr=lmr, lmr_min_depth=lmr_min, lmr_move_index=lmr_idx, use_parallel=parallel, use_asp=asp, asp_window=asp_w, use_pvs=pvs, use_mvv_lva=mvv_lva)
            move_time = time.time() - t0
            depth_reached = _last_depth_reached
            time_pct = round(move_time / time_limit * 100, 1) if time_limit else None
            if move is not None:
                from_pos, to_pos = move
                result = game.make_move(from_pos, to_pos)
                gain = PIECE_POINTS.get(result['captured'], 0) if result['captured'] else 0
                move_entry = {
                    'round': round_number,
                    'move': result['move'],
                    'depth': depth_reached,
                    'time': round(move_time, 3),
                    'time_pct': time_pct,
                    'captured': result['captured'],
                }
                if team == 'AB':
                    ab_score += gain
                    ab_moves.append(f"R{round_number} AB: {result['move']}")
                    ab_move_log.append(move_entry)
                else:
                    uv_score += gain
                    uv_moves.append(f"R{round_number} UV: {result['move']}")
                    uv_move_log.append(move_entry)
                any_move = True
        if not any_move:
            break

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


def simulate_ai_battle(ab_depth=MINIMAX_DEPTH, uv_depth=MINIMAX_DEPTH, games=10, rounds=20, time_limit=None, ab_strategy='minimax', uv_strategy='minimax', ab_nmp=True, uv_nmp=True, ab_nmp_r=DEFAULT_NMP_R, uv_nmp_r=DEFAULT_NMP_R, first_team='random', ab_lmr=True, uv_lmr=True, ab_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, ab_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, uv_lmr_min_depth=DEFAULT_LMR_MIN_DEPTH, uv_lmr_move_index=DEFAULT_LMR_MOVE_INDEX, ab_parallel=False, uv_parallel=False, ab_asp=True, uv_asp=True, ab_asp_window=ASPIRATION_WINDOW, uv_asp_window=ASPIRATION_WINDOW, ab_pvs=True, uv_pvs=True):
    results = {
        'games': games,
        'ab_wins': 0,
        'uv_wins': 0,
        'draws': 0,
        'ab_win_rate': 0.0,
        'uv_win_rate': 0.0,
        'draw_rate': 0.0,
        'ab_depth': ab_depth,
        'uv_depth': uv_depth,
        'ab_strategy': ab_strategy,
        'uv_strategy': uv_strategy,
        'ab_nmp': ab_nmp,
        'uv_nmp': uv_nmp,
        'ab_nmp_r': ab_nmp_r,
        'uv_nmp_r': uv_nmp_r,
        'first_team': first_team,
        'time_limit': time_limit,
    }

    last_result = None
    game_log = []
    ab_total_score = 0
    uv_total_score = 0
    total_rounds = 0

    for i in range(games):
        game_result = play_ai_battle_game(ab_depth, uv_depth, rounds=rounds, time_limit=time_limit, ab_strategy=ab_strategy, uv_strategy=uv_strategy, ab_nmp=ab_nmp, uv_nmp=uv_nmp, ab_nmp_r=ab_nmp_r, uv_nmp_r=uv_nmp_r, first_team=first_team, ab_lmr=ab_lmr, uv_lmr=uv_lmr, ab_lmr_min_depth=ab_lmr_min_depth, ab_lmr_move_index=ab_lmr_move_index, uv_lmr_min_depth=uv_lmr_min_depth, uv_lmr_move_index=uv_lmr_move_index, ab_parallel=ab_parallel, uv_parallel=uv_parallel, ab_asp=ab_asp, uv_asp=uv_asp, ab_asp_window=ab_asp_window, uv_asp_window=uv_asp_window, ab_pvs=ab_pvs, uv_pvs=uv_pvs)
        if game_result['winner'] == 'AB':
            results['ab_wins'] += 1
        elif game_result['winner'] == 'UV':
            results['uv_wins'] += 1
        else:
            results['draws'] += 1
        ab_total_score += game_result['ab_score']
        uv_total_score += game_result['uv_score']
        total_rounds += game_result['rounds']
        game_log.append({
            'game': i + 1,
            'winner': game_result['winner'],
            'ab_score': game_result['ab_score'],
            'uv_score': game_result['uv_score'],
            'rounds': game_result['rounds'],
            'first_team': game_result['first_team'],
        })
        last_result = game_result

    if games > 0:
        results['ab_win_rate'] = round(results['ab_wins'] / games * 100, 1)
        results['uv_win_rate'] = round(results['uv_wins'] / games * 100, 1)
        results['draw_rate'] = round(results['draws'] / games * 100, 1)
        results['avg_ab_score'] = round(ab_total_score / games, 1)
        results['avg_uv_score'] = round(uv_total_score / games, 1)
        results['avg_rounds'] = round(total_rounds / games, 1)
    else:
        results['avg_ab_score'] = 0.0
        results['avg_uv_score'] = 0.0
        results['avg_rounds'] = 0.0

    results['game_log'] = game_log

    if last_result is not None:
        results.update({
            'rounds': last_result['rounds'],
            'winner': last_result['winner'],
            'ab_score': last_result['ab_score'],
            'uv_score': last_result['uv_score'],
            'ab_moves': last_result['ab_moves'],
            'uv_moves': last_result['uv_moves'],
            'state': last_result['state'],
        })

    return results


def _game_worker(args):
    """Module-level worker for game-level parallelism. Move-level parallel is forced OFF."""
    (game_idx, ab_depth, uv_depth, time_limit, ab_strategy, uv_strategy,
     ab_nmp, uv_nmp, ab_nmp_r, uv_nmp_r, first_team,
     ab_lmr, uv_lmr, ab_lmr_min_depth, ab_lmr_move_index,
     uv_lmr_min_depth, uv_lmr_move_index,
     ab_asp, uv_asp, ab_asp_window, uv_asp_window, ab_pvs, uv_pvs,
     ab_mvv_lva, uv_mvv_lva) = args
    gr = play_ai_battle_game(
        ab_depth, uv_depth, rounds=20, time_limit=time_limit,
        ab_strategy=ab_strategy, uv_strategy=uv_strategy,
        ab_nmp=ab_nmp, uv_nmp=uv_nmp, ab_nmp_r=ab_nmp_r, uv_nmp_r=uv_nmp_r,
        first_team=first_team, ab_lmr=ab_lmr, uv_lmr=uv_lmr,
        ab_lmr_min_depth=ab_lmr_min_depth, ab_lmr_move_index=ab_lmr_move_index,
        uv_lmr_min_depth=uv_lmr_min_depth, uv_lmr_move_index=uv_lmr_move_index,
        ab_parallel=False, uv_parallel=False,
        ab_asp=ab_asp, uv_asp=uv_asp, ab_asp_window=ab_asp_window, uv_asp_window=uv_asp_window,
        ab_pvs=ab_pvs, uv_pvs=uv_pvs,
        ab_mvv_lva=ab_mvv_lva, uv_mvv_lva=uv_mvv_lva,
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

    try:
        time_limit     = None if time_limit is None else float(time_limit)
        nmp_r          = max(1, min(int(data.get('nmp_r',          DEFAULT_NMP_R)),          4))
        lmr_min_depth  = max(2, min(int(data.get('lmr_min_depth',  DEFAULT_LMR_MIN_DEPTH)),  10))
        lmr_move_index = max(1, min(int(data.get('lmr_move_index', DEFAULT_LMR_MOVE_INDEX)), 10))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Invalid parameter value.'}), 400

    _game.start_turn_timer()

    moves = _game.board.all_legal_moves(_game.current_team)
    if not moves:
        return jsonify({'ok': False, 'error': 'No legal moves available'}), 400

    depth = 50 if (time_limit and time_limit > 0) else MINIMAX_DEPTH
    move = choose_minimax_move(
        _game.board, _game.current_team,
        depth=depth, time_limit=time_limit,
        use_nmp=use_nmp, nmp_r=nmp_r,
        use_lmr=use_lmr, lmr_min_depth=lmr_min_depth, lmr_move_index=lmr_move_index,
        use_pvs=use_pvs, use_mvv_lva=use_mvv_lva, use_parallel=use_parallel,
    )
    if move is None:
        return jsonify({'ok': False, 'error': 'No valid AI move found.'}), 400
    from_pos, to_pos = move
    piece = _game.board.get(from_pos[0], from_pos[1])
    notation = Board.format_move(piece, from_pos, to_pos)

    # 開關關閉：只回傳 AI 建議，不移動棋子
    if not auto_apply:
        # 記錄 AI 真正的計算耗時，然後立刻停止 timer
        # 這樣人類決策時間不會被計入 move_time
        ai_elapsed = _game.get_elapsed_time()
        _game.turn_start_time = None
        return jsonify({
            'ok': True,
            'suggestion_only': True,
            'from_pos': from_pos,
            'to_pos': to_pos,
            'piece': piece,
            'move': notation,
            'ai_elapsed': ai_elapsed,
            'state': _game.get_state()
        })

    # 開關開啟：維持原本功能，AI 直接下棋
    try:
        result = _game.make_move(from_pos, to_pos)
        result['state'] = _game.get_state()
        result['suggestion_only'] = False
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
        time_limit = data.get('time_limit')
        time_limit = None if time_limit is None else float(time_limit)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Depth, game count, and time limit must be numbers.'}), 400

    max_depth = 50 if (time_limit and time_limit > 0) else 8
    ab_depth = max(1, min(ab_depth, max_depth))
    uv_depth = max(1, min(uv_depth, max_depth))
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
                (i, ab_depth, uv_depth, time_limit, ab_strategy, uv_strategy,
                 ab_nmp, uv_nmp, ab_nmp_r, uv_nmp_r, first_team,
                 ab_lmr, uv_lmr, ab_lmr_min_depth, ab_lmr_move_index,
                 uv_lmr_min_depth, uv_lmr_move_index,
                 ab_asp, uv_asp, ab_asp_window, uv_asp_window, ab_pvs, uv_pvs,
                 ab_mvv_lva, uv_mvv_lva)
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
                    ab_depth, uv_depth, rounds=20, time_limit=time_limit,
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
        result['state'] = _game.get_state()
        return jsonify({'ok': True, **result})
    except ValueError as e:
        _game.turn_start_time = None
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/new_game', methods=['POST'])
def api_new_game():
    global _game
    data = request.get_json() or {}
    grid = data.get('grid')
    try:
        board = Board.from_grid(grid) if grid else Board()
        _game = Game(board=board)
        return jsonify({'ok': True, 'state': _game.get_state()})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

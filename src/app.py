import os
import random
import time
from collections import defaultdict

from flask import Flask, jsonify, request, render_template

from .game import Game
from .board import Board, PIECE_POINTS, get_team


class SearchTimeout(Exception):
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(_BASE, 'templates'),
    static_folder=os.path.join(_BASE, 'static'),
)

_game = Game()


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


MINIMAX_DEPTH = 7

# 評估函式：L7 版本，包含材料、位置、行動力、威脅評估
PIECE_PST_TYPE = {
    'A': 'A', 'U': 'A',
    'B': 'B', 'V': 'B',
    'c': 'c', 'w': 'c',
    'd': 'd', 'x': 'd',
    'e': 'e', 'y': 'e',
    'f': 'f', 'z': 'f',
}

PIECE_SQUARE_TABLES = {
    'A': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'B': [
        [0,  0,  1,  1,  1,  1,  0,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [1,  2,  3,  3,  3,  3,  2,  1],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [1,  2,  3,  3,  3,  3,  2,  1],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  0,  1,  1,  1,  1,  0,  0],
    ],
    'c': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'd': [
        [0,  0,  0,  0,  0,  0,  0,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  2,  2,  2,  2,  1,  0],
        [0,  1,  1,  1,  1,  1,  1,  0],
        [0,  0,  0,  0,  0,  0,  0,  0],
    ],
    'e': [
        [0,  0,  0,  1,  1,  0,  0,  0],
        [0,  1,  1,  2,  2,  1,  1,  0],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [1,  2,  3,  4,  4,  3,  2,  1],
        [0,  1,  2,  3,  3,  2,  1,  0],
        [0,  1,  1,  2,  2,  1,  1,  0],
        [0,  0,  0,  1,  1,  0,  0,  0],
    ],
    'f': [
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


def piece_square_value(piece, row, col):
    base_type = PIECE_PST_TYPE.get(piece)
    if base_type is None:
        return 0
    table = PIECE_SQUARE_TABLES[base_type]
    return table[row][col]


def move_counts(board, team):
    moves = board.all_legal_moves(team)
    capture_moves = 0
    non_capture_moves = 0
    for _, dest in moves:
        if board.get(dest[0], dest[1]) is not None:
            capture_moves += 1
        else:
            non_capture_moves += 1
    return len(moves), capture_moves, non_capture_moves


def attack_map(board, team):
    from collections import defaultdict
    counts = defaultdict(int)
    for _, dest in board.all_legal_moves(team):
        counts[dest] += 1
    return counts


def mobility_score(board, maximizing_team):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_moves, own_captures, _ = move_counts(board, maximizing_team)
    opp_moves, opp_captures, _ = move_counts(board, opponent)
    return 0.08 * (own_moves - opp_moves) + 0.24 * (own_captures - opp_captures)


def threatened_score(board, maximizing_team):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_attacks = attack_map(board, maximizing_team)
    opp_attacks = attack_map(board, opponent)

    score = 0
    for r, c, piece in board.pieces(maximizing_team):
        attack_count = opp_attacks.get((r, c), 0)
        if attack_count:
            score -= PIECE_POINTS[piece] * min(attack_count, 3) * 0.28
    for r, c, piece in board.pieces(opponent):
        attack_count = own_attacks.get((r, c), 0)
        if attack_count:
            score += PIECE_POINTS[piece] * min(attack_count, 3) * 0.22
    return score


def activity_score(board, maximizing_team):
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'
    own_moves, own_captures, own_non_capture = move_counts(board, maximizing_team)
    opp_moves, opp_captures, opp_non_capture = move_counts(board, opponent)
    score = 0.05 * (own_moves - opp_moves)
    score += 0.18 * (own_captures - opp_captures)
    score += 0.1 * ((own_non_capture - opp_non_capture) / 2)
    return score


def evaluate_board(board, maximizing_team):
    score = 0
    opponent = 'UV' if maximizing_team == 'AB' else 'AB'

    for r in range(8):
        for c in range(8):
            piece = board.get(r, c)
            if piece is None:
                continue
            material = PIECE_POINTS[piece]
            pst = piece_square_value(piece, r, c)
            piece_value = material + 0.35 * pst
            if get_team(piece) == maximizing_team:
                score += piece_value
                if (r, c) in CENTER_SQUARES:
                    score += 0.12
            else:
                score -= piece_value
                if (r, c) in CENTER_SQUARES:
                    score -= 0.12

    score += mobility_score(board, maximizing_team)
    score += activity_score(board, maximizing_team)
    score += threatened_score(board, maximizing_team)
    return score


def board_key(board):
    return tuple(tuple(row) for row in board.to_dict())


def is_capture_move(board, move):
    _, to_pos = move
    return board.get(to_pos[0], to_pos[1]) is not None


def move_score(board, move, best_move=None, history_heuristic=None):
    from_pos, to_pos = move
    captured = board.get(to_pos[0], to_pos[1])
    capture_value = PIECE_POINTS.get(captured, 0) if captured is not None else 0
    row, col = to_pos
    center_distance = abs(row - 3.5) + abs(col - 3.5)
    history_bonus = 0
    if history_heuristic is not None:
        history_bonus = history_heuristic.get(move, 0)
    best_bonus = 10000 if move == best_move else 0
    return (best_bonus, capture_value * 100, history_bonus, -center_distance)


def order_moves(board, moves, transposition_table, history_heuristic, team, maximizing_team):
    tt_entry = transposition_table.get((board_key(board), team, maximizing_team)) if transposition_table is not None else None
    best_move = tt_entry.get('best_move') if tt_entry else None
    scored_moves = []
    for move in moves:
        score = move_score(board, move, best_move=best_move, history_heuristic=history_heuristic)
        scored_moves.append((score, move))
    scored_moves.sort(reverse=True)
    return [move for _, move in scored_moves]


def quiescence_search(board, team, maximizing_team, alpha, beta, start_time=None, time_limit=None, history_heuristic=None):
    if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
        raise SearchTimeout()

    stand_pat = evaluate_board(board, maximizing_team)
    if stand_pat >= beta:
        return beta
    alpha = max(alpha, stand_pat)

    moves = [move for move in board.all_legal_moves(team) if is_capture_move(board, move)]
    if not moves:
        return stand_pat

    moves = order_moves(board, moves, None, history_heuristic, team, maximizing_team)
    opponent = 'UV' if team == 'AB' else 'AB'

    for from_pos, to_pos in moves:
        if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
            raise SearchTimeout()
        child = board.copy()
        child.apply_move(from_pos, to_pos)
        score = quiescence_search(child, opponent, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic)
        if score >= beta:
            return beta
        alpha = max(alpha, score)
    return alpha


def minimax(board, team, depth, maximizing_team, alpha=-float('inf'), beta=float('inf'), start_time=None, time_limit=None, transposition_table=None, history_heuristic=None):
    if time_limit is not None and start_time is not None:
        if time.time() - start_time >= time_limit:
            raise SearchTimeout()

    if depth == 0:
        return quiescence_search(board, team, maximizing_team, alpha, beta, start_time, time_limit, history_heuristic)

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

    moves = order_moves(board, moves, transposition_table, history_heuristic, team, maximizing_team)
    opponent = 'UV' if team == 'AB' else 'AB'
    alpha_orig, beta_orig = alpha, beta

    if team == maximizing_team:
        best = -float('inf')
        best_move = None
        for from_pos, to_pos in moves:
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, start_time, time_limit, transposition_table, history_heuristic)
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
        for from_pos, to_pos in moves:
            if time_limit is not None and start_time is not None and time.time() - start_time >= time_limit:
                raise SearchTimeout()
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            value = minimax(child, opponent, depth - 1, maximizing_team, alpha, beta, start_time, time_limit, transposition_table, history_heuristic)
            if value < best:
                best = value
                best_move = (from_pos, to_pos)
            beta = min(beta, best)
            if beta <= alpha:
                if history_heuristic is not None and best_move is not None:
                    history_heuristic[best_move] += depth * depth
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


def choose_minimax_move(board, team, depth=MINIMAX_DEPTH, time_limit=None):
    moves = board.all_legal_moves(team)
    if not moves:
        return None

    if time_limit is not None and time_limit <= 0:
        time_limit = None

    start_time = time.time()
    opponent = 'UV' if team == 'AB' else 'AB'

    fallback_move = random.choice(moves)
    last_completed_moves = [fallback_move]
    transposition_table = {}
    history_heuristic = defaultdict(int)

    for current_depth in range(1, depth + 1):
        if time_limit is not None and time.time() - start_time >= time_limit:
            break

        best_value = -float('inf')
        current_moves = []
        ordered_moves = order_moves(board, moves, transposition_table, history_heuristic, team, team)

        try:
            for from_pos, to_pos in ordered_moves:
                if time_limit is not None and time.time() - start_time >= time_limit:
                    raise SearchTimeout()
                child = board.copy()
                child.apply_move(from_pos, to_pos)
                value = minimax(child, opponent, current_depth - 1, team, -float('inf'), float('inf'), start_time, time_limit, transposition_table, history_heuristic)
                if value > best_value:
                    best_value = value
                    current_moves = [(from_pos, to_pos)]
                elif value == best_value:
                    current_moves.append((from_pos, to_pos))
        except SearchTimeout:
            break

        if current_moves:
            last_completed_moves = current_moves
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


def play_ai_battle_game(ab_depth, uv_depth, rounds=20, time_limit=None):
    board = Board.random_legal_board()
    game = Game(board=board)
    game.current_team = 'AB'
    game.turn_start_time = None

    ab_moves = []
    uv_moves = []
    ab_score = 0
    uv_score = 0

    for round_number in range(1, rounds + 1):
        ab_move = None
        game.current_team = 'AB'
        if game.board.all_legal_moves('AB'):
            move = choose_minimax_move(game.board, 'AB', depth=ab_depth, time_limit=time_limit)
            if move is not None:
                from_pos, to_pos = move
                result = game.make_move(from_pos, to_pos)
                ab_score += PIECE_POINTS.get(result['captured'], 0) if result['captured'] is not None else 0
                ab_moves.append(f"R{round_number} AB: {result['move']}")
                ab_move = result

        uv_move = None
        game.current_team = 'UV'
        if game.board.all_legal_moves('UV'):
            move = choose_minimax_move(game.board, 'UV', depth=uv_depth, time_limit=time_limit)
            if move is not None:
                from_pos, to_pos = move
                result = game.make_move(from_pos, to_pos)
                uv_score += PIECE_POINTS.get(result['captured'], 0) if result['captured'] is not None else 0
                uv_moves.append(f"R{round_number} UV: {result['move']}")
                uv_move = result

        if ab_move is None and uv_move is None:
            break

    if ab_score > uv_score:
        winner = 'AB'
    elif uv_score > ab_score:
        winner = 'UV'
    else:
        winner = 'draw'

    return {
        'rounds': round_number,
        'winner': winner,
        'ab_score': ab_score,
        'uv_score': uv_score,
        'ab_moves': ab_moves,
        'uv_moves': uv_moves,
        'state': game.get_state(),
    }


def simulate_ai_battle(ab_depth=MINIMAX_DEPTH, uv_depth=MINIMAX_DEPTH, games=10, rounds=20, time_limit=None):
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
        'time_limit': time_limit,
    }

    last_result = None
    for _ in range(games):
        game_result = play_ai_battle_game(ab_depth, uv_depth, rounds=rounds, time_limit=time_limit)
        if game_result['winner'] == 'AB':
            results['ab_wins'] += 1
        elif game_result['winner'] == 'UV':
            results['uv_wins'] += 1
        else:
            results['draws'] += 1
        last_result = game_result

    if games > 0:
        results['ab_win_rate'] = round(results['ab_wins'] / games * 100, 1)
        results['uv_win_rate'] = round(results['uv_wins'] / games * 100, 1)
        results['draw_rate'] = round(results['draws'] / games * 100, 1)

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


@app.route('/api/ask_ai', methods=['POST'])
def api_ask_ai():
    data = request.get_json() or {}
    auto_apply = data.get('auto_apply', True)
    time_limit = data.get('time_limit')

    try:
        time_limit = None if time_limit is None else float(time_limit)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Time limit must be a number.'}), 400

    _game.start_turn_timer()

    moves = _game.board.all_legal_moves(_game.current_team)
    if not moves:
        return jsonify({'ok': False, 'error': 'No legal moves available'}), 400

    move = choose_minimax_move(_game.board, _game.current_team, time_limit=time_limit)
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

    if games < 1:
        return jsonify({'ok': False, 'error': 'Game count must be at least 1.'}), 400

    result = simulate_ai_battle(ab_depth=ab_depth, uv_depth=uv_depth, games=games, rounds=20, time_limit=time_limit)
    return jsonify({'ok': True, **result})


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

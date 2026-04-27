import os
import random
import time

from flask import Flask, jsonify, request, render_template

from .game import Game
from .board import Board, PIECE_POINTS, get_team

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


MINIMAX_DEPTH = 4

# 評估函式：簡單以棋子價值計分，自己的棋子加分、敵方棋子扣分
def evaluate_board(board, maximizing_team):
    score = 0
    for r in range(8):
        for c in range(8):
            piece = board.get(r, c)
            if piece is None:
                continue
            value = PIECE_POINTS[piece]
            if get_team(piece) == maximizing_team:
                score += value
            else:
                score -= value
    return score


def minimax(board, team, depth, maximizing_team):
    # 到達搜尋深度或無路可走時，回傳局面評分
    if depth == 0:
        return evaluate_board(board, maximizing_team)

    moves = board.all_legal_moves(team)
    if not moves:
        return evaluate_board(board, maximizing_team)

    opponent = 'UV' if team == 'AB' else 'AB'
    if team == maximizing_team:
        best = -float('inf')
        for from_pos, to_pos in moves:
            child = board.copy()
            child.apply_move(from_pos, to_pos)
            value = minimax(child, opponent, depth - 1, maximizing_team)
            best = max(best, value)
        return best

    best = float('inf')
    for from_pos, to_pos in moves:
        child = board.copy()
        child.apply_move(from_pos, to_pos)
        value = minimax(child, opponent, depth - 1, maximizing_team)
        best = min(best, value)
    return best


def choose_minimax_move(board, team, depth=MINIMAX_DEPTH):
    moves = board.all_legal_moves(team)
    best_value = -float('inf')
    best_moves = []
    opponent = 'UV' if team == 'AB' else 'AB'

    for from_pos, to_pos in moves:
        child = board.copy()
        child.apply_move(from_pos, to_pos)
        value = minimax(child, opponent, depth - 1, team)
        if value > best_value:
            best_value = value
            best_moves = [(from_pos, to_pos)]
        elif value == best_value:
            best_moves.append((from_pos, to_pos))

    return random.choice(best_moves) if best_moves else random.choice(moves)


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


def simulate_ai_battle(game, rounds=20):
    l3_team = random.choice(['AB', 'UV'])
    l2_team = 'UV' if l3_team == 'AB' else 'AB'

    game.current_team = 'AB'  # AB always starts in the battle
    game.turn_start_time = None

    ab_moves = []
    uv_moves = []
    ab_score = 0
    uv_score = 0

    for round_number in range(1, rounds + 1):
        # AB 先手
        ab_move = None
        game.current_team = 'AB'
        if game.board.all_legal_moves('AB'):
            chooser = choose_minimax_move if l3_team == 'AB' else choose_greedy_move
            from_pos, to_pos = chooser(game.board, 'AB')
            result = game.make_move(from_pos, to_pos)
            ab_score += PIECE_POINTS.get(result['captured'], 0) if result['captured'] is not None else 0
            ab_moves.append(f"R{round_number} AB: {result['move']}")
            ab_move = result

        # UV 後手
        uv_move = None
        game.current_team = 'UV'
        if game.board.all_legal_moves('UV'):
            chooser = choose_minimax_move if l3_team == 'UV' else choose_greedy_move
            from_pos, to_pos = chooser(game.board, 'UV')
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
        'l3_team': l3_team,
        'l2_team': l2_team,
        'state': game.get_state(),
    }


@app.route('/api/ask_ai', methods=['POST'])
def api_ask_ai():
    data = request.get_json() or {}
    auto_apply = data.get('auto_apply', True)

    _game.start_turn_timer()

    moves = _game.board.all_legal_moves(_game.current_team)
    if not moves:
        return jsonify({'ok': False, 'error': 'No legal moves available'}), 400

    from_pos, to_pos = choose_minimax_move(_game.board, _game.current_team)
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
    result = simulate_ai_battle(_game, rounds=20)
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

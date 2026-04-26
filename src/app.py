import os
import random

from flask import Flask, jsonify, request, render_template

from .game import Game
from .board import Board

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


@app.route('/api/ask_ai', methods=['POST'])
def api_ask_ai():
    _game.start_turn_timer()
    moves = _game.board.all_legal_moves(_game.current_team)
    if not moves:
        return jsonify({'ok': False, 'error': 'No legal moves available'}), 400
    from_pos, to_pos = random.choice(moves)
    try:
        result = _game.make_move(from_pos, to_pos)
        result['state'] = _game.get_state()
        return jsonify({'ok': True, **result})
    except ValueError as e:
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

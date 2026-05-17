# EZChess 加速計畫

## 進度總覽

| Stage | 內容 | 狀態 | Commit |
|-------|------|------|--------|
| Route A | evaluate_board 內消除重複 legal_moves 呼叫 | ✅ main | `4d10ce9` |
| B2 | MVV-LVA 吃子排序 + per-team A/B 測試開關 | ✅ main | `0c2352e` `2b4ae34` |
| 正常下棋 AI 設定 | Actions 卡片加策略設定，比賽用 | ✅ main | `02e6f93` |
| **B1** | **Board._grid → numpy int8** | 🔲 branch: `perf/numpy-board` | — |
| B3 | Futility Pruning | 🔲 待 B1 穩定後 | — |
| C | Numba JIT（選配，競賽後） | 🔲 — | — |

**規則：perf/numpy-board 在使用者確認可正常運行前，不合併進 main。**

---

## 效能對比方法（B1 前後比較）

B1 合入前，先在 main 跑一次基準：

```powershell
# 在 main branch 上：
.\.venv\Scripts\python.exe benchmark.py baseline-main --parallel
# 記下輸出的 Mean time（約 0.5-0.6s / 局面）
```

B1 實作完後，在 `perf/numpy-board` 再跑一次：

```powershell
# 在 perf/numpy-board branch 上：
.\.venv\Scripts\python.exe benchmark.py numpy-board --parallel
# 比較兩次的 Mean time
```

目標：`board.copy()` 和 `board.get()` 密集呼叫的場景應有 1.3-2× 加速。

---

## Stage B1：Board._grid 換 numpy int8

### 前提

- Route A 已完成（evaluate_board 不再重複呼叫 legal_moves）
- 所有 18 個 test 必須全過才算完成
- benchmark.py 結果不能比 main 慢

### 棋子整數編碼（固定對應，不可改動）

```python
PIECE_TO_INT = {
    'A': 1,  'B': 2,  'c': 3,  'd': 4,  'e': 5,  'f': 6,
    'U': 7,  'V': 8,  'w': 9,  'x': 10, 'y': 11, 'z': 12,
}
INT_TO_PIECE = {v: k for k, v in PIECE_TO_INT.items()}
# INT_TO_PIECE[0] = None（空格）
```

AB 隊：1-6，UV 隊：7-12，0：空格。判斷隊伍：`1 <= n <= 6` 為 AB，`7 <= n <= 12` 為 UV。

### board.py 逐方法改動

**`__init__`**：
```python
import numpy as np
def __init__(self):
    self._grid = np.zeros((8, 8), dtype=np.int8)
```

**`from_grid`**：
```python
board._grid[r, c] = PIECE_TO_INT[cell] if cell not in (None, '.', '+') else 0
```

**`copy`**（這是最高頻呼叫，也是最大收益）：
```python
def copy(self):
    new = Board()
    new._grid = self._grid.copy()   # np.copy，比 [row[:] for row in...] 快 5×
    return new
```

**`get`**：
```python
def get(self, row, col):
    v = int(self._grid[row, col])
    return INT_TO_PIECE[v] if v != 0 else None
```

**`set`**：
```python
def set(self, row, col, piece):
    self._grid[row, col] = PIECE_TO_INT[piece] if piece is not None else 0
```

**`pieces`**：
```python
def pieces(self, team):
    lo, hi = (1, 6) if team == 'AB' else (7, 12)
    rs, cs = np.where((self._grid >= lo) & (self._grid <= hi))
    for r, c in zip(rs.tolist(), cs.tolist()):
        yield r, c, INT_TO_PIECE[int(self._grid[r, c])]
```

**`legal_moves`**（內部用整數比較，不呼叫 get）：
```python
def legal_moves(self, row, col):
    piece_int = int(self._grid[row, col])
    if piece_int == 0:
        return []
    piece = INT_TO_PIECE[piece_int]
    team_lo, team_hi = (1, 6) if piece_int <= 6 else (7, 12)
    directions, max_steps = _PIECE_RULES[piece]
    moves = []
    for dr, dc in directions:
        for step in range(1, max_steps + 1):
            r, c = row + dr * step, col + dc * step
            if not (0 <= r < 8 and 0 <= c < 8):
                break
            target = int(self._grid[r, c])
            if target == 0:
                moves.append((r, c))
            elif not (team_lo <= target <= team_hi):
                moves.append((r, c))   # capture
                break
            else:
                break                  # blocked by own piece
    return moves
```

**`apply_move`**：
```python
def apply_move(self, from_pos, to_pos):
    r1, c1 = from_pos
    r2, c2 = to_pos
    piece_int    = int(self._grid[r1, c1])
    captured_int = int(self._grid[r2, c2])
    self._grid[r2, c2] = piece_int
    self._grid[r1, c1] = 0
    return INT_TO_PIECE[captured_int] if captured_int != 0 else None
```

**`display` / `to_dict`**：用 `INT_TO_PIECE` 轉換輸出字串，邏輯不變。

**`random_legal_board`**：呼叫 `board.set()` 不變，set 內部會轉碼。

### app.py 需要同步修改的地方

| 位置 | 現在 | 改成 |
|------|------|------|
| `board_key(board)` | `tuple(tuple(row) for row in board._grid)` | `board._grid.tobytes()` |
| `_root_move_worker` 序列化 | `board_grid = tuple(tuple(row) for row in board._grid)` | `board_grid = board._grid.copy()` |
| `_root_move_worker` 還原 | `child._grid = [list(row) for row in board_grid]` | `child._grid = board_grid.copy()` |
| `influence_map` 空格判斷 | `board.get(nr, nc) is not None` | `board._grid[nr, nc] != 0`（省略 get 呼叫） |
| `game_phase` 空格判斷 | `board.get(r, c) is not None` | `board._grid[r, c] != 0` |

### 驗收標準（合併前必須全過）

1. `pytest tests/ -v` → 18/18
2. `python run.py` → 開啟網頁，正常下棋、Ask AI 可用
3. `benchmark.py numpy-board` → Mean time ≤ main 的 baseline

---

## Stage B3：Futility Pruning（B1 穩定後）

**目標**：depth=1 的 MAX 節點，若 `static_eval + margin ≤ alpha`，跳過整個節點。

實作位置：`minimax()` 函式，在 `moves = order_moves(...)` 之後的移動迴圈裡。

```python
# 加在 MAX 節點移動迴圈頂部
FUTILITY_MARGIN = {1: 150, 2: 300}   # depth → margin，可調整
if (team == maximizing_team
        and depth in FUTILITY_MARGIN
        and not is_capture_move(board, (from_pos, to_pos))):
    static = evaluate_board(board, maximizing_team)
    if static + FUTILITY_MARGIN[depth] <= alpha:
        continue
```

**驗收**：AI Battle 勝率不退步（與 main 對比 20+ 局），再合入 main。

---

## Stage C（選配，競賽後）：Numba JIT

前提：B1 完成（numpy board）。最小可行方案：只 JIT `evaluate_board` 的 material+PST 迴圈。其餘 helper functions 複雜度高，不建議在競賽截止前嘗試。

---

## 分支管理記錄

```
main ── Route A (4d10ce9)
     ├─ Merge perf/mvv-lva (c5ec78e)
     └─ AI 設定面板 (02e6f93)
          └── perf/numpy-board  ← 當前工作分支（未合併）
```

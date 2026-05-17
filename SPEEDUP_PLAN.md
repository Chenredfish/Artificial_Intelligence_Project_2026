# EZChess 加速計畫（Route B 起）

這份文件規劃將 `Board` 換成 numpy 陣列的各個分段，
以及後續 Numba JIT 的選配路線。
每個 Stage 可以獨立合入 main，測試後再繼續下一段。

---

## 現狀說明

- Route A（已完成，main）：消除 `evaluate_board` 內重複的 `legal_moves` 呼叫
- 現在 `Board._grid` 是 `list[list[str|None]]`，所有操作走 Python 物件
- `board.get(r, c)` 每次都是 `self._grid[r][c]`，在深度搜索中呼叫幾十萬次

---

## Stage B1：Board 內部換 numpy int8，對外 API 不變

**目標**：把 `Board._grid` 從 `list[list[str|None]]` 換成 `numpy.ndarray(shape=(8,8), dtype=int8)`。
所有 `.get()` / `.set()` / `.pieces()` 等 public API 簽名不動，只改內部實作。

**編碼方案（建議）**：

| 值 | 意義 |
|----|------|
| 0  | 空格 |
| 1-6 | AB 隊棋子：A=1, B=2, c=3, d=4, e=5, f=6 |
| 7-12 | UV 隊棋子：U=7, V=8, w=9, x=10, y=11, z=12 |

需要兩個映射 dict（啟動時建立一次）：
```python
STR_TO_INT: dict[str, int8]   # 'A' -> 1, None -> 0
INT_TO_STR: dict[int8, str]   # 1 -> 'A', 0 -> None
```

**需要修改的檔案**：

- `src/board.py`（主要工作量）
  - `__init__`：`_grid = np.zeros((8,8), dtype=np.int8)`，解析字串時用 STR_TO_INT
  - `get(r, c)`：回傳 `INT_TO_STR[self._grid[r, c]]`
  - `set(r, c, piece)`：`self._grid[r, c] = STR_TO_INT[piece] if piece else 0`
  - `pieces(team)`：用 `np.argwhere` 篩出該隊棋子的格子
  - `copy()`：`np.copy(self._grid)` 比 list comprehension 快
  - `_grid` 存取的其他內部方法全部改用 numpy 索引

- `src/app.py`
  - `board_key(board)`：目前是 `tuple(tuple(row) for row in board._grid)`，
    numpy 版改為 `board._grid.tobytes()` 速度更快且結果唯一
  - `influence_map`：`board.get(nr, nc)` 可改為直接 `board._grid[nr, nc] != 0`

**預期收益**：
- `board.get()` / `board.set()`：3-5× 加速
- `board.copy()`：`np.copy` 比 list deepcopy 快約 5×
- `board_key()`（TT 查表）：`tobytes()` 比巢狀 tuple 快 3-4×

**風險**：
- 中等。`pieces()`、`all_legal_moves()` 等邏輯較複雜，需要仔細測試
- 建議：18 個現有 tests 必須全過才算完成

**工程量估計**：2-4 小時

---

## Stage B2：MVV-LVA 吃子排序

**目標**：在 `move_score()` 的吃子優先度加入攻擊方價值（Least Valuable Attacker）。

**現狀**：`capture_value * 100`，只看被吃子的價值。
若 A（高價值）去吃 f（低價值），排序跟 c（低價值）去吃 f 一樣。

**改動**：
```python
# 現在
capture_value = PIECE_POINTS.get(captured, 0) if captured is not None else 0
return (best_bonus, capture_value * 100, history_bonus, -center_distance)

# 改成 MVV-LVA
mvv = PIECE_POINTS.get(captured, 0) * 100 if captured else 0
lva = -EVAL_PIECE_WEIGHTS.get(board.get(from_pos[0], from_pos[1]), 0) if captured else 0
return (best_bonus, mvv + lva, history_bonus, -center_distance)
```

**原理**：優先嘗試「用小吃大」的走法，α-β 剪枝效率更高（更早產生 cutoff）。

**預期收益**：+0.2-0.4 有效層數，不增加任何計算量。

**風險**：低。只改排序，邏輯不變。

**工程量估計**：30 分鐘

---

## Stage B3：Futility Pruning（葉節點剪枝）

**目標**：在接近葉節點的位置，若當前局勢已落後超過一定邊界，跳過靜態評估直接 return。

**實作位置**：`minimax()` 函式中，`depth == 1` 或 `depth == 2` 時加入。

**概念**：
```python
# 在 minimax depth=1 的 MAX 節點：
if depth == 1 and not is_capture and not in_check:
    futility_margin = 200  # 可調整
    static_eval = evaluate_board(board, maximizing_team)
    if static_eval + futility_margin <= alpha:
        continue  # 這步棋不可能提升 alpha，跳過
```

**注意事項**：
- 只對非吃子移動套用（吃子有明確收益，不能剪）
- 需要一個「是否被將軍」的判斷，或保守一點只在 depth==1 用
- 和 LMR 不同：LMR 減少深度，Futility 是直接略過

**預期收益**：+0.3-0.5 有效層數（對局面明顯落後的節點省下大量計算）

**風險**：中等。若 margin 設太大可能跳過關鍵走法，需要用 AI Battle 驗證勝率不下降。

**工程量估計**：2-3 小時（含測試）

---

## Stage C（選配）：Numba JIT on evaluate_board

**前提**：Stage B1 完成（numpy 陣列的 board）。

**最小可行方案**：JIT 編譯 `evaluate_board` 的核心棋子迴圈。

**可以 JIT 的部分**（B1 完成後）：
```python
@numba.jit(nopython=True)
def _eval_material_pst(grid, piece_weights_arr, pst_arr, center_mask, near_center_mask, team_mask):
    # 純 numpy 操作的 8x8 迴圈
    score = 0.0
    for r in range(8):
        for c in range(8):
            p = grid[r, c]
            if p == 0:
                continue
            ...
    return score
```

**無法輕易 JIT 的部分**（需要大量重寫）：
- `moves_and_attacks`（呼叫 `all_legal_moves`，含複雜移動邏輯）
- `influence_map`（可以 JIT，但需要把 `_PIECE_RULES` 轉成 numpy）
- `static_exchange_score`、`mobility_score`（只是迴圈，不算難）

**建議策略**：
只 JIT `_eval_material_pst`（材料 + PST），這部分佔 evaluate_board 約 30-40% 的時間，改動最小。

**預期收益**：material+PST 部分加速 5-10×，整體 evaluate_board 加速約 1.5-2×。

**風險**：高。Numba 的 `nopython=True` 對型別非常嚴格，debug 難度高。
建議等到 B1/B2/B3 都穩定後再做，或競賽結束後做。

**工程量估計**：4-8 小時（含 debug）

---

## 建議執行順序

```
main
 └─ branch: perf/numpy-board
      Stage B2（30 min）→ 測試→ merge main
      Stage B1（半天）→ 測試 18 tests → merge main
      Stage B3（半天）→ AI Battle 勝率驗證 → merge main
      Stage C（選配，競賽後）
```

B2 最簡單且獨立，先做可以馬上得到移動排序的收益。
B1 是 B3 和 C 的基礎，但對 B2 不是前提。
B3 需要 AI Battle 勝率驗證，建議預留半天測試時間。

---

## 分支管理建議

每個 Stage 用一個 feature branch：
```
git checkout -b perf/mvv-lva       # Stage B2
git checkout -b perf/numpy-board   # Stage B1
git checkout -b perf/futility      # Stage B3
```

確認 18 tests 全過 + AI Battle 勝率不退步 → PR to main。

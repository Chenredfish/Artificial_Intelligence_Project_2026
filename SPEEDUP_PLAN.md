# EZChess 加速計畫

## 進度總覽

| Stage | 內容 | 狀態 | Commit |
|-------|------|------|--------|
| Route A | evaluate_board 內消除重複 legal_moves 呼叫 | ✅ main | `4d10ce9` |
| B2 | MVV-LVA 吃子排序 + per-team A/B 測試開關 | ✅ main | `0c2352e` `2b4ae34` |
| 正常下棋 AI 設定 | Actions 卡片加策略設定，比賽用 | ✅ main | `02e6f93` |
| **Piece List Cache** | **Board._ab_pieces/_uv_pieces — pieces() O(64)→O(6)** | ✅ main | `4d6a927` |
| B1 | Board._grid → numpy int8 | ❌ 放棄 | `perf/numpy-board` |
| C | Numba JIT | ❌ 放棄 | `perf/numpy-board` |
| **B3** | **Futility Pruning + Delta Pruning** | ❌ 放棄 | `perf/b3-pruning` |

---

## 已完成優化效果

### Piece List Cache（`4d6a927`，在 main）

- **原理**：Board 內維護 `_ab_pieces`/`_uv_pieces` 列表，`set`/`apply_move` 時同步更新
- **效果**：`pieces()` 從掃 64 格改為直接 yield 快取列表（O(6)）
- **實測（depth=5, 5 boards）**：

| 模式 | 舊 main | 新 main | 改善 |
|------|---------|---------|------|
| Sequential | 0.519s | 0.380s | **-27%** |
| Parallel | 1.760s | 1.458s | **-17%** |

- **預估深度增益**：parallel 60s 模式約 +0.1~0.2 depth（非整數，因為每多一層需 ~4× 節點）

### B1 + Numba JIT 評估結論（`perf/numpy-board` 分支，不合入 main）

- numpy board 對 8×8 小棋盤反而更慢（element access overhead > copy() 收益）
- Numba JIT 在 parallel 模式每個 worker process 重新載入 cache (~0.2-0.4s/worker × 8 workers)，淨負擔
- Profile 確認真正瓶頸是 `pieces()`（152,681 calls），不是 material loop

---

## 要穩定 +1 depth 需要多少加速

目前 parallel 60s 徘徊在 depth 7-8-9。每多一層需要約 4× 節點（有效分支因子含 alpha-beta 剪枝）。

| 累計節點減少 | 預估 depth 增益 |
|------------|--------------|
| -17%（piece list，已做） | +0.1~0.2 |
| -30%（+ B3 Futility） | +0.2~0.3 |
| -50%（+ Delta Pruning） | +0.4~0.5 |
| -75% | **穩定 +1** |

單靠剪枝難以一次達到 -75%。B3 + Delta 合計約 -40~50%，帶來 **+0.4~0.5 depth**，讓目前 7-8-9 推進到 8-9-10 的概率明顯提升。

---

## Stage B3：Futility Pruning + Delta Pruning（❌ 實驗失敗，已放棄）

### 實驗結論（perf/b3-pruning，2026-05-17）

**參數掃描結果（fixed depth=5, sequential）：**

| 設定 | Mean time | vs main | 正確性 |
|------|-----------|---------|--------|
| no-B3 | 0.378s | +2% | ✅ |
| F150/300 D200（lazy） | 0.380s | +3% | ✅ |
| F50/80 D30 | 0.384s | +4% | ✅ |
| F30/50 D20 | 0.381s | +3% | ✅ |
| F20/35 D15 | 0.701s | **+89%** | ❌ 1 move 錯誤 |
| F10/20 D10 | 0.569s | **+54%** | ❌ 1 move 錯誤 |
| F5/10 D5 | 0.477s | **+29%** | ❌ 2 moves 錯誤 |

**根本原因：** 本遊戲的 eval 函式（influence map + PST）一步 quiet move 可改變 20–50 分，
不滿足 Futility Pruning 的「quiet move 最多漲 N 分」前提。
margin 大 → 從不觸發（只有開銷）；margin 小 → 錯誤剪枝破壞 alpha-beta 效率。

**結論：** 不適用，`perf/b3-pruning` 存檔不合入。

---

## Stage B3：Futility Pruning + Delta Pruning（原始規格，保留參考）

### B3a：Futility Pruning（在 minimax 的移動迴圈頂部）

**位置**：`minimax()` 的 MAX 節點移動迴圈裡，非吃子 move 才適用。

```python
FUTILITY_MARGIN = {1: 150, 2: 300}

# 加在 MAX 節點的 for 移動迴圈頂部：
if (team == maximizing_team
        and depth in FUTILITY_MARGIN
        and board.get(to_pos[0], to_pos[1]) is None):   # 非吃子
    static = evaluate_board(board, maximizing_team)
    if static + FUTILITY_MARGIN[depth] <= alpha:
        continue
```

**預估效果**：depth=1/2 節點減少 20-30%，整體 -10~15%（因為大部分節點在更深層）。

### B3b：Delta Pruning（在 quiescence_search 的吃子迴圈頂部）

**位置**：`quiescence_search()` 中，在考慮每個吃子 move 之前。

```python
DELTA_MARGIN = 200  # 可調整

# 加在 quiescence 的吃子迴圈頂部（MAX 節點）：
if team == maximizing_team:
    captured_piece = board.get(to_pos[0], to_pos[1])
    if captured_piece is not None:
        gain = EVAL_PIECE_WEIGHTS.get(captured_piece, 0)
        if stand_pat + gain + DELTA_MARGIN <= alpha:
            continue   # 即使吃這個子也不夠翻盤，跳過
```

`stand_pat` 是進入 quiescence 時的靜態評估值（已有）。

**預估效果**：quiescence 節點減少 15-25%，整體 -10~15%。

### 驗收標準

1. `pytest tests/ -v` → 18/18
2. AI Battle：與舊 main 對比 30+ 局，勝率不退步
3. `benchmark.py --time=60 --parallel`：mean depth_reached 提升

---

## 分支管理記錄

```
main ── Route A (4d10ce9)
     ├─ Merge perf/mvv-lva (c5ec78e)
     ├─ AI 設定面板 (02e6f93)
     ├─ Piece List Cache (4d6a927)  ← 最新
     └── perf/numpy-board  ← 存檔，不合入
```

**下一步**：在 main 上直接實作 B3a（Futility Pruning），測試通過後接著做 B3b（Delta Pruning）。

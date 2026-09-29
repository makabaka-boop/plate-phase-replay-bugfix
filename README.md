# 薄板热扩散模拟器（Plate Heat Diffusion）

精确有理数求解的薄板热扩散模拟：Flask 后端逐帧返回全部结果，React 网格编辑器通过 Docker Compose 中的 `plate-api` / `plate-ui` 两个服务播放热图。

## 模拟规则

- 网格为 3～12 行 × 3～12 列，初温为 -100～100 的整数。
- 至多 30 条**阻断边**（正交相邻格之间的边，不传热）。
- 1～25 个时间步，边界模式：
  - `insulated`（绝热）：不与外界交换热量；
  - `fixed-zero`（零温）：边界格每条朝外的边与 0℃ 环境交换热量。
- 每一步对每条**未阻断内边**同步更新：

  ```
  flux = (T_a - T_b) / 4   # 从高温格流向低温格
  T_a' = T_a - flux,  T_b' = T_b + flux
  ```

  `fixed-zero` 下朝外的边等价于连向温度恒为 0 的格：`flux = T_cell / 4`。
- **所有通量基于同一步开始时的温度读取，更新写入全新网格**，杜绝边算边改邻格。
- 全部数值使用 Python `Fraction` 精确有理数计算，序列化为 `"分子/分母"` 字符串；绝热模式总温逐步严格守恒（测试断言）。

## 目录结构

```
backend/          Flask API + 精确模拟引擎 + pytest（含独立逐边通量对拍模型）
  app/simulation.py   校验 / 模拟 / 序列化
  app/api.py          /api/simulate、/api/constraints、/health
  tests/              pytest 用例
ui/               React + Vite 网格编辑器/热图播放器/单格曲线
  src/                App、GridEditor、HeatMap、CellChart
  tests/              Playwright 浏览器主流程测试
docker-compose.yml  plate-api（:5000）+ plate-ui（:8080）
```

## 一键运行（Docker Compose）

```bash
docker compose up --build
# UI:  http://localhost:8080
# API: http://localhost:5000/health
```

UI 容器内 nginx 把 `/api/*` 代理到 `plate-api:5000`。

## 本地开发

```bash
# 后端
cd backend
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:5000 app.api:app    # 或 python -m app.api

# 前端（Vite 会把 /api 代理到 VITE_API_TARGET，默认 http://localhost:5000）
cd ui
npm install
npm run dev                                 # http://localhost:5173
```

## 阶段设置

请求可带 `schedule` 数组；各项包含 `step`（从 1 开始）及可选的 `boundary`、`blocked_edges`，页面提供 JSON 编辑框。

## API

`POST /api/simulate`

```json
{
  "matrix": [[40, 0, 0], [40, 0, 0], [40, 0, 0]],
  "steps": 6,
  "boundary": "insulated",
  "blocked_edges": [[0, 0, 0, 1]]
}
```

`blocked_edges` 的每条边可写成 `[r1,c1,r2,c2]` 或 `[[r1,c1],[r2,c2]]`，顺序无关、自动去重。

响应：

```json
{
  "rows": 3, "cols": 3, "steps": 6, "boundary": "insulated",
  "frames": [[["40", "0", "0"], ...], ...],
  "boundary_flow": ["0", "0", ...],
  "total_temperature": ["120", ...],
  "blocked_edges": [[[0, 0], [0, 1]]]
}
```

- `frames`：`steps+1` 帧（第 0 帧为初温），每格是精确有理数字符串；
- `boundary_flow[t]`：第 t+1 步的边界**净**流量（正＝流向外界，负＝从环境吸热）；绝热时恒为 `"0"`；
- `total_temperature`：每帧总温。

非法输入返回 `400 {"error": "..."}`。

## 测试

```bash
# 后端：独立“逐格逐边通量”参考模型对拍随机工况 + 守恒/校验/API 用例
cd backend && python -m pytest -q

# 浏览器主流程（核对页面帧 == 服务帧、阻断边与画面一致、编辑后旧帧失效）
cd ui && npx playwright install chromium && npx playwright test
```

### 关键正确性保证

1. **引擎对拍**：生产引擎按“无向内边列表”累计通量；测试中的参考模型对每格四个方向独立枚举通量（含阻断/外界判定），两者在 40 组随机矩阵 × 步数 × 阻断边 × 两种边界下逐 `Fraction` 相等。
2. **守恒**：绝热模式每帧总温等于初始总温；零温模式 `总温(t) - 总温(t+1) == boundary_flow[t]`。
3. **同步更新**：每步从旧网格只读、写入新网格（单角格一步得 2、对角邻居一步仍为 0 的用例锁定该语义）。
4. **浏览器**：逐格比对 DOM 上的 `data-value` 与服务帧浮点值；断言阻断条数量/位置；编辑后播放器整体卸载、进行中的 fetch 通过 `AbortController` + 单调请求序号作废，旧响应不可能覆盖新状态。

## 页面功能

- 整数初温矩阵编辑（行列 3～12，带范围校验）；
- 「编辑阻断边」模式下点击任意内边切换阻断（粗黑条显示，上限 30）；
- 运行后播放/暂停/步进/拖动帧、调速；
- 点击热图格子切换该格的逐帧温度曲线（最多 8 条）；
- 每步总温与边界净流量表格；
- 任何编辑立即废弃当前结果与在途请求，提示重新运行。

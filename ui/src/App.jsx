import { useMemo, useRef, useState } from "react";
import { simulate } from "./lib/api.js";
import { edgeKey, formatFrac, normalizeEdge } from "./lib/heat.js";
import GridEditor from "./components/GridEditor.jsx";
import { Player } from "./components/HeatMap.jsx";
import CellChart from "./components/CellChart.jsx";

const MAX_SELECTED = 8;

function makeMatrix(rows, cols, fill = 0) {
  return Array.from({ length: rows }, () => Array(cols).fill(fill));
}

function resizeMatrix(matrix, rows, cols) {
  const next = makeMatrix(rows, cols, 0);
  for (let r = 0; r < Math.min(rows, matrix.length); r++) {
    for (let c = 0; c < Math.min(cols, matrix[r].length); c++) {
      next[r][c] = matrix[r][c];
    }
  }
  return next;
}

/** Drop blocked edges that no longer exist after a resize. */
function trimEdges(edges, rows, cols) {
  return edges.filter(([a, b]) => {
    for (const [r, c] of [a, b]) {
      if (r < 0 || r >= rows || c < 0 || c >= cols) return false;
    }
    return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;
  });
}

export default function App() {
  const [rows, setRows] = useState(3);
  const [cols, setCols] = useState(4);
  const [matrix, setMatrix] = useState(() => [
    [40, 0, 0, 0],
    [40, 0, 0, 0],
    [40, 0, 0, 0],
  ]);
  const [steps, setSteps] = useState(6);
  const [boundary, setBoundary] = useState("insulated");
  const [blockedEdges, setBlockedEdges] = useState([]);
  const [scheduleText, setScheduleText] = useState("[]");
  const [edgeMode, setEdgeMode] = useState(false);
  const [editing, setEditing] = useState(false);

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [selectedCells, setSelectedCells] = useState([[0, 0]]);

  // Monotonic sequence + AbortController: stale responses (and in-flight
  // requests from before an edit) can never overwrite the current state.
  const requestSeq = useRef(0);
  const abortRef = useRef(null);

  function markEdited() {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = null;
    requestSeq.current += 1;
    setResult(null);
    setLoading(false);
    setError(null);
    setEditing(true);
  }

  function changeRows(nextRows) {
    const r = Math.max(3, Math.min(12, Number(nextRows) || 3));
    setRows(r);
    setMatrix((m) => resizeMatrix(m, r, cols));
    setBlockedEdges((e) => trimEdges(e, r, cols));
    markEdited();
  }

  function changeCols(nextCols) {
    const c = Math.max(3, Math.min(12, Number(nextCols) || 3));
    setCols(c);
    setMatrix((m) => resizeMatrix(m, rows, c));
    setBlockedEdges((e) => trimEdges(e, rows, c));
    markEdited();
  }

  function changeTemp(r, c, raw) {
    setMatrix((m) => {
      const next = m.map((row) => row.slice());
      // Keep raw text so intermediate states like "-" or "" remain typeable.
      next[r][c] = raw === "" ? "" : Number(raw);
      return next;
    });
    markEdited();
  }

  function fillAll(value) {
    setMatrix(makeMatrix(rows, cols, value));
    markEdited();
  }

  function toggleEdge(edge) {
    const normalized = normalizeEdge(edge[0], edge[1]);
    const key = edgeKey(normalized);
    setBlockedEdges((current) => {
      const present = current.some((e) => edgeKey(e) === key);
      if (present) return current.filter((e) => edgeKey(e) !== key);
      if (current.length >= 30) return current; // hard cap
      return [...current, normalized];
    });
    markEdited();
  }

  function toggleCell(cell) {
    setSelectedCells((current) => {
      const key = `${cell[0]},${cell[1]}`;
      const present = current.some(([r, c]) => `${r},${c}` === key);
      if (present) return current.filter(([r, c]) => `${r},${c}` !== key);
      if (current.length >= MAX_SELECTED) return current;
      return [...current, cell];
    });
  }

  function validateInput() {
    if (!Number.isInteger(rows) || !Number.isInteger(cols)) {
      return "行列数必须是整数";
    }
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const v = matrix[r][c];
        if (v === "" || !Number.isInteger(v)) {
          return `第 ${r + 1} 行第 ${c + 1} 列必须填写整数初温`;
        }
        if (v < -100 || v > 100) {
          return `第 ${r + 1} 行第 ${c + 1} 列初温 ${v} 超出 -100～100`;
        }
      }
    }
    if (!Number.isInteger(steps) || steps < 1 || steps > 25) {
      return "时间步数必须为 1～25 的整数";
    }
    if (blockedEdges.length > 30) return "阻断边至多 30 条";
    return null;
  }

  async function runSimulation() {
    const validationError = validateInput();
    if (validationError) {
      setError(validationError);
      return;
    }

    let schedule;
    try {
      schedule = JSON.parse(scheduleText);
    } catch {
      setError("阶段设置不是合法 JSON：请检查语法（需要一个数组，例如 [{\"step\":2}]）");
      return;
    }
    if (!Array.isArray(schedule)) {
      setError("阶段设置必须是 JSON 数组，每项形如 {\"step\":2,\"boundary\":\"fixed-zero\"}");
      return;
    }

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;

    const payload = {
      matrix: matrix.map((row) => row.map((v) => Number(v))),
      steps,
      boundary,
      blocked_edges: blockedEdges.map(([a, b]) => [
        a[0],
        a[1],
        b[0],
        b[1],
      ]),
      schedule,
    };

    setLoading(true);
    setError(null);
    try {
      const data = await simulate(payload, controller.signal);
      // Stale guard: a newer edit/run invalidated this response.
      if (seq !== requestSeq.current) return;
      setResult(data);
      setSelectedCells((cells) =>
        cells.filter(([r, c]) => r < data.rows && c < data.cols).slice(0, MAX_SELECTED)
      );
      setEditing(false);
    } catch (err) {
      if (err.name === "AbortError") return;
      if (seq !== requestSeq.current) return;
      setError(err.message);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }

  const totals = useMemo(
    () => (result ? result.total_temperature.map((v) => formatFrac(v, 4)) : []),
    [result]
  );
  const flows = useMemo(
    () => (result ? result.boundary_flow.map((v) => formatFrac(v, 4)) : []),
    [result]
  );
  // Per-frame active settings (schedules); identical across frames without one.
  const frameSettings = useMemo(
    () =>
      result
        ? result.frame_settings ??
          Array.from({ length: result.steps + 1 }, () => ({
            boundary: result.boundary,
            blocked_edges: result.blocked_edges,
          }))
        : [],
    [result]
  );
  const boundaryLabel = (mode) =>
    mode === "fixed-zero" ? "零温" : "绝热";

  return (
    <div className="app">
      <header>
        <h1>薄板热扩散模拟器</h1>
        <p className="subtitle">
          每步沿未阻断内边传递温差的四分之一 · 有理数精确求解 · 同步更新
        </p>
      </header>

      <div className="layout">
        <section className="panel editor-panel">
          <h2>网格编辑器</h2>

          <div className="form-row">
            <label>
              行数
              <input
                type="number"
                min={3}
                max={12}
                value={rows}
                data-testid="input-rows"
                onChange={(e) => changeRows(e.target.value)}
              />
            </label>
            <label>
              列数
              <input
                type="number"
                min={3}
                max={12}
                value={cols}
                data-testid="input-cols"
                onChange={(e) => changeCols(e.target.value)}
              />
            </label>
            <label>
              时间步
              <input
                type="number"
                min={1}
                max={25}
                value={steps}
                data-testid="input-steps"
                onChange={(e) => {
                  setSteps(Number(e.target.value));
                  markEdited();
                }}
              />
            </label>
          </div>

          <div className="form-row">
            <span className="field-label">边界模式</span>
            <label className="radio-label">
              <input
                type="radio"
                name="boundary"
                value="insulated"
                checked={boundary === "insulated"}
                onChange={() => {
                  setBoundary("insulated");
                  markEdited();
                }}
              />
              绝热 insulated
            </label>
            <label className="radio-label">
              <input
                type="radio"
                name="boundary"
                value="fixed-zero"
                checked={boundary === "fixed-zero"}
                onChange={() => {
                  setBoundary("fixed-zero");
                  markEdited();
                }}
              />
              零温 fixed-zero
            </label>
          </div>

          <div className="form-row">
            <button
              type="button"
              className={"toggle-edge" + (edgeMode ? " active" : "")}
              data-testid="edge-mode"
              onClick={() => setEdgeMode((v) => !v)}
            >
              {edgeMode ? "退出阻断边模式" : "编辑阻断边"}
            </button>
            <span className="hint" data-testid="edge-count">
              已阻断 {blockedEdges.length} / 30 条边
            </span>
          </div>

          <GridEditor
            rows={rows}
            cols={cols}
            matrix={matrix}
            blockedEdges={blockedEdges}
            edgeMode={edgeMode}
            onTempChange={changeTemp}
            onToggleEdge={toggleEdge}
          />

          <label className="form-row">
            阶段设置（JSON 数组）
            <textarea
              data-testid="schedule-input"
              value={scheduleText}
              onChange={(e) => {
                setScheduleText(e.target.value);
                markEdited();
              }}
            />
          </label>

          <div className="form-row">
            <button type="button" onClick={() => fillAll(0)}>
              全部置 0
            </button>
            <button
              type="button"
              data-testid="clear-edges"
              onClick={() => {
                setBlockedEdges([]);
                markEdited();
              }}
            >
              清除全部阻断边
            </button>
          </div>

          <button
            type="button"
            className="run-button"
            data-testid="run-button"
            onClick={runSimulation}
            disabled={loading}
          >
            {loading ? "计算中…" : "运行模拟"}
          </button>

          {error && (
            <div className="error-box" data-testid="error-box">
              {error}
            </div>
          )}
          {editing && !loading && !error && (
            <div className="stale-hint" data-testid="stale-hint">
              参数已修改，请重新运行模拟以获取新结果。
            </div>
          )}
        </section>

        <div className="results">
          {!result && !loading && (
            <section className="panel placeholder" data-testid="placeholder">
              <h2>热图播放</h2>
              <p className="hint">编辑初温矩阵后点击「运行模拟」。</p>
            </section>
          )}
          {result && (
            <Player
              result={result}
              selectedCells={selectedCells}
              onToggleCell={toggleCell}
            />
          )}

          {result && (
            <section className="panel" data-testid="stats-panel">
              <h2>守恒量与边界通量</h2>
              <div className="stats-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>时间步</th>
                      <th>总温</th>
                      <th>该步边界设置</th>
                      <th>该步边界净流量（+ 表示流向外界）</th>
                    </tr>
                  </thead>
                  <tbody>
                    {totals.map((total, t) => {
                      const setting = frameSettings[t];
                      const edgeCount = setting.blocked_edges.length;
                      return (
                        <tr key={t} data-testid={`stats-row-${t}`}>
                          <td>{t}</td>
                          <td>{total}</td>
                          <td data-testid={`stats-mode-${t}`}>
                            {boundaryLabel(setting.boundary)} · 阻断 {edgeCount} 条
                          </td>
                          <td>{t === 0 ? "—" : flows[t - 1]}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="hint" data-testid="conservation-hint">
                逐行可复核：总温(t) − 总温(t+1) = 第 t+1 步净流量；绝热阶段总温严格守恒，零温阶段总温减少量等于净流量。
              </p>
            </section>
          )}

          {result && (
            <CellChart
              result={result}
              selectedCells={selectedCells}
              onRemoveCell={toggleCell}
            />
          )}
        </div>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { edgeKey, fracToNumber, heatColor, normalizeEdge } from "../lib/heat.js";

/**
 * Read-only heatmap for one frame plus the blocked-edge overlay. Cells can be
 * clicked to toggle their per-cell temperature curve.
 */
export default function HeatMap({
  rows,
  cols,
  frame,
  blockedEdges,
  selectedCells,
  onToggleCell,
  stepIndex,
}) {
  const blockedSet = useMemo(
    () => new Set(blockedEdges.map(edgeKey)),
    [blockedEdges]
  );

  const internalEdges = useMemo(() => {
    const list = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (c + 1 < cols) list.push([[r, c], [r, c + 1]]);
        if (r + 1 < rows) list.push([[r, c], [r + 1, c]]);
      }
    }
    return list;
  }, [rows, cols]);

  const selectedSet = useMemo(
    () => new Set(selectedCells.map(([r, c]) => `${r},${c}`)),
    [selectedCells]
  );

  return (
    <div
      className="plate-wrap"
      style={{ aspectRatio: `${cols} / ${rows}` }}
      data-testid="heatmap"
    >
      <div
        className="cell-grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
        }}
      >
        {frame.map((row, r) =>
          row.map((value, c) => {
            const selected = selectedSet.has(`${r},${c}`);
            return (
              <button
                type="button"
                key={`${r}-${c}`}
                className={"heat-cell" + (selected ? " heat-cell-selected" : "")}
                style={{ backgroundColor: heatColor(value) }}
                data-testid={`heat-${r}-${c}`}
                data-r={r}
                data-c={c}
                data-value={fracToNumber(value)}
                title={`(${r},${c}) = ${value}`}
                onClick={() => onToggleCell([r, c])}
              >
                <span className="heat-value">
                  {Math.abs(fracToNumber(value)) < 0.05 &&
                  fracToNumber(value) !== 0
                    ? fracToNumber(value).toFixed(2)
                    : value}
                </span>
              </button>
            );
          })
        )}
      </div>

      <svg
        className="edge-layer"
        viewBox={`0 0 ${cols} ${rows}`}
        preserveAspectRatio="none"
      >
        {internalEdges.map(([a, b]) => {
          const [ea, eb] = normalizeEdge(a, b);
          const blocked = blockedSet.has(edgeKey([ea, eb]));
          if (!blocked) return null;
          const sameRow = ea[0] === eb[0];
          const thickness = 0.07;
          const rect = sameRow
            ? {
                x: ea[1] + 1 - thickness / 2,
                y: ea[0],
                width: thickness,
                height: 1,
              }
            : {
                x: ea[1],
                y: ea[0] + 1 - thickness / 2,
                width: 1,
                height: thickness,
              };
          return (
            <rect
              key={edgeKey([ea, eb])}
              {...rect}
              className="edge edge-blocked"
            />
          );
        })}
      </svg>
    </div>
  );
}

/**
 * Player with play/pause, step slider and a timer that only advances frames
 * from the currently accepted server response. Editing invalidates the
 * response in the parent, which unmounts this component entirely.
 */
export function Player({ result, selectedCells, onToggleCell }) {
  const steps = result.steps;
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [intervalMs, setIntervalMs] = useState(700);
  const timerRef = useRef(null);

  // Any time a new result arrives, restart playback from frame 0.
  useEffect(() => {
    setIndex(0);
    setPlaying(false);
  }, [result]);

  useEffect(() => {
    if (!playing) return undefined;
    timerRef.current = setInterval(() => {
      setIndex((prev) => (prev < steps ? prev + 1 : prev));
    }, intervalMs);
    return () => clearInterval(timerRef.current);
  }, [playing, intervalMs, steps]);

  // Stop automatically once the last frame is reached.
  useEffect(() => {
    if (playing && index >= steps) setPlaying(false);
  }, [playing, index, steps]);

  const frame = result.frames[index];

  // Settings actually in force for the displayed frame (the ones used by the
  // engine to produce this frame). Fall back to the top-level set for older
  // responses that predate frame_settings.
  const frameSettings =
    (result.frame_settings && result.frame_settings[index]) || null;
  const blockedEdges = frameSettings
    ? frameSettings.blocked_edges
    : result.blocked_edges;
  const boundaryMode = frameSettings
    ? frameSettings.boundary
    : result.boundary;

  return (
    <section className="panel" data-testid="player">
      <h2>热图播放</h2>
      <HeatMap
        rows={result.rows}
        cols={result.cols}
        frame={frame}
        blockedEdges={blockedEdges}
        selectedCells={selectedCells}
        onToggleCell={onToggleCell}
        stepIndex={index}
      />

      <div className="frame-settings" data-testid="frame-settings">
        <span>
          第 {index} 帧设置：
          {boundaryMode === "fixed-zero" ? "零温边界" : "绝热边界"} · 阻断边{" "}
          {blockedEdges.length} 条
        </span>
        {index < steps && (
          <span className="hint">
            （以上设置在第 {index + 1} 步开始时生效，决定本帧）
          </span>
        )}
      </div>

      <div className="player-controls">
        <button
          type="button"
          data-testid="play-button"
          onClick={() => {
            if (index >= steps) setIndex(0);
            setPlaying((p) => !p);
          }}
        >
          {playing ? "暂停" : "播放"}
        </button>
        <button type="button" onClick={() => setIndex(0)} disabled={index === 0}>
          首帧
        </button>
        <button
          type="button"
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0}
        >
          上一步
        </button>
        <span className="step-label" data-testid="step-label">
          第 {index} / {steps} 步
        </span>
        <button
          type="button"
          onClick={() => setIndex((i) => Math.min(steps, i + 1))}
          disabled={index === steps}
        >
          下一步
        </button>
        <input
          type="range"
          min={0}
          max={steps}
          value={index}
          data-testid="step-slider"
          onChange={(e) => {
            setPlaying(false);
            setIndex(Number(e.target.value));
          }}
        />
        <label className="speed-label">
          速度
          <select
            value={intervalMs}
            onChange={(e) => setIntervalMs(Number(e.target.value))}
          >
            <option value={1200}>慢</option>
            <option value={700}>中</option>
            <option value={300}>快</option>
          </select>
        </label>
      </div>
    </section>
  );
}

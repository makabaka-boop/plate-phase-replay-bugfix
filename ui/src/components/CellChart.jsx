import { fracToNumber } from "../lib/heat.js";

const PALETTE = [
  "#b30000",
  "#0059b3",
  "#2d8f2d",
  "#a64dff",
  "#e68a00",
  "#009999",
  "#cc0066",
  "#5c5c00",
];

/**
 * Per-cell temperature curves for every frame. Data is read directly from the
 * server frames (exact fraction strings converted to numbers), so the curves
 * always agree with the heatmap rather than with any client-side math.
 */
export default function CellChart({ result, selectedCells, onRemoveCell }) {
  if (selectedCells.length === 0) {
    return (
      <section className="panel" data-testid="cell-chart">
        <h2>单格温度曲线</h2>
        <p className="hint">点击热图中的格子即可在此显示它随时间的温度曲线。</p>
      </section>
    );
  }

  const W = 520;
  const H = 240;
  const PAD = 42;
  const steps = result.steps;

  const series = selectedCells.map(([r, c]) => ({
    r,
    c,
    values: result.frames.map((frame) => fracToNumber(frame[r][c])),
  }));

  let min = Math.min(0, ...series.flatMap((s) => s.values));
  let max = Math.max(0, ...series.flatMap((s) => s.values));
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  min -= span * 0.08;
  max += span * 0.08;

  const x = (t) => PAD + (t / steps) * (W - 2 * PAD);
  const y = (v) => H - PAD - ((v - min) / (max - min)) * (H - 2 * PAD);

  const zeroY = y(0);

  return (
    <section className="panel" data-testid="cell-chart">
      <h2>单格温度曲线</h2>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart"
        role="img"
        aria-label="单格温度随时间变化曲线"
      >
        {/* zero baseline */}
        <line
          x1={PAD}
          x2={W - PAD}
          y1={zeroY}
          y2={zeroY}
          className="chart-zero"
        />
        {/* y axis labels */}
        {[max, (max + min) / 2, min].map((v, i) => (
          <text key={i} x={4} y={y(v) + 4} className="chart-tick">
            {v.toFixed(1)}
          </text>
        ))}
        {/* x axis labels */}
        {Array.from({ length: steps + 1 }, (_, t) =>
          t % Math.max(1, Math.ceil(steps / 8)) === 0 || t === steps ? (
            <text key={t} x={x(t) - 6} y={H - PAD + 18} className="chart-tick">
              {t}
            </text>
          ) : null
        )}
        {series.map((s, i) => {
          const color = PALETTE[i % PALETTE.length];
          const d = s.values
            .map((v, t) => `${t === 0 ? "M" : "L"} ${x(t)} ${y(v)}`)
            .join(" ");
          return (
            <g key={`${s.r}-${s.c}`}>
              <path d={d} fill="none" stroke={color} strokeWidth={2} />
              {s.values.map((v, t) => (
                <circle key={t} cx={x(t)} cy={y(v)} r={2.5} fill={color} />
              ))}
            </g>
          );
        })}
      </svg>
      <ul className="legend">
        {series.map((s, i) => (
          <li key={`${s.r}-${s.c}`}>
            <span
              className="legend-swatch"
              style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
            />
            行 {s.r + 1}，列 {s.c + 1}（{s.values[s.values.length - 1].toFixed(3)}）
            <button
              type="button"
              className="legend-remove"
              data-testid={`remove-cell-${s.r}-${s.c}`}
              onClick={() => onRemoveCell([s.r, s.c])}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

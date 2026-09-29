import { edgeKey, normalizeEdge } from "../lib/heat.js";

/**
 * Matrix editor. Rows of integer temperature inputs with an SVG overlay of
 * internal edges: in "edge mode" every internal edge is a clickable bar,
 * blocked edges are drawn as thick dark bars.
 */
export default function GridEditor({
  rows,
  cols,
  matrix,
  blockedEdges,
  edgeMode,
  onTempChange,
  onToggleEdge,
}) {
  const blockedSet = new Set(blockedEdges.map(edgeKey));

  const internalEdges = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (c + 1 < cols) internalEdges.push([[r, c], [r, c + 1]]);
      if (r + 1 < rows) internalEdges.push([[r, c], [r + 1, c]]);
    }
  }

  return (
    <div
      className="plate-wrap"
      style={{ aspectRatio: `${cols} / ${rows}` }}
      data-testid="grid-editor"
      data-edge-mode={edgeMode ? "1" : "0"}
    >
      <div
        className="cell-grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
        }}
      >
        {matrix.map((row, r) =>
          row.map((value, c) => (
            <div className="cell-box" key={`${r}-${c}`}>
              <input
                className="cell-input"
                type="number"
                min={-100}
                max={100}
                step={1}
                value={value}
                aria-label={`温度 行${r + 1} 列${c + 1}`}
                data-testid={`cell-${r}-${c}`}
                onChange={(e) => onTempChange(r, c, e.target.value)}
                disabled={edgeMode}
              />
            </div>
          ))
        )}
      </div>

      <svg
        className="edge-layer"
        viewBox={`0 0 ${cols} ${rows}`}
        preserveAspectRatio="none"
      >
        {internalEdges.map(([a, b]) => {
          const [ea, eb] = normalizeEdge(a, b);
          const key = edgeKey([ea, eb]);
          const blocked = blockedSet.has(key);
          // Thin rectangular hit strips: cells side-by-side share a vertical
          // strip, stacked cells a horizontal one.
          const sameRow = ea[0] === eb[0];
          const thickness = blocked ? 0.07 : 0.09;
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
              key={key}
              {...rect}
              className={
                "edge" +
                (blocked ? " edge-blocked" : "") +
                (edgeMode ? " edge-clickable" : " edge-inert")
              }
              data-testid={`edge-${ea[0]}-${ea[1]}-${eb[0]}-${eb[1]}`}
              data-blocked={blocked ? "1" : "0"}
              onClick={() => edgeMode && onToggleEdge([ea, eb])}
            />
          );
        })}
      </svg>
    </div>
  );
}

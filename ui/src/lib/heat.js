// Shared pure helpers for the plate UI.

/** Parse an exact fraction string ("-3/16" or "5") into a float. */
export function fracToNumber(value) {
  if (typeof value === "number") return value;
  const s = String(value);
  if (s.includes("/")) {
    const [n, d] = s.split("/");
    return Number(n) / Number(d);
  }
  return Number(s);
}

/** Human-readable approximation of an exact fraction string. */
export function formatFrac(value, digits = 3) {
  const n = fracToNumber(value);
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

function mix(a, b, t) {
  return Math.round(a + (b - a) * t);
}

/**
 * Diverging colormap: negative -> blue, 0 -> white, positive -> red.
 * Magnitude is normalized against [-scale, scale].
 */
export function heatColor(value, scale = 100) {
  const v = clamp(fracToNumber(value) / scale, -1, 1);
  if (v >= 0) {
    // white (255,255,255) -> red (204,0,0)
    return `rgb(${mix(255, 204, v)}, ${mix(255, 0, v)}, ${mix(255, 0, v)})`;
  }
  const t = -v;
  return `rgb(${mix(255, 0, t)}, ${mix(255, 76, t)}, ${mix(255, 153, t)})`;
}

/** Canonical orientation of an undirected edge between adjacent cells. */
export function normalizeEdge(a, b) {
  const keyA = a[0] * 1000 + a[1];
  const keyB = b[0] * 1000 + b[1];
  return keyA <= keyB ? [a, b] : [b, a];
}

export function edgeKey(edge) {
  const [a, b] = edge;
  return `${a[0]},${a[1]}|${b[0]},${b[1]}`;
}

/** True if two orthogonally adjacent cells share a border. */
export function isVerticalBorder(a, b) {
  // Border runs vertically when the cells differ in column.
  return a[1] !== b[1];
}

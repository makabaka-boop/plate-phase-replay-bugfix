"""Exact rational heat-diffusion simulation on a rectangular plate.

Rules (applied synchronously every step):
  * Every *internal* edge that is not blocked transfers one quarter of the
    temperature difference between its two cells, from the hotter cell to the
    colder one: q = (T_a - T_b) / 4 leaves a and enters b.
  * ``insulated`` boundary: the plate exchanges no heat with the outside.
  * ``fixed-zero`` boundary: every external side of a border cell behaves like
    an edge to a zero-temperature environment, i.e. q = T_cell / 4 leaves the
    plate through that side (negative q means heat enters the plate).

All arithmetic uses :class:`fractions.Fraction`, so totals are exact; in
insulated mode the total temperature is provably conserved frame to frame.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Iterable

MIN_DIM = 3
MAX_DIM = 12
MIN_TEMP = -100
MAX_TEMP = 100
MAX_STEPS = 25
MAX_BLOCKED_EDGES = 30
BOUNDARY_MODES = ("insulated", "fixed-zero")


class ValidationError(ValueError):
    """Raised when the request payload does not satisfy the input contract."""


def _is_int(value: Any) -> bool:
    # ``bool`` is a subclass of int but is not a legitimate temperature.
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_cell(value: Any) -> tuple[int, int]:
    """Accept either [r, c] or a flat [r1, c1, r2, c2] fragment."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValidationError("每个格子必须是形如 [row, col] 的两个整数")
    r, c = value
    if not (_is_int(r) and _is_int(c)):
        raise ValidationError("格子坐标必须是整数")
    return int(r), int(c)


def validate_payload(data: Any) -> dict:
    """Validate a decoded JSON payload and return a normalized kwargs dict."""
    if not isinstance(data, dict):
        raise ValidationError("请求体必须是 JSON 对象")

    if "matrix" not in data:
        raise ValidationError("缺少初始温度矩阵 matrix")
    raw_matrix = data["matrix"]
    if not isinstance(raw_matrix, list) or not raw_matrix:
        raise ValidationError("matrix 必须是非空二维数组")
    rows = len(raw_matrix)
    if not (MIN_DIM <= rows <= MAX_DIM):
        raise ValidationError(f"行数必须在 {MIN_DIM}～{MAX_DIM} 之间")

    matrix: list[list[int]] = []
    cols = None
    for r, row in enumerate(raw_matrix):
        if not isinstance(row, list) or not row:
            raise ValidationError(f"第 {r} 行必须是非空数组")
        if cols is None:
            cols = len(row)
            if not (MIN_DIM <= cols <= MAX_DIM):
                raise ValidationError(f"列数必须在 {MIN_DIM}～{MAX_DIM} 之间")
        elif len(row) != cols:
            raise ValidationError(f"第 {r} 行长度与首行不一致，矩阵必须为矩形")
        parsed_row = []
        for c, value in enumerate(row):
            if not _is_int(value):
                raise ValidationError(f"matrix[{r}][{c}] 必须是整数")
            if not (MIN_TEMP <= value <= MAX_TEMP):
                raise ValidationError(
                    f"matrix[{r}][{c}] = {value} 超出范围 [{MIN_TEMP}, {MAX_TEMP}]"
                )
            parsed_row.append(int(value))
        matrix.append(parsed_row)
    assert cols is not None

    steps = data.get("steps")
    if not _is_int(steps) or not (1 <= int(steps) <= MAX_STEPS):
        raise ValidationError(f"steps 必须是 1～{MAX_STEPS} 之间的整数")
    steps = int(steps)

    boundary = data.get("boundary", "insulated")
    if boundary not in BOUNDARY_MODES:
        raise ValidationError(
            f"boundary 必须是 {BOUNDARY_MODES[0]!r} 或 {BOUNDARY_MODES[1]!r}"
        )

    blocked: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    raw_edges = data.get("blocked_edges", [])
    if raw_edges is None:
        raw_edges = []
    if not isinstance(raw_edges, list):
        raise ValidationError("blocked_edges 必须是数组")
    if len(raw_edges) > MAX_BLOCKED_EDGES:
        raise ValidationError(f"阻断边最多 {MAX_BLOCKED_EDGES} 条")
    for index, edge in enumerate(raw_edges):
        if not isinstance(edge, list) or len(edge) not in (2, 4):
            raise ValidationError(
                f"blocked_edges[{index}] 必须是 [r1,c1,r2,c2] 或 [[r1,c1],[r2,c2]]"
            )
        if len(edge) == 4:
            if not all(_is_int(v) for v in edge):
                raise ValidationError(f"blocked_edges[{index}] 坐标必须是整数")
            a = (int(edge[0]), int(edge[1]))
            b = (int(edge[2]), int(edge[3]))
        else:
            a = _parse_cell(edge[0])
            b = _parse_cell(edge[1])

        for cell in (a, b):
            if not (0 <= cell[0] < rows and 0 <= cell[1] < cols):
                raise ValidationError(
                    f"blocked_edges[{index}] 坐标 {cell} 超出网格范围"
                )
        if a == b:
            raise ValidationError(f"blocked_edges[{index}] 的两个端点不能相同")
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            raise ValidationError(
                f"blocked_edges[{index}] 的 {a} 与 {b} 不是正交相邻格"
            )
        blocked.add((min(a, b), max(a, b)))

    return {
        "rows": rows,
        "cols": cols,
        "matrix": matrix,
        "steps": steps,
        "boundary": boundary,
        "blocked_edges": sorted(blocked),
        "schedule": data.get("schedule", []),
    }


def _external_sides(r: int, c: int, rows: int, cols: int) -> int:
    """Number of sides of cell (r, c) facing the outside world."""
    return (r == 0) + (r == rows - 1) + (c == 0) + (c == cols - 1)


def simulate(
    matrix: Iterable[Iterable[int]],
    steps: int,
    boundary: str,
    blocked_edges: Iterable[tuple[tuple[int, int], tuple[int, int]]] = (),
    schedule: list | None = None,
    rows: int | None = None,
    cols: int | None = None,
) -> dict:
    """Run the simulation and return exact Fraction data.

    Returns a dict with keys:
        frames         – list of steps+1 flat grids (list[list[Fraction]]),
                         frame 0 is the initial state
        boundary_flow  – list of ``steps`` Fractions, net heat leaving the
                         plate at each step (positive = loss to environment)
        total_temperature – list of steps+1 Fractions
        blocked_edges  – normalized sorted edge list
    """
    initial = [[Fraction(v) for v in row] for row in matrix]
    if rows is None:
        rows = len(initial)
    if cols is None:
        cols = len(initial[0]) if initial else 0

    blocked = set(blocked_edges)
    if schedule:
        # The final controls are used for a run with a schedule.
        last = schedule[-1]
        boundary = last.get("boundary", boundary)

    # All internal undirected edges, rightward and downward.
    internal_edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                edge = ((r, c), (r, c + 1))
                if edge not in blocked:
                    internal_edges.append(edge)
            if r + 1 < rows:
                edge = ((r, c), (r + 1, c))
                if edge not in blocked:
                    internal_edges.append(edge)

    outside_counts = {
        (r, c): _external_sides(r, c, rows, cols)
        for r in range(rows)
        for c in range(cols)
    }

    def grid_total(grid: dict | list) -> Fraction:
        total = Fraction(0)
        for r in range(rows):
            for c in range(cols):
                total += grid[r][c]
        return total

    current = [row[:] for row in initial]
    frames: list[list[list[Fraction]]] = [[row[:] for row in current]]
    totals: list[Fraction] = [grid_total(current)]
    flows: list[Fraction] = []

    for _ in range(steps):
        # Every delta is read from ``current``; ``nxt`` is the only grid
        # mutated, which guarantees synchronous updates.
        nxt = [row[:] for row in current]
        boundary_flow = Fraction(0)

        for (ra, ca), (rb, cb) in internal_edges:
            flux = (current[ra][ca] - current[rb][cb]) / 4
            if flux != 0:
                nxt[ra][ca] -= flux
                nxt[rb][cb] += flux

        if boundary == "fixed-zero":
            for r in range(rows):
                for c in range(cols):
                    sides = outside_counts[(r, c)]
                    if sides:
                        flux = current[r][c] * sides / 4
                        nxt[r][c] -= flux
                        boundary_flow += flux
        # insulated: no external exchange, flow stays exactly zero

        current = nxt
        frames.append([row[:] for row in current])
        totals.append(grid_total(current))
        flows.append(boundary_flow)

    return {
        "rows": rows,
        "cols": cols,
        "boundary": boundary,
        "steps": steps,
        "frames": frames,
        "boundary_flow": flows,
        "total_temperature": totals,
        "blocked_edges": sorted(blocked),
        "schedule": schedule or [],
    }


def _frac_to_str(value: Fraction) -> str:
    """Serialize a Fraction exactly as an integer or 'num/den' string."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def serialize_result(result: dict) -> dict:
    """Convert the simulation result to a JSON-safe structure."""
    return {
        "rows": result["rows"],
        "cols": result["cols"],
        "boundary": result["boundary"],
        "steps": result["steps"],
        "frames": [
            [[_frac_to_str(v) for v in row] for row in frame]
            for frame in result["frames"]
        ],
        "boundary_flow": [_frac_to_str(v) for v in result["boundary_flow"]],
        "total_temperature": [_frac_to_str(v) for v in result["total_temperature"]],
        "blocked_edges": [
            [[a[0], a[1]], [b[0], b[1]]] for a, b in result["blocked_edges"]
        ],
        "schedule": result["schedule"],
    }

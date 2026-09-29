"""Tests for the exact rational heat simulation.

The core cross-check uses an *independent* reference model that enumerates the
four sides of every cell separately (per-side outgoing fluxes), rather than
the edge-list formulation used by the engine. The two implementations must
agree bit-for-bit as Fractions for random plates under both boundary modes.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from app.api import create_app
from app.simulation import (
    ValidationError,
    serialize_result,
    simulate,
    validate_payload,
)

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ---------------------------------------------------------------------------
# Independent reference model: enumerate each side of each cell separately.
# ---------------------------------------------------------------------------


def _edge_key(a, b):
    return tuple(sorted((a, b)))


def reference_simulate(matrix, steps, boundary, blocked_edges):
    rows, cols = len(matrix), len(matrix[0])
    blocked = {_edge_key(a, b) for a, b in blocked_edges}
    grid = [[Fraction(v) for v in row] for row in matrix]
    frames = [[row[:] for row in grid]]
    flows = []

    for _ in range(steps):
        delta = [[Fraction(0) for _ in range(cols)] for _ in range(rows)]
        ext_flow = Fraction(0)
        for r in range(rows):
            for c in range(cols):
                for dr, dc in DIRS:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        if _edge_key((r, c), (nr, nc)) in blocked:
                            continue
                        # flux leaving (r,c) through this side
                        delta[r][c] -= (grid[r][c] - grid[nr][nc]) / 4
                    elif boundary == "fixed-zero":
                        flux = grid[r][c] / 4
                        delta[r][c] -= flux
                        ext_flow += flux
        grid = [[grid[r][c] + delta[r][c] for c in range(cols)] for r in range(rows)]
        frames.append([row[:] for row in grid])
        flows.append(ext_flow)
    return frames, flows


def _random_case(seed):
    rng = random.Random(seed)
    rows = rng.randint(3, 6)
    cols = rng.randint(3, 6)
    matrix = [
        [rng.randint(-100, 100) for _ in range(cols)] for _ in range(rows)
    ]
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    candidate_edges = []
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                candidate_edges.append(((r, c), (r, c + 1)))
            if r + 1 < rows:
                candidate_edges.append(((r, c), (r + 1, c)))
    rng.shuffle(candidate_edges)
    n_block = rng.randint(0, min(6, len(candidate_edges)))
    blocked = candidate_edges[:n_block]
    steps = rng.randint(1, 8)
    boundary = rng.choice(("insulated", "fixed-zero"))
    return matrix, steps, boundary, blocked, cells


# ---------------------------------------------------------------------------
# Cross-check against the independent model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_engine_matches_independent_per_side_model(seed):
    matrix, steps, boundary, blocked, _ = _random_case(seed)
    ref_frames, ref_flows = reference_simulate(matrix, steps, boundary, blocked)

    result = simulate(matrix, steps, boundary, blocked)
    assert result["frames"] == ref_frames
    assert result["boundary_flow"] == ref_flows


@pytest.mark.parametrize("seed", range(10))
def test_insulated_total_temperature_conserved(seed):
    matrix, steps, _, blocked, _ = _random_case(1000 + seed)
    result = simulate(matrix, steps, "insulated", blocked)
    initial_total = Fraction(sum(sum(row) for row in matrix))
    assert all(total == initial_total for total in result["total_temperature"])
    assert all(flow == 0 for flow in result["boundary_flow"])


@pytest.mark.parametrize("seed", range(10))
def test_fixed_zero_flow_accounts_for_total_change(seed):
    matrix, steps, _, blocked, _ = _random_case(2000 + seed)
    result = simulate(matrix, steps, "fixed-zero", blocked)
    totals = result["total_temperature"]
    for t in range(steps):
        assert totals[t] - totals[t + 1] == result["boundary_flow"][t]


def test_blocked_edge_carries_no_flux():
    # Two hot cells on the left, two cold on the right; the vertical seam is
    # entirely blocked, so left/right values evolve independently.
    matrix = [
        [8, 8, 0, 0],
        [8, 8, 0, 0],
        [8, 8, 0, 0],
    ]
    blocked = [((0, 1), (0, 2)), ((1, 1), (1, 2)), ((2, 1), (2, 2))]
    result = simulate(matrix, 3, "insulated", blocked)
    frame1 = result["frames"][1]
    # No heat crosses the seam: column 2 gains nothing from column 1, but it
    # still exchanges vertically with column 3 and within itself.
    for r in range(3):
        assert frame1[r][1] > 0
        # Column 2's only initial contacts are vertical (same column) and the
        # blocked seam; with identical zeros at t0 it must stay zero at t1.
        assert frame1[r][2] == 0
    # Explicitly: totals on each side of the seam are separately conserved.
    for frame in result["frames"]:
        left = sum(frame[r][c] for r in range(3) for c in (0, 1))
        right = sum(frame[r][c] for r in range(3) for c in (2, 3))
        assert left == 48
        assert right == 0


def test_single_step_is_exact_quarter_and_synchronous():
    matrix = [
        [4, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
    ]
    result = simulate(matrix, 1, "insulated", ())
    f0, f1 = result["frames"]
    # The corner (0,0) has two neighbors: loses 1/4 of the diff to each.
    assert f1[0][0] == Fraction(2)
    assert f1[0][1] == Fraction(1)
    assert f1[1][0] == Fraction(1)
    # Synchronous: neighbors of those cells must still read zero at step 1
    # (they were zero when all fluxes were read).
    assert f1[0][2] == 0
    assert f1[1][1] == 0
    assert f1[2][0] == 0


def test_fixed_zero_corner_loses_half_per_step_if_cold_neighbors():
    # Corner with two external sides and two zero-valued neighbors loses
    # 4 * (1/4) = its full value in one step.
    matrix = [[4, 0, 0], [0, 0, 0], [0, 0, 0]]
    result = simulate(matrix, 1, "fixed-zero", ())
    assert result["frames"][1][0][0] == 0
    flow = result["boundary_flow"][0]
    # Two outside sides at temperature 4 each leak 1.
    assert flow == 2


def test_fixed_zero_cold_plate_absorbs_heat_from_environment():
    matrix = [
        [-4, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
    ]
    result = simulate(matrix, 1, "fixed-zero", ())
    # Negative temperature: signed flux means heat flows IN from outside.
    assert result["boundary_flow"][0] == -2
    assert result["total_temperature"][1] > result["total_temperature"][0]


def test_frame_count_and_initial_frame():
    matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    result = simulate(matrix, 5, "insulated", ())
    assert len(result["frames"]) == 6
    assert len(result["boundary_flow"]) == 5
    assert result["frames"][0] == [[Fraction(v) for v in row] for row in matrix]


def test_duplicate_and_reversed_blocked_edges_deduplicated():
    payload = {
        "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        "steps": 2,
        "boundary": "insulated",
        "blocked_edges": [
            [0, 0, 0, 1],
            [0, 1, 0, 0],
            [[0, 0], [0, 1]],
        ],
    }
    params = validate_payload(payload)
    assert len(params["blocked_edges"]) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


GOOD = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def _payload(**overrides):
    payload = {"matrix": GOOD, "steps": 3, "boundary": "insulated"}
    payload.update(overrides)
    return payload


def test_valid_payload_passes():
    params = validate_payload(_payload())
    assert params["rows"] == 3 and params["cols"] == 3
    assert params["steps"] == 3


def test_default_boundary_is_insulated():
    params = validate_payload({"matrix": GOOD, "steps": 1})
    assert params["boundary"] == "insulated"


@pytest.mark.parametrize(
    "payload",
    [
        _payload(matrix=[[1, 2, 3], [4, 5, 6]]),              # 2 rows
        _payload(matrix=[[1] * 13] * 13),                    # 13 rows/cols
        _payload(matrix=[[1, 2], [3, 4], [5, 6]]),           # 2 cols
        _payload(matrix=[[1, 2, 3], [4, 5], [7, 8, 9]]),     # ragged
        _payload(matrix=[]),
        _payload(matrix="not-an-array"),
        _payload(matrix=[[1, 2, 3], [4, 5.5, 6], [7, 8, 9]]),  # float temp
        _payload(matrix=[[1, 2, 101], [4, 5, 6], [7, 8, 9]]),  # temp > 100
        _payload(matrix=[[1, 2, -101], [4, 5, 6], [7, 8, 9]]),
        _payload(steps=0),
        _payload(steps=26),
        _payload(steps="3"),
        _payload(boundary="periodic"),
        _payload(blocked_edges=[[0, 0, 0, 2]]),              # not adjacent
        _payload(blocked_edges=[[0, 0, 0, 0]]),              # same cell
        _payload(blocked_edges=[[0, 0, 3, 0]]),              # out of grid
        _payload(blocked_edges=[[0, 0, 0]]),                 # malformed
        _payload(blocked_edges=[[i, 0, i + 1, 0] for i in range(31)]),
    ],
)
def test_invalid_payloads_rejected(payload):
    with pytest.raises(ValidationError):
        validate_payload(payload)


def test_exactly_30_edges_allowed():
    # Build a 3x12 grid: it has 51 internal edges, so 30 blocked is possible.
    matrix = [[0] * 12 for _ in range(3)]
    edges = [[r, c, r, c + 1] for r in range(3) for c in range(10)]
    params = validate_payload(
        {"matrix": matrix, "steps": 1, "blocked_edges": edges}
    )
    assert len(params["blocked_edges"]) == 30


def test_serialize_uses_exact_fraction_strings():
    matrix = [
        [1, 0, 0],
        [0, 0, 0],
        [0, 0, 0],
    ]
    data = serialize_result(simulate(matrix, 2, "fixed-zero", ()))
    # Corner (0,0) at t1: 1 - 1/4 (right) - 1/4 (down) - 1/4 (up out) - 1/4
    # (left out) = 0 exactly. Cell (0,1) holds 1/4 at t1 and loses 1/4 to the
    # outside plus gains/loses with (0,2) and (1,1) (all zero) by t2.
    assert data["frames"][0][0][0] == "1"
    assert data["frames"][1][0][1] == "1/4"
    # Exact t2 values from the synchronous rule: corner (0,0) receives 1/16
    # back from each 1/4 neighbor; (0,1) returns to zero; (0,2) only keeps
    # the flux it received because it had two external sides at zero value.
    assert data["frames"][2][0][0] == "1/8"
    assert data["frames"][2][0][1] == "0"
    assert data["frames"][2][0][2] == "1/16"
    assert data["frames"][2][1][1] == "1/8"
    # Every string parses back to a Fraction without error.
    from fractions import Fraction as F

    for frame in data["frames"]:
        for row in frame:
            for v in row:
                F(v)
    assert data["blocked_edges"] == []
    assert data["boundary"] == "fixed-zero"


# ---------------------------------------------------------------------------
# Flask API
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    app = create_app()
    app.testing = True
    return app.test_client()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_simulate_api_happy_path(client):
    resp = client.post(
        "/api/simulate",
        json={
            "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            "steps": 4,
            "boundary": "insulated",
            "blocked_edges": [[0, 0, 0, 1]],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rows"] == 3 and data["cols"] == 3
    assert len(data["frames"]) == 5
    assert data["boundary_flow"] == ["0", "0", "0", "0"]
    totals = [Fraction(v) for v in data["total_temperature"]]
    assert totals == [Fraction(45)] * 5
    # Blocked edge is echoed back, normalized.
    assert data["blocked_edges"] == [[[0, 0], [0, 1]]]


def test_simulate_api_rejects_bad_payload(client):
    resp = client.post("/api/simulate", json={"matrix": [[1]], "steps": 1})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_simulate_api_rejects_non_json(client):
    resp = client.post("/api/simulate", data="not json")
    assert resp.status_code == 400


def test_fixed_zero_api_flow_values(client):
    resp = client.post(
        "/api/simulate",
        json={
            "matrix": [[4, 0, 0], [0, 0, 0], [0, 0, 0]],
            "steps": 1,
            "boundary": "fixed-zero",
        },
    )
    data = resp.get_json()
    assert data["boundary_flow"] == ["2"]
    assert data["frames"][1][0][0] == "0"

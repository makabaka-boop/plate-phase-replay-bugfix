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


def reference_simulate_schedule(matrix, steps, boundary, blocked_edges, schedule):
    """Independent per-side model that applies the same step-keyed schedule."""
    rows, cols = len(matrix), len(matrix[0])
    changes = {entry["step"]: entry for entry in schedule}
    blocked = {_edge_key(a, b) for a, b in blocked_edges}
    grid = [[Fraction(v) for v in row] for row in matrix]
    frames = [[row[:] for row in grid]]
    flows = []

    for step in range(1, steps + 1):
        change = changes.get(step)
        if change is not None:
            if "boundary" in change:
                boundary = change["boundary"]
            if "blocked_edges" in change:
                blocked = {
                    _edge_key(tuple(a), tuple(b))
                    for a, b in change["blocked_edges"]
                }
        delta = [[Fraction(0) for _ in range(cols)] for _ in range(rows)]
        ext_flow = Fraction(0)
        for r in range(rows):
            for c in range(cols):
                for dr, dc in DIRS:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        if _edge_key((r, c), (nr, nc)) in blocked:
                            continue
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


def test_frame_count_and_initial_frame():
    matrix = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    result = simulate(matrix, 5, "insulated", ())
    assert len(result["frames"]) == 6
    assert len(result["boundary_flow"]) == 5
    assert result["frames"][0] == [[Fraction(v) for v in row] for row in matrix]


# ---------------------------------------------------------------------------
# Schedule: settings take effect at the beginning of the named step.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_schedule_matches_independent_model(seed):
    matrix, steps, boundary, blocked, _ = _random_case(3000 + seed)
    rng = random.Random(9000 + seed)
    # Pick a subset of steps (1-based), each changing either the boundary, the
    # blocked set, or both. Entries are handed in shuffled order on purpose:
    # the validator must sort and the engine must not depend on order.
    change_steps = sorted(
        rng.sample(range(1, steps + 1), rng.randint(1, min(3, steps)))
    )
    all_edges = []
    for r in range(len(matrix)):
        for c in range(len(matrix[0])):
            if c + 1 < len(matrix[0]):
                all_edges.append(((r, c), (r, c + 1)))
            if r + 1 < len(matrix):
                all_edges.append(((r, c), (r + 1, c)))
    schedule = []
    for s in change_steps:
        entry = {"step": s}
        mode = rng.random()
        if mode < 0.35:
            entry["boundary"] = rng.choice(("insulated", "fixed-zero"))
        elif mode < 0.7:
            n = rng.randint(0, min(5, len(all_edges)))
            entry["blocked_edges"] = [
                [a[0], a[1], b[0], b[1]]
                for a, b in rng.sample(all_edges, n)
            ]
        else:
            entry["boundary"] = rng.choice(("insulated", "fixed-zero"))
            n = rng.randint(0, min(5, len(all_edges)))
            entry["blocked_edges"] = [
                [a[0], a[1], b[0], b[1]]
                for a, b in rng.sample(all_edges, n)
            ]
        schedule.append(entry)
    rng.shuffle(schedule)

    params = validate_payload(
        {
            "matrix": matrix,
            "steps": steps,
            "boundary": boundary,
            "blocked_edges": [
                [a[0], a[1], b[0], b[1]] for a, b in blocked
            ],
            "schedule": schedule,
        }
    )
    result = simulate(**params)

    ref_frames, ref_flows = reference_simulate_schedule(
        matrix,
        steps,
        boundary,
        [tuple(e) for e in blocked],
        params["schedule"],
    )
    assert result["frames"] == ref_frames
    assert result["boundary_flow"] == ref_flows
    # The bookkeeping identity holds step by step whatever the settings are.
    for t in range(steps):
        assert (
            result["total_temperature"][t]
            - result["total_temperature"][t + 1]
            == result["boundary_flow"][t]
        )


def test_schedule_settings_do_not_affect_earlier_frames():
    matrix = [[40, 0, 0], [40, 0, 0], [40, 0, 0]]
    plain = simulate(matrix, 6, "insulated", ())
    with_schedule = simulate(
        matrix,
        6,
        "insulated",
        (),
        [
            {"step": 2, "blocked_edges": [((1, 0), (1, 1))]},
            {"step": 3, "boundary": "fixed-zero"},
            {"step": 4, "boundary": "insulated"},
        ],
    )
    # Frames strictly before the first change point must be identical.
    assert with_schedule["frames"][0] == plain["frames"][0]
    assert with_schedule["frames"][1] == plain["frames"][1]
    # Frame 2 already reflects the new blocked edge, so it must differ.
    assert with_schedule["frames"][2] != plain["frames"][2]
    # The top-level boundary still names the initial setting.
    assert with_schedule["boundary"] == "insulated"


def test_schedule_boundary_switch_only_changes_named_step():
    matrix = [[40, 0, 0], [40, 0, 0], [40, 0, 0]]
    result = simulate(
        matrix, 3, "insulated", (), [{"step": 2, "boundary": "fixed-zero"}]
    )
    settings = result["frame_settings"]
    assert [s["boundary"] for s in settings] == [
        "insulated",
        "insulated",
        "fixed-zero",
        "fixed-zero",
    ]
    # Step 1 is insulated: total conserved and flow exactly zero.
    assert result["boundary_flow"][0] == 0
    assert result["total_temperature"][1] == result["total_temperature"][0]
    # Steps 2 and 3 lose heat through the outside.
    assert result["boundary_flow"][1] > 0
    assert result["boundary_flow"][2] > 0
    assert result["total_temperature"][3] < result["total_temperature"][1]


def test_schedule_boundary_restore_resumes_conservation():
    matrix = [[40, 0, 0], [40, 0, 0], [40, 0, 0]]
    result = simulate(
        matrix,
        4,
        "insulated",
        (),
        [
            {"step": 2, "boundary": "fixed-zero"},
            {"step": 3, "boundary": "insulated"},
        ],
    )
    flows = result["boundary_flow"]
    assert flows[0] == 0
    assert flows[1] > 0
    assert flows[2] == 0  # insulated again: no external exchange
    assert flows[3] == 0
    totals = result["total_temperature"]
    assert totals[3] == totals[2] == totals[4]
    assert totals[2] < totals[0]  # but the heat lost at step 2 stays lost


def test_schedule_blocked_edges_apply_at_named_step():
    matrix = [
        [8, 8, 0, 0],
        [8, 8, 0, 0],
        [8, 8, 0, 0],
    ]
    seam = [
        ((0, 1), (0, 2)),
        ((1, 1), (1, 2)),
        ((2, 1), (2, 2)),
    ]
    result = simulate(
        matrix, 3, "insulated", (), [{"step": 2, "blocked_edges": seam}]
    )
    settings = result["frame_settings"]
    # Frame 0/1 use the initial empty set; the seam exists from frame 2 on.
    assert settings[0]["blocked_edges"] == []
    assert settings[1]["blocked_edges"] == []
    assert [tuple(sorted(e)) for e in settings[2]["blocked_edges"]] == [
        tuple(sorted(e)) for e in seam
    ]
    assert settings[3]["blocked_edges"] == settings[2]["blocked_edges"]
    # Frame 1: heat has already crossed the seam (column 2 is positive).
    assert all(result["frames"][1][r][2] > 0 for r in range(3))
    # After blocking at step 2, each side of the seam is separately conserved.
    for frame in result["frames"][2:]:
        left = sum(frame[r][c] for r in range(3) for c in (0, 1))
        right = sum(frame[r][c] for r in range(3) for c in (2, 3))
        assert left + right == Fraction(48)
        assert right == sum(result["frames"][1][r][2] + result["frames"][1][r][3]
                            for r in range(3))


def test_schedule_blocked_edges_replaces_entire_active_set():
    edge_a = ((0, 0), (0, 1))
    edge_b = ((1, 0), (1, 1))
    result = simulate(
        [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        3,
        "insulated",
        [edge_a],
        [
            {"step": 2, "blocked_edges": [edge_b]},
            {"step": 3, "blocked_edges": []},
        ],
    )
    active = [
        [tuple(sorted(e)) for e in s["blocked_edges"]]
        for s in result["frame_settings"]
    ]
    assert active[0] == active[1] == [tuple(sorted(edge_a))]
    assert active[2] == [tuple(sorted(edge_b))]  # replaced, not merged
    assert active[3] == []  # explicit empty list clears all blocks


def test_empty_schedule_behaves_exactly_like_omitted_schedule():
    matrix, steps, boundary, blocked, _ = _random_case(42)
    plain = simulate(matrix, steps, boundary, blocked, [])
    omitted = simulate(matrix, steps, boundary, blocked, None)
    assert plain["frames"] == omitted["frames"]
    assert plain["boundary_flow"] == omitted["boundary_flow"]
    assert plain["frame_settings"] == omitted["frame_settings"]
    assert plain["schedule"] == []


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
        # Malformed schedules must be rejected with 400, never a 500.
        _payload(schedule=[{"step": 1}]),                    # nothing to apply
        _payload(schedule=[{"boundary": "insulated"}]),      # missing step
        _payload(schedule=[{"step": 0}]),                    # step below 1
        _payload(schedule=[{"step": 4}]),                    # step above steps
        _payload(schedule=[{"step": "1"}]),                  # non-int step
        _payload(schedule=[{"step": 2, "boundary": "vacuum"}]),
        _payload(schedule=[{"step": 1}, {"step": 1}]),       # duplicate step
        _payload(schedule=[{"step": 1, "unknown": 1}]),      # unknown field
        _payload(schedule="not-a-list"),
        _payload(schedule=[42]),
        _payload(
            schedule=[{"step": 1, "blocked_edges": [[0, 0, 0, 9]]}]
        ),                                                   # edge out of grid
        _payload(
            schedule=[{"step": 1, "blocked_edges": [[0, 0]]}]
        ),                                                   # malformed edge
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


def test_simulate_api_schedule_happy_path(client):
    resp = client.post(
        "/api/simulate",
        json={
            "matrix": [[40, 0, 0], [40, 0, 0], [40, 0, 0]],
            "steps": 4,
            "boundary": "insulated",
            "schedule": [
                {"step": 2, "blocked_edges": [[1, 0, 1, 1]]},
                {"step": 3, "boundary": "fixed-zero"},
                {"step": 4, "boundary": "insulated"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["frame_settings"]) == 5
    assert [f["boundary"] for f in data["frame_settings"]] == [
        "insulated",
        "insulated",
        "insulated",
        "fixed-zero",
        "insulated",
    ]
    assert [len(f["blocked_edges"]) for f in data["frame_settings"]] == [
        0,
        0,
        1,
        1,
        1,
    ]
    # Echoed back sorted by step, with normalized edges.
    assert [item["step"] for item in data["schedule"]] == [2, 3, 4]
    assert data["schedule"][0]["blocked_edges"] == [[[1, 0], [1, 1]]]


def test_simulate_api_rejects_malformed_schedule_with_400(client):
    # A malformed schedule used to escape validation and crash the engine
    # with a 500; it must be a 400 with a usable error message instead.
    resp = client.post(
        "/api/simulate",
        json={
            "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            "steps": 3,
            "schedule": [{"step": 2}],
        },
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_simulate_api_without_schedule_keeps_original_contract(client):
    resp = client.post(
        "/api/simulate",
        json={
            "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            "steps": 2,
            "boundary": "insulated",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["schedule"] == []
    assert len(data["frame_settings"]) == 3
    assert all(f["boundary"] == "insulated" for f in data["frame_settings"])
    assert all(f["blocked_edges"] == [] for f in data["frame_settings"])

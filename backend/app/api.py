"""Flask API for the plate heat-diffusion simulation."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from .simulation import (
    BOUNDARY_MODES,
    MAX_BLOCKED_EDGES,
    MAX_DIM,
    MAX_STEPS,
    MAX_TEMP,
    MIN_DIM,
    MIN_TEMP,
    ValidationError,
    serialize_result,
    simulate,
    validate_payload,
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_cors_headers(response):
        # UI and API are separate compose services on different origins.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/constraints")
    def constraints():
        return jsonify(
            {
                "min_dim": MIN_DIM,
                "max_dim": MAX_DIM,
                "min_temp": MIN_TEMP,
                "max_temp": MAX_TEMP,
                "max_steps": MAX_STEPS,
                "max_blocked_edges": MAX_BLOCKED_EDGES,
                "boundary_modes": list(BOUNDARY_MODES),
            }
        )

    @app.post("/api/simulate")
    def run_simulation():
        data = request.get_json(silent=True)
        try:
            params = validate_payload(data)
            result = simulate(**params)
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:  # pragma: no cover - defensive
            logger.exception("simulation failed")
            return jsonify({"error": "服务器内部错误"}), 500
        return jsonify(serialize_result(result))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

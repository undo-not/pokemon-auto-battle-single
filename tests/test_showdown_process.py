from __future__ import annotations

import pytest

from champions_sim.core.canonical import canonical_json
from champions_sim.showdown.process import (
    PROTOCOL_VERSION,
    ShowdownBridgeError,
    ShowdownProcessError,
    _response_result,
)


def test_response_contract_accepts_exact_result_without_node() -> None:
    line = canonical_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": 7,
            "ok": True,
            "result": {"value": 1},
        }
    )

    assert _response_result(line, 7) == {"value": 1}


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            '{"protocol_version":"1.0.0","request_id":7,"request_id":7,'
            '"ok":true,"result":{}}',
            "duplicate JSON key",
        ),
        (
            canonical_json(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": 8,
                    "ok": True,
                    "result": {},
                }
            ),
            "response identity mismatch",
        ),
        (
            canonical_json(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": 7,
                    "ok": True,
                    "result": [],
                }
            ),
            "result must be an object",
        ),
    ],
)
def test_response_contract_rejects_transport_drift_without_node(
    line: str, message: str
) -> None:
    with pytest.raises(ShowdownProcessError, match=message):
        _response_result(line, 7)


def test_response_contract_preserves_stable_bridge_error_without_node() -> None:
    line = canonical_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": 7,
            "ok": False,
            "error": {
                "code": "CHOICE_REJECTED",
                "message": "illegal choice",
                "details": {"player": "p1"},
            },
        }
    )

    with pytest.raises(ShowdownBridgeError) as captured:
        _response_result(line, 7)
    assert captured.value.code == "CHOICE_REJECTED"
    assert captured.value.details == {"player": "p1"}

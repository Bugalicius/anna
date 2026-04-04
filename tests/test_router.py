import pytest
from unittest.mock import AsyncMock, patch
from app.router import decide_route, FIXED_FLOW_STAGES


def test_new_stage_routes_to_flow():
    assert decide_route("new") == "flow"


def test_awaiting_payment_routes_to_flow():
    assert decide_route("awaiting_payment") == "flow"


def test_scheduling_routes_to_flow():
    assert decide_route("scheduling") == "flow"


def test_confirmed_routes_to_flow():
    assert decide_route("confirmed") == "flow"


def test_presenting_routes_to_ai():
    assert decide_route("presenting") == "ai"


def test_collecting_info_routes_to_ai():
    assert decide_route("collecting_info") == "ai"


def test_cold_lead_routes_to_ai():
    assert decide_route("cold_lead") == "ai"


def test_archived_routes_to_flow():
    # Contatos arquivados não devem receber resposta de IA
    assert decide_route("archived") == "flow"


def test_all_fixed_stages():
    for stage in FIXED_FLOW_STAGES:
        assert decide_route(stage) == "flow"

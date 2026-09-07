import pytest

from app.services.business_assistant_evaluation import score_business_intents
from tests.business_assistant_golden_set import GOLDEN_CASES


@pytest.fixture(autouse=True)
def db_engine():
    """The release-gate scorer is pure and does not require PostgreSQL."""

    yield None


def test_golden_set_has_two_hundred_unique_business_expressions():
    assert len(GOLDEN_CASES) == 200
    assert len({item["caseId"] for item in GOLDEN_CASES}) == 200
    assert len({item["utterance"] for item in GOLDEN_CASES}) == 200


def test_business_intent_release_gate_enforces_all_thresholds():
    predictions = [
        {
            "caseId": item["caseId"],
            "intent": item["expectedIntent"],
            "target": {"pageKey": item["expectedPageKey"]},
            "toolCalls": 0,
            "validFirstPass": True,
        }
        for item in GOLDEN_CASES
    ]
    result = score_business_intents(GOLDEN_CASES, predictions)
    assert result["passed"] is True
    predictions[0]["toolCalls"] = 1
    assert score_business_intents(GOLDEN_CASES, predictions)["passed"] is False

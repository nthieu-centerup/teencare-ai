from types import SimpleNamespace
from pathlib import Path
import json
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIStatusError

from app import main
from app.models import AnalysisRequest, ReasoningResult, Assessment
from app.mock import analyze_mock

client = TestClient(main.app)
CASES = json.loads((Path(__file__).parent / "fixtures" / "analysis_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_editorial_scenarios_keep_mock_honest_and_evidence_traceable(case):
    response = client.post("/analyze", json=case["request"])
    assert response.status_code == 200
    result = response.json()
    assert result["modelVersion"] == "mock-v4"
    assert result["promptVersion"] == "mock-v4"
    assert result["assessments"] == []
    assert result["overviewSummary"].startswith("[Mô phỏng]")
    assert not result["hypotheses"] and not result["recommendations"]
    validate_request = AnalysisRequest.model_validate(case["request"])
    eligible_ids = {str(o.revision_id) for o in validate_request.observations
                    if o.occurred_at is None or o.occurred_at <= min(validate_request.as_of_utc, o.recorded_at)}
    for assessment in result["assessments"]:
        assert assessment["content"].startswith("[Mô phỏng]")
        assert all(e["observationRevisionId"] in eligible_ids for e in assessment["evidence"])
    prose = " ".join([a["content"] for a in result["assessments"]] + [g["question"] for g in result["informationGaps"]])
    assert not any(word in prose for word in ["occurredAt", "recordedAt", "asOfUtc", "UTC", "Parent", "Mentor"])
    if case["name"] == "invalid_event_times":
        assert result["assessments"] == []
        assert len(result["informationGaps"]) == 2


def test_only_invalid_event_times_produce_questions_without_findings():
    invalid = next(case["request"] for case in CASES if case["name"] == "invalid_event_times")
    request = dict(invalid, observations=invalid["observations"][1:])
    response = client.post("/analyze", json=request)
    assert response.status_code == 200
    result = response.json()
    assert not result["assessments"] and not result["hypotheses"] and not result["recommendations"]
    assert len(result["informationGaps"]) == 2


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


@pytest.fixture
def payload():
    return {
        "jobId": str(uuid4()), "teenId": str(uuid4()), "inputVersion": 1,
        "asOfUtc": "2026-09-04T09:00:00Z",
        "observations": [{"revisionId": str(uuid4()), "observationId": str(uuid4()),
                          "source": "Parent", "content": "Quan sát để kiểm thử, không phải chẩn đoán.",
                          "occurredAt": None, "recordedAt": "2026-09-03T08:00:00Z"}],
    }


def test_mock_is_deterministic_and_preserves_evidence(payload):
    assert client.get("/health").json()["provider"] == "mock"
    first = client.post("/analyze", json=payload)
    assert first.status_code == 200
    assert first.json() == client.post("/analyze", json=payload).json()
    result = first.json()
    assert result["modelVersion"].startswith("mock")
    assert result["assessments"] == []
    assert result["overviewSummary"]
    assert result["informationGaps"][0]["dimension"] is None


@pytest.mark.parametrize("change", ["source", "empty", "naive_date"])
def test_invalid_input_is_rejected(payload, change):
    obs = payload["observations"][0]
    if change == "source": obs["source"] = "Invalid"
    if change == "empty": obs["content"] = ""
    if change == "naive_date": obs["recordedAt"] = "2026-09-03T08:00:00"
    assert client.post("/analyze", json=payload).status_code == 422


def test_empty_input_has_no_claims(payload):
    payload["observations"] = []
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["assessments"] == []


def test_openai_missing_configuration_never_falls_back(payload, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    response = client.post("/analyze", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "MISSING_OPENAI_CONFIGURATION"


def fake_openai(monkeypatch, payload, *, modify=None, status=None):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-never-sent")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    mock = analyze_mock(AnalysisRequest.model_validate(payload))
    result = ReasoningResult.model_validate(mock.model_dump(exclude={"model_version", "prompt_version"}))
    # Synthetic structured finding for validator tests; ordinary mock never classifies behavior.
    if payload["observations"]:
        result.assessments = [Assessment.model_validate({
            "key": "test-finding", "content": "Nhận định giả lập để kiểm tra liên kết.",
            "reasoning": "Chỉ dùng trong bộ kiểm thử, không phải suy luận của model.", "confidence": 0,
            "dimension": "SelfDiscipline", "informationStatus": "NeedMoreInformation", "trend": "Unknown",
            "evidence": [{"observationRevisionId": payload["observations"][0]["revisionId"],
                          "relation": "Context", "isStale": False, "explanation": "Bằng chứng kiểm thử."}]
        })]
    if modify: modify(result)
    calls = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            self.responses = self

        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

        async def parse(self, **kwargs):
            calls.append(kwargs)
            if status:
                response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"))
                raise APIStatusError("Private provider message", response=response, body=None)
            return SimpleNamespace(output_parsed=result, model="test-model")

    monkeypatch.setattr(main, "AsyncOpenAI", FakeOpenAI)
    return calls


def test_openai_structured_output_contract_without_paid_call(payload, monkeypatch):
    calls = fake_openai(monkeypatch, payload)
    response = client.post("/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["modelVersion"] == "test-model"
    assert response.json()["promptVersion"] == "state-v6"
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is main.ReasoningResult
    assert payload["observations"][0]["revisionId"] in calls[0]["input"]


def test_foreign_evidence_is_rejected(payload, monkeypatch):
    fake_openai(monkeypatch, payload, modify=lambda r: setattr(r.assessments[0].evidence[0], "observation_revision_id", uuid4()))
    response = client.post("/analyze", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_AI_EVIDENCE"


@pytest.mark.parametrize(("provider_status", "expected"), [(429, 429), (500, 503), (401, 400)])
def test_provider_errors_are_sanitized_and_no_mock_fallback(payload, monkeypatch, provider_status, expected):
    fake_openai(monkeypatch, payload, status=provider_status)
    response = client.post("/analyze", json=payload)
    assert response.status_code == expected
    assert response.json() == {"detail": "OPENAI_REQUEST_FAILED"}


def with_baseline(payload):
    previous = analyze_mock(AnalysisRequest.model_validate(payload)).model_dump(mode="json", by_alias=True)
    updated = deepcopy(payload)
    updated["inputVersion"] += 1
    updated["previousState"] = {
        "snapshotId": str(uuid4()), "version": 1, "createdAt": payload["asOfUtc"],
        "inputRevisionIds": [o["revisionId"] for o in payload["observations"]], "state": previous,
    }
    updated["inputChanges"] = {"addedRevisionIds": [], "updatedPreviousRevisions": [], "removedRevisions": []}
    return updated


def test_baseline_and_repeat_distinguish_unknown_change_from_no_change(payload):
    first = client.post("/analyze", json=payload).json()
    assert first["hasMeaningfulChanges"] is None
    assert first["changeEvidenceRevisionIds"] == []
    repeated = client.post("/analyze", json=with_baseline(payload))
    assert repeated.status_code == 200
    assert repeated.json()["hasMeaningfulChanges"] is False
    assert repeated.json()["changeEvidenceRevisionIds"] == []
    assert repeated.json()["assessments"] == first["assessments"]


def test_partial_baseline_is_invalid_input(payload):
    updated = with_baseline(payload)
    updated.pop("inputChanges")
    assert client.post("/analyze", json=updated).status_code == 422


@pytest.mark.parametrize("scenario,content", [
    ("supports", "Phụ huynh ghi nhận một lần tương tự vào hôm qua."),
    ("contradicts", "Mentor báo cáo điều khác với tình huống ở nhà."),
    ("gap_answered", "Em nói bước đọc đề khiến em mất nhiều thời gian."),
    ("action_feedback", "Phụ huynh đã thử bước nhỏ; em làm được hai buổi nhưng vẫn cần nhắc."),
    ("late_report", "Bổ sung một sự việc đã xảy ra từ tháng trước."),
])
def test_update_context_reaches_one_structured_request_without_paid_call(payload, monkeypatch, scenario, content):
    updated = with_baseline(payload)
    new = dict(payload["observations"][0], revisionId=str(uuid4()), observationId=str(uuid4()), content=content)
    if scenario == "late_report": new["occurredAt"] = "2026-08-01T08:00:00Z"
    updated["observations"].append(new)
    updated["inputChanges"]["addedRevisionIds"] = [new["revisionId"]]
    calls = fake_openai(monkeypatch, updated)
    response = client.post("/analyze", json=updated)
    assert response.status_code == 200
    assert len(calls) == 1
    sent = json.loads(calls[0]["input"])
    assert sent["previousState"] == updated["previousState"]
    assert sent["inputChanges"] == updated["inputChanges"]
    assert sent["observations"][-1]["content"] == content
    assert response.json()["changeEvidenceRevisionIds"] == [new["revisionId"]]
    # This checks contract plumbing, not real-model inference quality.
    assert response.json()["hasMeaningfulChanges"] is False


@pytest.mark.parametrize("removed", [False, True])
def test_replaced_or_removed_evidence_is_only_usable_for_update_summary(payload, monkeypatch, removed):
    updated = with_baseline(payload)
    old = deepcopy(updated["observations"][0])
    if removed:
        updated["inputChanges"]["removedRevisions"] = [old]
        updated["observations"] = []
    else:
        updated["inputChanges"]["updatedPreviousRevisions"] = [old]
        updated["observations"][0].update(revisionId=str(uuid4()), content="Ghi nhận được sửa lại.")
    result = client.post("/analyze", json=updated)
    assert result.status_code == 200
    assert old["revisionId"] in result.json()["changeEvidenceRevisionIds"]
    assert all(e["observationRevisionId"] != old["revisionId"] for a in result.json()["assessments"] for e in a["evidence"])
    if not removed:
        fake_openai(monkeypatch, updated, modify=lambda r: setattr(r.assessments[0].evidence[0], "observation_revision_id", UUID(old["revisionId"])))
        assert client.post("/analyze", json=updated).json()["detail"] == "INVALID_AI_EVIDENCE"


@pytest.mark.parametrize("invalid", ["foreign", "duplicate", "missing_evidence", "wrong_baseline"])
def test_invalid_change_summary_references_are_rejected(payload, monkeypatch, invalid):
    updated = with_baseline(payload)
    def modify(result):
        if invalid == "foreign": result.change_evidence_revision_ids = [uuid4()]
        if invalid == "duplicate": result.change_evidence_revision_ids = [UUID(updated["observations"][0]["revisionId"])] * 2
        if invalid == "missing_evidence": result.has_meaningful_changes = True
        if invalid == "wrong_baseline": result.has_meaningful_changes = None
    fake_openai(monkeypatch, updated, modify=modify)
    response = client.post("/analyze", json=updated)
    assert response.status_code == 422
    assert response.json()["detail"] == ("INVALID_AI_CHANGE_BASELINE" if invalid == "wrong_baseline" else "INVALID_AI_CHANGE_EVIDENCE")

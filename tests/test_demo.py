from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.demo import DEMO
from app.main import validate_references
from app.mock import analyze_mock
from app.models import AnalysisInputChanges, AnalysisPreviousState, AnalysisRequest, Audience, Relation


def demo_request(follow_up=False):
    now = datetime(2026, 9, 4, 8, tzinfo=timezone.utc)
    examples = [*DEMO["initial"], *([DEMO["followUp"]] if follow_up else [])]
    return AnalysisRequest.model_validate({
        "jobId": uuid4(), "teenId": uuid4(), "inputVersion": 4 if follow_up else 3, "asOfUtc": now,
        "observations": [dict(item, revisionId=uuid4(), observationId=uuid4(), recordedAt=now,
                              occurredAt=now - timedelta(days=1 if index == 3 else 5))
                         for index, item in enumerate(examples)],
    })


def test_demo_recommendations_reference_exact_evidence_and_cover_both_audiences():
    request = demo_request()
    result = analyze_mock(request)
    assert result == analyze_mock(request)
    assert result.model_version == "mock-demo-v4"
    assert result.prompt_version == "mock-demo-v4"
    assert {r.audience for r in result.recommendations} == {Audience.parent, Audience.mentor}
    assert all(r.hypothesis_key == result.hypotheses[0].key for r in result.recommendations)
    assert all(x.content.startswith("[Mô phỏng]") for x in [*result.assessments, *result.hypotheses])
    assert all(r.action.startswith("[Mô phỏng]") for r in result.recommendations)
    validate_references(request, result)
    request.observations.reverse()
    assert analyze_mock(request) == result


def test_later_report_changes_advice_and_cites_both_periods_without_overwriting_first_result():
    request = demo_request()
    first = analyze_mock(request)
    original = first.model_dump_json()
    request.previous_state = AnalysisPreviousState(snapshot_id=uuid4(), version=1, created_at=request.as_of_utc,
        input_revision_ids=[o.revision_id for o in request.observations], state=first)
    follow_up = demo_request(True).observations[-1]
    request.observations.append(follow_up)
    request.input_changes = AnalysisInputChanges(added_revision_ids=[follow_up.revision_id], updated_previous_revisions=[], removed_revisions=[])
    request.input_version += 1
    second = analyze_mock(request)
    assert second.model_version == "mock-demo-v4"
    assert second.assessments[0].content != first.assessments[0].content
    assert second.recommendations[0].action != first.recommendations[0].action
    assert {e.observation_revision_id for e in second.assessments[0].evidence} == {
        request.observations[0].revision_id, follow_up.revision_id,
    }
    assert "chưa chứng minh tiến bộ bền vững" in second.assessments[0].reasoning
    assert first.model_dump_json() == original
    assert second.has_meaningful_changes is True
    assert second.change_evidence_revision_ids == [follow_up.revision_id]
    assert "điều chỉnh hướng dẫn" in second.change_summary
    validate_references(request, second)
    request.previous_state = AnalysisPreviousState(snapshot_id=uuid4(), version=2, created_at=request.as_of_utc,
        input_revision_ids=[o.revision_id for o in request.observations], state=second)
    request.input_changes = AnalysisInputChanges(added_revision_ids=[], updated_previous_revisions=[], removed_revisions=[])
    repeated = analyze_mock(request)
    assert repeated.has_meaningful_changes is False
    assert repeated.recommendations == second.recommendations
    assert repeated.change_evidence_revision_ids == []
    validate_references(request, repeated)
    request.observations.pop()
    request.input_changes.removed_revisions = [follow_up]
    reverted = analyze_mock(request)
    assert reverted.has_meaningful_changes is True
    assert reverted.recommendations == first.recommendations
    assert reverted.change_evidence_revision_ids == [follow_up.revision_id]
    validate_references(request, reverted)


@pytest.mark.parametrize("change", ["edited", "extra", "missing", "wrong_source", "unknown_time", "future",
                                  "after_recording", "stale", "duplicate_id", "earlier_follow_up"])
def test_demo_never_applies_scripted_advice_to_different_or_unusable_inputs(change):
    request = demo_request(True)
    observation = request.observations[0]
    if change == "edited": observation.content += " Nhưng hôm nay tình hình khác."
    elif change == "extra":
        extra = deepcopy(observation)
        extra.revision_id, extra.observation_id = uuid4(), uuid4()
        extra.content = "Thông tin mới mâu thuẫn với ghi nhận trước."
        request.observations.append(extra)
    elif change == "missing": request.observations.pop(0)
    elif change == "wrong_source": observation.source = request.observations[1].source
    elif change == "unknown_time": observation.occurred_at = None
    elif change == "future": observation.occurred_at = request.as_of_utc + timedelta(hours=1)
    elif change == "after_recording": observation.recorded_at = observation.occurred_at - timedelta(hours=1)
    elif change == "stale": observation.occurred_at = request.as_of_utc - timedelta(days=60)
    elif change == "duplicate_id": observation.revision_id = request.observations[1].revision_id
    elif change == "earlier_follow_up": request.observations[-1].occurred_at = observation.occurred_at - timedelta(days=1)
    result = analyze_mock(request)
    assert result.model_version == "mock-v4"
    assert not result.hypotheses and not result.recommendations


def test_old_reports_remain_context_without_current_behavior_claims():
    request = demo_request()
    for observation in request.observations:
        observation.occurred_at = request.as_of_utc - timedelta(days=60)
    result = analyze_mock(request)
    assert not result.assessments
    assert not result.hypotheses and not result.recommendations

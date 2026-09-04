"""Deterministic demo adapter. It does not claim to perform behavioral analysis."""
from .models import AnalysisRequest, AnalysisResponse, InformationGap, Source
from .demo import analyze_demo


def analyze_mock(request: AnalysisRequest) -> AnalysisResponse:
    demo = analyze_demo(request)
    if demo is not None:
        return describe_changes(request, demo)
    questions = []
    names = {Source.parent: "phụ huynh", Source.teen: "teen", Source.mentor: "mentor"}
    for observation in request.observations:
        if observation.occurred_at is not None and observation.occurred_at > min(request.as_of_utc, observation.recorded_at):
            question = f"Có thể xác nhận lại ngày xảy ra sự việc trong ghi nhận từ {names[observation.source]} không?"
            if question not in questions:
                questions.append(question)

    return describe_changes(request, AnalysisResponse(
        model_version="mock-v4", prompt_version="mock-v4", assessments=[],
        overview_summary=(f"[Mô phỏng] Đã tiếp nhận {len(request.observations)} ghi nhận để theo dõi. "
                          "Chế độ này chưa phân tích hành vi nên các khía cạnh chưa có thông tin kết luận; bạn có thể xem lại dữ liệu và bổ sung bối cảnh."),
        change_summary="[Mô phỏng] Tạo mốc theo dõi đầu vào; chưa mô phỏng kết luận hành vi.",
        has_meaningful_changes=None, change_evidence_revision_ids=[],
        hypotheses=[], recommendations=[],
        information_gaps=[InformationGap(question=q) for q in (questions[:3] or
            (["Sự việc diễn ra trong bối cảnh nào và có lặp lại không?"] if request.observations
             else ["Bạn muốn chia sẻ một tình huống gần đây của con không?"]))],
    ))


def describe_changes(request: AnalysisRequest, result: AnalysisResponse) -> AnalysisResponse:
    if request.previous_state is None:
        return result
    changes = request.input_changes
    if changes is None:
        raise ValueError("Missing input changes for baseline")
    previous = request.previous_state.state
    current_by_observation = {o.observation_id: o for o in request.observations}
    references = [*changes.added_revision_ids,
                  *(o.revision_id for o in changes.updated_previous_revisions),
                  *(current_by_observation[o.observation_id].revision_id for o in changes.updated_previous_revisions),
                  *(o.revision_id for o in changes.removed_revisions)]
    result.change_evidence_revision_ids = list(dict.fromkeys(references))
    counts = (f"[Mô phỏng] Đã xem {len(changes.added_revision_ids)} ghi nhận mới, "
              f"{len(changes.updated_previous_revisions)} bản sửa và {len(changes.removed_revisions)} ghi nhận rút khỏi đầu vào. ")
    was_demo = previous.model_version.startswith("mock-demo-")
    is_demo = result.model_version.startswith("mock-demo-")
    # This is an exact scripted-stage comparison, not semantic matching of real AI findings.
    changed_stage = is_demo and was_demo and [r.action for r in previous.recommendations] != [r.action for r in result.recommendations]
    result.has_meaningful_changes = was_demo != is_demo or changed_stage
    if changed_stage:
        result.change_summary = counts + ("Kịch bản mẫu điều chỉnh lại hướng dẫn vì ghi nhận làm căn cứ đã được sửa hoặc rút khỏi đầu vào."
            if changes.updated_previous_revisions or changes.removed_revisions else
            "Kịch bản mẫu điều chỉnh hướng dẫn theo phản hồi của phụ huynh; vài buổi thử chưa chứng minh tiến bộ bền vững.")
    elif is_demo and not was_demo:
        result.change_summary = counts + "Đầu vào hiện khớp bộ demo đầy đủ, nên bổ sung giả thuyết và việc nên thử được viết sẵn."
    elif was_demo and not is_demo:
        result.change_summary = counts + "Đầu vào không còn phù hợp với kịch bản demo; các gợi ý viết sẵn được rút lại."
    else:
        result.change_summary = counts + ("Chưa có thay đổi đáng kể trong nội dung kịch bản mẫu." if is_demo
                                        else "Chưa mô phỏng thay đổi về hiểu biết hay hướng dẫn hành vi.")
    if result.has_meaningful_changes and not result.change_evidence_revision_ids:
        result.change_evidence_revision_ids = request.previous_state.input_revision_ids[:2]
    return result

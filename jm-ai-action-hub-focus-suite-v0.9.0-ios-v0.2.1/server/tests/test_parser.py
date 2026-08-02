from datetime import datetime
from zoneinfo import ZoneInfo

from action_hub.models import ActionType, Destination
from action_hub.services.parser import RuleBasedActionParser


def test_korean_multi_action_parsing(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    text = """내일 오전 10시 선진 HCI 미팅
오늘 오후 6시까지 견적서 초안 작성
repo:whelp99-code/Proof-Graph 로그인 버그 수정"""
    items = parser.parse(text, reference, "Asia/Seoul")
    assert len(items) == 3
    assert items[0].item_type == ActionType.EVENT
    assert items[0].destination == Destination.LOCAL_ICS
    assert items[0].start_at.isoformat() == "2026-07-29T10:00:00+09:00"
    assert items[1].item_type == ActionType.TODO
    assert items[1].due_at.isoformat() == "2026-07-28T18:00:00+09:00"
    assert items[2].item_type == ActionType.PROJECT_TASK
    assert items[2].destination == Destination.GITHUB
    assert items[2].repository == "whelp99-code/Proof-Graph"


def test_event_without_time_requires_review(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    item = parser.parse("내일 고객 미팅", reference, "Asia/Seoul")[0]
    assert item.needs_review is True
    assert "시작 시간이 없음" in item.review_reason


def test_vague_time_requires_review(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    item = parser.parse("다음 주 중 견적서 검토", reference, "Asia/Seoul")[0]
    assert item.needs_review is True


def test_comma_separated_voice_input_becomes_three_actions(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    items = parser.parse(
        "내일 10시 고객 미팅, 미팅 전에 GPU 라이선스 확인, 금요일까지 견적 보내기",
        reference,
        "Asia/Seoul",
    )
    assert [item.item_type for item in items] == [ActionType.EVENT, ActionType.TODO, ActionType.TODO]
    assert items[0].start_at.isoformat() == "2026-07-29T10:00:00+09:00"
    assert items[1].destination == Destination.TODOIST
    assert items[2].due_at.isoformat() == "2026-07-31T23:59:00+09:00"


def test_event_word_used_as_task_context_is_not_calendar_event(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    items = parser.parse(
        "회의 후 결과 보고\n미팅 자료 준비\n내일 오후 2시 개발 회의",
        reference,
        "Asia/Seoul",
    )
    assert items[0].item_type == ActionType.TODO
    assert items[1].item_type == ActionType.TODO
    assert items[2].item_type == ActionType.EVENT


def test_project_route_maps_hashtag_to_github(settings):
    routed_settings = settings.model_copy(update={
        "github_default_repo": None,
        "project_routes_json": '{"proof":"whelp99-code/Proof-Graph"}',
    })
    parser = RuleBasedActionParser(routed_settings)
    reference = datetime(2026, 7, 28, 19, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    item = parser.parse("#proof 로그인 흐름 수정", reference, "Asia/Seoul")[0]
    assert item.item_type == ActionType.PROJECT_TASK
    assert item.destination == Destination.GITHUB
    assert item.repository == "whelp99-code/Proof-Graph"
    assert "#proof" not in item.title

def test_duration_is_not_misread_as_clock_time(settings):
    parser = RuleBasedActionParser(settings)
    reference = datetime(2026, 7, 29, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    item = parser.parse(
        "금요일까지 제안서 보내기 2시간 deep work",
        reference,
        "Asia/Seoul",
    )[0]
    assert item.item_type == ActionType.TODO
    assert item.due_at.isoformat() == "2026-07-31T23:59:00+09:00"
    assert item.deadline_at.isoformat() == "2026-07-31T23:59:00+09:00"
    assert item.estimated_minutes == 120
    assert item.is_all_day is True
    assert item.title == "제안서 보내기 deep work"

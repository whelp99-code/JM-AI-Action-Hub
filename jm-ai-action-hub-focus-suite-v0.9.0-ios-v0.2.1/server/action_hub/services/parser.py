from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..models import ActionType, Destination, ExecutorType
from ..schemas import ActionItemDraft
from .date_parser import parse_temporal


EVENT_KEYWORDS = {
    "회의", "미팅", "면담", "약속", "예약", "교육", "세미나", "행사", "출장",
    "방문", "인터뷰", "통화", "콜", "meeting", "appointment", "interview", "webinar",
}
PROJECT_KEYWORDS = {
    "개발", "구현", "코드", "버그", "배포", "릴리스", "테스트", "리팩터링", "pr ",
    "pull request", "issue", "github", "저장소", "api", "docker", "ci", "기능명세",
}
REMINDER_KEYWORDS = {"알려줘", "알림", "리마인드", "기억해", "remind"}
ACTION_KEYWORDS = {
    "작성", "확인", "검토", "전달", "보내", "연락", "전화", "준비", "정리", "보고",
    "만들", "등록", "예약", "구매", "신청", "처리", "완료", "수정", "업로드", "설치",
    "구축", "분석", "비교", "문의", "회신", "제출", "결제", "발행", "개발", "구현",
    "배포", "테스트", "review", "write", "send", "call", "check", "prepare", "create",
}
NO_ACTION_PATTERNS = [r"^(안녕|감사|고마워|네|예|확인했습니다)[.!\s]*$", r"^참고[:：]?\s*$"]
EVENT_CONTEXT_TASK_PATTERNS = [
    r"(?:회의|미팅|면담|약속|교육|세미나|행사|출장|방문|인터뷰|통화|콜)\s*(?:전(?:에|까지)?|후(?:에)?|이전|이후|끝나(?:면|고)|자료|안건|결과|회의록|내용|일정)",
    r"(?:회의|미팅|면담|약속|교육|세미나|행사|출장|방문|인터뷰|통화|콜).{0,24}(?:확인|검토|준비|정리|보고|작성|전달|보내|문의|회신)",
]


class _LLMActionEnvelope(BaseModel):
    items: list[ActionItemDraft]


class ActionParser(Protocol):
    name: str

    def parse(self, text: str, reference: datetime, timezone_name: str) -> list[ActionItemDraft]: ...


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t ]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _has_action_signal(value: str) -> bool:
    lowered = value.lower()
    keywords = EVENT_KEYWORDS | PROJECT_KEYWORDS | REMINDER_KEYWORDS | ACTION_KEYWORDS
    if any(keyword in lowered for keyword in keywords):
        return True
    return bool(
        re.search(
            r"(?:오늘|내일|모레|이번\s*주|다음\s*주|\d{1,2}월\s*\d{1,2}일|"
            r"월요일|화요일|수요일|목요일|금요일|토요일|일요일|"
            r"\d{1,2}시|\d{1,2}:\d{2}|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _split_comma_clauses(value: str) -> list[str]:
    tokens = [x.strip() for x in re.split(r"[,，]\s*", value) if x.strip()]
    if len(tokens) <= 1:
        return tokens
    result: list[str] = []
    buffer = tokens[0]
    for token in tokens[1:]:
        if _has_action_signal(buffer) and _has_action_signal(token):
            result.append(buffer)
            buffer = token
        else:
            buffer = f"{buffer}, {token}"
    result.append(buffer)
    return result


def _event_is_context_for_task(fragment: str) -> bool:
    return any(re.search(pattern, fragment, flags=re.IGNORECASE) for pattern in EVENT_CONTEXT_TASK_PATTERNS)


def split_fragments(text: str) -> list[str]:
    normalized = normalize_text(text)
    normalized = re.sub(r"(?:^|\n)\s*[-*•·☐☑✅]\s*", "\n", normalized)
    primary = re.split(r"\n+|[;；]+|(?<=[.!?。])\s+", normalized)
    fragments: list[str] = []
    for chunk in primary:
        chunk = chunk.strip(" -•·\t")
        if not chunk:
            continue
        parts = re.split(r"\s*(?:그리고|또한|그다음|그 후)\s*", chunk)
        for part in parts:
            for clause in _split_comma_clauses(part):
                clause = clause.strip(" ,，")
                if clause:
                    fragments.append(clause)
    return fragments[:100]


def _clean_title(fragment: str, matched: list[str] | None) -> str:
    title = fragment
    for token in sorted(matched or [], key=len, reverse=True):
        title = title.replace(token, " ")
    title = re.sub(r"(?:(?:오늘|내일|모레|이번\s*주|다음\s*주)\s*)", " ", title)
    title = re.sub(r"(?:오전|오후|아침|점심|저녁|밤)\s*", " ", title)
    title = re.sub(
        r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        " ", title, flags=re.IGNORECASE,
    )
    title = re.sub(r"(?:까지|마감(?:으로)?|예정(?:으로)?|해야\s*(?:해|합니다|한다)?|해주세요|해줘|바랍니다)", " ", title)
    title = re.sub(r"(?:repo|저장소)\s*[:=]\s*[\w.-]+/[\w.-]+", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"(?:^|\s)[#@][\w가-힣.-]{2,80}", " ", title)
    title = re.sub(r"(?:약\s*)?(?:\d+(?:\.\d+)?\s*(?:시간|분|hours?|hrs?|minutes?|mins?))", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.-")
    return title[:500] or fragment[:500]


def _extract_repo(fragment: str) -> str | None:
    patterns = [
        r"(?:repo|repository|저장소)\s*[:=]\s*([\w.-]+/[\w.-]+)",
        r"\b([\w.-]+/[\w.-]+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, fragment, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_project(fragment: str) -> str | None:
    match = re.search(r"#([\w가-힣.-]{2,80})", fragment)
    return match.group(1) if match else None


def _extract_assignee(fragment: str) -> str | None:
    match = re.search(r"@([\w가-힣.-]{2,80})", fragment)
    return match.group(1) if match else None


def _priority(fragment: str) -> int:
    lowered = fragment.lower()
    if any(x in lowered for x in ("긴급", "최우선", "p1", "urgent", "critical")):
        return 4
    if any(x in lowered for x in ("중요", "우선", "p2", "high")):
        return 3
    if any(x in lowered for x in ("낮음", "p4", "low")):
        return 1
    return 2


def _duration_minutes(fragment: str) -> int | None:
    korean_numbers = {"한": 1, "두": 2, "세": 3, "네": 4}
    match = re.search(r"(?:약\s*)?(\d+(?:\.\d+)?)\s*(시간|hours?|hrs?)", fragment, flags=re.IGNORECASE)
    if match:
        return max(1, int(float(match.group(1)) * 60))
    match = re.search(r"(?:약\s*)?(\d+)\s*(분|minutes?|mins?)", fragment, flags=re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    match = re.search(r"\b(한|두|세|네)\s*시간", fragment)
    if match:
        return korean_numbers[match.group(1)] * 60
    return None


def _work_mode(fragment: str, item_type: ActionType) -> str:
    lowered = fragment.lower()
    if item_type == ActionType.EVENT:
        return "meeting"
    if any(x in lowered for x in ("전화", "통화", "콜", "call", "문의")):
        return "call"
    if any(x in lowered for x in ("구매", "방문", "픽업", "수령", "errand")):
        return "errand"
    if any(x in lowered for x in ("결제", "세금계산서", "발행", "등록", "신청", "업로드", "제출", "admin")):
        return "admin"
    if any(x in lowered for x in ("개발", "구현", "설계", "분석", "작성", "리팩터링", "코드", "제안서", "보고서", "deep")):
        return "deep"
    if item_type in {ActionType.TODO, ActionType.PROJECT_TASK}:
        return "shallow"
    return "unspecified"


def _executor(fragment: str) -> tuple[ExecutorType, str | None]:
    lowered = fragment.lower()
    workers = {
        "codex": ("codex", "코덱스"),
        "claude": ("claude", "클로드"),
        "copilot": ("copilot", "코파일럿"),
        "orca": ("orca", "오르카"),
        "hermes": ("hermes", "헤르메스"),
    }
    preferred = next((name for name, tokens in workers.items() if any(token in lowered for token in tokens)), None)
    if any(x in lowered for x in ("회신 대기", "답변 대기", "응답 대기", "기다리는", "waiting for")):
        return ExecutorType.EXTERNAL, preferred
    if any(x in lowered for x in ("ai 초안", "초안 후 검토", "검토 후 승인", "human review", "하이브리드")):
        return ExecutorType.HYBRID, preferred
    if preferred or any(x in lowered for x in ("ai에게", "ai로", "에이전트에게", "agent-ready", "자동 개발")):
        return ExecutorType.AI, preferred
    return ExecutorType.HUMAN, None


def _waiting_for(fragment: str) -> str | None:
    patterns = [
        r"([\w가-힣 ._-]{2,50}?)(?:에게|한테|의)\s*(?:회신|답변|응답|확인|결과)\s*(?:대기|기다)",
        r"([\w가-힣 ._-]{2,50}?)\s*(?:회신|답변|응답)\s*대기",
        r"waiting\s+for\s+([\w ._-]{2,50})",
    ]
    for pattern in patterns:
        match = re.search(pattern, fragment, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def action_fingerprint(item: ActionItemDraft) -> str:
    canonical = "|".join(
        [
            item.item_type.value,
            item.destination.value,
            re.sub(r"\s+", " ", item.title.lower()).strip(),
            item.repository or "",
            item.start_at.isoformat() if item.start_at else "",
            item.due_at.isoformat() if item.due_at else "",
            item.deadline_at.isoformat() if item.deadline_at else "",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RuleBasedActionParser:
    name = "rules-v2"

    def __init__(self, settings: Settings):
        self.settings = settings

    def parse(self, text: str, reference: datetime, timezone_name: str) -> list[ActionItemDraft]:
        tz = ZoneInfo(timezone_name)
        reference = reference.replace(tzinfo=tz) if reference.tzinfo is None else reference.astimezone(tz)

        result: list[ActionItemDraft] = []
        for fragment in split_fragments(text):
            if any(re.match(pattern, fragment.strip(), flags=re.IGNORECASE) for pattern in NO_ACTION_PATTERNS):
                continue
            lowered = fragment.lower()
            temporal = parse_temporal(fragment, reference, timezone_name)
            repo = _extract_repo(fragment)
            project = _extract_project(fragment)
            assignee = _extract_assignee(fragment)
            routed_repo = self.settings.project_routes.get(project.lower()) if project else None

            has_event_keyword = any(keyword in lowered for keyword in EVENT_KEYWORDS)
            has_project_keyword = any(keyword in lowered for keyword in PROJECT_KEYWORDS)
            event_is_context = has_event_keyword and _event_is_context_for_task(fragment)

            if repo or routed_repo:
                item_type = ActionType.PROJECT_TASK
            elif has_event_keyword and not event_is_context:
                item_type = ActionType.EVENT
            elif has_project_keyword:
                item_type = ActionType.PROJECT_TASK
            elif any(keyword in lowered for keyword in REMINDER_KEYWORDS):
                item_type = ActionType.REMINDER
            elif event_is_context or any(keyword in lowered for keyword in ACTION_KEYWORDS) or temporal.has_date:
                item_type = ActionType.TODO
            else:
                item_type = ActionType.NOTE

            if item_type == ActionType.EVENT:
                destination = Destination.GOOGLE_CALENDAR if self.settings.google_calendar_access_token else Destination.LOCAL_ICS
            elif item_type == ActionType.PROJECT_TASK:
                destination = Destination.GITHUB if (repo or routed_repo or self.settings.github_default_repo) else Destination.TODOIST
            elif item_type in {ActionType.TODO, ActionType.REMINDER}:
                destination = Destination.TODOIST
            else:
                destination = Destination.NONE

            needs_review = temporal.vague
            reasons: list[str] = []
            if temporal.vague:
                reasons.append("모호한 시간 표현")
            if item_type == ActionType.EVENT and (not temporal.has_date or not temporal.has_time):
                needs_review = True
                reasons.append("일정의 날짜 또는 시작 시간이 없음")
            if item_type == ActionType.PROJECT_TASK and destination == Destination.GITHUB and not (
                repo or routed_repo or self.settings.github_default_repo
            ):
                needs_review = True
                reasons.append("GitHub 저장소가 지정되지 않음")

            start_at = end_at = due_at = deadline_at = earliest_start_at = latest_finish_at = None
            if item_type == ActionType.EVENT:
                if temporal.at:
                    start_at = temporal.at
                    end_at = temporal.at if temporal.is_all_day else temporal.at + timedelta(minutes=self.settings.default_event_minutes)
            elif temporal.at:
                due_at = temporal.at
                if re.search(r"(?:까지|마감|deadline|due\s+by)", fragment, flags=re.IGNORECASE):
                    deadline_at = temporal.at
                if re.search(r"(?:이후|부터|after)", fragment, flags=re.IGNORECASE):
                    earliest_start_at = temporal.at
                if re.search(r"(?:전에|이전|before)", fragment, flags=re.IGNORECASE):
                    latest_finish_at = temporal.at

            executor, preferred_worker = _executor(fragment)
            waiting_for = _waiting_for(fragment)
            if waiting_for:
                executor = ExecutorType.EXTERNAL
            follow_up_at = None
            if executor == ExecutorType.EXTERNAL:
                follow_up_at = temporal.at if temporal.at else reference + timedelta(days=self.settings.followup_default_days)

            work_mode = _work_mode(fragment, item_type)
            estimated = _duration_minutes(fragment)
            if estimated is None and item_type != ActionType.NOTE:
                estimated = self.settings.default_event_minutes if item_type == ActionType.EVENT else self.settings.default_estimated_minutes
            energy = "high" if work_mode == "deep" else ("low" if work_mode in {"admin", "errand"} else "medium")

            confidence = 0.58
            if item_type != ActionType.NOTE:
                confidence += 0.12
            if temporal.has_date:
                confidence += 0.08
            if temporal.has_time:
                confidence += 0.08
            if repo or project:
                confidence += 0.06
            if estimated:
                confidence += 0.03
            if needs_review:
                confidence -= 0.12
            confidence = max(0.1, min(0.98, confidence))

            title = _clean_title(fragment, temporal.matched_text)
            labels: list[str] = []
            if project:
                labels.append(project)
            if item_type == ActionType.PROJECT_TASK:
                labels.append("action-hub")
            if work_mode != "unspecified":
                labels.append(work_mode)
            if executor in {ExecutorType.AI, ExecutorType.HYBRID}:
                labels.append("agent-ready")

            result.append(
                ActionItemDraft(
                    item_type=item_type,
                    destination=destination,
                    title=title,
                    description=f"원문: {fragment}",
                    source_fragment=fragment,
                    project=project,
                    repository=(repo or routed_repo or self.settings.github_default_repo) if item_type == ActionType.PROJECT_TASK else None,
                    assignee=assignee,
                    start_at=start_at,
                    end_at=end_at,
                    due_at=due_at,
                    deadline_at=deadline_at,
                    earliest_start_at=earliest_start_at,
                    latest_finish_at=latest_finish_at,
                    is_all_day=temporal.is_all_day,
                    priority=_priority(fragment),
                    labels=list(dict.fromkeys(labels)),
                    confidence=round(confidence, 2),
                    needs_review=needs_review,
                    review_reason="; ".join(dict.fromkeys(reasons)) or None,
                    estimated_minutes=estimated,
                    work_mode=work_mode,
                    executor=executor,
                    preferred_worker=preferred_worker,
                    energy_level=energy,
                    waiting_for=waiting_for,
                    follow_up_at=follow_up_at,
                )
            )
        return result


@dataclass(slots=True)
class LLMActionParser:
    settings: Settings
    name: str = "openai-compatible-json-v2"

    def parse(self, text: str, reference: datetime, timezone_name: str) -> list[ActionItemDraft]:
        if not self.settings.llm_base_url or not self.settings.llm_api_key or not self.settings.llm_model:
            raise RuntimeError("LLM parser is not configured")
        endpoint = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        schema = _LLMActionEnvelope.model_json_schema()
        system = (
            "Convert Korean or English messages into action items. Never invent dates, assignees, repositories, "
            "durations, or commitments. Separate scheduled dates from hard deadlines. Classify executor as human, "
            "ai, hybrid, or external. Events require exact date and time; otherwise needs_review=true. Return JSON only."
        )
        user = json.dumps(
            {
                "reference_time": reference.isoformat(),
                "timezone": timezone_name,
                "destination_policy": {
                    "event": "google_calendar when configured, otherwise local_ics",
                    "personal_task": "todoist",
                    "project_task": "github only when repository is known; otherwise todoist with needs_review",
                    "note": "none",
                },
                "schema": schema,
                "input": text,
            },
            ensure_ascii=False,
        )
        with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": self.settings.llm_model,
                    "temperature": 0,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            payload = response.json()
        raw = payload["choices"][0]["message"]["content"]
        try:
            return _LLMActionEnvelope.model_validate(json.loads(raw)).items
        except (ValidationError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LLM returned invalid action schema: {exc}") from exc


class HybridActionParser:
    name = "hybrid-v2"

    def __init__(self, settings: Settings):
        self.rules = RuleBasedActionParser(settings)
        self.llm = LLMActionParser(settings)

    def parse(self, text: str, reference: datetime, timezone_name: str) -> list[ActionItemDraft]:
        try:
            return self.llm.parse(text, reference, timezone_name)
        except Exception:
            return self.rules.parse(text, reference, timezone_name)


def build_parser(settings: Settings) -> ActionParser:
    if settings.parser_mode == "llm":
        return LLMActionParser(settings)
    if settings.parser_mode == "hybrid":
        return HybridActionParser(settings)
    return RuleBasedActionParser(settings)

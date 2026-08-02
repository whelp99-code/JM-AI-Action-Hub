from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActionItem, ExecutorType, PersonalRule
from ..schemas import ActionItemDraft
from .audit import record_audit


SAFE_RULE_FIELDS = {
    "project",
    "repository",
    "assignee",
    "priority",
    "labels",
    "estimated_minutes",
    "work_mode",
    "executor",
    "preferred_worker",
    "energy_level",
    "waiting_for",
}


def _normalized(value: Any) -> Any:
    return value.lower().strip() if isinstance(value, str) else value


def rule_matches(draft: ActionItemDraft, condition: dict[str, Any]) -> bool:
    for key, expected in condition.items():
        if key == "title_contains":
            terms = expected if isinstance(expected, list) else [expected]
            if not all(str(term).lower() in draft.title.lower() for term in terms):
                return False
            continue
        if key == "labels_any":
            labels = {_normalized(x) for x in draft.labels}
            options = expected if isinstance(expected, list) else [expected]
            if not labels.intersection({_normalized(x) for x in options}):
                return False
            continue
        actual = getattr(draft, key, None)
        if hasattr(actual, "value"):
            actual = actual.value
        if isinstance(expected, list):
            if _normalized(actual) not in {_normalized(x) for x in expected}:
                return False
        elif _normalized(actual) != _normalized(expected):
            return False
    return True


def _apply_action(draft: ActionItemDraft, action: dict[str, Any]) -> None:
    for field, value in action.items():
        if field not in SAFE_RULE_FIELDS:
            continue
        if field == "labels":
            values = value if isinstance(value, list) else [value]
            draft.labels = list(dict.fromkeys([*draft.labels, *[str(x) for x in values]]))
        elif field == "executor":
            draft.executor = ExecutorType(str(value))
        elif field == "priority":
            draft.priority = max(1, min(4, int(value)))
        elif field == "estimated_minutes":
            draft.estimated_minutes = max(1, int(value))
        else:
            setattr(draft, field, value)


def apply_active_rules(db: Session, drafts: list[ActionItemDraft]) -> int:
    rules = list(db.scalars(select(PersonalRule).where(PersonalRule.status == "active")))
    applied = 0
    for rule in rules:
        matches = 0
        for draft in drafts:
            if rule_matches(draft, rule.condition_json or {}):
                _apply_action(draft, rule.action_json or {})
                matches += 1
        if matches:
            rule.applied_count += matches
            applied += matches
            record_audit(
                db,
                entity_type="personal_rule",
                entity_id=rule.id,
                event_type="rule.applied",
                payload={"matches": matches},
            )
    return applied


def create_rule(
    db: Session,
    *,
    name: str,
    condition: dict[str, Any],
    action: dict[str, Any],
    status: str = "proposed",
) -> PersonalRule:
    unsafe = set(action) - SAFE_RULE_FIELDS
    if unsafe:
        raise ValueError(f"Rule contains unsafe fields: {', '.join(sorted(unsafe))}")
    if not condition:
        raise ValueError("Rule condition must not be empty")
    rule = PersonalRule(
        name=name,
        condition_json=condition,
        action_json=action,
        status=status,
        confidence=1.0 if status == "active" else 0.5,
    )
    db.add(rule)
    db.flush()
    record_audit(
        db,
        entity_type="personal_rule",
        entity_id=rule.id,
        event_type="rule.created",
        actor="user",
        payload={"status": status, "condition": condition, "action": action},
    )
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(db: Session, rule_id: str, changes: dict[str, Any]) -> PersonalRule:
    rule = db.get(PersonalRule, rule_id)
    if rule is None:
        raise LookupError("Personal rule not found")
    if changes.get("action") is not None:
        unsafe = set(changes["action"]) - SAFE_RULE_FIELDS
        if unsafe:
            raise ValueError(f"Rule contains unsafe fields: {', '.join(sorted(unsafe))}")
        rule.action_json = changes["action"]
    if changes.get("condition") is not None:
        if not changes["condition"]:
            raise ValueError("Rule condition must not be empty")
        rule.condition_json = changes["condition"]
    if changes.get("name") is not None:
        rule.name = changes["name"]
    if changes.get("status") is not None:
        rule.status = changes["status"]
        if rule.status == "active":
            rule.confidence = max(rule.confidence, 0.8)
    record_audit(
        db,
        entity_type="personal_rule",
        entity_id=rule.id,
        event_type="rule.updated",
        actor="user",
        payload={key: value for key, value in changes.items() if value is not None},
    )
    db.commit()
    db.refresh(rule)
    return rule


def _stable_value(items: list[ActionItem], field: str, minimum: int) -> tuple[Any, float] | None:
    values = [getattr(item, field) for item in items if getattr(item, field) not in (None, "", [], "unspecified")]
    if len(values) < minimum:
        return None
    counter = Counter(str(value) if not isinstance(value, (list, dict)) else repr(value) for value in values)
    encoded, count = counter.most_common(1)[0]
    if count < minimum or count / len(values) < 0.8:
        return None
    original = next(value for value in values if (str(value) if not isinstance(value, (list, dict)) else repr(value)) == encoded)
    return original, count / len(values)


def suggest_rules(db: Session, minimum_observations: int = 3) -> list[PersonalRule]:
    items = list(db.scalars(select(ActionItem).where(ActionItem.project.is_not(None))))
    grouped: dict[str, list[ActionItem]] = defaultdict(list)
    for item in items:
        grouped[str(item.project)].append(item)
    existing = list(db.scalars(select(PersonalRule)))
    existing_conditions = {repr(sorted((rule.condition_json or {}).items())) for rule in existing}
    created: list[PersonalRule] = []
    for project, project_items in grouped.items():
        if len(project_items) < minimum_observations:
            continue
        action: dict[str, Any] = {}
        confidences: list[float] = []
        for field in ("repository", "work_mode", "executor", "preferred_worker", "estimated_minutes", "energy_level"):
            stable = _stable_value(project_items, field, minimum_observations)
            if stable:
                action[field], confidence = stable
                confidences.append(confidence)
        if not action:
            continue
        condition = {"project": project}
        key = repr(sorted(condition.items()))
        if key in existing_conditions:
            continue
        rule = PersonalRule(
            name=f"{project} 기본 실행 규칙",
            condition_json=condition,
            action_json=action,
            status="proposed",
            confidence=min(confidences) if confidences else 0.5,
            observations=len(project_items),
        )
        db.add(rule)
        db.flush()
        created.append(rule)
        existing_conditions.add(key)
        record_audit(
            db,
            entity_type="personal_rule",
            entity_id=rule.id,
            event_type="rule.suggested",
            payload={"project": project, "observations": len(project_items), "action": action},
        )
    db.commit()
    for rule in created:
        db.refresh(rule)
    return created

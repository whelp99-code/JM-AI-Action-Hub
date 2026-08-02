#!/usr/bin/env python3
"""Verify the frozen server/mobile contract used by the native iOS client."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "OpenAPI" / "action-hub.openapi.json"

REQUIRED_OPERATIONS = {
    ("GET", "/api/v1/mobile/capabilities"): "mobileCapabilities",
    ("POST", "/api/v1/mobile/pairings/claim"): "claimMobilePairing",
    ("POST", "/api/v1/mobile/token/refresh"): "refreshMobileToken",
    ("GET", "/api/v1/mobile/dashboard"): "getMobileDashboard",
    ("GET", "/api/v1/mobile/review"): "listMobileReviewPlans",
    ("GET", "/api/v1/mobile/plans/{plan_id}"): "getMobilePlan",
    ("PATCH", "/api/v1/mobile/plans/{plan_id}/items/{item_id}"): "updateMobileActionItem",
    ("POST", "/api/v1/mobile/plans/{plan_id}/approve"): "approveMobilePlan",
    ("POST", "/api/v1/mobile/plans/{plan_id}/reject"): "rejectMobilePlan",
    ("POST", "/api/v1/mobile/plans/{plan_id}/execute"): "executeMobilePlan",
    ("POST", "/api/v1/mobile/captures/batch"): "uploadMobileCaptures",
    ("GET", "/api/v1/mobile/activity"): "getMobileActivity",
    ("GET", "/api/v1/mobile/changes"): "getMobileChanges",
    ("POST", "/api/v1/mobile/devices/me/push-token"): "registerMobilePushToken",
    ("PATCH", "/api/v1/mobile/devices/me/notification-preferences"): "updateMobileNotificationPreferences",
    ("DELETE", "/api/v1/mobile/devices/me"): "revokeCurrentMobileDevice",
    ("GET", "/api/v1/mobile/triage"): "listMobileFocusTriage",
    ("POST", "/api/v1/mobile/actions/{item_id}/classify"): "classifyMobileFocusAction",
    ("GET", "/api/v1/mobile/matrix"): "getMobileFocusMatrix",
    ("GET", "/api/v1/mobile/commitments/today"): "getMobileBig3",
    ("POST", "/api/v1/mobile/commitments"): "setMobileBig3",
    ("POST", "/api/v1/mobile/actions/{item_id}/decompose"): "decomposeMobileFocusAction",
    ("PATCH", "/api/v1/mobile/microsteps/{step_id}"): "updateMobileMicroStep",
    ("GET", "/api/v1/mobile/focus-sessions/active"): "getMobileActiveFocusSession",
    ("POST", "/api/v1/mobile/focus-sessions"): "startMobileFocusSession",
    ("PATCH", "/api/v1/mobile/focus-sessions/{session_id}"): "updateMobileFocusSession",
    ("POST", "/api/v1/mobile/day-close"): "closeMobileFocusDay",
    ("GET", "/api/v1/mobile/reports/focus-weekly"): "getMobileFocusWeeklyReport",
}

REQUIRED_SCHEMA_FIELDS = {
    "MobileTokenResponse": {"access_token", "expires_in", "refresh_token", "refresh_expires_at", "device"},
    "MobileDeviceRead": {"id", "device_name", "status", "scopes", "token_version", "notification_preferences"},
    "MobileDashboard": {"server_version", "minimum_ios_app_version", "review_count", "brief", "decision", "recent_activity"},
    "MobileCaptureBatchResponse": {"accepted", "processed", "duplicate", "failed", "receipts"},
    "MobileChangesResponse": {"next_cursor", "has_more", "changes"},
    "PlanRead": {"id", "status", "revision", "items"},
    "ActionItemRead": {"id", "plan_id", "revision", "state", "title", "destination", "executor"},
    "MobileActionItemUpdate": {"expected_revision"},
    "ExecutionSummary": {"plan_id", "plan_status", "completed", "failed", "items"},
    "TriageResponse": {"generated_at", "total", "items"},
    "PriorityAssessmentRead": {"action_item_id", "importance_score", "urgency_score", "quadrant", "reasons_json"},
    "MatrixResponse": {"counts", "q1", "q2", "q3", "q4", "untriaged_count"},
    "DualBig3Response": {"date", "available_minutes", "human", "ai", "overload_minutes"},
    "FocusSessionRead": {"action_item_id", "planned_minutes", "elapsed_seconds", "state", "traffic_state", "micro_steps"},
    "FocusWeeklyReport": {"focus_minutes", "big3_completion_rate", "q2_investment_minutes", "carry_over_count"},
}


def fail(message: str) -> None:
    raise SystemExit(f"OPENAPI_CONTRACT_FAILED: {message}")


def main() -> None:
    document = json.loads(OPENAPI.read_text())
    if document.get("info", {}).get("version") != "0.9.0":
        fail(f"unexpected server version: {document.get('info', {}).get('version')}")

    operation_ids: list[str] = []
    for path, path_item in document.get("paths", {}).items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and operation.get("operationId"):
                operation_ids.append(operation["operationId"])
    duplicates = sorted({value for value in operation_ids if operation_ids.count(value) > 1})
    if duplicates:
        fail(f"duplicate operation IDs: {duplicates}")

    for (method, path), expected in REQUIRED_OPERATIONS.items():
        operation = document.get("paths", {}).get(path, {}).get(method.lower())
        if not operation:
            fail(f"missing {method} {path}")
        if operation.get("operationId") != expected:
            fail(f"{method} {path} operationId={operation.get('operationId')!r}, expected={expected!r}")

    schemes = document.get("components", {}).get("securitySchemes", {})
    bearer = schemes.get("ActionHubMobileBearer", {})
    if bearer.get("type") != "http" or bearer.get("scheme") != "bearer":
        fail("ActionHubMobileBearer security scheme is missing or malformed")
    admin = schemes.get("ActionHubAdminKey", {})
    if admin.get("type") != "apiKey" or admin.get("name") != "X-Action-Hub-Key":
        fail("ActionHubAdminKey security scheme is missing or malformed")

    protected = document["paths"]["/api/v1/mobile/dashboard"]["get"].get("security", [])
    if {"ActionHubMobileBearer": []} not in protected:
        fail("mobile dashboard is not declared as bearer protected")

    schemas = document.get("components", {}).get("schemas", {})
    for name, fields in REQUIRED_SCHEMA_FIELDS.items():
        schema = schemas.get(name)
        if not schema:
            fail(f"missing schema {name}")
        properties = set(schema.get("properties", {}))
        missing = sorted(fields - properties)
        if missing:
            fail(f"schema {name} misses properties {missing}")

    source = (ROOT / "Packages" / "ActionHubCore" / "Sources" / "ActionHubCore" / "ActionHubAPIClient.swift").read_text()
    for _method, path in REQUIRED_OPERATIONS:
        static_prefix = path.split("{")[0].rstrip("/")
        if static_prefix and static_prefix not in source:
            fail(f"Swift client does not reference API prefix {static_prefix}")

    digest = hashlib.sha256(OPENAPI.read_bytes()).hexdigest()
    print(json.dumps({"status": "ok", "version": "0.9.0", "operations": len(operation_ids), "sha256": digest}, sort_keys=True))


if __name__ == "__main__":
    main()

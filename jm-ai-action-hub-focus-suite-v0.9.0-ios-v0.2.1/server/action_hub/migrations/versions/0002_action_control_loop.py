"""Closed-loop sync, durable execution, workers, follow-up, meetings, and learning."""

import sqlalchemy as sa
from alembic import op

revision = "0002_action_control_loop"
down_revision = "0001_initial_v010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    additions = [
        sa.Column("source_fragment", sa.Text(), nullable=False, server_default=""),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("earliest_start_at", sa.DateTime(), nullable=True),
        sa.Column("latest_finish_at", sa.DateTime(), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("work_mode", sa.String(32), nullable=False, server_default="unspecified"),
        sa.Column("executor", sa.String(32), nullable=False, server_default="human"),
        sa.Column("preferred_worker", sa.String(64), nullable=True),
        sa.Column("energy_level", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("waiting_for", sa.String(255), nullable=True),
        sa.Column("follow_up_at", sa.DateTime(), nullable=True),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("completion_evidence", sa.Text(), nullable=True),
        sa.Column("reschedule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("registered_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    ]
    with op.batch_alter_table("action_items") as batch:
        for column in additions:
            batch.add_column(column)
        batch.create_index("ix_action_items_work_mode", ["work_mode"])
        batch.create_index("ix_action_items_executor", ["executor"])
        batch.create_index("ix_action_items_follow_up_at", ["follow_up_at"])

    with op.batch_alter_table("audit_events") as batch:
        batch.alter_column("entity_id", type_=sa.String(64), existing_type=sa.String(36))

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("destination", sa.String(64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
    )
    for name, columns, unique in (
        ("ix_outbox_events_aggregate_type", ["aggregate_type"], False),
        ("ix_outbox_events_aggregate_id", ["aggregate_id"], False),
        ("ix_outbox_events_event_type", ["event_type"], False),
        ("ix_outbox_events_destination", ["destination"], False),
        ("ix_outbox_events_idempotency_key", ["idempotency_key"], True),
        ("ix_outbox_events_state", ["state"], False),
        ("ix_outbox_events_next_attempt_at", ["next_attempt_at"], False),
    ):
        op.create_index(name, "outbox_events", columns, unique=unique)

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("delivery_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("headers_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "delivery_id", name="uq_webhook_provider_delivery"),
    )
    for name, columns in (
        ("ix_webhook_deliveries_provider", ["provider"]),
        ("ix_webhook_deliveries_event_type", ["event_type"]),
        ("ix_webhook_deliveries_status", ["status"]),
    ):
        op.create_index(name, "webhook_deliveries", columns)

    op.create_table(
        "external_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_item_id", sa.String(36), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("state", sa.String(64), nullable=False, server_default="open"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("external_updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
        sa.Column("sync_error", sa.Text(), nullable=True),
        sa.Column("source_version", sa.String(80), nullable=True),
        sa.UniqueConstraint("provider", "external_id", name="uq_external_provider_id"),
    )
    for name, columns in (
        ("ix_external_states_action_item_id", ["action_item_id"]),
        ("ix_external_states_provider", ["provider"]),
        ("ix_external_states_external_id", ["external_id"]),
        ("ix_external_states_state", ["state"]),
    ):
        op.create_index(name, "external_states", columns)

    op.create_table(
        "sync_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_item_id", sa.String(36), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("conflict_type", sa.String(80), nullable=False),
        sa.Column("local_value", sa.JSON(), nullable=False),
        sa.Column("external_value", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    for name, columns in (
        ("ix_sync_conflicts_action_item_id", ["action_item_id"]),
        ("ix_sync_conflicts_provider", ["provider"]),
        ("ix_sync_conflicts_conflict_type", ["conflict_type"]),
    ):
        op.create_index(name, "sync_conflicts", columns)

    op.create_table(
        "worker_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_item_id", sa.String(36), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("worker", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("dispatch_id", sa.String(255), nullable=True),
        sa.Column("repository", sa.String(255), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("workflow_run_id", sa.String(255), nullable=True),
        sa.Column("artifacts_json", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_worker_executions_action_item_id", ["action_item_id"]),
        ("ix_worker_executions_worker", ["worker"]),
        ("ix_worker_executions_state", ["state"]),
        ("ix_worker_executions_dispatch_id", ["dispatch_id"]),
    ):
        op.create_index(name, "worker_executions", columns)

    op.create_table(
        "followups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_item_id", sa.String(36), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("waiting_for", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(40), nullable=True),
        sa.Column("expected_by", sa.DateTime(), nullable=True),
        sa.Column("follow_up_at", sa.DateTime(), nullable=False),
        sa.Column("template", sa.Text(), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reminded_at", sa.DateTime(), nullable=True),
        sa.Column("response_received_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_followups_action_item_id", ["action_item_id"]),
        ("ix_followups_state", ["state"]),
        ("ix_followups_follow_up_at", ["follow_up_at"]),
    ):
        op.create_index(name, "followups", columns)

    op.create_table(
        "personal_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("condition_json", sa.JSON(), nullable=False),
        sa.Column("action_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_personal_rules_status", "personal_rules", ["status"])

    op.create_table(
        "metric_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(32), nullable=False, server_default="count"),
        sa.Column("action_item_id", sa.String(36), sa.ForeignKey("action_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_metric_events_metric_name", ["metric_name"]),
        ("ix_metric_events_action_item_id", ["action_item_id"]),
        ("ix_metric_events_occurred_at", ["occurred_at"]),
    ):
        op.create_index(name, "metric_events", columns)

    op.create_table(
        "meeting_intakes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="fireflies"),
        sa.Column("external_meeting_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("transcript_url", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("action_plan_id", sa.String(36), sa.ForeignKey("action_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("provider", "external_meeting_id", "event_type", name="uq_meeting_event"),
    )
    op.create_index("ix_meeting_intakes_status", "meeting_intakes", ["status"])
    op.create_index("ix_meeting_intakes_action_plan_id", "meeting_intakes", ["action_plan_id"])


def downgrade() -> None:
    for table in (
        "meeting_intakes",
        "metric_events",
        "personal_rules",
        "followups",
        "worker_executions",
        "sync_conflicts",
        "external_states",
        "webhook_deliveries",
        "outbox_events",
    ):
        op.drop_table(table)
    with op.batch_alter_table("action_items") as batch:
        for column in (
            "completed_at", "registered_at", "reschedule_count", "completion_evidence", "depends_on",
            "follow_up_at", "waiting_for", "energy_level", "preferred_worker", "executor", "work_mode",
            "actual_minutes", "estimated_minutes", "latest_finish_at", "earliest_start_at", "deadline_at",
            "source_fragment",
        ):
            batch.drop_column(column)

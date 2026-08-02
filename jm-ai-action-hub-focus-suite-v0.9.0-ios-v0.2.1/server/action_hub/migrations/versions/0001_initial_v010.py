"""JM-AI Action Hub v0.1.0 baseline schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_v010"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="paste"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Seoul"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="parsed"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_inbox_entries_fingerprint"),
    )
    op.create_index("ix_inbox_entries_fingerprint", "inbox_entries", ["fingerprint"], unique=True)

    op.create_table(
        "action_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("inbox_id", sa.String(36), sa.ForeignKey("inbox_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("parser_name", sa.String(80), nullable=False, server_default="rules-v1"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reference_time", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_plans_inbox_id", "action_plans", ["inbox_id"])
    op.create_index("ix_action_plans_status", "action_plans", ["status"])

    op.create_table(
        "action_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("action_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("destination", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("project", sa.String(255), nullable=True),
        sa.Column("repository", sa.String(255), nullable=True),
        sa.Column("assignee", sa.String(255), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("execution_payload", sa.JSON(), nullable=False),
        sa.Column("execution_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_action_items_plan_id", ["plan_id"]),
        ("ix_action_items_item_type", ["item_type"]),
        ("ix_action_items_destination", ["destination"]),
        ("ix_action_items_needs_review", ["needs_review"]),
        ("ix_action_items_state", ["state"]),
        ("ix_action_items_fingerprint", ["fingerprint"]),
        ("ix_action_items_destination_fingerprint_state", ["destination", "fingerprint", "state"]),
    ):
        op.create_index(name, "action_items", columns)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False, server_default="system"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_audit_events_entity_type", ["entity_type"]),
        ("ix_audit_events_entity_id", ["entity_id"]),
        ("ix_audit_events_event_type", ["event_type"]),
        ("ix_audit_events_created_at", ["created_at"]),
    ):
        op.create_index(name, "audit_events", columns)


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("action_items")
    op.drop_table("action_plans")
    op.drop_table("inbox_entries")

"""Add secure native mobile companion foundation."""

import sqlalchemy as sa
from alembic import op

revision = "0004_mobile_foundation"
down_revision = "0003_operational_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("action_plans", "action_items"):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("revision", sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table_name} SET revision = 1 WHERE revision IS NULL")
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column("revision", nullable=False)

    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("hardware_model", sa.String(length=128), nullable=True),
        sa.Column("os_version", sa.String(length=64), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("push_token", sa.String(length=512), nullable=True, unique=True),
        sa.Column("push_environment", sa.String(length=24), nullable=False),
        sa.Column("notification_preferences", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_mobile_devices_platform", "mobile_devices", ["platform"])
    op.create_index("ix_mobile_devices_status", "mobile_devices", ["status"])
    op.create_index("ix_mobile_devices_last_seen_at", "mobile_devices", ["last_seen_at"])

    op.create_table(
        "mobile_pairing_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_device_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["claimed_device_id"], ["mobile_devices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_mobile_pairing_sessions_status", "mobile_pairing_sessions", ["status"])
    op.create_index("ix_mobile_pairing_sessions_expires_at", "mobile_pairing_sessions", ["expires_at"])
    op.create_index(
        "ix_mobile_pairing_sessions_claimed_device_id",
        "mobile_pairing_sessions",
        ["claimed_device_id"],
    )

    op.create_table(
        "mobile_refresh_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by_id", sa.String(length=36), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["mobile_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["mobile_refresh_tokens.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_mobile_refresh_tokens_device_id", "mobile_refresh_tokens", ["device_id"])
    op.create_index("ix_mobile_refresh_tokens_family_id", "mobile_refresh_tokens", ["family_id"])
    op.create_index("ix_mobile_refresh_tokens_expires_at", "mobile_refresh_tokens", ["expires_at"])

    op.create_table(
        "mobile_captures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("client_capture_id", sa.String(length=80), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["mobile_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["action_plans.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("device_id", "client_capture_id", name="uq_mobile_capture_device_client"),
    )
    op.create_index("ix_mobile_captures_device_id", "mobile_captures", ["device_id"])
    op.create_index("ix_mobile_captures_content_hash", "mobile_captures", ["content_hash"])
    op.create_index("ix_mobile_captures_plan_id", "mobile_captures", ["plan_id"])
    op.create_index("ix_mobile_captures_status", "mobile_captures", ["status"])

    op.create_table(
        "push_notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["mobile_devices.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_push_notifications_device_id", "push_notifications", ["device_id"])
    op.create_index("ix_push_notifications_event_type", "push_notifications", ["event_type"])
    op.create_index("ix_push_notifications_entity_id", "push_notifications", ["entity_id"])
    op.create_index("ix_push_notifications_state", "push_notifications", ["state"])
    op.create_index("ix_push_notifications_next_attempt_at", "push_notifications", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_table("push_notifications")
    op.drop_table("mobile_captures")
    op.drop_table("mobile_refresh_tokens")
    op.drop_table("mobile_pairing_sessions")
    op.drop_table("mobile_devices")
    for table_name in ("action_items", "action_plans"):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("revision")

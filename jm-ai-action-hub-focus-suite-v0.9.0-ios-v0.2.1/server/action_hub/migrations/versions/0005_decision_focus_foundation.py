"""Add decision, focus, micro-step, and carry-over control loop."""

import sqlalchemy as sa
from alembic import op

revision = "0005_decision_focus_foundation"
down_revision = "0004_mobile_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("action_items") as batch:
        batch.add_column(sa.Column("attention_state", sa.String(length=32), nullable=True))
    op.execute("UPDATE action_items SET attention_state = 'untriaged' WHERE attention_state IS NULL")
    with op.batch_alter_table("action_items") as batch:
        batch.alter_column("attention_state", nullable=False)
    op.create_index("ix_action_items_attention_state", "action_items", ["attention_state"])

    op.create_table(
        "priority_assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action_item_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("urgency_score", sa.Float(), nullable=False),
        sa.Column("quadrant", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons_json", sa.JSON(), nullable=False),
        sa.Column("user_overridden", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_priority_assessments_action_item_id", "priority_assessments", ["action_item_id"])
    op.create_index("ix_priority_assessments_quadrant", "priority_assessments", ["quadrant"])

    op.create_table(
        "daily_focus_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_date", sa.Date(), nullable=False, unique=True),
        sa.Column("available_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_daily_focus_plans_plan_date", "daily_focus_plans", ["plan_date"])

    op.create_table(
        "daily_commitments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("commitment_date", sa.Date(), nullable=False),
        sa.Column("action_item_id", sa.String(length=36), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("committed_minutes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("commitment_date", "owner_type", "rank", name="uq_commitment_owner_rank"),
        sa.UniqueConstraint("commitment_date", "action_item_id", name="uq_commitment_date_item"),
    )
    op.create_index("ix_daily_commitments_commitment_date", "daily_commitments", ["commitment_date"])
    op.create_index("ix_daily_commitments_action_item_id", "daily_commitments", ["action_item_id"])
    op.create_index("ix_daily_commitments_owner_type", "daily_commitments", ["owner_type"])
    op.create_index("ix_daily_commitments_state", "daily_commitments", ["state"])
    op.create_index(
        "ix_daily_commitments_date_owner_state",
        "daily_commitments",
        ["commitment_date", "owner_type", "state"],
    )

    op.create_table(
        "micro_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action_item_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("executor", sa.String(length=32), nullable=False),
        sa.Column("preferred_worker", sa.String(length=64), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("action_item_id", "position", name="uq_micro_step_position"),
    )
    op.create_index("ix_micro_steps_action_item_id", "micro_steps", ["action_item_id"])
    op.create_index("ix_micro_steps_state", "micro_steps", ["state"])

    op.create_table(
        "focus_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action_item_id", sa.String(length=36), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("extension_minutes", sa.Integer(), nullable=False),
        sa.Column("active_slot", sa.String(length=32), nullable=True, unique=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("traffic_state", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("paused_seconds", sa.Integer(), nullable=False),
        sa.Column("pause_count", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("started_by", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_focus_sessions_action_item_id", "focus_sessions", ["action_item_id"])
    op.create_index("ix_focus_sessions_state", "focus_sessions", ["state"])
    op.create_index("ix_focus_sessions_traffic_state", "focus_sessions", ["traffic_state"])
    op.create_index("ix_focus_sessions_started_at", "focus_sessions", ["started_at"])

    op.create_table(
        "carry_over_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action_item_id", sa.String(length=36), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_item_id"], ["action_items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_carry_over_decisions_action_item_id", "carry_over_decisions", ["action_item_id"])
    op.create_index("ix_carry_over_decisions_from_date", "carry_over_decisions", ["from_date"])
    op.create_index("ix_carry_over_decisions_to_date", "carry_over_decisions", ["to_date"])
    op.create_index("ix_carry_over_decisions_decision", "carry_over_decisions", ["decision"])
    op.create_index("ix_carry_over_decisions_created_at", "carry_over_decisions", ["created_at"])


def downgrade() -> None:
    op.drop_table("carry_over_decisions")
    op.drop_table("focus_sessions")
    op.drop_table("micro_steps")
    op.drop_table("daily_commitments")
    op.drop_table("daily_focus_plans")
    op.drop_table("priority_assessments")
    with op.batch_alter_table("action_items") as batch:
        batch.drop_index("ix_action_items_attention_state")
        batch.drop_column("attention_state")

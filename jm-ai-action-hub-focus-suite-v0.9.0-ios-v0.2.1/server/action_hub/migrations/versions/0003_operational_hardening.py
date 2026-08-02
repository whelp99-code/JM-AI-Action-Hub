"""Add recoverable webhook processing locks."""

import sqlalchemy as sa
from alembic import op

revision = "0003_operational_hardening"
down_revision = "0002_action_control_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.add_column(sa.Column("locked_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_webhook_deliveries_locked_at", ["locked_at"])
    op.execute("UPDATE webhook_deliveries SET updated_at = received_at WHERE updated_at IS NULL")
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.alter_column("updated_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("webhook_deliveries") as batch:
        batch.drop_index("ix_webhook_deliveries_locked_at")
        batch.drop_column("updated_at")
        batch.drop_column("locked_at")

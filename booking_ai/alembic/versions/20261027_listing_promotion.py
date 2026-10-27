"""Add listing workflow, promotion payments, notifications, and balance audit."""
from alembic import op
import sqlalchemy as sa

from mysite.database.ai_models import AIBase

revision = "20261027_listing_promotion"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # This project has no prior Alembic baseline. Create any missing current tables
    # additively, then add the new columns to databases whose tables predate them.
    AIBase.metadata.create_all(bind=bind, checkfirst=True)
    inspector = sa.inspect(bind)
    existing = {table: {column["name"] for column in inspector.get_columns(table)}
                for table in ("users", "listings") if inspector.has_table(table)}
    if "balance" not in existing.get("users", set()):
        op.add_column("users", sa.Column("balance", sa.Numeric(14, 2), nullable=False,
                                          server_default=sa.text("0")))
    if "photo_urls" not in existing.get("listings", set()):
        op.add_column("listings", sa.Column("photo_urls", sa.JSON(), nullable=False,
                                             server_default=sa.text("'[]'")))
    if "moderation_reason" not in existing.get("listings", set()):
        op.add_column("listings", sa.Column("moderation_reason", sa.Text(), nullable=True))
    if "promotion_ends_at" not in existing.get("listings", set()):
        op.add_column("listings", sa.Column("promotion_ends_at", sa.DateTime(timezone=True), nullable=True))
    for table in ("promotion_tariffs", "user_notifications", "promotion_payments", "payment_events",
                  "promotion_activations", "balance_operations"):
        AIBase.metadata.tables[table].create(bind=bind, checkfirst=True)
    if "ix_listings_promotion_ends_at" not in {i["name"] for i in sa.inspect(bind).get_indexes("listings")}:
        op.create_index("ix_listings_promotion_ends_at", "listings", ["promotion_ends_at"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("balance_operations", "promotion_activations", "payment_events", "promotion_payments",
                  "user_notifications", "promotion_tariffs"):
        AIBase.metadata.tables[table].drop(bind=bind, checkfirst=True)
    op.drop_index("ix_listings_promotion_ends_at", table_name="listings")
    op.drop_column("listings", "promotion_ends_at")
    op.drop_column("listings", "moderation_reason")
    op.drop_column("listings", "photo_urls")
    op.drop_column("users", "balance")

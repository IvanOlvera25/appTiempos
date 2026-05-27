"""Add area manager user role

Revision ID: 9b1c4d7e2a31
Revises: e47599565e1c
Create Date: 2026-05-19 12:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '9b1c4d7e2a31'
down_revision = 'e47599565e1c'
branch_labels = None
depends_on = None


def _has_column(bind, table_name: str, column_name: str) -> bool:
    insp = sa.inspect(bind)
    return any(col.get("name") == column_name for col in insp.get_columns(table_name))


def upgrade():
    bind = op.get_bind()

    if not _has_column(bind, "users", "is_area_manager"):
        op.add_column(
            "users",
            sa.Column("is_area_manager", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )

    if not _has_column(bind, "users", "area_manager_department"):
        op.add_column(
            "users",
            sa.Column("area_manager_department", sa.String(length=100), nullable=True)
        )


def downgrade():
    bind = op.get_bind()

    if _has_column(bind, "users", "area_manager_department"):
        op.drop_column("users", "area_manager_department")

    if _has_column(bind, "users", "is_area_manager"):
        op.drop_column("users", "is_area_manager")

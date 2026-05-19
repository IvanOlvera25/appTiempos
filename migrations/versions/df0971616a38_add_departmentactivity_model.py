"""Add DepartmentActivity model

Revision ID: df0971616a38
Revises: f52ee82b4f9d
Create Date: 2025-10-17 21:06:56.628972
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'df0971616a38'
down_revision = 'f52ee82b4f9d'
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    insp = sa.inspect(bind)
    return table_name in insp.get_table_names()


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        idx = insp.get_indexes(table_name)
    except Exception:
        return False
    return any(i.get("name") == index_name for i in idx)


def _unique_exists(bind, table_name: str, unique_name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        uqs = insp.get_unique_constraints(table_name)
    except Exception:
        return False
    return any(u.get("name") == unique_name for u in uqs)


def upgrade():
    bind = op.get_bind()

    # 1) Crear tabla si no existe
    if not _table_exists(bind, "department_activities"):
        op.create_table(
            'department_activities',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('department', sa.String(length=50), nullable=False),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        )
        # Unique (department, name)
        op.create_unique_constraint('uq_department_activity', 'department_activities', ['department', 'name'])

    else:
        # Asegurar el UNIQUE si falta
        if not _unique_exists(bind, 'department_activities', 'uq_department_activity'):
            op.create_unique_constraint('uq_department_activity', 'department_activities', ['department', 'name'])

    # 2) Índice por department (si no existe)
    idx_name = 'ix_department_activities_department'
    if not _index_exists(bind, 'department_activities', idx_name):
        op.create_index(idx_name, 'department_activities', ['department'], unique=False)


def downgrade():
    bind = op.get_bind()

    # Quitar índice si existe
    idx_name = 'ix_department_activities_department'
    if _index_exists(bind, 'department_activities', idx_name):
        op.drop_index(idx_name, table_name='department_activities')

    # Quitar UNIQUE si existe
    if _unique_exists(bind, 'department_activities', 'uq_department_activity'):
        op.drop_constraint('uq_department_activity', 'department_activities', type_='unique')

    # Borrar tabla si existe
    if _table_exists(bind, 'department_activities'):
        op.drop_table('department_activities')

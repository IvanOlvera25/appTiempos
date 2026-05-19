"""Add DepartmentActivity models (safe)

Revision ID: af8ca395f6a1
Revises: df0971616a38
Create Date: 2025-10-17 22:35:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'af8ca395f6a1'
down_revision = 'df0971616a38'
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def _has_index(bind, table: str, index_name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        indexes = insp.get_indexes(table)
    except Exception:
        return False
    return any(ix.get("name") == index_name for ix in indexes)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1) department_activities: crear si no existe; si existe, asegurar NOT NULL y defaults
    if not _has_table(bind, "department_activities"):
        op.create_table(
            'department_activities',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('department', sa.String(length=50), nullable=False, index=True),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.UniqueConstraint('department', 'name', name='uq_department_activity')
        )
        # índice sobre department (por si el backend lo usa en filtros)
        if not _has_index(bind, "department_activities", "ix_department_activities_department"):
            op.create_index("ix_department_activities_department", "department_activities", ["department"])
    else:
        # asegurar NOT NULL + defaults
        op.alter_column(
            'department_activities', 'is_active',
            existing_type=sa.Boolean(), nullable=False,
            server_default=sa.text("1")
        )
        op.alter_column(
            'department_activities', 'sort_order',
            existing_type=sa.Integer(), nullable=False,
            server_default=sa.text("0")
        )
        if not _has_index(bind, "department_activities", "ix_department_activities_department"):
            op.create_index("ix_department_activities_department", "department_activities", ["department"])

    # 2) projects.folio: cambiar a Integer y crear índice si no existe
    #    OJO: si hay valores no numéricos, MySQL los convertirá a 0.
    #    Si prefieres no tocar datos, quita este bloque y deja folio como VARCHAR en el modelo.
    try:
        op.alter_column(
            'projects', 'folio',
            existing_type=sa.String(length=100),
            type_=sa.Integer(),
            existing_nullable=True
        )
    except Exception:
        # Si ya era Integer o la conversión está aplicada, ignoramos.
        pass

    if not _has_index(bind, "projects", "ix_projects_folio"):
        op.create_index("ix_projects_folio", "projects", ["folio"])

    # 3) projects.active: NOT NULL + default
    try:
        op.alter_column(
            'projects', 'active',
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("1")
        )
    except Exception:
        pass

    # 4) Índices en time_records
    if not _has_index(bind, "time_records", "ix_time_records_employee_id"):
        op.create_index("ix_time_records_employee_id", "time_records", ["employee_id"])
    if not _has_index(bind, "time_records", "ix_time_records_project_id"):
        op.create_index("ix_time_records_project_id", "time_records", ["project_id"])

    # 5) Índices en users (no tocar 'user' **singular**)
    if _has_table(bind, "users"):
        if not _has_index(bind, "users", "ix_users_username"):
            op.create_index("ix_users_username", "users", ["username"], unique=True)
        if not _has_index(bind, "users", "ix_users_employee_id"):
            # employee_id es único para sostener relación 1-1
            op.create_index("ix_users_employee_id", "users", ["employee_id"], unique=True)

    # Importante: NO tocar la tabla 'user' (singular).
    # Si la tienes todavía y la quieres eliminar, hazlo en una migración manual aparte:
    #   - Dropea primero la FK (ALTER TABLE `user` DROP FOREIGN KEY nombre_fk;)
    #   - Luego el índice involucrado
    #   - Finalmente DROP TABLE `user`
    # Aquí la omitimos para evitar el error (1553) de MySQL.


def downgrade():
    bind = op.get_bind()

    # Revertir índices en users (si existen)
    if _has_table(bind, "users"):
        if _has_index(bind, "users", "ix_users_employee_id"):
            op.drop_index("ix_users_employee_id", table_name="users")
        if _has_index(bind, "users", "ix_users_username"):
            op.drop_index("ix_users_username", table_name="users")

    # Revertir índices en time_records
    if _has_index(bind, "time_records", "ix_time_records_project_id"):
        op.drop_index("ix_time_records_project_id", table_name="time_records")
    if _has_index(bind, "time_records", "ix_time_records_employee_id"):
        op.drop_index("ix_time_records_employee_id", table_name="time_records")

    # Revertir projects.active (permitir NULL) — quita server_default
    try:
        op.alter_column(
            'projects', 'active',
            existing_type=sa.Boolean(),
            nullable=True,
            server_default=None
        )
    except Exception:
        pass

    # Revertir projects.folio a VARCHAR(100)
    try:
        if _has_index(bind, "projects", "ix_projects_folio"):
            op.drop_index("ix_projects_folio", table_name="projects")
        op.alter_column(
            'projects', 'folio',
            existing_type=sa.Integer(),
            type_=sa.String(length=100),
            existing_nullable=True
        )
    except Exception:
        pass

    # department_activities: revertir cambios
    if _has_table(bind, "department_activities"):
        # quitar índice
        if _has_index(bind, "department_activities", "ix_department_activities_department"):
            op.drop_index("ix_department_activities_department", table_name="department_activities")
        # permitir NULLs de nuevo
        try:
            op.alter_column(
                'department_activities', 'sort_order',
                existing_type=sa.Integer(), nullable=True, server_default=None
            )
            op.alter_column(
                'department_activities', 'is_active',
                existing_type=sa.Boolean(), nullable=True, server_default=None
            )
        except Exception:
            pass
        # si quieres borrar la tabla en downgrade:
        # op.drop_table('department_activities')

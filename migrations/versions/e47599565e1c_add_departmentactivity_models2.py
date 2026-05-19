"""Add DepartmentActivity models2 (safe 'user' cleanup & idempotent indexes)"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine.reflection import Inspector

# Asegúrate que coincidan con tu historial
revision = 'e47599565e1c'
down_revision = 'af8ca395f6a1'
branch_labels = None
depends_on = None


# -------- helpers --------
def _insp(bind):
    return Inspector.from_engine(bind)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in _insp(bind).get_table_names()


def _fk_names_for_column(bind, table_name: str, column_name: str):
    names = []
    for fk in _insp(bind).get_foreign_keys(table_name):
        if column_name in (fk.get('constrained_columns') or []):
            if fk.get('name'):
                names.append(fk['name'])
            else:
                # fallback: buscar en information_schema
                rows = bind.execute(text("""
                    SELECT CONSTRAINT_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :t
                      AND COLUMN_NAME = :c
                      AND REFERENCED_TABLE_NAME IS NOT NULL
                """), {"t": table_name, "c": column_name}).fetchall()
                for r in rows:
                    names.append(r[0])
    return names


def _drop_fk_if_exists(bind, table_name: str, column_name: str):
    for fkname in _fk_names_for_column(bind, table_name, column_name):
        bind.execute(text(f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{fkname}`"))


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    row = bind.execute(text("""
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :t
          AND INDEX_NAME = :i
        LIMIT 1
    """), {"t": table_name, "i": index_name}).fetchone()
    return bool(row)


def _drop_index_if_exists(bind, table_name: str, index_name: str):
    if _index_exists(bind, table_name, index_name):
        bind.execute(text(f"DROP INDEX `{index_name}` ON `{table_name}`"))


def _create_index_if_absent(table: str, index_name: str, columns: list[str], unique: bool = False):
    """
    Usa op.get_bind() internamente para comprobar y crear el índice solo si no existe.
    """
    bind = op.get_bind()
    if not _index_exists(bind, table, index_name):
        op.create_index(index_name, table, columns, unique=unique)


# -------- upgrade/downgrade --------
def upgrade():
    bind = op.get_bind()

    # 1) department_activities solo si no existe
    if not _table_exists(bind, "department_activities"):
        op.create_table(
            'department_activities',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('department', sa.String(length=50), nullable=False, index=True),
            sa.Column('name', sa.String(length=200), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.UniqueConstraint('department', 'name', name='uq_department_activity'),
        )
        _create_index_if_absent('department_activities', 'ix_department_activities_department', ['department'], unique=False)

    # 2) limpiar tabla legacy `user` si existe
    if _table_exists(bind, "user"):
        # quitar FK sobre employee_id
        _drop_fk_if_exists(bind, "user", "employee_id")
        # quitar índices que estorban
        _drop_index_if_exists(bind, "user", "employee_id")
        _drop_index_if_exists(bind, "user", "username")
        # eliminar tabla
        bind.execute(text("DROP TABLE IF EXISTS `user`"))

    # 3) asegurar índices coherentes con models.py — **solo si no existen**
    # users.username (único)
    _create_index_if_absent('users', 'ix_users_username', ['username'], unique=True)

    # users.employee_id (único)
    _create_index_if_absent('users', 'ix_users_employee_id', ['employee_id'], unique=True)

    # time_records: performance
    _create_index_if_absent('time_records', 'ix_time_records_employee_id', ['employee_id'], unique=False)
    _create_index_if_absent('time_records', 'ix_time_records_project_id',  ['project_id'],  unique=False)

    # projects.folio: si en tu models lo tienes con index
    _create_index_if_absent('projects', 'ix_projects_folio', ['folio'], unique=False)


def downgrade():
    bind = op.get_bind()

    # quitar índices creados
    _drop_index_if_exists(bind, "projects", "ix_projects_folio")
    _drop_index_if_exists(bind, "time_records", "ix_time_records_project_id")
    _drop_index_if_exists(bind, "time_records", "ix_time_records_employee_id")
    _drop_index_if_exists(bind, "users", "ix_users_employee_id")
    _drop_index_if_exists(bind, "users", "ix_users_username")

    # department_activities (solo si existe)
    if _table_exists(bind, "department_activities"):
        _drop_index_if_exists(bind, "department_activities", "ix_department_activities_department")
        bind.execute(text("DROP TABLE `department_activities`"))

    # recrear legacy `user` (opcional)
    if not _table_exists(bind, "user"):
        op.create_table(
            'user',
            sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
            sa.Column('username', sa.String(length=80), nullable=False),
            sa.Column('password', sa.String(length=255), nullable=False),
            sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column('employee_id', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name='user_ibfk_1'),
            mysql_engine='InnoDB',
            mysql_default_charset='utf8'
        )
        op.create_index('username', 'user', ['username'], unique=True)
        op.create_index('employee_id', 'user', ['employee_id'], unique=True)

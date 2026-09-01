"""Perfiles RH y Ejecutivo + sistema de incidencias

Las vacaciones no aparecen aquí: viven íntegramente en AD17_RH (tablas
Vacaciones, MediosDias, Supervisores y sus reglas), que administra el sistema
de RH. Esta migración solo agrega lo que es propio de la app.

Revision ID: d4e19a7c5b83
Revises: c3f81b6e4a72
Create Date: 2026-09-01 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e19a7c5b83'
down_revision = 'c3f81b6e4a72'
branch_labels = None
depends_on = None


_CLASIFICACIONES = [
    'Retrabajo',
    'Material defectuoso',
    'Falta de material',
    'Error de medidas o planos',
    'Retraso en entrega',
    'Daño en montaje',
    'Cambio solicitado por el cliente',
    'Falla de equipo o maquinaria',
    'Accidente o incidente de seguridad',
    'Otro',
]


def _tiene_columna(bind, tabla, columna):
    return any(c['name'] == columna for c in sa.inspect(bind).get_columns(tabla))


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ── Nuevos perfiles ──────────────────────────────────────────────
    if not _tiene_columna(bind, 'users', 'is_rh'):
        op.add_column('users', sa.Column(
            'is_rh', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    if not _tiene_columna(bind, 'users', 'is_ejecutivo'):
        op.add_column('users', sa.Column(
            'is_ejecutivo', sa.Boolean(), nullable=False, server_default=sa.text('0')))

    # ── Catálogo de clasificaciones ──────────────────────────────────
    if not insp.has_table('incident_classifications'):
        op.create_table(
            'incident_classifications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nombre', sa.String(length=120), nullable=False),
            sa.Column('activa', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('orden', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('nombre', name='uq_incident_classification_nombre'),
        )
        op.bulk_insert(
            sa.table('incident_classifications',
                     sa.column('nombre', sa.String),
                     sa.column('activa', sa.Boolean),
                     sa.column('orden', sa.Integer)),
            [{'nombre': n, 'activa': True, 'orden': i}
             for i, n in enumerate(_CLASIFICACIONES)]
        )

    # ── Incidencias consolidadas ─────────────────────────────────────
    # Sin FK hacia `employees`: a partir de la migración c3f81b6e4a72 es una
    # vista sobre AD17_RH y una vista no puede ser destino de una llave foránea.
    if not insp.has_table('incidents'):
        op.create_table(
            'incidents',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('created_by_user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('descripcion', sa.Text(), nullable=False),
            sa.Column('clasificacion_id', sa.Integer(), nullable=True),
            sa.Column('responsable_tipo', sa.String(length=20), nullable=False,
                      server_default=sa.text("'AREA'")),
            sa.Column('responsable_area', sa.String(length=100), nullable=True),
            sa.Column('responsable_employee_id', sa.Integer(), nullable=True),
            sa.Column('responsable_texto', sa.String(length=200), nullable=True),
            sa.Column('costo', sa.Numeric(12, 2), nullable=False, server_default=sa.text('0')),
            sa.Column('estado', sa.String(length=20), nullable=False,
                      server_default=sa.text("'ABIERTA'")),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['clasificacion_id'], ['incident_classifications.id']),
        )
        op.create_index('ix_incidents_created_by', 'incidents', ['created_by_user_id'])
        op.create_index('ix_incidents_responsable_emp', 'incidents',
                        ['responsable_employee_id'])

    if not insp.has_table('incident_projects'):
        op.create_table(
            'incident_projects',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('incident_id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
            sa.UniqueConstraint('incident_id', 'project_id', name='uq_incident_project'),
        )

    # ── Informes de incidencia ───────────────────────────────────────
    if not insp.has_table('incident_reports'):
        op.create_table(
            'incident_reports',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('reporter_user_id', sa.Integer(), nullable=False),
            sa.Column('nivel_autor', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('motivo', sa.Text(), nullable=False),
            sa.Column('repercusion', sa.Text(), nullable=True),
            sa.Column('clasificacion_id', sa.Integer(), nullable=True),
            sa.Column('causante_tipo', sa.String(length=20), nullable=False,
                      server_default=sa.text("'AREA'")),
            sa.Column('causante_area', sa.String(length=100), nullable=True),
            sa.Column('causante_employee_id', sa.Integer(), nullable=True),
            sa.Column('causante_texto', sa.String(length=200), nullable=True),
            sa.Column('invalido', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('incident_id', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['clasificacion_id'], ['incident_classifications.id']),
            sa.ForeignKeyConstraint(['incident_id'], ['incidents.id']),
        )
        op.create_index('ix_incident_reports_reporter', 'incident_reports',
                        ['reporter_user_id'])
        op.create_index('ix_incident_reports_nivel', 'incident_reports', ['nivel_autor'])
        op.create_index('ix_incident_reports_incident', 'incident_reports', ['incident_id'])
        op.create_index('ix_incident_reports_invalido', 'incident_reports', ['invalido'])
        op.create_index('ix_incident_reports_causante_area', 'incident_reports',
                        ['causante_area'])
        op.create_index('ix_incident_reports_causante_emp', 'incident_reports',
                        ['causante_employee_id'])

    if not insp.has_table('incident_report_projects'):
        op.create_table(
            'incident_report_projects',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('report_id', sa.Integer(), nullable=False),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['report_id'], ['incident_reports.id']),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
            sa.UniqueConstraint('report_id', 'project_id', name='uq_incident_report_project'),
        )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for tabla in ('incident_report_projects', 'incident_reports',
                  'incident_projects', 'incidents', 'incident_classifications'):
        if insp.has_table(tabla):
            op.drop_table(tabla)

    if _tiene_columna(bind, 'users', 'is_ejecutivo'):
        op.drop_column('users', 'is_ejecutivo')
    if _tiene_columna(bind, 'users', 'is_rh'):
        op.drop_column('users', 'is_rh')

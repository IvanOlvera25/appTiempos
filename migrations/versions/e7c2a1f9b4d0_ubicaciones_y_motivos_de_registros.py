"""Ubicación al iniciar y al finalizar, y motivo de los cambios hechos desde Costos

Solo crea dos tablas nuevas; no toca `time_records` (la usan los triggers de
analítica de Impresión) ni ningún dato existente.

Va ANTES de c3f81b6e4a72 (employees como vista, detenida) para poder aplicarse
sola: `flask db upgrade e7c2a1f9b4d0`, o al recargar la app (app/migraciones.py).

Crea solo las tablas que falten, por si alguna ya se creó a mano con el SQL de
DESPLIEGUE.md o quedó a medias.

Revision ID: e7c2a1f9b4d0
Revises: d4e19a7c5b83
Create Date: 2026-11-16 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7c2a1f9b4d0'
down_revision = 'd4e19a7c5b83'
branch_labels = None
depends_on = None


def _existentes():
    try:
        return set(sa.inspect(op.get_bind()).get_table_names())
    except Exception:
        return set()    # modo --sql: no hay base que revisar


def upgrade():
    existentes = _existentes()
    if 'time_record_locations' not in existentes:
        _crear_ubicaciones()
    if 'time_record_changes' not in existentes:
        _crear_cambios()


def _crear_ubicaciones():
    op.create_table(
        'time_record_locations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('time_record_id', sa.Integer(),
                  sa.ForeignKey('time_records.id', ondelete='CASCADE'), nullable=False),
        sa.Column('momento', sa.String(10), nullable=False),
        sa.Column('latitude', sa.Double(), nullable=False),
        sa.Column('longitude', sa.Double(), nullable=False),
        sa.Column('precision_m', sa.Float(), nullable=True),
        sa.Column('registrada_en', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('time_record_id', 'momento', name='uq_time_record_location'),
    )
    op.create_index('ix_time_record_locations_time_record_id', 'time_record_locations',
                    ['time_record_id'])


def _crear_cambios():
    op.create_table(
        'time_record_changes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('time_record_id', sa.Integer(),
                  sa.ForeignKey('time_records.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('creado_en', sa.DateTime(), nullable=False),
        sa.Column('accion', sa.String(12), nullable=False),
        sa.Column('motivo', sa.String(60), nullable=False),
        sa.Column('detalle', sa.Text(), nullable=True),
    )
    op.create_index('ix_time_record_changes_time_record_id', 'time_record_changes',
                    ['time_record_id'])


def downgrade():
    op.drop_index('ix_time_record_changes_time_record_id', table_name='time_record_changes')
    op.drop_table('time_record_changes')
    op.drop_index('ix_time_record_locations_time_record_id', table_name='time_record_locations')
    op.drop_table('time_record_locations')

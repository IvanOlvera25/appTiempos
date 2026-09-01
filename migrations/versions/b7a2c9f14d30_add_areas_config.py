"""Add areas_config (áreas que registran tiempos)

Revision ID: b7a2c9f14d30
Revises: eab38da21ce0
Create Date: 2026-09-01 10:00:00
"""
import os

from alembic import op
import sqlalchemy as sa


revision = 'b7a2c9f14d30'
down_revision = 'eab38da21ce0'
branch_labels = None
depends_on = None


# Áreas históricas: se siembran aquí para que la app quede igual que antes de
# volver configurable el catálogo. 'Impresion' conserva su flujo multi-registro.
_SEED = [
    ('Metal',          'estandar'),
    ('Costura',        'estandar'),
    ('Impresion',      'impresion'),
    ('Stagging',       'estandar'),
    ('Montaje',        'estandar'),
    ('Transporte',     'estandar'),
    ('Administración', 'estandar'),
]


def _has_table(bind, name):
    return sa.inspect(bind).has_table(name)


# AD17_General.Areas no escribe los nombres igual que la app ("Staging" vs
# "Stagging", "Administracion" sin acento). Se comparan normalizados para poder
# enlazar cada área con su regID de RH.
_ALIAS = {'stagging': 'staging'}


def _clave(nombre):
    import unicodedata
    limpio = ''.join(
        c for c in unicodedata.normalize('NFD', nombre or '')
        if unicodedata.category(c) != 'Mn'
    ).strip().lower()
    return _ALIAS.get(limpio, limpio)


def _enlazar_areas_con_rh(bind):
    """
    Rellena areas_config.rh_area_id a partir de AD17_General.Areas.

    Importa más de lo que parece: la vista `employees` que publica la siguiente
    migración resuelve el departamento con COALESCE(areas_config.nombre, ...).
    Sin este enlace devolvería el nombre literal de RH ("Staging"), que no casa
    con el que traen los registros históricos ("Stagging").
    """
    general = os.environ.get('GENERAL_DB_NAME') or 'AD17_General'
    try:
        catalogo = bind.execute(
            sa.text("SELECT regID, area FROM `%s`.Areas" % general)).fetchall()
    except Exception as e:
        print("  aviso: no se pudo leer %s.Areas (%s); las áreas quedan sin "
              "enlazar y se pueden ligar a mano en Administración → Áreas." % (general, e))
        return

    por_clave = {_clave(area): reg_id for reg_id, area in catalogo}
    for area_id, nombre in bind.execute(
            sa.text("SELECT id, nombre FROM areas_config WHERE rh_area_id IS NULL")).fetchall():
        rh_id = por_clave.get(_clave(nombre))
        if rh_id is not None:
            bind.execute(sa.text("UPDATE areas_config SET rh_area_id = :rh WHERE id = :id"),
                         {'rh': rh_id, 'id': area_id})
            print("  área %-18s -> RH #%s" % (nombre, rh_id))


def upgrade():
    bind = op.get_bind()

    if not _has_table(bind, 'areas_config'):
        op.create_table(
            'areas_config',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('nombre', sa.String(length=100), nullable=False),
            sa.Column('rh_area_id', sa.Integer(), nullable=True),
            sa.Column('activa', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('flujo', sa.String(length=20), nullable=False, server_default=sa.text("'estandar'")),
            sa.Column('orden', sa.Integer(), nullable=False, server_default=sa.text('0')),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('nombre', name='uq_areas_config_nombre'),
        )
        op.create_index('ix_areas_config_rh_area_id', 'areas_config', ['rh_area_id'])

    ya_sembrado = bind.execute(sa.text('SELECT COUNT(*) FROM areas_config')).scalar()
    if not ya_sembrado:
        tabla = sa.table(
            'areas_config',
            sa.column('nombre', sa.String),
            sa.column('activa', sa.Boolean),
            sa.column('flujo', sa.String),
            sa.column('orden', sa.Integer),
        )
        op.bulk_insert(tabla, [
            {'nombre': nombre, 'activa': True, 'flujo': flujo, 'orden': idx}
            for idx, (nombre, flujo) in enumerate(_SEED)
        ])

    _enlazar_areas_con_rh(bind)


def downgrade():
    bind = op.get_bind()
    if _has_table(bind, 'areas_config'):
        op.drop_index('ix_areas_config_rh_area_id', table_name='areas_config')
        op.drop_table('areas_config')

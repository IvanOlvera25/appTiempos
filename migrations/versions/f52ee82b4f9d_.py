"""Bootstrap base

Revision ID: f52ee82b4f9d
Revises:
Create Date: 2025-03-14 14:47:22.864286
"""
from alembic import op
import sqlalchemy as sa

# Identificadores de revisión
revision = 'f52ee82b4f9d'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Shim/base: no hace nada. Solo para que Alembic reconozca la base.
    pass

def downgrade():
    # Shim/base: no hace nada.
    pass

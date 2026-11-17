"""
Migraciones que la app aplica sola al arrancar (al recargar la web app).

En PythonAnywhere la consola no siempre puede correr `flask db` (ver la sección
4b de DESPLIEGUE.md), así que al arrancar se aplican las migraciones pendientes
hasta `HASTA` y nada más. La fase 2 (c3f81b6e4a72, employees como vista) es
destructiva y está detenida: queda fuera a propósito. Para que una migración
nueva se aplique sola hay que mover `HASTA` a su revisión, y solo si es aditiva.

No se usa `flask_migrate.upgrade()`: su env.py llama a logging.fileConfig, que
apagaría los loggers de la app en pleno arranque. Aquí se ejecutan las mismas
funciones upgrade() de los archivos de migrations/versions con Alembic directo.

Varios procesos pueden arrancar a la vez: un candado de MySQL (GET_LOCK) hace
que migre solo uno y los demás encuentren la base ya al día.

Para que no lo haga (por ejemplo, tras un downgrade a propósito), definir la
variable de entorno TIEMPOS_MIGRAR_AL_ARRANCAR=0.
"""
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

HASTA = 'e7c2a1f9b4d0'
_CANDADO = 'appTiempos_migraciones'


def _version(conn):
    try:
        return conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
    except Exception:
        conn.rollback()
        return None


def _pendientes(script, actual):
    """
    Revisiones por aplicar, de la más vieja a la más nueva. [] si ya está en
    HASTA; None si no se debe tocar: sin alembic_version, o la base ya va por
    otro lado (por ejemplo, con la fase 2 aplicada).
    """
    if actual == HASTA:
        return []
    if not actual:
        return None
    try:
        return list(reversed(list(script.iterate_revisions(HASTA, actual))))
    except Exception:
        return None


def aplicar_pendientes(app, db):
    """Nunca tumba el arranque: si algo falla queda en el log y la app sigue."""
    if os.environ.get('TIEMPOS_MIGRAR_AL_ARRANCAR', '1') == '0':
        return
    log = app.logger
    try:
        script = ScriptDirectory(os.path.join(os.path.dirname(app.root_path), 'migrations'))
        with app.app_context(), db.engine.connect() as conn:
            # Lo normal: ya está al día, y basta una consulta
            pasos = _pendientes(script, _version(conn))
            if not pasos:
                if pasos is None:
                    log.info('migraciones: la base está en %s; no se aplica nada solo.',
                             _version(conn))
                return

            mysql = conn.dialect.name == 'mysql'
            if mysql and conn.execute(text('SELECT GET_LOCK(:n, 120)'),
                                      {'n': _CANDADO}).scalar() != 1:
                log.error('migraciones: otro proceso tiene el candado desde hace 2 min; '
                          'no se migró en este arranque.')
                return
            try:
                # Otro proceso pudo haber migrado mientras se esperaba el candado
                actual = _version(conn)
                for rev in _pendientes(script, actual) or []:
                    with Operations.context(MigrationContext.configure(conn)):
                        rev.module.upgrade()
                    conn.execute(text('UPDATE alembic_version SET version_num = :nueva '
                                      'WHERE version_num = :anterior'),
                                 {'nueva': rev.revision, 'anterior': actual})
                    conn.commit()
                    actual = rev.revision
                    log.warning('migraciones: se aplicó %s (%s)', rev.revision,
                                (rev.doc or '').strip())
            finally:
                if mysql:
                    conn.execute(text('SELECT RELEASE_LOCK(:n)'), {'n': _CANDADO})
    except Exception:
        log.exception('migraciones: no se pudo migrar al arrancar; la app sigue sin la migración')

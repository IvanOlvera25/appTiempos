import os
import logging

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from .config import Config
from flask_login import LoginManager
from flask_apscheduler import APScheduler

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message = "Por favor inicia sesión para acceder a esta página"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()
migrate = Migrate()

def _threads_available() -> bool:
    """
    Devuelve True si estamos fuera de uWSGI **o** si uWSGI fue
    arrancado con --enable-threads.  En cualquier otro caso ⇒ False.
    """
    try:
        import uwsgi                                # solo existe dentro de uWSGI
        # `uwsgi.opt` es un dict con los flags de arranque en bytes
        return bool(uwsgi.opt.get(b'enable-threads') or uwsgi.opt.get(b'threads'))
    except ImportError:
        # No estamos bajo uWSGI ⇒ hilos disponibles
        return True


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializar extensiones base
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # ---------------- Scheduler: configuración segura ----------------
    # 1) Por defecto NO expongas rutas del scheduler (evita colisiones de endpoints)
    app.config.setdefault('SCHEDULER_API_ENABLED', False)

    # 2) Permite saltar el scheduler en contextos CLI (migraciones, etc.)
    skip_scheduler = os.environ.get('FLASK_SKIP_SCHEDULER') == '1'

    # 3) Si quieres habilitar el API en runtime normal, hazlo en tu config de prod:
    #    app.config['SCHEDULER_API_ENABLED'] = True

    # Sólo iniciar el scheduler si:
    # - No estamos en CLI de migración (skip_scheduler == False)
    # - Hay hilos disponibles (uWSGI con --enable-threads o fuera de uWSGI)
    if not skip_scheduler and _threads_available():
        # Carga jobs (tu job de sync) una sola vez
        class ConfigScheduler:
            JOBS = [
                {
                    "id": "sync_job",
                    "func": "app.sync_remote:sync_with_remote_db",
                    "trigger": "interval",
                    "seconds": 3600
                }
            ]
            # Respeta lo que ya esté en app.config; si no, usa el default False de arriba
            SCHEDULER_API_ENABLED = app.config.get('SCHEDULER_API_ENABLED', False)

        app.config.from_object(ConfigScheduler)

        # Evitar doble init si create_app() se llama varias veces en el mismo proceso
        if not getattr(app, "_scheduler_initialized", False):
            app.scheduler = APScheduler()
            app.scheduler.init_app(app)

            # Personal desde RH cada hora. `employees` es una copia de AD17_RH
            # mientras la migracion que la vuelve vista siga detenida (ver
            # BUG_IMPRESION_ANALITICA.md). Va aqui y no en JOBS porque
            # flask-apscheduler NO abre contexto de aplicacion para los jobs.
            def _sincronizar_rh_job(app=app):
                with app.app_context():
                    from .rh import sincronizar_empleados
                    try:
                        r = sincronizar_empleados()
                        app.logger.info(
                            "sync_rh: altas=%d cambios=%d bajas=%d reactivados=%d conflictos=%d",
                            len(r['altas']), len(r['cambios']), len(r['bajas']),
                            len(r['reactivados']), len(r['conflictos']))
                        if r['conflictos']:
                            app.logger.warning("sync_rh: sin tocar por apuntar a otra persona: %s",
                                               '; '.join(r['conflictos']))
                    except Exception as e:
                        app.logger.error("sync_rh: %s", e)

            app.scheduler.add_job(id='sync_rh', func=_sincronizar_rh_job,
                                  trigger='interval', hours=1)

            # Start protegido por try/except para el caso de uWSGI sin hilos
            try:
                app.scheduler.start()
                app.logger.info("APScheduler iniciado.")
            except RuntimeError as exc:
                if "threads have been disabled" in str(exc).lower():
                    app.logger.warning(
                        "APScheduler no se inició: uWSGI sin hilos (--enable-threads)."
                    )
                else:
                    raise
            app._scheduler_initialized = True
    else:
        if skip_scheduler:
            app.logger.info("FLASK_SKIP_SCHEDULER=1 ⇒ APScheduler NO se inicia (modo CLI).")
        elif not _threads_available():
            app.logger.warning("Hilos deshabilitados ⇒ APScheduler NO se inicia.")

    # ---------------- Blueprints & Login loader ----------------
    # Importar modelos para que SQLAlchemy los registre
    from app import models

    with app.app_context():
        from .routes import main
        app.register_blueprint(main)

        from .routes_vacaciones import bp as vacaciones_bp
        app.register_blueprint(vacaciones_bp)

        from .routes_incidencias import bp as incidencias_bp
        app.register_blueprint(incidencias_bp)

    with app.app_context():
        from .models import User

        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    # ---------------- CLI Commands (dejas tus comandos tal cual) ----------------
    # (Aquí sigue tu código de import_employees e import_employees_remote sin cambios)

    # ----------------------------------------------------------------------------
    # Los comandos import_employees / import_employees_remote se eliminaron
    # pensando en que `employees` seria una vista sobre AD17_RH (migracion
    # c3f81b6e4a72). Esa migracion esta detenida (ver BUG_IMPRESION_ANALITICA.md),
    # asi que mientras tanto `employees` se alinea con RH desde aqui, desde el
    # boton de la pantalla de Empleados y desde el job horario del scheduler.
    # ----------------------------------------------------------------------------
    import click

    @app.cli.command('sincronizar-rh')
    @click.option('--dry-run', is_flag=True, help='Solo muestra que cambiaria, sin guardar.')
    def sincronizar_rh(dry_run):
        """Alinea la tabla employees con el personal de RH (AD17_RH)."""
        from .rh import sincronizar_empleados
        r = sincronizar_empleados(dry_run=dry_run)
        for clave in ('altas', 'cambios', 'bajas', 'reactivados', 'conflictos'):
            for nombre in r[clave]:
                click.echo('%-12s %s' % (clave, nombre))
        click.echo('%saltas=%d cambios=%d bajas=%d reactivados=%d conflictos=%d' % (
            '(simulacion) ' if dry_run else '',
            len(r['altas']), len(r['cambios']), len(r['bajas']), len(r['reactivados']),
            len(r['conflictos'])))

    return app

import click
import csv
import os
from io import BytesIO
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

    with app.app_context():
        from .models import User

        @login_manager.user_loader
        def load_user(user_id):
            return User.query.get(int(user_id))

    # ---------------- CLI Commands (dejas tus comandos tal cual) ----------------
    # (Aquí sigue tu código de import_employees e import_employees_remote sin cambios)

    return app

    # ----------------------------------------------------------------------------
    # COMANDO 1: Importar empleados desde un archivo CSV
    # ----------------------------------------------------------------------------
    @app.cli.command("import_employees")
    @click.argument("csv_path")
    def import_employees(csv_path):
        """Importa empleados desde un archivo CSV."""
        from .models import Employee

        if not os.path.exists(csv_path):
            click.echo(f"Error: El archivo '{csv_path}' no existe.")
            return

        try:
            with open(csv_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    existing_employee = Employee.query.filter_by(n_empleado=row['N de empleado']).first()
                    if existing_employee:
                        click.echo(f"Empleado '{row['N de empleado']}' ya existe. Saltando.")
                        continue

                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(row['N de empleado'])
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    qr_buffer = BytesIO()
                    img.save(qr_buffer, format='PNG')
                    qr_data = qr_buffer.getvalue()
                    qr_code_str = f"qr_{row['N de empleado']}.png"

                    qr_path = os.path.join(app.root_path, 'static', 'qr_codes')
                    os.makedirs(qr_path, exist_ok=True)
                    qr_full_path = os.path.join(qr_path, qr_code_str)
                    with open(qr_full_path, 'wb') as f:
                        f.write(qr_data)
                    click.echo(f"Código QR guardado en '{qr_full_path}'.")

                    new_employee = Employee(
                        nompropio=row['Nompropio'],
                        n_empleado=row['N de empleado'],
                        nombre=row['Nombre(s)'],
                        apellido_paterno=row['Apellido Paterno'],
                        apellido_materno=row['Apellido Materno'],
                        departamento=row['Departamento'],
                        puesto=row.get('Puesto', ''),
                        qr_code=qr_code_str
                    )
                    db.session.add(new_employee)
                    click.echo(f"Empleado '{row['Nompropio']}' agregado exitosamente.")

            db.session.commit()
            click.echo("Importación completada exitosamente desde CSV.")

        except Exception as e:
            click.echo(f"Error durante la importación: {e}")
            db.session.rollback()

    # ----------------------------------------------------------------------------
    # COMANDO 2: Importar empleados desde la BD remota "AD17_RH" usando el nuevo query
    # ----------------------------------------------------------------------------
    @app.cli.command("import_employees_remote")
    def import_employees_remote():
        """
        Importa empleados desde la base de datos remota "AD17_RH" usando el siguiente query:

        Extrae: id, nombre (concatenado de nombre, paterno y materno),
        id_area, titulo_area, titulo_posicion, salario, costo_hora.

        Se usará el valor de "titulo_area" como 'departamento'. Se utilizará 'id'
        (convertido a string) como n_empleado, y se intentará separar el campo "nombre" en
        nombre, apellido_paterno y apellido_materno.
        Si el empleado ya existe, se actualizará el campo 'departamento' si es diferente.
        """
        import pymysql
        from .models import Employee
        from app import db

        remote_conn = pymysql.connect(
            host="ad17solutions.dscloud.me",
            port=3307,
            user="IvanUriel",
            password="iuOp20!!25",
            database="AD17_RH",
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        query = """
            SELECT i.regID AS id,
                   CONCAT(d.nombre, ' ', d.paterno, ' ', d.materno) AS nombre,
                   a.regID AS id_area,
                   a.area AS titulo_area,
                   p.regID AS id_area,
                   p.posicion AS titulo_posicion,
                   hp.mensualidad AS salario,
                   ROUND(
                     (hp.mensualidad / TIMESTAMPDIFF(DAY, CONCAT(YEAR(NOW()),'-',MONTH(NOW()),'-01'),
                        DATE_ADD(CONCAT(YEAR(NOW()),'-',MONTH(NOW()),'-01'), INTERVAL 1 MONTH)) / 10),
                     2
                   ) AS costo_hora
            FROM AD17_RH.ID AS i
            LEFT JOIN (SELECT * FROM AD17_RH.Datos WHERE regID IN (SELECT MAX(regID) FROM AD17_RH.Datos GROUP BY rhID)) AS d
              ON d.rhID LIKE i.regID
            LEFT JOIN (SELECT * FROM AD17_RH.HistorialPosiciones WHERE regID IN (SELECT MAX(regID) FROM AD17_RH.HistorialPosiciones GROUP BY rhID)) AS hp
              ON hp.rhID LIKE i.regID
            LEFT JOIN AD17_General.Areas AS a
              ON hp.areaID LIKE a.regID
            LEFT JOIN AD17_RH.Posiciones AS p
              ON hp.posicionID LIKE p.regID
            WHERE a.regID <> 2
            ORDER BY nombre;
        """

        try:
            with remote_conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()

                for row in rows:
                    remote_id = row['id']
                    full_name = row['nombre'] or ''
                    parts = full_name.split()
                    if len(parts) >= 3:
                        nombre = parts[0]
                        apellido_paterno = parts[1]
                        apellido_materno = " ".join(parts[2:])
                    else:
                        nombre = full_name
                        apellido_paterno = ""
                        apellido_materno = ""

                    # Usar el valor de 'titulo_area' como departamento
                    departamento = row.get('titulo_area') or 'N/A'

                    n_empleado = str(remote_id)
                    nompropio = full_name.strip()

                    existing_employee = Employee.query.filter_by(n_empleado=n_empleado).first()
                    if existing_employee:
                        # Si ya existe, actualizar el campo departamento si es diferente
                        if existing_employee.departamento != departamento:
                            print(f"Actualizando departamento para empleado {n_empleado}: {existing_employee.departamento} -> {departamento}")
                            existing_employee.departamento = departamento
                        continue

                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(n_empleado)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    qr_buffer = BytesIO()
                    img.save(qr_buffer, format='PNG')
                    qr_data = qr_buffer.getvalue()
                    qr_code_str = f"qr_{n_empleado}.png"

                    qr_path = os.path.join(app.root_path, 'static', 'qr_codes')
                    os.makedirs(qr_path, exist_ok=True)
                    qr_full_path = os.path.join(qr_path, qr_code_str)
                    with open(qr_full_path, 'wb') as f:
                        f.write(qr_data)
                    print(f"Código QR guardado en '{qr_full_path}'.")

                    new_employee = Employee(
                        nompropio=nompropio,
                        n_empleado=n_empleado,
                        nombre=nombre,
                        apellido_paterno=apellido_paterno,
                        apellido_materno=apellido_materno,
                        departamento=departamento,
                        puesto='',
                        qr_code=qr_code_str
                    )
                    db.session.add(new_employee)
                    print(f"Empleado '{nompropio}' agregado exitosamente.")

            db.session.commit()
            print("Importación completada exitosamente desde 'AD17_RH' (Datos + posiciones).")
        except Exception as e:
            db.session.rollback()
            print(f"Error durante la importación: {e}")
        finally:
            remote_conn.close()

    return app
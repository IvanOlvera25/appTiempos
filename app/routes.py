from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app
from .models import db, Employee, Project, TimeRecord, User, DepartmentActivity, AreaConfig
from .catalogs import (
    GENERAL_KEY, GENERAL_LABEL, activity_departments, area_usa_flujo_impresion,
    department_label, ensure_seed_activities, ensure_seed_areas, get_area,
    get_area_names, get_areas, get_department_activities, get_general_activities,
    next_area_order,
)
from . import rh
from .forms import QRForm, ProjectForm, RegisterTimeForm
from .forms import RegistrationForm, LoginForm
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pytz
from sqlalchemy import func, text  # Para MySQL TIMESTAMPDIFF
from wtforms.validators import DataRequired, Length, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from . import db, csrf
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError
import pymysql
from pytz import timezone
import traceback
import unicodedata

main = Blueprint('main', __name__)


def area_departments():
    """Areas dadas de alta para registrar tiempos (antes una lista fija)."""
    return get_area_names(solo_activas=True)


@main.app_context_processor
def inject_areas():
    """Deja el catalogo de areas al alcance de todas las plantillas."""
    try:
        areas = get_areas(solo_activas=True)
    except Exception as e:  # la nav no debe tumbar la pagina si la tabla falta
        current_app.logger.warning("inject_areas: no se pudo leer areas_config: %s", e)
        areas = []
    return {'areas': areas, 'area_departments': [a.nombre for a in areas]}


def _require_area_manager():
    if not current_user.is_authenticated:
        return redirect(url_for('main.login'))
    if not getattr(current_user, 'is_area_manager', False):
        flash('Acceso denegado. Esta vista es solo para Jefes de Area.', 'danger')
        return redirect(url_for('main.home'))
    if not current_user.area_manager_department:
        flash('Tu usuario no tiene un área asignada.', 'warning')
        return redirect(url_for('main.home'))
    return None


def _to_mx(dt):
    if not dt:
        return None
    utc_tz = pytz.UTC
    cdmx_tz = pytz.timezone('America/Mexico_City')
    if dt.tzinfo is None:
        dt = utc_tz.localize(dt)
    return dt.astimezone(cdmx_tz)


# `time_records` tiene triggers que el equipo de analitica instalo en la base
# (AD17_Analytics_DEV). El de Impresion se dispara en cada INSERT/UPDATE de un
# registro de esa area y, si falla, MySQL aborta la operacion completa: la app
# no puede hacer nada al respecto porque el usuario de la aplicacion ni siquiera
# tiene acceso a ese esquema. Se detectan aqui para no culpar al formulario, que
# es lo que hacia el mensaje generico de "verifica los datos".
_MARCAS_TRIGGER_ANALITICA = (
    'uk_evento',
    'ad17_analytics',
    'sp_impresion_recalcular_dia',
    'sp_autocierre_areas',
    'trigger_log',
)


def _rechazado_por_analitica(exc):
    """True si la base rechazo el guardado desde el trigger de analitica."""
    texto = str(exc).lower()
    return any(marca in texto for marca in _MARCAS_TRIGGER_ANALITICA)

@main.route('/')
def home():
    # Si el usuario autenticado es empleado, lo brincamos directo

    return render_template('home.html')
@main.route('/list_employees')
def list_employees():
    employees = Employee.query.all()
    return render_template('list_employees.html', employees=employees)

@main.route('/register_employee', methods=['GET'])
def register_employee():
    """
    Pantalla 1: Selección de Empleado (manual).
    MODIFICADA: Solo muestra empleados únicos por nompropio, eliminando duplicados.
    """
    if current_user.is_authenticated and getattr(current_user, 'is_employee', False):
        emp = Employee.query.get(current_user.employee_id)
        if emp:
            dept_param = request.args.get('department', '').strip() or None
            return _redirect_employee_to_project(emp, dept_param)

    department = request.args.get('department', '').strip()
    current_app.logger.debug("register_employee: department='%s'", department)

    # CAMBIO PRINCIPAL: Obtener empleados únicos por nompropio
    # Usar subquery para obtener solo un empleado por cada nompropio único
    unique_employees_subquery = (
        db.session.query(
            Employee.nompropio,
            func.min(Employee.id).label('min_id')
        )
        .group_by(Employee.nompropio)
        .subquery()
    )

    # Obtener los empleados únicos
    unique_employees = (
        db.session.query(Employee)
        .join(
            unique_employees_subquery,
            db.and_(
                Employee.nompropio == unique_employees_subquery.c.nompropio,
                Employee.id == unique_employees_subquery.c.min_id
            )
        )
        .filter(Employee.active == True)
        .order_by(Employee.nompropio)
        .all()
    )

    # Filtrar empleados dinámicamente por su campo 'departamento'
    # Los trabajadores cuyo departamento coincide con el seleccionado van primero
    if department:
        filtered_employees = [emp for emp in unique_employees if emp.departamento == department]
        rest_employees = [emp for emp in unique_employees if emp.departamento != department]
    else:
        filtered_employees = []
        rest_employees = unique_employees

    # Combinar las listas (departamento específico primero, luego el resto)
    employees = filtered_employees + rest_employees

    current_app.logger.debug("register_employee: Total empleados únicos a mostrar: %d", len(employees))

    # Cantidad de registros activos en este departamento
    active_count = (
        db.session.query(TimeRecord)
        .filter(
            TimeRecord.departamento == department,
            TimeRecord.end_time.is_(None)
        )
        .count()
    )

    active_records = TimeRecord.query.filter_by(
        departamento=department, end_time=None
    ).all()

    # Decidir a dónde redirigir al seleccionar un empleado
    next_route = ('main.register_project_imp' if area_usa_flujo_impresion(department)
                  else 'main.register_project')

    return render_template(
        'register_employee.html',
        employees=employees,
        department=department,
        active_count=active_count,
        next_route=next_route,
        active_records=active_records
    )




@main.route('/register_project', methods=['GET', 'POST'])
def register_project():
    if request.method == 'GET':
        department = request.args.get('department', '')
        employee_id = request.args.get('employee_id', '')
        if not employee_id and current_user.is_authenticated and getattr(current_user, 'is_employee', False):
            employee_id = current_user.employee_id

        if employee_id:
            emp = Employee.query.get(int(employee_id))
            if not emp or not emp.active:
                flash('Empleado no encontrado o deshabilitado.', 'danger')
                return redirect(url_for('main.register_employee', department=department))

        # Asegurarse de que el proyecto especial exista (folio=0)
        special_project = Project.query.filter_by(folio=0).first()
        if not special_project:
            # No existía: lo creamos con valores por defecto
            special_project = Project(
                folio=0,
                delivery_date=None,
                client='Administrativos',
                name='Costos Administrativos',
                active=True
            )
            db.session.add(special_project)
            db.session.commit()
        else:
            # Ya existía: si le falta nombre, cliente o está inactivo, lo actualizamos
            needs_update = False
            if not special_project.client or special_project.client.strip() == '':
                special_project.client = 'Administrativos'
                needs_update = True
            if not special_project.name or special_project.name.strip() == '':
                special_project.name = 'Costos Administrativos'
                needs_update = True
            if not special_project.active:
                special_project.active = True
                needs_update = True
            if needs_update:
                db.session.commit()

        # Inicializa/siembra actividades si la tabla está vacía
        ensure_seed_activities()

        # Actividades del area, mas las generales que se ofrecen sobre el FP 0
        activities = get_department_activities(department)
        general_activities = get_general_activities()

        # (Opcional) mapa de actividades activas por proyecto en el flujo de impresion
        active_activities = {}
        if area_usa_flujo_impresion(department) and employee_id:
            active_records = TimeRecord.query.filter_by(
                employee_id=employee_id,
                end_time=None
            ).all()
            for record in active_records:
                active_activities.setdefault(record.project_id, []).append(record.actividad or 'Sin especificar')

        # Contador de registros activos en el departamento
        if department:
            active_count = db.session.query(TimeRecord).filter(
                TimeRecord.departamento == department,
                TimeRecord.end_time == None
            ).count()
        else:
            active_count = 0

        # Proyectos activos
        projects = Project.query.filter_by(active=True).order_by(Project.folio.asc()).all()

        # Formulario
        form = RegisterTimeForm()
        employees = Employee.query.filter_by(active=True).all()
        form.employee_id.choices = [(emp.id, f"{emp.nombre} {emp.apellido_paterno}") for emp in employees]
        form.project_id.choices = [(proj.id, proj.name) for proj in projects]

        return render_template(
            'register_project.html',
            employee_id=employee_id,
            department=department,
            projects=projects,
            activities=activities,
            active_count=active_count,
            form=form,
            general_activities=general_activities,
            active_activities=active_activities  # por si tu template lo usa
        )

    # ───────── POST ─────────
    department = request.args.get('department', '')  # conservar filtro
    # Reasignamos las choices para evitar errores en validación
    employees = Employee.query.filter_by(active=True).all()
    projects = Project.query.filter_by(active=True).all()
    form = RegisterTimeForm()
    form.employee_id.choices = [(emp.id, f"{emp.nombre} {emp.apellido_paterno}") for emp in employees]
    form.project_id.choices = [(proj.id, proj.name) for proj in projects]

    # Acciones de POST
    if 'finalizar' in request.form:
        employee_id = form.employee_id.data or request.form.get('employee_id')
        # Buscar el registro abierto más reciente para el empleado
        open_record = TimeRecord.query.filter_by(
            employee_id=employee_id,
            end_time=None
        ).order_by(TimeRecord.start_time.desc()).first()
        if not open_record:
            flash('No se encontró ningún registro de tiempo abierto para este empleado.', 'warning')
            return redirect(url_for('main.register_project', department=department, employee_id=employee_id))
        open_record.end_time = datetime.utcnow()
        db.session.commit()
        flash('Registro de tiempo finalizado exitosamente.', 'success')
        return redirect(url_for('main.register_employee', department=department, employee_id=employee_id))

    # Iniciar nuevo registro
    if form.validate_on_submit():
        if form.iniciar.data:
            # Finalizar registro(s) abierto(s) previos
            if area_usa_flujo_impresion(department):
                open_record = TimeRecord.query.filter_by(
                    employee_id=form.employee_id.data,
                    project_id=form.project_id.data,
                    end_time=None
                ).first()
                if open_record:
                    open_record.end_time = datetime.utcnow()
                    db.session.commit()
                    flash("Se finalizó automáticamente el registro anterior para este proyecto.", "info")
            else:
                open_record = TimeRecord.query.filter_by(
                    employee_id=form.employee_id.data,
                    end_time=None
                ).first()
                if open_record:
                    open_record.end_time = datetime.utcnow()
                    db.session.commit()
                    flash("Se finalizó automáticamente el registro anterior.", "info")

            # Geolocalización opcional
            try:
                latitude = float(request.form.get('latitude', 0))
                longitude = float(request.form.get('longitude', 0))
            except ValueError:
                latitude, longitude = None, None

            activity = (request.form.get('activity') or '').strip()
            if not activity:
                flash('Debes seleccionar una actividad antes de iniciar el registro.', 'warning')
                return redirect(url_for('main.register_project',
                                        department=department,
                                        employee_id=form.employee_id.data))

            new_record = TimeRecord(
                employee_id=form.employee_id.data,
                project_id=form.project_id.data,
                start_time=datetime.utcnow(),
                end_time=None,
                latitude=latitude,
                longitude=longitude,
                departamento=department,
                actividad=activity
            )
            db.session.add(new_record)
            db.session.commit()
            flash('Registro de tiempo iniciado exitosamente.', 'success')
            return redirect(url_for('main.register_employee',
                                    department=department,
                                    employee_id=form.employee_id.data))
    else:
        flash('Error en la validación del formulario.', 'danger')

    # En caso de error, re-render del template básico
    return render_template('register_project.html', form=form, department=department)

@main.route('/register_project_imp', methods=['GET', 'POST'])
def register_project_imp():
    # Vista de las areas con flujo de impresion (varios registros abiertos a la vez)
    department  = request.args.get('department', 'Impresion').strip()
    employee_id = request.args.get('employee_id', '').strip()

    if not employee_id and current_user.is_authenticated and getattr(current_user, 'is_employee', False):
        employee_id = current_user.employee_id

    # validar empleado
    if not employee_id:
        flash('Debes seleccionar un empleado primero.', 'warning')
        return redirect(url_for('main.register_employee', department=department))

    selected_employee = Employee.query.get(int(employee_id))
    if not selected_employee or not selected_employee.active:
        flash('Empleado no encontrado o deshabilitado.', 'danger')
        return redirect(url_for('main.register_employee', department=department))

    # asegurar proyecto folio=0
    special_project = Project.query.filter_by(folio=0).first()
    if not special_project:
        special_project = Project(
            folio=0, delivery_date=None,
            client='Administrativos',
            name='Costos Administrativos',
            active=True
        )
        db.session.add(special_project)
        db.session.commit()

    # Inicializa/siembra actividades si la tabla está vacía
    ensure_seed_activities()

    # Actividades del area, mas las generales que se ofrecen sobre el FP 0
    activities = get_department_activities(department)
    general_activities = get_general_activities()

    # proyectos activos
    projects = Project.query.filter_by(active=True).order_by(Project.folio.asc()).all()

    # registros activos de este empleado
    active_records = TimeRecord.query.filter_by(
        employee_id=selected_employee.id,
        end_time=None
    ).all()

    # mapa proyecto->actividades activas
    active_activities = {}
    for rec in active_records:
        active_activities.setdefault(rec.project_id, []).append(rec.actividad or 'Sin especificar')

    # preparar formulario
    form = RegisterTimeForm()
    form.employee_id.choices = [(selected_employee.id, selected_employee.nompropio)]
    form.project_id.choices  = [(p.id, p.name) for p in projects]

    if request.method == 'POST':
        # finalizar registro específico (por id)
        if 'finalize_rec_id' in request.form:
            rec = TimeRecord.query.get(int(request.form['finalize_rec_id']))
            if rec and rec.end_time is None:
                rec.end_time = datetime.utcnow()
                db.session.commit()
                flash('Registro específico finalizado.', 'success')
            return redirect(url_for(
                'main.register_project_imp',
                department=department,
                employee_id=employee_id
            ))

        # iniciar sin cerrar previos (propio del flujo de impresion)
        if form.validate_on_submit() and 'iniciar' in request.form:
            proj_id  = form.project_id.data
            activity = request.form.get('activity')
            if not proj_id or not activity:
                flash('Selecciona proyecto y actividad.', 'warning')
            else:
                try:
                    lat = float(request.form.get('latitude', 0))
                    lon = float(request.form.get('longitude', 0))
                except ValueError:
                    lat = lon = None

                # Aquí NO cerramos otros proyectos del mismo empleado,
                # sólo cerraríamos si existiera uno exacto (empleado+proyecto) si así lo deseas.
                # Si quieres forzar uno a la vez por proyecto:
                open_same = TimeRecord.query.filter_by(
                    employee_id=selected_employee.id,
                    project_id=proj_id,
                    end_time=None
                ).first()
                if open_same:
                    open_same.end_time = datetime.utcnow()
                    db.session.commit()
                    flash("Se finalizó automáticamente el registro anterior de este proyecto.", "info")

                new_rec = TimeRecord(
                    employee_id=selected_employee.id,
                    project_id=proj_id,
                    actividad=activity,
                    start_time=datetime.utcnow(),
                    end_time=None,
                    latitude=lat,
                    longitude=lon,
                    departamento=department
                )
                db.session.add(new_rec)
                db.session.commit()
                flash('Registro de impresión iniciado.', 'success')
                return redirect(url_for(
                    'main.register_employee',
                    department=department
                ))

    return render_template(
        'register_project_imp.html',
        department=department,
        selected_employee=selected_employee,
        projects=projects,
        activities=activities,
        general_activities=general_activities,
        active_records=active_records,
        active_activities=active_activities,
        form=form
    )


# Agregar estas rutas a tu routes.py

@main.route('/projects/edit/<int:project_id>', methods=['GET', 'POST'])
@login_required
def edit_project(project_id):
    """Editar un proyecto existente"""
    if not current_user.has_admin_privileges:
        flash('Acceso denegado. Solo administradores pueden editar proyectos.', 'danger')
        return redirect(url_for('main.home'))

    project = Project.query.get_or_404(project_id)

    # No permitir editar el proyecto especial
    if project.folio == 0:
        flash('No se puede editar el proyecto de Costos Administrativos.', 'warning')
        return redirect(url_for('main.project_page'))

    form = ProjectForm(obj=project)

    if form.validate_on_submit():
        try:
            # Verificar si el folio cambió y ya existe
            if project.folio != int(form.folio.data):
                existing = Project.query.filter_by(folio=form.folio.data).first()
                if existing:
                    flash('Ya existe un proyecto con ese folio.', 'danger')
                    return redirect(url_for('main.edit_project', project_id=project_id))

            project.folio = form.folio.data
            project.name = form.name.data
            project.client = form.client.data
            project.delivery_date = form.delivery_date.data

            db.session.commit()
            flash(f'Proyecto "{project.name}" actualizado exitosamente.', 'success')
            return redirect(url_for('main.project_page'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editando proyecto: {e}")
            flash('Error al actualizar el proyecto.', 'danger')

    return render_template('edit_project.html', form=form, project=project)

@main.route('/projects/delete/<int:project_id>', methods=['POST'])
@login_required
def delete_project(project_id):
    """Eliminar un proyecto"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    try:
        project = Project.query.get_or_404(project_id)

        # No permitir eliminar el proyecto especial
        if project.folio == 0:
            return jsonify({'success': False, 'message': 'No se puede eliminar el proyecto de Costos Administrativos'}), 400

        # Verificar si tiene registros de tiempo asociados
        time_records_count = TimeRecord.query.filter_by(project_id=project_id).count()
        if time_records_count > 0:
            return jsonify({
                'success': False,
                'message': f'No se puede eliminar. El proyecto tiene {time_records_count} registros de tiempo asociados.'
            }), 400

        project_name = project.name
        db.session.delete(project)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Proyecto "{project_name}" eliminado exitosamente.'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error eliminando proyecto: {e}")
        return jsonify({'success': False, 'message': 'Error al eliminar el proyecto'}), 500

@main.route('/get_gantt_data', methods=['GET'])
@login_required
def get_gantt_data():
    """API endpoint para obtener datos del Gantt Chart, ahora con selector de semana."""
    if not current_user.has_admin_privileges:
        return jsonify({'error': 'Acceso denegado'}), 403

    try:
        view_type = request.args.get('view_type', 'employee')
        department_filter = request.args.get('department', '').strip()
        selected_week = request.args.get('selected_week') # ej: "2025-W30"

        mexico_tz = timezone('America/Mexico_City')

        # CORRECCIÓN: Calcular la semana correctamente usando ISO week
        if selected_week:
            # Parsear usando ISO week date (formato: YYYY-Www)
            year, week_str = selected_week.split('-W')
            year = int(year)
            week = int(week_str)

            # Usar fromisocalendar para obtener el lunes correcto
            start_of_week_mx = datetime.fromisocalendar(year, week, 1).date()
        else:
            # Si no, usamos la semana actual
            today_mx = datetime.now(mexico_tz).date()
            start_of_week_mx = today_mx - timedelta(days=today_mx.weekday())

        # Convertimos el inicio de la semana a UTC para la consulta en la BD
        start_of_week_utc = mexico_tz.localize(datetime.combine(start_of_week_mx, datetime.min.time())).astimezone(timezone('UTC'))
        end_of_week_utc = start_of_week_utc + timedelta(days=7)

        current_app.logger.debug(f"Semana seleccionada: {selected_week}")
        current_app.logger.debug(f"Inicio de semana (MX): {start_of_week_mx}")
        current_app.logger.debug(f"Filtro de departamento: '{department_filter}'")
        current_app.logger.debug(f"Tipo de vista: {view_type}")

        # Query base
        query = TimeRecord.query.filter(
            TimeRecord.start_time >= start_of_week_utc,
            TimeRecord.start_time < end_of_week_utc
        ).join(Employee).join(Project)

        def create_record_dict(record):
            start_time_utc_iso = record.start_time.isoformat() + 'Z'
            end_time = record.end_time or datetime.utcnow()
            duration = (end_time - record.start_time).total_seconds() / 3600

            # Calcular la hora de fin en zona horaria de México
            if record.end_time:
                end_time_mx = record.end_time.replace(tzinfo=timezone('UTC')).astimezone(mexico_tz)
                end_time_formatted = end_time_mx.strftime('%H:%M')
            else:
                end_time_formatted = 'En progreso'

            return {
                'startTimeUTC': start_time_utc_iso,
                'duration': round(duration, 2),
                'project': record.project.name,
                'projectFolio': record.project.folio,
                'activity': record.actividad or 'Sin especificar',
                'department': record.departamento or 'Sin departamento',
                'endTime': end_time_formatted,
                'isActive': record.end_time is None,
                'recordId': record.id,
                'employee': record.employee.nompropio
            }

        gantt_data = []

        if view_type == 'employee':
            # CORRECCIÓN: Aplicar filtro de departamento correctamente
            if department_filter:
                # Filtrar empleados por su departamento
                employees_query = Employee.query.filter(
                    Employee.departamento == department_filter
                ).order_by(Employee.nompropio)
                current_app.logger.debug(f"Filtrando empleados por departamento: {department_filter}")
            else:
                employees_query = Employee.query.order_by(Employee.nompropio)

            employees = employees_query.all()
            current_app.logger.debug(f"Empleados encontrados: {len(employees)}")

            for employee in employees:
                emp_records = query.filter(TimeRecord.employee_id == employee.id).all()
                current_app.logger.debug(f"Empleado {employee.nompropio}: {len(emp_records)} registros")

                if emp_records:
                    gantt_data.append({
                        'label': employee.nompropio,
                        'type': 'employee',
                        'employeeId': employee.id,
                        'department': employee.departamento,
                        'records': [create_record_dict(r) for r in emp_records]
                    })

        else:  # view_type == 'department'
            # Para vista por departamento, filtrar registros por departamento
            if department_filter:
                query = query.filter(TimeRecord.departamento == department_filter)
                current_app.logger.debug(f"Filtrando registros por departamento: {department_filter}")

            all_records = query.all()
            current_app.logger.debug(f"Registros encontrados: {len(all_records)}")

            records_by_dept = {}

            for record in all_records:
                dept = record.departamento or 'Sin departamento'
                if dept not in records_by_dept:
                    records_by_dept[dept] = []
                records_by_dept[dept].append(create_record_dict(record))

            for dept, records in records_by_dept.items():
                gantt_data.append({
                    'label': dept,
                    'type': 'department',
                    'records': records
                })

        current_app.logger.debug(f"Datos finales del gantt: {len(gantt_data)} elementos")

        # Información de la semana
        week_info = []
        today_date_mx = datetime.now(mexico_tz).date()
        for i in range(7):
            date = start_of_week_mx + timedelta(days=i)
            week_info.append({
                'date': date.strftime('%Y-%m-%d'),
                'isWeekend': date.weekday() >= 5,
                'isToday': date == today_date_mx
            })

        return jsonify({
            'success': True,
            'data': gantt_data,
            'weekInfo': week_info,
            'viewType': view_type,
            'weekStart': start_of_week_mx.strftime('%Y-%m-%d'),  # Para debug
            'departmentFilter': department_filter  # Para debug
        })

    except Exception as e:
        current_app.logger.error(f"Error en get_gantt_data: {e}")
        import traceback
        current_app.logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'message': str(e)
        }), 500

@main.route('/admin/add_project', methods=['GET', 'POST'])
@login_required
def add_project():
    if not current_user.has_admin_privileges:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    form = ProjectForm()
    if form.validate_on_submit():
        try:
            # Normalizar/validar folio
            folio_raw = form.folio.data
            try:
                folio = int(folio_raw)
            except (TypeError, ValueError):
                flash("Folio inválido. Debe ser numérico.", "danger")
                return redirect(url_for('main.add_project'))

            if folio == 0:
                flash("El folio 0 está reservado para 'Costos Administrativos'.", "warning")
                return redirect(url_for('main.add_project'))

            # Datos del formulario
            delivery_date = form.delivery_date.data
            client = (form.client.data or "").strip()
            name = (form.name.data or "").strip()

            # Si ya existe (pudo ser creado por /search_fp), ACTUALIZA/ACTIVA
            project = Project.query.filter_by(folio=folio).first()
            if project:
                if name:
                    project.name = name
                if client:
                    project.client = client
                project.delivery_date = delivery_date  # puede ser None si no eliges
                project.active = True                  # asegúralo activo
                db.session.commit()
                flash(f'Proyecto "{project.name}" actualizado/activado correctamente.', 'success')
            else:
                # Crear nuevo
                new_project = Project(
                    folio=folio,
                    delivery_date=delivery_date,
                    client=client,
                    name=name,
                    active=True
                )
                db.session.add(new_project)
                db.session.commit()
                flash("Proyecto agregado con éxito.", "success")

            # A dónde quieres regresar: dashboard o lista de proyectos
            return redirect(url_for('main.admin_dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error en add_project: {e}")
            flash("Error al guardar el proyecto. Intenta de nuevo.", "danger")

    return render_template('add_project.html', form=form)


@main.route('/worker_analysis', methods=['GET'])
def worker_analysis():
    employee_id = request.args.get('employee_id')
    if not employee_id:
        return jsonify({"error": "No se proporcionó el ID del empleado"}), 400
    try:
        employee = Employee.query.get(int(employee_id))
        if not employee:
            return jsonify({"error": "Empleado no encontrado"}), 404

        # Tiempo total invertido (en segundos)
        total_seconds = db.session.query(
            func.sum(func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time))
        ).filter(
            TimeRecord.employee_id == employee_id,
            TimeRecord.end_time != None
        ).scalar() or 0
        total_hours = round(total_seconds / 3600, 2)

        # Tiempo invertido por proyecto
        time_by_project = db.session.query(
            Project.name,
            func.sum(func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time))
        ).join(Project, Project.id == TimeRecord.project_id
        ).filter(
            TimeRecord.employee_id == employee_id,
            TimeRecord.end_time != None
        ).group_by(Project.name).all()
        time_by_project = [(proj, round(seconds / 3600, 2)) for proj, seconds in time_by_project]

        # Tiempo invertido por actividad
        time_by_activity = db.session.query(
            TimeRecord.actividad,
            func.sum(func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time))
        ).filter(
            TimeRecord.employee_id == employee_id,
            TimeRecord.end_time != None
        ).group_by(TimeRecord.actividad).all()
        time_by_activity = [(act if act else "Sin especificar", round(seconds / 3600, 2))
                            for act, seconds in time_by_activity]

        # Renderizar un fragmento HTML (usa un template nuevo, por ejemplo: worker_analysis_fragment.html)
        html = render_template('worker_analysis_fragment.html',
                               employee=employee,
                               total_time=total_hours,
                               time_by_project=time_by_project,
                               time_by_activity=time_by_activity)
        return jsonify({"html": html})
    except Exception as e:
        current_app.logger.error("Error en worker_analysis: %s", str(e))
        return jsonify({"error": "Error interno"}), 500

@main.route('/test_qr')
def test_qr():
    return render_template('test_qr.html')

@main.route('/test')
def test():
    return "Ruta de prueba accesible."

@main.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.has_admin_privileges:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    # 1. Trabajadores Activos por Proyecto
    active_workers_query = db.session.query(
        Project.name,
        func.count(TimeRecord.id)
    ).join(TimeRecord).filter(TimeRecord.end_time == None).group_by(Project.name).all()
    active_workers = {pname: count for (pname, count) in active_workers_query}

    # 2. Tiempo Invertido por Proyecto (en Horas) con TIMESTAMPDIFF
    time_invested_query = db.session.query(
        Project.name,
        func.sum(
            func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) / 3600.0
        )
    ).join(TimeRecord).filter(TimeRecord.end_time != None).group_by(Project.name).all()
    time_invested = {pname: round(hours or 0, 2) for (pname, hours) in time_invested_query}

    # 3. Horas Invertidas por Departamento - CORREGIDO
    dept_invested_data = {}
    all_projects = Project.query.order_by(Project.id).all()
    for proj in all_projects:
        dept_invested_data[proj.id] = {}

    # Query corregido para obtener departamento del TimeRecord directamente
    dept_query = (
        db.session.query(
            Project.id.label("proj_id"),
            TimeRecord.departamento.label("dept"),
            func.sum(
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) / 3600.0
            ).label("total_hrs")
        )
        .join(TimeRecord, Project.id == TimeRecord.project_id)
        .filter(TimeRecord.end_time != None)
        .filter(TimeRecord.departamento != None)
        .group_by(Project.id, TimeRecord.departamento)
        .all()
    )

    current_app.logger.debug("Debug - Datos de departamentos obtenidos:")
    for row in dept_query:
        proj_id = row.proj_id
        dept = row.dept or "Sin Departamento"
        total_hrs = row.total_hrs or 0
        dept_invested_data[proj_id][dept] = round(total_hrs, 2)
        current_app.logger.debug(f"Proyecto {proj_id}: {dept} = {total_hrs} horas")

    # 4. Horas Invertidas por Actividad (Por Proyecto) - MEJORADO
    activity_query = (
        db.session.query(
            Project.name.label("project_name"),
            TimeRecord.actividad,
            func.sum(
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) / 3600.0
            ).label("hours")
        )
        .join(Project, Project.id == TimeRecord.project_id)
        .filter(TimeRecord.end_time != None)
        .filter(TimeRecord.actividad != None)
        .filter(TimeRecord.actividad != '')
        .group_by(Project.name, TimeRecord.actividad)
        .all()
    )

    activity_metrics = {}
    current_app.logger.debug("Debug - Datos de actividades obtenidos:")
    for row in activity_query:
        proj_name = row.project_name
        act = row.actividad or "Sin especificar"
        hrs = round(row.hours or 0, 2)

        if proj_name not in activity_metrics:
            activity_metrics[proj_name] = {}
        activity_metrics[proj_name][act] = hrs
        current_app.logger.debug(f"Proyecto {proj_name}: {act} = {hrs} horas")

    # 5. Horas Invertidas por Actividad (Por Día) - últimos 30 días
    from datetime import datetime, timedelta

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_query = (
        db.session.query(
            func.date(TimeRecord.start_time).label("date"),
            func.sum(
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) / 3600.0
            ).label("hours")
        )
        .filter(
            TimeRecord.end_time != None,
            TimeRecord.start_time >= thirty_days_ago
        )
        .group_by(func.date(TimeRecord.start_time))
        .all()
    )
    daily_activity_metrics = {}
    for row in daily_query:
        date_str = row.date.strftime('%Y-%m-%d')
        daily_activity_metrics[date_str] = round(row.hours or 0, 2)

    # 6. Obtener todos los empleados para análisis
    employees = Employee.query.order_by(Employee.nombre, Employee.apellido_paterno).all()

    # 7. Estadísticas adicionales
    projects_count = Project.query.filter_by(active=True).count()
    total_employees = Employee.query.count()

    # 8. Registros recientes con mejor información
    records = (
        TimeRecord.query
        .join(Employee)
        .join(Project)
        .order_by(TimeRecord.id.desc())
        .limit(20)
        .all()
    )

    # 9. Métricas de eficiencia
    # Total de horas trabajadas hoy
    today = datetime.utcnow().date()
    today_hours_query = db.session.query(
        func.sum(
            func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) / 3600.0
        )
    ).filter(
        TimeRecord.end_time != None,
        func.date(TimeRecord.start_time) == today
    ).scalar()

    today_hours = round(today_hours_query or 0, 2)

    # 10. Trabajadores activos ahora mismo
    active_workers_now = db.session.query(
        func.count(func.distinct(TimeRecord.employee_id))
    ).filter(TimeRecord.end_time == None).scalar() or 0

    # 11. Proyectos con actividad reciente (últimos 7 días)
    week_ago = datetime.utcnow() - timedelta(days=7)
    active_projects_week = db.session.query(
        func.count(func.distinct(TimeRecord.project_id))
    ).filter(TimeRecord.start_time >= week_ago).scalar() or 0

    dashboard_data = {
        'active_workers': active_workers,
        'time_invested': time_invested,
        'total_active_workers': active_workers_now,
        'today_hours': today_hours,
        'active_projects_week': active_projects_week
    }

    # Debug: Imprimir datos para verificar
    current_app.logger.debug(f"Active workers: {active_workers}")
    current_app.logger.debug(f"Time invested: {time_invested}")
    current_app.logger.debug(f"Department data: {dept_invested_data}")
    current_app.logger.debug(f"Activity metrics: {activity_metrics}")

    departments = (
        db.session.query(TimeRecord.departamento)
        .filter(TimeRecord.departamento.isnot(None))
        .filter(TimeRecord.departamento != '')
        .distinct()
        .order_by(TimeRecord.departamento)
        .all()
    )
    unique_departments = [dept[0] for dept in departments if dept[0]]


    return render_template(
        'admin_dashboard.html',
        dashboard_data=dashboard_data,
        projects_count=projects_count,
        total_employees=total_employees,
        records=records,
        all_projects=all_projects,
        employees=employees,
        dept_invested_data=dept_invested_data,
        activity_metrics=activity_metrics,
        daily_activity_metrics=daily_activity_metrics,
        today_hours=today_hours,
        active_workers_now=active_workers_now,unique_departments=unique_departments
    )

# Reemplaza la función get_active_records en tu routes.py con esta versión corregida:

# Reemplaza la función get_active_records en tu routes.py con esta versión simplificada:
@main.route('/costs/finalize/<int:record_id>', methods=['POST'])
@login_required
def finalize_time_record_from_costs(record_id):
    """Finalizar un registro de tiempo desde el dashboard de costos"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    try:
        record = TimeRecord.query.get_or_404(record_id)

        if record.end_time is not None:
            return jsonify({'success': False, 'message': 'El registro ya está finalizado'})

        employee_name = record.employee.nompropio
        project_name = record.project.name

        record.end_time = datetime.utcnow()
        db.session.commit()

        message = f'Registro finalizado: {employee_name} - {project_name}'
        flash(message, 'success')

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error finalizando registro: {e}")
        return jsonify({'success': False, 'message': 'Error al finalizar el registro'}), 500

@main.route('/get_active_records', methods=['GET'])
@login_required
def get_active_records():
    """API endpoint para obtener registros activos - versión simplificada"""
    if not current_user.has_admin_privileges:
        return jsonify({'error': 'Acceso denegado'}), 403

    try:
        # Parámetros de filtro
        department_filter = request.args.get('department', '').strip()
        project_filter = request.args.get('project_id', type=int)

        # Query base igual al de registros recientes, pero filtrando solo activos
        query = (
            TimeRecord.query
            .join(Employee)
            .join(Project)
            .filter(TimeRecord.end_time == None)  # Solo registros activos
            .order_by(TimeRecord.start_time.desc())
        )

        # Aplicar filtros si existen
        if department_filter:
            query = query.filter(TimeRecord.departamento == department_filter)

        if project_filter:
            query = query.filter(TimeRecord.project_id == project_filter)

        # Obtener los registros
        active_records = query.all()

        # Log para debug
        current_app.logger.info(f"Registros activos encontrados: {len(active_records)}")

        # Convertir a formato JSON usando la misma lógica que el dashboard
        records_data = []
        for record in active_records:
            # Calcular duración
            now = datetime.utcnow()
            duration_seconds = (now - record.start_time).total_seconds()
            duration_hours = int(duration_seconds // 3600)
            duration_minutes = int((duration_seconds % 3600) // 60)

            # Formatear tiempo de inicio (puedes ajustar el formato según necesites)
            import pytz
            cdmx_tz = pytz.timezone('America/Mexico_City')
            utc_tz = pytz.UTC

            start_utc = utc_tz.localize(record.start_time)
            start_cdmx = start_utc.astimezone(cdmx_tz)

            record_data = {
                'id': record.id,
                'employee_name': f"{record.employee.nombre} {record.employee.apellido_paterno}",
                'employee_full_name': record.employee.nompropio,
                'department': record.departamento or 'N/A',
                'project_name': record.project.name,
                'project_folio': record.project.folio,
                'activity': record.actividad or 'Sin especificar',
                'start_time': start_cdmx.strftime('%d/%m %H:%M'),
                'duration': f"{duration_hours}h {duration_minutes}m",
                'duration_minutes': int(duration_seconds // 60)
            }
            records_data.append(record_data)

        return jsonify({
            'success': True,
            'records': records_data,
            'total': len(records_data)
        })

    except Exception as e:
        current_app.logger.error(f"Error en get_active_records: {e}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'message': str(e)
        }), 500
@main.route('/finalize_record_admin/<int:record_id>', methods=['POST'])
@login_required
@csrf.exempt
def finalize_record_admin(record_id):
    """Finalizar un registro específico desde el dashboard admin"""
    if not current_user.has_admin_privileges:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    try:
        record = TimeRecord.query.get_or_404(record_id)

        if record.end_time is not None:
            return jsonify({'success': False, 'message': 'El registro ya está finalizado'})

        record.end_time = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Registro finalizado: {record.employee.nompropio} - {record.project.name}'
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error finalizando registro {record_id}: {e}")
        return jsonify({'success': False, 'message': 'Error al finalizar el registro'}), 500

@main.route('/toggle_project/<int:project_id>', methods=['POST'])
@login_required
def toggle_project(project_id):
    if not current_user.has_admin_privileges:
        return jsonify({"error": "Acceso denegado."}), 403

    project = Project.query.get_or_404(project_id)
    if project.folio == 0:
        return jsonify({"error": "El proyecto especial no se puede activar ni desactivar."}), 400

    project.active = not project.active
    db.session.commit()

    message = f"El proyecto '{project.name}' ha sido {'activado' if project.active else 'desactivado'}."
    return jsonify({"success": True, "active": project.active, "message": message})

@main.route('/projects/bulk_toggle', methods=['POST'])
@login_required
def bulk_toggle_projects():
    if not current_user.has_admin_privileges:
        return jsonify({"error": "Acceso denegado."}), 403

    data = request.get_json() or {}
    project_ids = data.get('project_ids', [])
    action = data.get('action')  # 'activate' | 'deactivate'

    if not project_ids or action not in ('activate', 'deactivate'):
        return jsonify({"error": "Parámetros inválidos."}), 400

    target_active = (action == 'activate')
    projects = Project.query.filter(Project.id.in_(project_ids), Project.folio != 0).all()
    updated_count = 0

    for project in projects:
        if project.active != target_active:
            project.active = target_active
            updated_count += 1

    db.session.commit()

    verb = "activado" if target_active else "desactivado"
    message = f"Se han {verb}s {updated_count} proyecto(s) correctamente."
    return jsonify({"success": True, "updated_count": updated_count, "message": message})

@main.route('/get_employee/<qr_code>', methods=['GET'])
def get_employee(qr_code):
    employee = Employee.query.filter_by(n_empleado=qr_code).first()
    if employee:
        if not employee.active:
            return jsonify({'error': 'Empleado deshabilitado'}), 400
        return jsonify({
            'id': employee.id,
            'nombre_completo': f"{employee.nombre} {employee.apellido_paterno} {employee.apellido_materno}",
            'nompropio': employee.nompropio
        })
    else:
        return jsonify({'error': 'Empleado no encontrado'}), 404

# ─────────────────────────────────────────────────────────────
# 1) REGISTRO DE USUARIOS
#    • user_type        : 'empleado' | 'administrador'  (hidden en el form)
#    • employee_name    : id del Employee elegido (solo empleados)
#    • verification_code: clave para admins
# ─────────────────────────────────────────────────────────────
@main.route('/register', methods=['GET', 'POST'])
def register():
    from .models import Employee, User

    employees = Employee.query.filter_by(active=True).order_by(Employee.nompropio).all()
    form = RegistrationForm()

    # ───────── POST ─────────
    if request.method == 'POST':
        user_type = request.form.get('user_type')
        username  = form.username.data
        password  = form.password.data

        # ── validaciones básicas ──
        if User.query.filter_by(username=username).first():
            flash('Ese correo ya está registrado.', 'danger')
            return redirect(url_for('main.register'))

        # Todos los perfiles arrancan apagados y cada rama enciende el suyo:
        # así ninguna combinación queda a medias.
        is_admin = is_project_leader = is_area_manager = False
        is_rh = is_ejecutivo = False
        area_manager_department = None
        employee_id = None

        codigo = form.verification_code.data

        # ▸ Registrar ADMIN
        if user_type == 'administrador':
            if codigo != current_app.config.get('ADMIN_CODE', 'HI35C3'):
                flash('Código de administrador inválido.', 'danger')
                return redirect(url_for('main.register'))
            is_admin = True

        # ▸ Registrar LÍDER DE PROYECTO
        elif user_type == 'lider_proyecto':
            if codigo != current_app.config.get('LEADER_CODE', 'LP92B4'):
                flash('Código de líder de proyecto inválido.', 'danger')
                return redirect(url_for('main.register'))
            is_project_leader = True

        # ▸ Registrar RH
        elif user_type == 'rh':
            if codigo != current_app.config.get('RH_CODE', 'RH71D2'):
                flash('Código de RH inválido.', 'danger')
                return redirect(url_for('main.register'))
            is_rh = True

        # ▸ Registrar JEFE DE AREA
        elif user_type == 'jefe_area':
            area = (request.form.get('area_manager_department') or '').strip()
            if codigo != current_app.config.get('AREA_MANAGER_CODE', 'AR845C'):
                flash('Código de Jefe de Area inválido.', 'danger')
                return redirect(url_for('main.register'))
            if area not in area_departments():
                flash('Selecciona un área válida para el Jefe de Area.', 'warning')
                return redirect(url_for('main.register'))
            is_area_manager = True
            area_manager_department = area

        # ▸ Registrar EJECUTIVO
        elif user_type == 'ejecutivo':
            if codigo != current_app.config.get('EJECUTIVO_CODE', 'EJ38F6'):
                flash('Código de Ejecutivo inválido.', 'danger')
                return redirect(url_for('main.register'))
            is_ejecutivo = True

        # ▸ Registrar EMPLEADO
        elif user_type == 'empleado':
            employee_id = request.form.get('employee_name')
            if not employee_id:
                flash('Selecciona tu nombre de la lista.', 'warning')
                return redirect(url_for('main.register'))
            if not Employee.query.get(int(employee_id)):
                flash('Empleado no encontrado en la base.', 'danger')
                return redirect(url_for('main.register'))

        # ▸ Tipo de usuario no elegido
        else:
            flash('Debes elegir el tipo de usuario.', 'warning')
            return redirect(url_for('main.register'))

        # Los perfiles que no son "empleado" pueden ligarse a un empleado de RH
        # para tener saldo de vacaciones propio.
        if user_type != 'empleado':
            vinculo = (request.form.get('employee_name') or '').strip()
            if vinculo and Employee.query.get(int(vinculo)):
                employee_id = int(vinculo)

        # ── crear usuario ──
        hashed = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(
            username         = username,
            password         = hashed,
            is_admin         = is_admin,
            is_project_leader = is_project_leader,
            is_area_manager  = is_area_manager,
            is_rh            = is_rh,
            is_ejecutivo     = is_ejecutivo,
            area_manager_department = area_manager_department,
            employee_id      = employee_id
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Usuario registrado con éxito. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('main.login'))

    # ───────── GET ─────────
    return render_template('register.html', form=form, employees=employees)

# ─────────────────────────────────────────────────────────────
# 2) INICIO DE SESIÓN
#    • Admin  ⇒  al dashboard de admin
#    • Empleado ⇒  directo a registrar proyecto (sin pasar por
#      la pantalla de elegir trabajador)
# ─────────────────────────────────────────────────────────────
@main.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            remember = request.form.get('remember', False) == 'on'
            login_user(user, remember=remember)
            flash('Inicio de sesión exitoso', 'success')

            # Redirección según rol
            if user.has_admin_privileges:  # Admin o Líder de Proyecto
                next_page = url_for('main.admin_dashboard')
            elif getattr(user, 'is_area_manager', False):
                next_page = url_for('main.area_status')
            else:
                # Empleado → tomar su departamento
                emp = Employee.query.get(user.employee_id)
                if emp:
                    next_page = url_for(
                        'main.home',
                        department=emp.departamento or '',
                        employee_id=emp.id
                    )
                else:
                    next_page = url_for('main.home')

            return redirect(next_page)

        flash('Credenciales incorrectas', 'danger')

    return render_template('login.html', form=form)

# ─────────────────────────────────────────────────────────────
# 3) LOGOUT
# ─────────────────────────────────────────────────────────────
@main.route('/logout')
@login_required
def logout():
    """
    Cierra completamente la sesión del usuario.
    - elimina la sesión de Flask-Login (logout_user)
    - limpia la sesión de Flask (session.clear)
    - redirige al home
    """
    logout_user()      # ← borra la cookie 'remember' y la sesión de login
      # ← opcional, remueve otros datos que hubieras puesto
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('main.home'))
def _redirect_employee_to_project(emp: Employee, dept_requested: str = None):
    """
    Devuelve un redirect a la vista register_project / register_project_imp.
    Si dept_requested (el botón que el usuario pulsó) existe se respeta; en otro
    caso usamos el departamento real del empleado. La pantalla destino depende
    del flujo configurado para el area.
    """
    dept = dept_requested or emp.departamento

    if area_usa_flujo_impresion(dept):
        return redirect(url_for(
            'main.register_project_imp',
            department=dept,
            employee_id=emp.id
        ))
    else:
        return redirect(url_for(
            'main.register_project',
            department=dept,
            employee_id=emp.id
        ))


@main.route('/area/status')
@login_required
def area_status():
    guard = _require_area_manager()
    if guard:
        return guard

    area = current_user.area_manager_department
    active_records = (
        TimeRecord.query
        .join(Employee, TimeRecord.employee_id == Employee.id)
        .join(Project, TimeRecord.project_id == Project.id)
        .filter(TimeRecord.departamento == area, TimeRecord.end_time.is_(None), Employee.active == True)
        .order_by(TimeRecord.start_time.desc())
        .all()
    )

    employee_ids = {
        emp_id for (emp_id,) in
        db.session.query(Employee.id).filter(Employee.departamento == area, Employee.active == True).all()
    }
    employee_ids.update(record.employee_id for record in active_records)

    employees = (
        Employee.query
        .filter(Employee.id.in_(employee_ids), Employee.active == True)
        .order_by(Employee.nompropio)
        .all()
        if employee_ids else []
    )

    active_by_employee = {}
    for record in active_records:
        record.start_time_mx = _to_mx(record.start_time)
        active_by_employee.setdefault(record.employee_id, []).append(record)

    return render_template(
        'area_status.html',
        area=area,
        employees=employees,
        active_by_employee=active_by_employee,
        now_mx=_to_mx(datetime.utcnow())
    )


@main.route('/area/records')
@login_required
def area_records():
    guard = _require_area_manager()
    if guard:
        return guard

    area = current_user.area_manager_department
    employee_filter = request.args.get('employee_id', type=int)
    project_filter = request.args.get('project_id', type=int)
    date_from = request.args.get('date_from', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 25

    query = (
        TimeRecord.query
        .join(Employee, TimeRecord.employee_id == Employee.id)
        .join(Project, TimeRecord.project_id == Project.id)
        .filter(TimeRecord.departamento == area)
    )

    if employee_filter:
        query = query.filter(TimeRecord.employee_id == employee_filter)
    if project_filter:
        query = query.filter(TimeRecord.project_id == project_filter)
    if date_from:
        try:
            start_local = datetime.strptime(date_from, '%Y-%m-%d')
            start_utc = pytz.timezone('America/Mexico_City').localize(start_local).astimezone(pytz.UTC).replace(tzinfo=None)
            query = query.filter(TimeRecord.start_time >= start_utc)
        except ValueError:
            flash('Fecha de inicio inválida.', 'warning')

    records = (
        query
        .order_by(TimeRecord.start_time.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    for record in records.items:
        record.start_time_mx = _to_mx(record.start_time)
        record.end_time_mx = _to_mx(record.end_time)

    employees = (
        db.session.query(Employee)
        .join(TimeRecord, TimeRecord.employee_id == Employee.id)
        .filter(TimeRecord.departamento == area)
        .distinct()
        .order_by(Employee.nompropio)
        .all()
    )
    projects = (
        db.session.query(Project)
        .join(TimeRecord, TimeRecord.project_id == Project.id)
        .filter(TimeRecord.departamento == area)
        .distinct()
        .order_by(Project.folio.desc())
        .all()
    )

    return render_template(
        'area_records.html',
        area=area,
        records=records,
        employees=employees,
        projects=projects,
        filters={
            'employee_id': employee_filter,
            'project_id': project_filter,
            'date_from': date_from
        }
    )

def _resumir_nombres(nombres, maximo=8):
    """'A, B, C y 4 mas' para no reventar el flash con toda la plantilla."""
    if len(nombres) <= maximo:
        return ', '.join(nombres)
    return '%s y %d mas' % (', '.join(nombres[:maximo]), len(nombres) - maximo)


@main.route('/admin/employees/sync_rh', methods=['POST'])
@login_required
def sync_employees_rh():
    """
    Trae a `employees` las altas, bajas y cambios del sistema de RH.

    Mientras `employees` siga siendo una copia (la migracion que la vuelve vista
    esta detenida, ver BUG_IMPRESION_ANALITICA.md), este boton es la unica forma
    de que una persona nueva en RH aparezca en la app.
    """
    guard = _solo_admin()
    if guard:
        return guard
    try:
        resumen = rh.sincronizar_empleados()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("sync_employees_rh: %s", e)
        current_app.logger.error(traceback.format_exc())
        flash('No se pudo sincronizar con RH: %s' % e, 'danger')
        return redirect(url_for('main.manage_employees'))

    partes = [
        '%d %s: %s' % (len(resumen[clave]), etiqueta, _resumir_nombres(resumen[clave]))
        for clave, etiqueta in (('altas', 'altas'), ('cambios', 'actualizados'),
                                ('bajas', 'bajas'), ('reactivados', 'reactivados'))
        if resumen[clave]
    ]
    if partes:
        flash('Personal sincronizado con RH. ' + ' | '.join(partes), 'success')
    else:
        flash('Personal sincronizado con RH: no habia cambios.', 'info')
    if resumen['conflictos']:
        flash('Sin tocar por apuntar a otra persona en RH (revisa su numero de '
              'empleado): ' + _resumir_nombres(resumen['conflictos']), 'warning')
    return redirect(url_for('main.manage_employees'))


@main.route('/employees')
@login_required
def manage_employees():
    if not current_user.has_admin_privileges:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    from datetime import datetime, date, time as dtime, timedelta
    from pytz import timezone, UTC
    from sqlalchemy import case, literal

    MX_TZ = timezone('America/Mexico_City')

    def to_mx(dt):
        """Convierte un datetime almacenado en UTC (naive o aware) a America/Mexico_City (aware)."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = UTC.localize(dt)  # asumimos que en BD están en UTC naive
        return dt.astimezone(MX_TZ)

    def local_midnight(dt_aware):
        """Devuelve el mismo día a las 00:00 en la misma zona (aware)."""
        return dt_aware.replace(hour=0, minute=0, second=0, microsecond=0)

    # Obtener empleados con conteo de registros y horas totales, ordenados por actividad
    sec_diff = func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time)

    employees_with_stats = (
        db.session.query(
            Employee,
            func.count(TimeRecord.id).label('record_count'),
            func.coalesce(func.sum(
                case(
                    (TimeRecord.end_time.isnot(None), sec_diff),
                    else_=literal(0)
                )
            ), 0).label('total_seconds')
        )
        .outerjoin(TimeRecord, Employee.id == TimeRecord.employee_id)
        .group_by(Employee.id)
        .order_by(func.count(TimeRecord.id).desc(), Employee.nompropio)
        .all()
    )

    # Crear lista de empleados con sus estadísticas
    employees = []
    for emp, record_count, total_seconds in employees_with_stats:
        emp.record_count = record_count
        emp.total_hours = round((total_seconds or 0) / 3600, 1)
        emp.has_activity = record_count > 0
        employees.append(emp)

    # Parámetros de filtro
    employee_id  = request.args.get('employee_id')
    period       = request.args.get('period', 'all')  # 'all' por defecto para ver todo el historial
    filter_day   = request.args.get('filter_day')   # 'YYYY-MM-DD'
    filter_week  = request.args.get('filter_week')  # 'YYYY-Www'
    filter_month = request.args.get('filter_month') # 'YYYY-MM'
    records_page = request.args.get('records_page', 1, type=int)

    # Variables para rango de fechas (None = sin filtro = todo el historial)
    start = None
    end = None
    use_date_filter = False

    # Determinar rango start-end en HORARIO DE MÉXICO y luego pasarlo a UTC (naive) para la consulta
    try:
        if period == 'day' and filter_day:
            d = datetime.strptime(filter_day, '%Y-%m-%d').date()
            start_local = MX_TZ.localize(datetime.combine(d, dtime.min))
            end_local   = start_local + timedelta(days=1)
            use_date_filter = True

        elif period == 'week' and filter_week:
            year, week_num = filter_week.split('-W')
            y, w = int(year), int(week_num)
            # Lunes de la semana ISO en fecha (sin tz)
            iso_monday = date.fromisocalendar(y, w, 1)
            start_local = MX_TZ.localize(datetime.combine(iso_monday, dtime.min))
            end_local   = start_local + timedelta(weeks=1)
            use_date_filter = True

        elif period == 'month' and filter_month:
            y, m = map(int, filter_month.split('-'))
            start_local = MX_TZ.localize(datetime(y, m, 1, 0, 0, 0))
            if m == 12:
                end_local = MX_TZ.localize(datetime(y + 1, 1, 1, 0, 0, 0))
            else:
                end_local = MX_TZ.localize(datetime(y, m + 1, 1, 0, 0, 0))
            use_date_filter = True

        # Si period == 'all' o no hay filtro específico, no aplicamos filtro de fechas
        if use_date_filter:
            # Convertir a UTC (aware) y luego a naive (lo que MySQL espera en DATETIME) para filtrar en BD
            start = start_local.astimezone(UTC).replace(tzinfo=None)
            end   = end_local.astimezone(UTC).replace(tzinfo=None)

    except ValueError:
        # En caso de parsing inválido, mostrar todo (sin filtro)
        start = None
        end = None

    selected_employee = None
    metrics = {'total': 0, 'projects': {}, 'activities': {}}
    time_records = None

    if employee_id:
        selected_employee = Employee.query.get(int(employee_id))
        if selected_employee:
            # Construir query base
            base_query = TimeRecord.query.filter(TimeRecord.employee_id == selected_employee.id)

            # Aplicar filtro de fechas solo si hay rango definido
            if start is not None and end is not None:
                base_query = base_query.filter(
                    TimeRecord.start_time >= start,
                    TimeRecord.start_time < end
                )

            # Historial de registros paginado
            time_records = (
                base_query
                .order_by(TimeRecord.start_time.desc())
                .paginate(page=records_page, per_page=25, error_out=False)
            )

            # Adjuntar horas convertidas a MX para mostrar en el template
            for r in time_records.items:
                r.start_time_mx = to_mx(r.start_time)  # aware en MX
                r.end_time_mx   = to_mx(r.end_time)    # aware en MX

            # Total de horas (usa diferencia en segundos en BD)
            sec_diff = func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time)

            # Query para total de horas
            total_query = (
                db.session.query(func.sum(sec_diff))
                .filter(
                    TimeRecord.employee_id == selected_employee.id,
                    TimeRecord.end_time.isnot(None)
                )
            )
            if start is not None and end is not None:
                total_query = total_query.filter(
                    TimeRecord.start_time >= start,
                    TimeRecord.start_time < end
                )
            total_secs = total_query.scalar() or 0
            metrics['total'] = round(total_secs / 3600, 2)

            # Horas por proyecto
            proj_query = (
                db.session.query(Project.name, func.sum(sec_diff))
                .join(Project, Project.id == TimeRecord.project_id)
                .filter(
                    TimeRecord.employee_id == selected_employee.id,
                    TimeRecord.end_time.isnot(None)
                )
            )
            if start is not None and end is not None:
                proj_query = proj_query.filter(
                    TimeRecord.start_time >= start,
                    TimeRecord.start_time < end
                )
            proj_times = proj_query.group_by(Project.name).all()
            metrics['projects'] = {p: round(s / 3600, 2) for p, s in proj_times}

            # Horas por actividad
            act_query = (
                db.session.query(TimeRecord.actividad, func.sum(sec_diff))
                .filter(
                    TimeRecord.employee_id == selected_employee.id,
                    TimeRecord.end_time.isnot(None)
                )
            )
            if start is not None and end is not None:
                act_query = act_query.filter(
                    TimeRecord.start_time >= start,
                    TimeRecord.start_time < end
                )
            act_times = act_query.group_by(TimeRecord.actividad).all()
            metrics['activities'] = {
                (a if a else 'Sin especificar'): round(s / 3600, 2)
                for a, s in act_times
            }

    return render_template(
        'employees.html',
        employees=employees,
        selected_employee=selected_employee,
        metrics=metrics,
        time_records=time_records  # usa r.start_time_mx / r.end_time_mx en el template
    )

# Las altas, bajas y ediciones de personal se hacen en el sistema de RH: aquí
# `employees` es una vista de solo lectura sobre AD17_RH y no admite escrituras.
# Por eso ya no existen las rutas /add, /employee/edit, /employee/delete ni
# /employee/toggle_active.

@main.route('/api/map_markers', methods=['GET'])
@login_required
def api_map_markers():
    """
    Devuelve puntos (marcadores) para el mapa.
    Filtros:
      - fp: folio del proyecto (exacto por defecto; usar match=prefix para prefijo)
      - project_id: alternativo a fp
      - only_active=1: sólo registros sin end_time
      - days=N: limita a los últimos N días (sobre start_time)
    """
    fp          = (request.args.get('fp') or '').strip()
    project_id  = request.args.get('project_id', type=int)
    only_active = (request.args.get('only_active', '0') == '1')
    days        = request.args.get('days', type=int)
    match_mode  = request.args.get('match', 'exact')  # 'exact' | 'prefix'

    try:
        q = (
            TimeRecord.query
            .join(Project, TimeRecord.project_id == Project.id)
            .join(Employee, TimeRecord.employee_id == Employee.id)
            .filter(
                TimeRecord.latitude.isnot(None),
                TimeRecord.longitude.isnot(None),
                TimeRecord.latitude != 0,
                TimeRecord.longitude != 0
            )
        )

        if getattr(current_user, 'is_area_manager', False):
            q = q.filter(TimeRecord.departamento == current_user.area_manager_department)

        if only_active:
            q = q.filter(TimeRecord.end_time.is_(None))

        if fp:
            if fp.isdigit():
                if match_mode == 'prefix':
                    q = q.filter(Project.folio.like(f'{fp}%'))
                else:
                    q = q.filter(Project.folio == int(fp))
            else:
                # Si el input trae algo no numérico, tratamos como prefijo
                q = q.filter(Project.folio.like(f'{fp}%'))

        if project_id:
            q = q.filter(TimeRecord.project_id == project_id)

        if days:
            since = datetime.utcnow() - timedelta(days=days)
            q = q.filter(TimeRecord.start_time >= since)

        rows = q.order_by(TimeRecord.start_time.desc()).all()

        import pytz
        utc  = pytz.UTC
        cdmx = pytz.timezone('America/Mexico_City')

        markers = []
        for r in rows:
            start_cdmx = utc.localize(r.start_time).astimezone(cdmx)
            end_str = None
            if r.end_time:
                end_str = utc.localize(r.end_time).astimezone(cdmx).strftime('%Y-%m-%d %H:%M:%S')

            markers.append({
                'lat': float(r.latitude),
                'lng': float(r.longitude),
                'employee': r.employee.nompropio,
                'project': r.project.name,
                'folio':   r.project.folio,
                'activity': r.actividad or 'Sin especificar',
                'department': r.departamento or 'N/A',
                'start_time': start_cdmx.strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': end_str,
                'active': r.end_time is None,
                'record_id': r.id
            })

        return jsonify({'success': True, 'count': len(markers), 'markers': markers})

    except Exception as e:
        current_app.logger.error(f"Error en api_map_markers: {e}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': 'Error interno'}), 500


@main.route('/capture_photo', methods=['POST'])
@csrf.exempt
def capture_photo():
    import base64
    employee_id = request.form.get('employee_id')
    photo_base64 = request.form.get('photo')
    if not employee_id or not photo_base64:
        return jsonify({'error': 'Faltan datos (employee_id o photo)'}), 400

    employee = Employee.query.get(int(employee_id))
    if not employee:
        return jsonify({'error': 'El empleado no existe'}), 404

    if 'base64,' in photo_base64:
        photo_base64 = photo_base64.split('base64,')[1]
    photo_data = base64.b64decode(photo_base64)

    base_folder_path = os.path.join(current_app.root_path, 'static', 'capture_photo')
    os.makedirs(base_folder_path, exist_ok=True)

    empleado_folder_name = employee.nompropio.strip().replace(' ', '_')
    employee_folder_path = os.path.join(base_folder_path, empleado_folder_name)
    os.makedirs(employee_folder_path, exist_ok=True)

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"foto_{timestamp_str}.png"
    file_path = os.path.join(employee_folder_path, filename)

    with open(file_path, 'wb') as f:
        f.write(photo_data)

    return jsonify({
        'message': 'Foto guardada exitosamente',
        'filename': filename,
        'folder': empleado_folder_name
    }), 200

@main.route('/map')
@login_required
def map():
    if current_user.is_employee:
        flash('Acceso denegado. La vista de mapa no está disponible para perfiles de empleado.', 'warning')
        return redirect(url_for('main.my_dashboard'))
    query = TimeRecord.query.filter(
        TimeRecord.latitude != None,
        TimeRecord.longitude != None,
        TimeRecord.latitude != 0,
        TimeRecord.longitude != 0,
        TimeRecord.end_time == None
    )

    if getattr(current_user, 'is_area_manager', False):
        query = query.filter(TimeRecord.departamento == current_user.area_manager_department)

    records = query.all()

    markers = []
    for record in records:
        markers.append({
            'lat': record.latitude,
            'lng': record.longitude,
            'employee': record.employee.nompropio,
            'start_time': record.start_time.strftime('%Y-%m-%d %H:%M:%S')
        })

    return render_template('map.html', markers=markers)

@main.route('/check_active_record')
def check_active_record():
    employee_id = request.args.get('employee_id')
    project_id = request.args.get('project_id')
    activity = request.args.get('activity')

    active_record = TimeRecord.query.filter_by(
        employee_id=employee_id,
        project_id=project_id,
        actividad=activity,
        end_time=None
    ).first()

    return jsonify({"active": bool(active_record)})
@main.route('/check_active_record_by_project/<int:employee_id>/<int:project_id>', methods=['GET'])
def check_active_record_by_project(employee_id, project_id):
    active_record = TimeRecord.query.filter_by(
        employee_id=employee_id,
        project_id=project_id,
        end_time=None
    ).first()
    return jsonify({"active": bool(active_record)})

@main.route('/finalize_active_record/<int:employee_id>/<int:project_id>', methods=['POST'])
@csrf.exempt
def finalize_active_record(employee_id, project_id):
    active_record = TimeRecord.query.filter_by(
        employee_id=employee_id,
        project_id=project_id,
        end_time=None
    ).first()
    if active_record:
        active_record.end_time = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "No se encontró registro activo."}), 404

@main.route('/projects')
def project_page():
    all_projects = Project.query.order_by(Project.id).all()
    return render_template('projects.html', all_projects=all_projects)


@main.route('/search_fp', methods=['GET'])
def search_fp():
    fp = request.args.get('fp', '').strip()
    current_app.logger.debug("search_fp: FP recibido: '%s'", fp)
    if not fp:
        current_app.logger.debug("search_fp: FP vacío")
        return jsonify({"error": "No se proporcionó un FP"}), 400

    try:
        # Primero buscar en la base de datos local
        local_projects = Project.query.filter(
            Project.folio.like(f'{fp}%')
        ).all()

        local_results = []
        for project in local_projects:
            if project.folio != 0:  # Excluir el proyecto especial
                local_results.append({
                    'fp': str(project.folio),
                    'proyecto': project.name,
                    'cliente': project.client,
                    'project_id': project.id,  # ID interno para el formulario
                    'source': 'local'
                })

        # Si hay resultados locales, devolverlos
        if local_results:
            current_app.logger.debug("search_fp: Encontrados %d proyectos locales", len(local_results))
            return jsonify(local_results)

        # Si no hay resultados locales, buscar en la base remota
        current_app.logger.debug("search_fp: Conectando a la base de datos remota...")
        remote_conn = pymysql.connect(
            host="ad17solutions.dscloud.me",
            port=3307,
            user="IvanUriel",
            password="iuOp20!!25",
            database="AD17_RH",
            cursorclass=pymysql.cursors.DictCursor
        )
        current_app.logger.debug("search_fp: Conexión establecida correctamente")
        cursor = remote_conn.cursor()

        query = """
            SELECT i.regID AS fp,
                   d.nombre AS proyecto,
                   c.nombre AS cliente
            FROM (SELECT * FROM AD17_Proyectos.ID WHERE regID LIKE %s) AS i
            LEFT JOIN (SELECT * FROM AD17_Proyectos.Datos
                       WHERE regID IN (SELECT MAX(regID) FROM AD17_Proyectos.Datos GROUP BY fp)) AS d
              ON d.fp LIKE i.regID
            LEFT JOIN (SELECT * FROM AD17_Clientes.Datos
                       WHERE regID IN (SELECT MAX(regID) FROM AD17_Clientes.Datos GROUP BY cliID)) AS c
              ON c.cliID LIKE d.cliente
            ORDER BY fp DESC;
        """
        param = fp + '%'
        current_app.logger.debug("search_fp: Ejecutando query con parámetro: '%s'", param)
        cursor.execute(query, (param,))
        remote_results = cursor.fetchall()
        current_app.logger.debug("search_fp: Query ejecutada. Resultados: %s", remote_results)
        cursor.close()
        remote_conn.close()

        # Procesar resultados remotos y crear proyectos locales si no existen
        final_results = []
        for remote_project in remote_results:
            fp_value = str(remote_project['fp'])
            project_name = remote_project['proyecto'] or f"Proyecto {fp_value}"
            client_name = remote_project['cliente'] or "Cliente desconocido"

            # Verificar si ya existe localmente por folio
            existing_project = Project.query.filter_by(folio=int(fp_value)).first()

            if not existing_project:
                # Verificar si existe un proyecto con el mismo nombre
                existing_by_name = Project.query.filter_by(name=project_name).first()

                if existing_by_name:
                    # Si existe un proyecto con el mismo nombre, modificar el nombre para hacerlo único
                    unique_name = f"{project_name} (FP: {fp_value})"
                    current_app.logger.debug("search_fp: Proyecto con nombre duplicado, usando: %s", unique_name)
                else:
                    unique_name = project_name

                try:
                    # Crear el proyecto localmente
                    new_project = Project(
                        folio=int(fp_value),
                        name=unique_name,
                        client=client_name,
                        active=True,
                        delivery_date=None
                    )
                    db.session.add(new_project)
                    db.session.commit()
                    project_id = new_project.id
                    current_app.logger.debug("search_fp: Creado proyecto local con ID %d", project_id)
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error("search_fp: Error creando proyecto: %s", str(e))
                    # Si aún hay error, intentar con un nombre más único
                    try:
                        unique_name = f"FP-{fp_value}-{project_name}-{client_name}"[:200]  # Limitar longitud
                        new_project = Project(
                            folio=int(fp_value),
                            name=unique_name,
                            client=client_name,
                            active=True,
                            delivery_date=None
                        )
                        db.session.add(new_project)
                        db.session.commit()
                        project_id = new_project.id
                        current_app.logger.debug("search_fp: Creado proyecto con nombre alternativo con ID %d", project_id)
                    except Exception as e2:
                        db.session.rollback()
                        current_app.logger.error("search_fp: Error fatal creando proyecto: %s", str(e2))
                        continue  # Saltar este proyecto si no se puede crear
            else:
                project_id = existing_project.id
                unique_name = existing_project.name
                current_app.logger.debug("search_fp: Proyecto ya existía con ID %d", project_id)

            final_results.append({
                'fp': fp_value,
                'proyecto': unique_name,  # Usar el nombre único/existente
                'cliente': client_name,
                'project_id': project_id,  # ID interno para el formulario
                'source': 'remote'
            })

        current_app.logger.debug("search_fp: Conexión cerrada. Retornando %d datos.", len(final_results))
        return jsonify(final_results)

    except Exception as e:
        current_app.logger.error("Error en search_fp: %s", str(e))
        return jsonify({"error": "Error interno en la búsqueda"}), 500
from flask import jsonify

@main.route('/finalize_time_record/<int:record_id>', methods=['POST'])
@csrf.exempt

def finalize_time_record(record_id):

    """
    Finaliza un registro de tiempo concreto por su ID.
    """
    rec = TimeRecord.query.get_or_404(record_id)
    if rec.end_time is not None:
        return jsonify({'success': False, 'message': 'Registro ya está finalizado.'})
    rec.end_time = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})

@main.route('/finalize_all_for_project/<int:employee_id>/<int:project_id>', methods=['POST'])
@csrf.exempt

def finalize_all_for_project(employee_id, project_id):
    """
    (Opcional) Cierra *todos* los registros activos de un proyecto dado.
    """
    recs = TimeRecord.query.filter_by(
        employee_id=employee_id,
        project_id=project_id,
        end_time=None
    ).all()
    for r in recs:
        r.end_time = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})

@main.route('/api/project_data/<int:project_id>')
@login_required
def get_project_data(project_id):
    """
    Esta es la nueva ruta de API que solo devuelve los datos del proyecto en formato JSON.
    """
    project = Project.query.get_or_404(project_id)

    # Preparamos la estructura de la respuesta
    response_data = {
        'time_by_worker': {},
        'time_by_dept': {},
        'time_by_activity': {}
    }

    records = db.session.query(
        TimeRecord,
        Employee.nombre,
        Employee.apellido_paterno
    ).join(Employee, TimeRecord.employee_id == Employee.id)\
     .filter(
        TimeRecord.project_id == project.id,
        TimeRecord.end_time != None
    ).all()

    if not records:
        return jsonify(response_data) # Devuelve datos vacíos si no hay registros

    # Usamos diccionarios temporales para sumar segundos
    worker_seconds = {}
    dept_seconds = {}
    activity_seconds = {}

    for record, nombre, paterno in records:
        duration_seconds = (record.end_time - record.start_time).total_seconds()

        worker_name = f"{nombre} {paterno}"
        worker_seconds[worker_name] = worker_seconds.get(worker_name, 0) + duration_seconds

        dept_name = record.departamento or 'No especificado'
        dept_seconds[dept_name] = dept_seconds.get(dept_name, 0) + duration_seconds

        activity_name = record.actividad or 'No especificada'
        activity_seconds[activity_name] = activity_seconds.get(activity_name, 0) + duration_seconds

    # Convertimos segundos a horas redondeadas para la respuesta final
    response_data['time_by_worker'] = {k: round(v / 3600.0, 2) for k, v in worker_seconds.items()}
    response_data['time_by_dept'] = {k: round(v / 3600.0, 2) for k, v in dept_seconds.items()}
    response_data['time_by_activity'] = {k: round(v / 3600.0, 2) for k, v in activity_seconds.items()}

    return jsonify(response_data)

# project_analysis en routes.py
# En routes.py
@main.route('/project_analysis', methods=['GET'])
@login_required
def project_analysis():
    if not current_user.has_admin_privileges:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    search_term = request.args.get('project_search', '')
    selected_project = None

    if search_term:
        if search_term.isdigit():
            selected_project = Project.query.get(int(search_term))
        if not selected_project:
            search_like = f"%{search_term}%"
            selected_project = Project.query.filter(
                (Project.name.ilike(search_like)) | (Project.folio.ilike(search_like))
            ).first()

    all_projects = Project.query.order_by(Project.name).all()

    analysis_data = {
        'total_hours': 0, 'num_participants': 0, 'start_date': None,
        'end_date': None, 'duration_days': 0
    }
    time_records = []
    time_by_worker = {}
    time_by_dept = {}
    time_by_activity = {}

    if selected_project:
        finalized_records = db.session.query(
            TimeRecord,
            Employee.nombre,
            Employee.apellido_paterno
        ).join(Employee, TimeRecord.employee_id == Employee.id)\
         .filter(
            TimeRecord.project_id == selected_project.id,
            TimeRecord.end_time != None
        ).all()

        time_records = TimeRecord.query.filter_by(project_id=selected_project.id)\
                                     .order_by(TimeRecord.start_time.desc()).all()

        if finalized_records:
            total_seconds = 0

            # ===== CORRECCIÓN DEFINITIVA AQUÍ =====
            min_start = min(r.start_time for r, _, _ in finalized_records)
            max_end = max(r.end_time for r, _, _ in finalized_records)
            # ======================================

            analysis_data['start_date'] = min_start.strftime('%d/%m/%Y')
            analysis_data['end_date'] = max_end.strftime('%d/%m/%Y')
            analysis_data['duration_days'] = (max_end.date() - min_start.date()).days + 1

            for record_obj, nombre, paterno in finalized_records:
                duration_hours = (record_obj.end_time - record_obj.start_time).total_seconds() / 3600.0
                total_seconds += (duration_hours * 3600.0)

                worker_name = f"{nombre} {paterno}"
                time_by_worker[worker_name] = time_by_worker.get(worker_name, 0) + duration_hours

                dept_name = record_obj.departamento or 'No especificado'
                time_by_dept[dept_name] = time_by_dept.get(dept_name, 0) + duration_hours

                activity_name = record_obj.actividad or 'No especificada'
                time_by_activity[activity_name] = time_by_activity.get(activity_name, 0) + duration_hours

            analysis_data['total_hours'] = round(total_seconds / 3600.0, 2)
            analysis_data['num_participants'] = len(time_by_worker)

            time_by_worker = {k: round(v, 2) for k, v in time_by_worker.items()}
            time_by_dept = {k: round(v, 2) for k, v in time_by_dept.items()}
            time_by_activity = {k: round(v, 2) for k, v in time_by_activity.items()}

    return render_template(
        'project_analysis.html',
        all_projects=all_projects,
        selected_project=selected_project,
        time_records=time_records,
        analysis_data=analysis_data,
        search_term=search_term,
        time_by_worker=time_by_worker,
        time_by_dept=time_by_dept,
        time_by_activity=time_by_activity
    )

@main.route('/my_dashboard')
@login_required
def my_dashboard():
    # Panel personal disponible para usuarios autenticados con un empleado asignado
    if not current_user.employee_id:
        flash('Panel disponible solo para usuarios con perfil de empleado asignado.', 'warning')
        return redirect(url_for('main.home'))

    employee = Employee.query.get_or_404(current_user.employee_id)

    # ── 1. Filtros ────────────────────────────────────────────────────────
    project_filter = request.args.get('project_id', type=int)
    department_filter = request.args.get('department', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 25

    query = (
        TimeRecord.query
        .join(Project, TimeRecord.project_id == Project.id)
        .filter(TimeRecord.employee_id == employee.id)
    )

    if project_filter:
        query = query.filter(TimeRecord.project_id == project_filter)
    if department_filter:
        query = query.filter(TimeRecord.departamento == department_filter)

    if date_from:
        try:
            start_local = datetime.strptime(date_from, '%Y-%m-%d')
            start_utc = pytz.timezone('America/Mexico_City').localize(start_local).astimezone(pytz.UTC).replace(tzinfo=None)
            query = query.filter(TimeRecord.start_time >= start_utc)
        except ValueError:
            flash('Fecha de inicio inválida.', 'warning')

    if date_to:
        try:
            end_local = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            end_utc = pytz.timezone('America/Mexico_City').localize(end_local).astimezone(pytz.UTC).replace(tzinfo=None)
            query = query.filter(TimeRecord.start_time < end_utc)
        except ValueError:
            flash('Fecha fin inválida.', 'warning')

    # ── 2. Consulta Paginada ────────────────────────────────────────────────
    records = (
        query
        .order_by(TimeRecord.start_time.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    for record in records.items:
        record.start_time_mx = _to_mx(record.start_time)
        record.end_time_mx = _to_mx(record.end_time)

    # ── 3. Cálculo de Totales ───────────────────────────────────────────────
    filtered_records_all = query.all()
    total_seconds = 0
    active_count = 0
    for r in filtered_records_all:
        if r.end_time and r.start_time:
            total_seconds += (r.end_time - r.start_time).total_seconds()
        elif not r.end_time:
            active_count += 1

    total_hours = round(total_seconds / 3600, 2)

    # Listas para los dropdowns de filtrado del empleado
    employee_projects = (
        db.session.query(Project)
        .join(TimeRecord, TimeRecord.project_id == Project.id)
        .filter(TimeRecord.employee_id == employee.id)
        .distinct()
        .order_by(Project.name)
        .all()
    )

    employee_departments = [
        dept for (dept,) in
        db.session.query(TimeRecord.departamento)
        .filter(TimeRecord.employee_id == employee.id)
        .distinct()
        .order_by(TimeRecord.departamento)
        .all()
        if dept
    ]

    filters = {
        'project_id': project_filter,
        'department': department_filter,
        'date_from': date_from,
        'date_to': date_to
    }

    return render_template(
        'employee_dashboard.html',
        employee=employee,
        records=records,
        total_hours=total_hours,
        active_count=active_count,
        employee_projects=employee_projects,
        employee_departments=employee_departments,
        filters=filters
    )

# =========================================================================
# Adicionales del empleado (BD remota AD17_Adicionales)
# =========================================================================
def _adicionales_conn():
    """Conexión a la BD remota de adicionales (credenciales configurables)."""
    cfg = current_app.config
    return pymysql.connect(
        host=cfg.get('ADICIONALES_DB_HOST', 'ad17solutions.dscloud.me'),
        port=int(cfg.get('ADICIONALES_DB_PORT', 3307)),
        user=cfg.get('ADICIONALES_DB_USER', 'IvanUriel'),
        password=cfg.get('ADICIONALES_DB_PASSWORD', 'iuOp20!!25'),
        database=cfg.get('ADICIONALES_DB_NAME', 'AD17_Adicionales'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=25
    )


def _fetch_adicionales_empleado(rh_id):
    """Ejecuta sp_adicionales_empleado en la BD remota AD17_Adicionales."""
    conn = _adicionales_conn()
    try:
        cursor = conn.cursor()
        cursor.callproc('sp_adicionales_empleado', (rh_id,))
        rows = cursor.fetchall() or []
        # Los SP dejan result sets pendientes; se drenan para liberar la conexión
        while cursor.nextset():
            pass
        cursor.close()
        return rows
    finally:
        conn.close()


def _serialize_adicional(row):
    """Normaliza una fila del SP al formato que consume el calendario."""
    def _fecha(valor):
        if not valor:
            return None
        if hasattr(valor, 'strftime'):
            return valor.strftime('%Y-%m-%d')
        return str(valor)[:10]

    def _num(valor):
        try:
            return float(valor)
        except (TypeError, ValueError):
            return 0.0

    return {
        'id': row.get('regID'),
        'fecha': _fecha(row.get('fecha')),
        'fecha_pago': _fecha(row.get('fecha_pago')),
        'cantidad': _num(row.get('cantidad')),
        'costo': _num(row.get('costo')),
        'estatus': (row.get('estatus_pago') or 'PENDIENTE').strip().upper()
    }


@main.route('/mis-adicionales')
@login_required
def my_adicionales():
    """Calendario mensual de adicionales autorizados — vista pensada para celular."""
    if not current_user.employee_id:
        flash('Vista disponible solo para usuarios con perfil de empleado asignado.', 'warning')
        return redirect(url_for('main.home'))

    employee = Employee.query.get_or_404(current_user.employee_id)

    # El SP recibe el rhID, que corresponde al n_empleado de la base local
    try:
        rh_id = int(str(employee.n_empleado).strip())
    except (TypeError, ValueError):
        rh_id = None

    adicionales = []
    load_error = None

    if rh_id is None:
        load_error = 'Tu número de empleado no es válido para consultar adicionales.'
    else:
        try:
            adicionales = [_serialize_adicional(r) for r in _fetch_adicionales_empleado(rh_id)]
        except Exception as e:
            current_app.logger.error("my_adicionales: error consultando AD17_Adicionales: %s", e)
            load_error = 'No fue posible consultar tus adicionales en este momento. Intenta de nuevo más tarde.'

    adicionales = sorted((a for a in adicionales if a['fecha']), key=lambda a: a['fecha'])

    hoy_mx = datetime.now(timezone('America/Mexico_City')).date()

    return render_template(
        'employee_adicionales.html',
        employee=employee,
        adicionales=adicionales,
        load_error=load_error,
        today=hoy_mx.strftime('%Y-%m-%d')
    )


# -------------------------------------------------------------------------
# Calendario global de adicionales (consulta para administradores)
# -------------------------------------------------------------------------
# Subconsulta reutilizable con el último registro de datos de cada empleado
_SQL_NOMBRES_RH = """
    (SELECT rhID, nombre, paterno, materno FROM AD17_RH.Datos
      WHERE regID IN (SELECT MAX(regID) FROM AD17_RH.Datos GROUP BY rhID))
"""


def _estatus_adicional(row):
    if not row.get('estatus_validacion'):
        return 'CANCELADO'
    return 'PAGADO' if row.get('pagado') else 'PENDIENTE'


def _serialize_adicional_admin(row):
    """Normaliza una fila de la tabla adicionales para el calendario administrativo."""
    def _fecha(valor):
        if not valor:
            return None
        return valor.strftime('%Y-%m-%d') if hasattr(valor, 'strftime') else str(valor)[:10]

    def _num(valor):
        try:
            return float(valor)
        except (TypeError, ValueError):
            return 0.0

    return {
        'id': row.get('regID'),
        'rh_id': row.get('rhID'),
        'empleado': (row.get('empleado') or '').strip() or 'RH %s' % row.get('rhID'),
        'fecha': _fecha(row.get('fecha')),
        'fecha_pago': _fecha(row.get('fecha_pago')),
        'tipo': row.get('tipo') or 'TIEMPO',
        'area_id': row.get('area'),
        'area': row.get('area_nombre') or '—',
        'cantidad': _num(row.get('cantidad')),
        'costo_unit': _num(row.get('costo_unit')),
        'costo': _num(row.get('costo')),
        'nota': row.get('nota') or '',
        'estatus': _estatus_adicional(row),
        'proyectos': []
    }


def _adicionales_catalogos():
    """Empleados vigentes (con su costo de adicional) y catálogo de áreas."""
    conn = _adicionales_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id AS rh_id, nomPropio AS nombre, id_area AS area_id,
                       titulo_area AS area, adicional AS costo_unit
                  FROM AD17_RH.empleados_activos
                 ORDER BY nomPropio
            """)
            empleados = [{
                'rh_id': r['rh_id'],
                'nombre': (r['nombre'] or '').strip() or 'RH %s' % r['rh_id'],
                'area_id': r['area_id'],
                'area': r['area'] or '',
                'costo_unit': float(r['costo_unit'] or 0)
            } for r in cur.fetchall()]

            cur.execute("SELECT regID AS id, area FROM AD17_General.Areas ORDER BY area")
            areas = [{'id': r['id'], 'nombre': r['area']} for r in cur.fetchall()]
    finally:
        conn.close()
    return empleados, areas


def _adicionales_rango(desde, hasta, alcance, area=None, rh_id=None, estatus=None):
    """
    Adicionales (con empleado, área y proyectos) dentro de un rango de fechas,
    limitados y enmascarados según el alcance del usuario.
    """
    sql = """
        SELECT a.regID, a.rhID, a.fecha, a.tipo, a.area, a.cantidad, a.nota,
               a.costo_unit, a.costo, a.fecha_pago, a.estatus_validacion, a.pagado,
               ar.area AS area_nombre,
               TRIM(CONCAT(COALESCE(d.nombre,''),' ',COALESCE(d.paterno,''),' ',COALESCE(d.materno,''))) AS empleado
          FROM adicionales a
          LEFT JOIN AD17_General.Areas ar ON ar.regID = a.area
          LEFT JOIN %s AS d ON d.rhID = a.rhID
         WHERE a.fecha BETWEEN %%s AND %%s
    """ % _SQL_NOMBRES_RH
    params = [desde, hasta]

    # Alcance: los jefes de área solo ven lo de su área y lo propio
    if not alcance.get('total'):
        condiciones = []
        if alcance.get('area_id'):
            condiciones.append('a.area = %s')
            params.append(alcance['area_id'])
        if alcance.get('rh_id'):
            condiciones.append('a.rhID = %s')
            params.append(alcance['rh_id'])
        if not condiciones:
            return []
        sql += " AND (%s)" % ' OR '.join(condiciones)

    if area:
        sql += " AND a.area = %s"
        params.append(area)
    if rh_id:
        sql += " AND a.rhID = %s"
        params.append(rh_id)
    if estatus == 'PENDIENTE':
        sql += " AND a.estatus_validacion = 1 AND a.pagado = 0"
    elif estatus == 'PAGADO':
        sql += " AND a.estatus_validacion = 1 AND a.pagado = 1"
    elif estatus == 'CANCELADO':
        sql += " AND a.estatus_validacion = 0"

    sql += " ORDER BY a.fecha, empleado"

    conn = _adicionales_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            registros = [_serialize_adicional_admin(r) for r in cur.fetchall()]

            if registros:
                ids = [r['id'] for r in registros]
                marcadores = ','.join(['%s'] * len(ids))
                cur.execute(
                    "SELECT adID, fp, porcentaje FROM ad_proyecto WHERE adID IN (%s) ORDER BY porcentaje DESC" % marcadores,
                    ids
                )
                por_adicional = {}
                for p in cur.fetchall():
                    por_adicional.setdefault(p['adID'], []).append({
                        'fp': p['fp'],
                        'porcentaje': round(float(p['porcentaje'] or 0) * 100, 2)
                    })
                for r in registros:
                    r['proyectos'] = por_adicional.get(r['id'], [])
    finally:
        conn.close()

    # El costo de los adicionales ajenos se oculta desde el servidor,
    # de modo que tampoco viaje en la respuesta JSON
    if not alcance.get('total'):
        propio = alcance.get('rh_id')
        for r in registros:
            if propio is None or r['rh_id'] != propio:
                r['costo'] = None
                r['costo_unit'] = None

    return registros


# Los nombres de área locales no siempre coinciden con los de AD17_General.Areas
_ALIAS_AREAS = {'stagging': 'staging'}


def _clave_area(nombre):
    """Normaliza un nombre de área para poder compararlo entre bases."""
    limpio = ''.join(
        c for c in unicodedata.normalize('NFD', nombre or '')
        if unicodedata.category(c) != 'Mn'
    ).strip().lower()
    return _ALIAS_AREAS.get(limpio, limpio)


def _area_id_por_nombre(nombre, areas):
    clave = _clave_area(nombre)
    if not clave:
        return None
    for a in areas:
        if _clave_area(a['nombre']) == clave:
            return a['id']
    return None


def _puede_ver_adicionales():
    return bool(
        current_user.is_admin
        or current_user.is_project_leader
        or getattr(current_user, 'is_area_manager', False)
    )


def _alcance_adicionales(areas):
    """
    Define qué adicionales puede ver el usuario:
      · Administradores y líderes de proyecto: todo el personal, con costos.
      · Jefes de área: los de su área (sin costo) y los propios (con costo).
    """
    if current_user.is_admin or current_user.is_project_leader:
        return {'total': True, 'area_id': None, 'rh_id': None, 'area_nombre': None}

    area_id = _area_id_por_nombre(current_user.area_manager_department, areas)

    rh_id = None
    if current_user.employee_id:
        empleado = db.session.get(Employee, current_user.employee_id)
        if empleado:
            try:
                rh_id = int(str(empleado.n_empleado).strip())
            except (TypeError, ValueError):
                rh_id = None

    return {
        'total': False,
        'area_id': area_id,
        'rh_id': rh_id,
        'area_nombre': current_user.area_manager_department
    }


def _bloquear_sin_acceso_adicionales():
    if not _puede_ver_adicionales():
        flash('Acceso denegado. No tienes permiso para consultar los adicionales.', 'danger')
        return redirect(url_for('main.home'))
    return None


def _mes_solicitado():
    """Año y mes de la vista (por querystring, con el mes actual como default)."""
    hoy = datetime.now(timezone('America/Mexico_City')).date()
    year = request.args.get('year', type=int) or hoy.year
    month = request.args.get('month', type=int) or hoy.month
    if not 1 <= month <= 12:
        month = hoy.month
    return year, month


def _filtros_adicionales():
    return {
        'area': request.args.get('area', type=int),
        'rh_id': request.args.get('rh_id', type=int),
        'estatus': (request.args.get('estatus') or '').strip().upper() or None
    }


@main.route('/adicionales')
@login_required
def adicionales_admin():
    """
    Calendario de adicionales. Administradores y líderes de proyecto ven a todo el
    personal; los jefes de área ven su área (sin costos) más los propios (con costo).
    """
    bloqueo = _bloquear_sin_acceso_adicionales()
    if bloqueo:
        return bloqueo

    year, month = _mes_solicitado()
    filtros = _filtros_adicionales()
    desde = datetime(year, month, 1).date()
    hasta = (desde + relativedelta(months=1)) - timedelta(days=1)

    registros, empleados, areas, error = [], [], [], None
    alcance = {'total': True, 'area_id': None, 'rh_id': None, 'area_nombre': None}
    try:
        empleados, areas = _adicionales_catalogos()
        alcance = _alcance_adicionales(areas)
        registros = _adicionales_rango(desde, hasta, alcance, **filtros)
    except Exception as e:
        current_app.logger.error("adicionales_admin: %s", e)
        error = 'No fue posible consultar la base de adicionales en este momento.'

    if not alcance['total']:
        # El listado de empleados se acota a su área (más él mismo)
        empleados = [
            e for e in empleados
            if e['area_id'] == alcance['area_id'] or e['rh_id'] == alcance['rh_id']
        ]
        if alcance['area_id'] is None and alcance['rh_id'] is None and not error:
            error = ('Tu usuario no tiene un área que coincida con el catálogo de adicionales, '
                     'ni un empleado asignado, por lo que no hay registros que mostrar.')

    hoy = datetime.now(timezone('America/Mexico_City')).date()

    return render_template(
        'adicionales_admin.html',
        registros=registros,
        empleados=empleados,
        areas=areas,
        filtros=filtros,
        alcance=alcance,
        year=year,
        month=month,
        today=hoy.strftime('%Y-%m-%d'),
        load_error=error
    )


@main.route('/adicionales/data')
@login_required
def adicionales_data():
    """Datos de un mes para la navegación del calendario."""
    if not _puede_ver_adicionales():
        return jsonify({'error': 'No autorizado'}), 403

    year, month = _mes_solicitado()
    desde = datetime(year, month, 1).date()
    hasta = (desde + relativedelta(months=1)) - timedelta(days=1)
    try:
        _, areas = _adicionales_catalogos()
        alcance = _alcance_adicionales(areas)
        registros = _adicionales_rango(desde, hasta, alcance, **_filtros_adicionales())
    except Exception as e:
        current_app.logger.error("adicionales_data: %s", e)
        return jsonify({'error': 'No fue posible consultar los adicionales.'}), 500

    return jsonify({'year': year, 'month': month, 'registros': registros})


@main.route('/costs')
@login_required
def costs_dashboard():
    """Dashboard principal de costos - solo administradores"""
    if not current_user.is_admin:
        flash('Acceso denegado. Solo administradores pueden acceder a esta sección.', 'danger')
        return redirect(url_for('main.home'))

    # Parámetros de filtro
    project_filter    = request.args.get('project_id', type=int)
    employee_filter   = request.args.get('employee_id', type=int)
    department_filter = request.args.get('department')
    search_filter     = request.args.get('search', '').strip()
    date_from         = request.args.get('date_from')
    date_to           = request.args.get('date_to')

    # duration_filter puede llegar como lista (select2) o simple
    duration_filters = set(
        request.args.getlist('duration_filter') +
        request.args.getlist('duration_filter[]')
    )
    _raw = request.args.get('duration_filter')
    if _raw and not duration_filters:
        duration_filters = {_raw}

    page     = request.args.get('page', 1, type=int)
    per_page = 25

    # Query base
    query = (
        TimeRecord.query
        .join(Employee, TimeRecord.employee_id == Employee.id)
        .join(Project,  TimeRecord.project_id  == Project.id)
    )

    # Filtros básicos
    if project_filter:
        query = query.filter(TimeRecord.project_id == project_filter)

    if employee_filter:
        query = query.filter(TimeRecord.employee_id == employee_filter)

    if department_filter:
        query = query.filter(TimeRecord.departamento == department_filter)

    if search_filter:
        search_like = f'%{search_filter}%'
        query = query.filter(
            db.or_(
                Project.folio.like(search_like),
                Project.name.like(search_like),
                TimeRecord.departamento.like(search_like),
                Employee.nompropio.like(search_like),
                Employee.nombre.like(search_like),
                Employee.apellido_paterno.like(search_like)
            )
        )

    # Rango de fechas sobre start_time (UTC almacenado)
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(TimeRecord.start_time >= date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(TimeRecord.start_time < date_to_obj)
        except ValueError:
            pass

    # ── Filtros de duración (independientes; si vienen varios, se intersectan) ──
    from sqlalchemy import text

    if duration_filters:
        if 'active' in duration_filters:
            query = query.filter(TimeRecord.end_time.is_(None))

        if '0-15min' in duration_filters:
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) <= 900
            )

        if '15-60min' in duration_filters:
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) > 900,
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) <= 3600
            )

        if '1-4h' in duration_filters:
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) > 3600,
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) <= 14400
            )

        if '4-10h' in duration_filters:
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) > 14400,
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) <= 36000
            )

        if '10h+' in duration_filters:
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time) > 36000
            )

        if '1day+' in duration_filters:
            # ✅ CDMX sin depender de CONVERT_TZ: desplaza -6h y compara DATE
            query = query.filter(
                TimeRecord.end_time.isnot(None),
                func.date(func.date_add(TimeRecord.start_time, text('INTERVAL -6 HOUR'))) !=
                func.date(func.date_add(TimeRecord.end_time,   text('INTERVAL -6 HOUR')))
            )

    # Orden y paginación
    query = query.order_by(TimeRecord.start_time.desc())
    records = query.paginate(page=page, per_page=per_page, error_out=False)

    # Conversión a CDMX para mostrar
    import pytz
    cdmx_tz = pytz.timezone('America/Mexico_City')
    utc_tz  = pytz.UTC

    for record in records.items:
        if record.start_time:
            record.start_time_cdmx = utc_tz.localize(record.start_time).astimezone(cdmx_tz)
        if record.end_time:
            record.end_time_cdmx   = utc_tz.localize(record.end_time).astimezone(cdmx_tz)
        else:
            record.end_time_cdmx = None

    # Empleados únicos (por nompropio)
    unique_employees_subquery = (
        db.session.query(
            Employee.nompropio,
            func.min(Employee.id).label('min_id')
        )
        .group_by(Employee.nompropio)
        .subquery()
    )

    employees = (
        db.session.query(Employee)
        .join(
            unique_employees_subquery,
            db.and_(
                Employee.nompropio == unique_employees_subquery.c.nompropio,
                Employee.id == unique_employees_subquery.c.min_id
            )
        )
        .order_by(Employee.nompropio)
        .all()
    )

    projects = Project.query.order_by(Project.name).all()

    # Estadísticas
    total_records = query.count()
    total_time_query = query.filter(TimeRecord.end_time.isnot(None))
    total_seconds = db.session.query(
        func.sum(
            func.timestampdiff(text('SECOND'), TimeRecord.start_time, TimeRecord.end_time)
        )
    ).filter(
        TimeRecord.id.in_(total_time_query.with_entities(TimeRecord.id))
    ).scalar() or 0
    total_hours = round(total_seconds / 3600, 2)

    return render_template(
        'costs/dashboard.html',
        records=records,
        projects=projects,
        employees=employees,
        total_records=total_records,
        total_hours=total_hours,
        filters={
            'project_id': project_filter,
            'employee_id': employee_filter,
            'department': department_filter,
            'search': search_filter,
            'date_from': date_from,
            'date_to': date_to,
            'duration_filter': list(duration_filters)
        }
    )



@main.route('/costs/create', methods=['GET', 'POST'])
@login_required
def create_time_record():
    """Crear un nuevo registro de tiempo"""
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        try:
            employee_id = request.form.get('employee_id', type=int)
            project_id = request.form.get('project_id', type=int)
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            departamento = request.form.get('departamento')
            actividad = request.form.get('actividad')

            # Validaciones
            if not all([employee_id, project_id, start_time, departamento]):
                flash('Todos los campos obligatorios deben ser completados.', 'danger')
                return redirect(url_for('main.create_time_record'))

            # Validar que el empleado esté activo
            emp = Employee.query.get(employee_id)
            if not emp or not emp.active:
                flash('El empleado seleccionado está deshabilitado.', 'danger')
                return redirect(url_for('main.create_time_record'))

            # Convertir fechas (restar 6 horas para convertir CDMX a UTC)
            start_time_cdmx = datetime.strptime(start_time, '%Y-%m-%dT%H:%M')
            start_time_utc = start_time_cdmx + timedelta(hours=6)  # CDMX a UTC

            end_time_utc = None
            if end_time:
                end_time_cdmx = datetime.strptime(end_time, '%Y-%m-%dT%H:%M')
                end_time_utc = end_time_cdmx + timedelta(hours=6)  # CDMX a UTC

                if end_time_utc <= start_time_utc:
                    flash('La hora de fin debe ser posterior a la hora de inicio.', 'danger')
                    return redirect(url_for('main.create_time_record'))

            # Crear registro
            new_record = TimeRecord(
                employee_id=employee_id,
                project_id=project_id,
                start_time=start_time_utc,
                end_time=end_time_utc,
                departamento=departamento,
                actividad=actividad or None,
                latitude=None,
                longitude=None
            )

            db.session.add(new_record)
            db.session.commit()

            flash('Registro de tiempo creado exitosamente.', 'success')
            return redirect(url_for('main.costs_dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creando registro: {e}")
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            if _rechazado_por_analitica(e):
                flash(
                    'No se pudo crear el registro: el modulo de analitica de '
                    'Impresion rechazo el alta. Los datos capturados son validos; '
                    'reportalo a Sistemas para que lo corrijan en la base.',
                    'danger')
            else:
                flash('Error al crear el registro. Verifica los datos ingresados.', 'danger')

    # GET request - CAMBIO: Usar empleados únicos
    unique_employees_subquery = (
        db.session.query(
            Employee.nompropio,
            func.min(Employee.id).label('min_id')
        )
        .group_by(Employee.nompropio)
        .subquery()
    )

    employees = (
        db.session.query(Employee)
        .join(
            unique_employees_subquery,
            db.and_(
                Employee.nompropio == unique_employees_subquery.c.nompropio,
                Employee.id == unique_employees_subquery.c.min_id
            )
        )
        .filter(Employee.active == True)
        .order_by(Employee.nompropio)
        .all()
    )

    projects = Project.query.filter_by(active=True).order_by(Project.name).all()

    return render_template('costs/create.html', employees=employees, projects=projects)

@main.route('/costs/edit/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_time_record(record_id):
    """Editar un registro de tiempo existente"""
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    record = TimeRecord.query.get_or_404(record_id)

    # Zona horaria CDMX
    import pytz
    cdmx_tz = pytz.timezone('America/Mexico_City')
    utc_tz = pytz.UTC

    # Convertir tiempos UTC a CDMX para mostrar en el formulario
    start_time_utc = utc_tz.localize(record.start_time)
    start_time_cdmx = start_time_utc.astimezone(cdmx_tz)
    record.start_time_cdmx = start_time_cdmx.strftime('%Y-%m-%dT%H:%M')

    if record.end_time:
        end_time_utc = utc_tz.localize(record.end_time)
        end_time_cdmx = end_time_utc.astimezone(cdmx_tz)
        record.end_time_cdmx = end_time_cdmx.strftime('%Y-%m-%dT%H:%M')
    else:
        record.end_time_cdmx = None

    if request.method == 'POST':
        try:
            employee_id = request.form.get('employee_id', type=int)
            project_id = request.form.get('project_id', type=int)
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            departamento = request.form.get('departamento')
            actividad = request.form.get('actividad')

            # Validaciones
            if not all([employee_id, project_id, start_time, departamento]):
                flash('Todos los campos obligatorios deben ser completados.', 'danger')
                return redirect(url_for('main.edit_time_record', record_id=record_id))

            # Validar que el empleado esté activo o sea el mismo del registro original
            emp = Employee.query.get(employee_id)
            if not emp or (not emp.active and employee_id != record.employee_id):
                flash('El empleado seleccionado está deshabilitado.', 'danger')
                return redirect(url_for('main.edit_time_record', record_id=record_id))

            # Convertir fechas de CDMX a UTC
            start_time_naive = datetime.strptime(start_time, '%Y-%m-%dT%H:%M')
            start_time_cdmx = cdmx_tz.localize(start_time_naive)
            start_time_utc = start_time_cdmx.astimezone(pytz.UTC).replace(tzinfo=None)

            end_time_utc = None
            if end_time:
                end_time_naive = datetime.strptime(end_time, '%Y-%m-%dT%H:%M')
                end_time_cdmx = cdmx_tz.localize(end_time_naive)
                end_time_utc = end_time_cdmx.astimezone(pytz.UTC).replace(tzinfo=None)

                if end_time_utc <= start_time_utc:
                    flash('La hora de fin debe ser posterior a la hora de inicio.', 'danger')
                    return redirect(url_for('main.edit_time_record', record_id=record_id))

            # Actualizar registro
            record.employee_id = employee_id
            record.project_id = project_id
            record.start_time = start_time_utc
            record.end_time = end_time_utc
            record.departamento = departamento
            record.actividad = actividad or None

            db.session.commit()

            flash('Registro actualizado exitosamente.', 'success')
            return redirect(url_for('main.costs_dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error editando registro {record_id}: {e}")
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            if _rechazado_por_analitica(e):
                flash(
                    f'No se pudo guardar el registro #{record_id}: el modulo de '
                    'analitica de Impresion rechazo el cambio de fecha o de empleado. '
                    'El registro quedo tal como estaba, no se perdio nada. Reporta '
                    'este ID a Sistemas para que lo corrijan en la base.',
                    'danger')
            else:
                flash('Error al actualizar el registro. Verifica los datos ingresados.', 'danger')

    # GET request - CAMBIO: Usar empleados únicos
    unique_employees_subquery = (
        db.session.query(
            Employee.nompropio,
            func.min(Employee.id).label('min_id')
        )
        .group_by(Employee.nompropio)
        .subquery()
    )

    employees = (
        db.session.query(Employee)
        .join(
            unique_employees_subquery,
            db.and_(
                Employee.nompropio == unique_employees_subquery.c.nompropio,
                Employee.id == unique_employees_subquery.c.min_id
            )
        )
        .filter(db.or_(Employee.active == True, Employee.id == record.employee_id))
        .order_by(Employee.nompropio)
        .all()
    )

    projects = Project.query.order_by(Project.name).all()

    return render_template('costs/edit.html', record=record, employees=employees, projects=projects)

# FUNCIÓN HELPER: Para reutilizar en múltiples lugares
def get_unique_employees(active_only=False):
    """
    Función helper para obtener empleados únicos por nompropio.
    Útil para reutilizar en múltiples vistas.
    """
    unique_employees_subquery = (
        db.session.query(
            Employee.nompropio,
            func.min(Employee.id).label('min_id')
        )
        .group_by(Employee.nompropio)
        .subquery()
    )

    q = (
        db.session.query(Employee)
        .join(
            unique_employees_subquery,
            db.and_(
                Employee.nompropio == unique_employees_subquery.c.nompropio,
                Employee.id == unique_employees_subquery.c.min_id
            )
        )
    )
    if active_only:
        q = q.filter(Employee.active == True)
    return q.order_by(Employee.nompropio).all()

@main.route('/costs/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_time_record(record_id):
    """Eliminar un registro de tiempo"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    try:
        record = TimeRecord.query.get_or_404(record_id)
        employee_name = record.employee.nompropio
        project_name = record.project.name

        db.session.delete(record)
        db.session.commit()

        message = f'Registro eliminado: {employee_name} - {project_name}'
        flash(message, 'success')

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error eliminando registro: {e}")
        return jsonify({'success': False, 'message': 'Error al eliminar el registro'}), 500

@main.route('/costs/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_records():
    """Eliminar múltiples registros"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Acceso denegado'}), 403

    try:
        record_ids = request.json.get('record_ids', [])
        if not record_ids:
            return jsonify({'success': False, 'message': 'No se seleccionaron registros'}), 400

        deleted_count = TimeRecord.query.filter(TimeRecord.id.in_(record_ids)).delete(synchronize_session=False)
        db.session.commit()

        message = f'{deleted_count} registros eliminados exitosamente.'
        return jsonify({'success': True, 'message': message})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error en eliminación masiva: {e}")
        return jsonify({'success': False, 'message': 'Error al eliminar los registros'}), 500

def _bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    return s in {"1", "true", "t", "yes", "y", "si", "sí"}



# ==== ADMIN: ACTIVIDADES POR DEPARTAMENTO ====
@main.route('/activities', methods=['GET', 'POST'], endpoint='activities_admin')
@login_required
def activities_admin():
    """Listado y alta rápida de actividades por departamento."""
    if not current_user.is_admin:
        flash('Acceso denegado. Solo administradores.', 'danger')
        return redirect(url_for('main.home'))

    # Alta (desde el formulario de activities_admin.html)
    if request.method == 'POST':
        department = (request.form.get('department') or '').strip()
        name = (request.form.get('name') or '').strip()

        if not department or not name:
            flash('Debe llenar todos los campos.', 'warning')
            return redirect(url_for('main.activities_admin'))

        if department not in {d for d, _ in activity_departments()}:
            flash('El área seleccionada no existe.', 'danger')
            return redirect(url_for('main.activities_admin'))

        try:
            # sort_order opcional: al final del grupo
            from sqlalchemy import func as sa_func
            last_order = (
                db.session.query(sa_func.max(DepartmentActivity.sort_order))
                .filter(DepartmentActivity.department == department)
                .scalar()
            )
            sort_order = (last_order or 0) + 1

            new_act = DepartmentActivity(
                department=department,
                name=name,
                is_active=True,
                sort_order=sort_order
            )
            db.session.add(new_act)
            db.session.commit()
            flash('Actividad registrada correctamente.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Ya existe una actividad con ese nombre en ese departamento.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: {e}', 'danger')

        return redirect(url_for('main.activities_admin'))

    # Listado
    from sqlalchemy import asc
    ensure_seed_activities()
    activities = DepartmentActivity.query.order_by(
        asc(DepartmentActivity.department),
        asc(DepartmentActivity.sort_order),
        asc(DepartmentActivity.name)
    ).all()

    return render_template(
        'activities_admin.html',
        activities=activities,
        department_options=activity_departments(),
        general_key=GENERAL_KEY,
        general_label=GENERAL_LABEL
    )


# ===========================
# EDITAR ACTIVIDAD (POST JSON)
# ===========================
@main.route('/activities/<int:activity_id>/update', methods=['POST'])
@login_required
def update_activity(activity_id: int):
    a = DepartmentActivity.query.get_or_404(activity_id)
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    department = (data.get('department') or '').strip()
    is_active = _bool(data.get('is_active'))
    sort_order = data.get('sort_order')

    if not name or not department:
        return jsonify(success=False, message='Departamento y nombre son requeridos.'), 400
    if department not in {d for d, _ in activity_departments()}:
        return jsonify(success=False, message='Departamento inválido.'), 400

    a.name = name
    a.department = department
    if is_active is not None:
        a.is_active = is_active
    try:
        a.sort_order = int(sort_order) if sort_order is not None else (a.sort_order or 0)
    except (TypeError, ValueError):
        return jsonify(success=False, message='sort_order debe ser numérico.'), 400

    try:
        db.session.commit()
        return jsonify(success=True, activity_id=a.id)
    except IntegrityError:
        db.session.rollback()
        # Violación de UNIQUE (department, name)
        return jsonify(success=False, message='Ya existe una actividad con ese nombre en ese departamento.'), 409
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al actualizar: {e}'), 500

# ==================================
# ACTIVAR / DESACTIVAR (POST sin body)
# ==================================
@main.route('/activities/<int:activity_id>/toggle', methods=['POST'])
@login_required
def toggle_activity(activity_id: int):
    a = DepartmentActivity.query.get_or_404(activity_id)
    # Si mandas explícito puedes leerlo de JSON; si no, se alterna.
    data = request.get_json(silent=True) or {}
    explicit = data.get('is_active', None)
    if explicit is None:
        a.is_active = not bool(a.is_active)
    else:
        a.is_active = _bool(explicit)

    try:
        db.session.commit()
        return jsonify(success=True, activity_id=a.id, is_active=a.is_active)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al cambiar estado: {e}'), 500
# ======================
# ELIMINAR (POST sin body)
# ======================
@main.route('/activities/<int:activity_id>/delete', methods=['POST'])
@login_required
def delete_activity(activity_id: int):
    a = DepartmentActivity.query.get_or_404(activity_id)

    try:
        db.session.delete(a)
        db.session.commit()
        return jsonify(success=True, activity_id=activity_id)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al eliminar: {e}'), 500


# ─────────────────────────────────────────────────────────────
# ADMIN: ÁREAS QUE REGISTRAN TIEMPOS
# ─────────────────────────────────────────────────────────────
def _solo_admin():
    if not current_user.is_admin:
        flash('Acceso denegado. Solo administradores.', 'danger')
        return redirect(url_for('main.home'))
    return None


def _rh_area_id(valor):
    """Normaliza el id de área de RH: cadena vacía significa 'sin enlazar'."""
    if valor in (None, '', 'None'):
        return None
    return int(valor)


def _renombrar_area(anterior, nuevo):
    """
    Propaga el cambio de nombre de un área a todo lo que la referencia por texto.

    TimeRecord.departamento es histórico: si no se reetiqueta, los registros
    viejos quedan huérfanos del área y desaparecen de los reportes por área.
    """
    if anterior == nuevo:
        return
    TimeRecord.query.filter_by(departamento=anterior).update(
        {'departamento': nuevo}, synchronize_session=False)
    DepartmentActivity.query.filter_by(department=anterior).update(
        {'department': nuevo}, synchronize_session=False)
    User.query.filter_by(area_manager_department=anterior).update(
        {'area_manager_department': nuevo}, synchronize_session=False)
    Employee.query.filter_by(departamento=anterior).update(
        {'departamento': nuevo}, synchronize_session=False)


@main.route('/admin/areas', methods=['GET', 'POST'], endpoint='areas_admin')
@login_required
def areas_admin():
    """Alta y listado de las áreas habilitadas para registrar tiempos."""
    bloqueo = _solo_admin()
    if bloqueo:
        return bloqueo

    if request.method == 'POST':
        nombre = (request.form.get('nombre') or '').strip()
        flujo = (request.form.get('flujo') or 'estandar').strip()

        if not nombre:
            flash('El nombre del área es obligatorio.', 'warning')
            return redirect(url_for('main.areas_admin'))
        if nombre == GENERAL_KEY:
            flash('Ese nombre está reservado por el sistema.', 'danger')
            return redirect(url_for('main.areas_admin'))
        if flujo not in AreaConfig.FLUJOS:
            flash('Flujo de registro inválido.', 'danger')
            return redirect(url_for('main.areas_admin'))

        try:
            db.session.add(AreaConfig(
                nombre=nombre,
                rh_area_id=_rh_area_id(request.form.get('rh_area_id')),
                flujo=flujo,
                activa=True,
                orden=next_area_order()
            ))
            db.session.commit()
            flash(f'Área "{nombre}" creada. Ahora puedes darle actividades.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Ya existe un área con ese nombre.', 'danger')
        except (TypeError, ValueError):
            db.session.rollback()
            flash('El área de RH seleccionada no es válida.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el área: {e}', 'danger')

        return redirect(url_for('main.areas_admin'))

    areas = get_areas(solo_activas=False)

    # Cuántas actividades y cuántos registros tiene cada área, para que el
    # administrador vea el impacto antes de desactivar o eliminar.
    conteo_actividades = dict(
        db.session.query(DepartmentActivity.department, func.count(DepartmentActivity.id))
        .group_by(DepartmentActivity.department).all()
    )
    conteo_registros = dict(
        db.session.query(TimeRecord.departamento, func.count(TimeRecord.id))
        .group_by(TimeRecord.departamento).all()
    )

    return render_template(
        'areas_admin.html',
        areas=areas,
        rh_areas=rh.listar_areas_seguro(),
        conteo_actividades=conteo_actividades,
        conteo_registros=conteo_registros,
        flujos=AreaConfig.FLUJOS
    )


@main.route('/admin/areas/<int:area_id>/update', methods=['POST'])
@login_required
def update_area(area_id: int):
    if not current_user.is_admin:
        return jsonify(success=False, message='Acceso denegado.'), 403

    area = AreaConfig.query.get_or_404(area_id)
    data = request.get_json(silent=True) or {}

    nombre = (data.get('nombre') or '').strip()
    flujo = (data.get('flujo') or area.flujo).strip()

    if not nombre:
        return jsonify(success=False, message='El nombre es requerido.'), 400
    if nombre == GENERAL_KEY:
        return jsonify(success=False, message='Ese nombre está reservado.'), 400
    if flujo not in AreaConfig.FLUJOS:
        return jsonify(success=False, message='Flujo de registro inválido.'), 400

    try:
        rh_area_id = _rh_area_id(data.get('rh_area_id'))
        orden = int(data.get('orden', area.orden) or 0)
    except (TypeError, ValueError):
        return jsonify(success=False, message='Área de RH y orden deben ser numéricos.'), 400

    anterior = area.nombre
    try:
        _renombrar_area(anterior, nombre)
        area.nombre = nombre
        area.flujo = flujo
        area.rh_area_id = rh_area_id
        area.orden = orden
        if data.get('activa') is not None:
            area.activa = _bool(data.get('activa'))
        db.session.commit()
        return jsonify(success=True, area_id=area.id)
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, message='Ya existe un área con ese nombre.'), 409
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al actualizar: {e}'), 500


@main.route('/admin/areas/<int:area_id>/toggle', methods=['POST'])
@login_required
def toggle_area(area_id: int):
    if not current_user.is_admin:
        return jsonify(success=False, message='Acceso denegado.'), 403

    area = AreaConfig.query.get_or_404(area_id)
    data = request.get_json(silent=True) or {}
    explicito = data.get('activa')
    area.activa = (not bool(area.activa)) if explicito is None else _bool(explicito)

    try:
        db.session.commit()
        return jsonify(success=True, area_id=area.id, activa=area.activa)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al cambiar estado: {e}'), 500


@main.route('/admin/areas/<int:area_id>/delete', methods=['POST'])
@login_required
def delete_area(area_id: int):
    if not current_user.is_admin:
        return jsonify(success=False, message='Acceso denegado.'), 403

    area = AreaConfig.query.get_or_404(area_id)

    # Borrar un área con historial dejaría registros que ya no se pueden filtrar
    # por área; en ese caso el camino correcto es desactivarla.
    registros = TimeRecord.query.filter_by(departamento=area.nombre).count()
    if registros:
        return jsonify(
            success=False,
            message=f'El área tiene {registros} registros de tiempo. Desactívala en vez de eliminarla.'
        ), 409

    try:
        DepartmentActivity.query.filter_by(department=area.nombre).delete(synchronize_session=False)
        db.session.delete(area)
        db.session.commit()
        return jsonify(success=True, area_id=area_id)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, message=f'Error al eliminar: {e}'), 500


# ─────────────────────────────────────────────────────────────
# GESTIÓN DE USUARIOS Y ROLES (ADMIN)
# ─────────────────────────────────────────────────────────────

@main.route('/admin/users', methods=['GET'])
@login_required
def manage_users():
    if not current_user.is_admin:
        flash('Acceso denegado. Se requieren privilegios de administrador.', 'danger')
        return redirect(url_for('main.home'))

    # Todos los usuarios registrados
    users = User.query.order_by(User.id.desc()).all()

    # Empleados que NO tienen un usuario asignado (para dar de alta)
    available_employees = Employee.query.outerjoin(User).filter(User.id == None, Employee.active == True).order_by(Employee.nompropio).all()

    # Al editar hace falta la lista completa, para poder mostrar el vínculo
    # actual de cada usuario aunque ese empleado ya esté ocupado.
    all_employees = Employee.query.filter(
        db.or_(Employee.active == True,
               Employee.id.in_([u.employee_id for u in users if u.employee_id] or [0]))
    ).order_by(Employee.nompropio).all()
    ocupados = {u.employee_id: u.username for u in users if u.employee_id}

    # Códigos de registro correspondientes
    admin_code = current_app.config.get('ADMIN_CODE', 'HI35C3')
    leader_code = current_app.config.get('LEADER_CODE', 'LP92B4')
    area_manager_code = current_app.config.get('AREA_MANAGER_CODE', 'AR845C')
    rh_code = current_app.config.get('RH_CODE', 'RH71D2')
    ejecutivo_code = current_app.config.get('EJECUTIVO_CODE', 'EJ38F6')

    return render_template(
        'manage_users.html',
        users=users,
        available_employees=available_employees,
        all_employees=all_employees,
        ocupados=ocupados,
        admin_code=admin_code,
        leader_code=leader_code,
        area_manager_code=area_manager_code,
        rh_code=rh_code,
        ejecutivo_code=ejecutivo_code
    )


@main.route('/admin/users/create', methods=['POST'])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    user_type = request.form.get('user_type', '').strip()

    if not username or not password or not user_type:
        flash('Todos los campos son obligatorios.', 'danger')
        return redirect(url_for('main.manage_users'))

    # Verificar que el usuario no exista
    if User.query.filter_by(username=username).first():
        flash('El usuario/correo ya está registrado.', 'danger')
        return redirect(url_for('main.manage_users'))

    is_admin = False
    is_project_leader = False
    is_area_manager = False
    is_rh = False
    is_ejecutivo = False
    area_manager_department = None
    employee_id = None

    if user_type == 'administrador':
        is_admin = True
    elif user_type == 'lider_proyecto':
        is_project_leader = True
    elif user_type == 'rh':
        is_rh = True
    elif user_type == 'ejecutivo':
        is_ejecutivo = True
    elif user_type == 'jefe_area':
        is_area_manager = True
        area = request.form.get('area_manager_department', '').strip()
        if area not in area_departments():
            flash('Selecciona un área válida para el Jefe de Área.', 'danger')
            return redirect(url_for('main.manage_users'))
        area_manager_department = area
    elif user_type == 'empleado':
        emp_id = request.form.get('employee_id')
        if not emp_id:
            flash('Selecciona un empleado de la lista.', 'danger')
            return redirect(url_for('main.manage_users'))
        employee_id = int(emp_id)
        # Verificar que el empleado exista y no tenga ya un usuario
        employee = Employee.query.get(employee_id)
        if not employee:
            flash('Empleado no encontrado.', 'danger')
            return redirect(url_for('main.manage_users'))
        if employee.user:
            flash('Este empleado ya tiene un usuario asignado.', 'danger')
            return redirect(url_for('main.manage_users'))
    else:
        flash('Tipo de usuario inválido.', 'danger')
        return redirect(url_for('main.manage_users'))

    # Ligar el usuario a un empleado de RH le da saldo de vacaciones propio,
    # aunque su perfil no sea "empleado".
    if user_type != 'empleado':
        vinculo = (request.form.get('employee_id') or '').strip()
        if vinculo:
            emp = Employee.query.get(int(vinculo))
            if not emp:
                flash('El empleado seleccionado no existe.', 'danger')
                return redirect(url_for('main.manage_users'))
            if emp.user:
                flash('%s ya tiene un usuario asignado; elige otro empleado o deja '
                      'el vínculo vacío.' % emp.nompropio, 'danger')
                return redirect(url_for('main.manage_users'))
            employee_id = emp.id

    # Cifrar contraseña
    hashed = generate_password_hash(password, method='pbkdf2:sha256')

    try:
        new_user = User(
            username=username,
            password=hashed,
            is_admin=is_admin,
            is_project_leader=is_project_leader,
            is_area_manager=is_area_manager,
            is_rh=is_rh,
            is_ejecutivo=is_ejecutivo,
            area_manager_department=area_manager_department,
            employee_id=employee_id
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f'Usuario {username} creado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creando usuario: {e}")
        flash('Error interno al crear el usuario.', 'danger')

    return redirect(url_for('main.manage_users'))


@main.route('/admin/users/<int:user_id>/update', methods=['POST'])
@login_required
def admin_update_user(user_id):
    """
    Cambia el perfil de un usuario y el empleado de RH al que está ligado.

    El vínculo con un empleado es lo que le da a la cuenta su saldo de
    vacaciones y su lugar en el árbol de supervisores, así que hace falta
    poder asignarlo también a usuarios que ya existían.
    """
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)
    user_type = (request.form.get('user_type') or '').strip()
    vinculo = (request.form.get('employee_id') or '').strip()

    perfiles = {
        'empleado':       dict(is_admin=False, is_project_leader=False,
                               is_area_manager=False, is_rh=False, is_ejecutivo=False),
        'ejecutivo':      dict(is_admin=False, is_project_leader=False,
                               is_area_manager=False, is_rh=False, is_ejecutivo=True),
        'jefe_area':      dict(is_admin=False, is_project_leader=False,
                               is_area_manager=True, is_rh=False, is_ejecutivo=False),
        'lider_proyecto': dict(is_admin=False, is_project_leader=True,
                               is_area_manager=False, is_rh=False, is_ejecutivo=False),
        'rh':             dict(is_admin=False, is_project_leader=False,
                               is_area_manager=False, is_rh=True, is_ejecutivo=False),
        'administrador':  dict(is_admin=True, is_project_leader=False,
                               is_area_manager=False, is_rh=False, is_ejecutivo=False),
    }
    if user_type not in perfiles:
        flash('Tipo de usuario inválido.', 'danger')
        return redirect(url_for('main.manage_users'))

    # Nadie se quita a sí mismo el rol de administrador: sería quedarse fuera.
    if user.id == current_user.id and user_type != 'administrador':
        flash('No puedes quitarte a ti mismo el rol de administrador.', 'danger')
        return redirect(url_for('main.manage_users'))

    # Y siempre debe quedar al menos un administrador.
    if user.is_admin and user_type != 'administrador':
        otros = User.query.filter(User.is_admin.is_(True), User.id != user.id).count()
        if not otros:
            flash('Es el único administrador; asigna otro antes de cambiarle el rol.', 'danger')
            return redirect(url_for('main.manage_users'))

    area = (request.form.get('area_manager_department') or '').strip()
    if user_type == 'jefe_area':
        if area not in area_departments():
            flash('Selecciona un área válida para el Jefe de Área.', 'danger')
            return redirect(url_for('main.manage_users'))
    else:
        area = None

    # Empleado ligado: vacío desliga la cuenta.
    nuevo_employee_id = None
    if vinculo:
        try:
            emp = Employee.query.get(int(vinculo))
        except (TypeError, ValueError):
            emp = None
        if not emp:
            flash('El empleado seleccionado no existe.', 'danger')
            return redirect(url_for('main.manage_users'))
        if emp.user and emp.user.id != user.id:
            flash('%s ya está ligado al usuario %s.' % (emp.nompropio, emp.user.username),
                  'danger')
            return redirect(url_for('main.manage_users'))
        nuevo_employee_id = emp.id
    elif user_type == 'empleado':
        flash('Un usuario de perfil Empleado debe estar ligado a un empleado.', 'warning')
        return redirect(url_for('main.manage_users'))

    for campo, valor in perfiles[user_type].items():
        setattr(user, campo, valor)
    user.area_manager_department = area
    user.employee_id = nuevo_employee_id

    try:
        db.session.commit()
        flash('Usuario %s actualizado.' % user.username, 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Ese empleado ya está ligado a otro usuario.', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("admin_update_user: %s", e)
        flash('No se pudo actualizar el usuario.', 'danger')

    return redirect(url_for('main.manage_users'))


@main.route('/admin/users/change_password/<int:user_id>', methods=['POST'])
@login_required
def admin_change_password(user_id):
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    auth_password = request.form.get('auth_password', '').strip()

    # Validar contraseña de autorización administrativa
    if auth_password != "Arribalaschivas2026":
        flash('Contraseña de autorización administrativa incorrecta. No se realizaron cambios.', 'danger')
        return redirect(url_for('main.manage_users'))

    if not new_password or len(new_password) < 6:
        flash('La nueva contraseña debe tener al menos 6 caracteres.', 'danger')
        return redirect(url_for('main.manage_users'))

    try:
        user.password = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        flash(f'Contraseña de {user.username} cambiada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cambiando contraseña: {e}")
        flash('Error al actualizar la contraseña.', 'danger')

    return redirect(url_for('main.manage_users'))


@main.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)

    # Evitar auto-eliminación
    if user.id == current_user.id:
        flash('No puedes eliminar tu propia cuenta de usuario.', 'danger')
        return redirect(url_for('main.manage_users'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash(f'Usuario {user.username} eliminado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error eliminando usuario: {e}")
        flash('Error al eliminar el usuario.', 'danger')

    return redirect(url_for('main.manage_users'))

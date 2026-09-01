"""
Vacaciones: solicitud, autorización por supervisor y administración por RH.

Quién ve qué:
  · Cualquier usuario ligado a un empleado: su saldo y sus solicitudes.
  · Quien tenga subordinados en AD17_RH.Supervisores: el calendario de su
    equipo y los pendientes por responder. La supervisión la define RH, no el
    perfil de la app, así que un Jefe de Área sin subordinados no ve equipo y
    un Ejecutivo con subordinados sí.
  · RH y Administradores: toda la plantilla, alta por cuenta de otros
    (autorizada de inmediato) y asignación de supervisores.
"""
import calendar
from datetime import date, datetime

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from .models import Employee
from . import vacaciones as vac
from .vacaciones import SinPermisoRH

bp = Blueprint('vacaciones', __name__, url_prefix='/vacaciones')

MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
         'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


# ─────────────────────────────────────────────────────────────
# Ayudantes
# ─────────────────────────────────────────────────────────────
def _mi_rh_id():
    """rhID del usuario en sesión, o None si su cuenta no está ligada a RH."""
    if not current_user.is_authenticated or not current_user.employee_id:
        return None
    return vac.rh_id_de(Employee.query.get(current_user.employee_id))


def _es_rh():
    return bool(current_user.is_admin or getattr(current_user, 'is_rh', False))


def _mes_pedido():
    """(anio, mes) de la query string, con el mes actual como respaldo."""
    hoy = date.today()
    try:
        anio = int(request.args.get('anio') or hoy.year)
        mes = int(request.args.get('mes') or hoy.month)
        if not 1 <= mes <= 12:
            raise ValueError
        date(anio, mes, 1)
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month
    return anio, mes


def _semanas_del_mes(anio, mes, eventos):
    """
    Rejilla del mes (lunes a domingo) con los eventos ya agrupados por día.

    Se arma en el servidor para que el calendario no dependa de JavaScript ni
    de una librería externa.
    """
    por_dia = {}
    for e in eventos:
        por_dia.setdefault(e['fecha'], []).append(e)

    cal = calendar.Calendar(firstweekday=0)
    semanas = []
    for semana in cal.monthdatescalendar(anio, mes):
        fila = []
        for dia in semana:
            fila.append({
                'fecha': dia,
                'del_mes': dia.month == mes,
                'hoy': dia == date.today(),
                'eventos': sorted(por_dia.get(dia, []), key=lambda x: x['empleado']),
            })
        semanas.append(fila)
    return semanas


def _navegacion_mes(anio, mes):
    ant = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    sig = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return {
        'titulo': '%s %s' % (MESES[mes], anio),
        'anio': anio, 'mes': mes,
        'anio_ant': ant[0], 'mes_ant': ant[1],
        'anio_sig': sig[0], 'mes_sig': sig[1],
    }


def _sin_permiso(e):
    """Mensaje accionable cuando falta el GRANT sobre AD17_RH."""
    current_app.logger.error("vacaciones: sin permiso de escritura en AD17_RH: %s", e)
    flash('No se pudo guardar: este sistema todavía no tiene permiso de escritura '
          'sobre las tablas de vacaciones en AD17_RH. Pide a RH que otorgue '
          'INSERT y UPDATE sobre AD17_RH.Vacaciones, MediosDias y Supervisores.',
          'danger')


def _fecha(valor):
    try:
        return datetime.strptime((valor or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
# Mi panel de vacaciones
# ─────────────────────────────────────────────────────────────
@bp.route('/')
@login_required
def mis_vacaciones():
    rh_id = _mi_rh_id()
    if not rh_id:
        flash('Tu usuario no está ligado a un empleado de RH, así que no tiene '
              'saldo de vacaciones. Pide a un administrador que lo vincule.', 'warning')
        return redirect(url_for('main.home'))

    saldo = vac.saldo_empleado(rh_id)
    if not saldo:
        flash('No encontramos tu registro en AD17_RH.', 'danger')
        return redirect(url_for('main.home'))

    solicitudes = vac.listar_vacaciones(rh_ids=[rh_id])
    pendientes = [s for s in solicitudes if s['estatus'] == 'PENDIENTE']
    historial = [s for s in solicitudes if s['estatus'] != 'PENDIENTE']
    historial.sort(key=lambda s: s['fecha'], reverse=True)

    return render_template(
        'vacaciones/mis_vacaciones.html',
        saldo=saldo,
        pendientes=pendientes,
        historial=historial,
        supervisores=vac.supervisores_de(rh_id),
        hoy=date.today().isoformat()
    )


@bp.route('/solicitar', methods=['POST'])
@login_required
def solicitar():
    rh_id = _mi_rh_id()
    if not rh_id:
        flash('Tu usuario no está ligado a un empleado de RH.', 'danger')
        return redirect(url_for('main.home'))

    saldo = vac.saldo_empleado(rh_id)
    tipo = (request.form.get('tipo') or 'VACACION').strip()

    try:
        if tipo == 'MEDIO_DIA':
            fecha = _fecha(request.form.get('fecha_medio_dia'))
            momento = (request.form.get('momento') or '').strip()
            if not fecha:
                flash('Indica la fecha del medio día.', 'warning')
                return redirect(url_for('vacaciones.mis_vacaciones'))
            if momento not in vac.TIPOS_MEDIO_DIA:
                flash('Indica si el medio día es al inicio o al final de la jornada.', 'warning')
                return redirect(url_for('vacaciones.mis_vacaciones'))
            if saldo['mediodias_libres'] < 1:
                flash('No te quedan medios días disponibles en este periodo.', 'warning')
                return redirect(url_for('vacaciones.mis_vacaciones'))
            if vac.fechas_ocupadas(rh_id, [fecha]):
                flash('Ya tienes una solicitud o vacación en esa fecha.', 'warning')
                return redirect(url_for('vacaciones.mis_vacaciones'))

            vac.crear_solicitud_medio_dia(rh_id, fecha, momento)
            flash('Medio día solicitado. Queda pendiente de autorización.', 'success')
            return redirect(url_for('vacaciones.mis_vacaciones'))

        desde = _fecha(request.form.get('desde'))
        hasta = _fecha(request.form.get('hasta')) or desde
        incluir_fines = bool(request.form.get('incluir_fines'))

        if not desde:
            flash('Indica al menos la fecha inicial.', 'warning')
            return redirect(url_for('vacaciones.mis_vacaciones'))
        if hasta < desde:
            flash('La fecha final no puede ser anterior a la inicial.', 'warning')
            return redirect(url_for('vacaciones.mis_vacaciones'))

        fechas = vac.dias_habiles(desde, hasta, incluir_fines)
        if not fechas:
            flash('El rango elegido no tiene días hábiles. Marca "incluir fines de '
                  'semana" si de verdad quieres pedir sábado o domingo.', 'warning')
            return redirect(url_for('vacaciones.mis_vacaciones'))

        ocupadas = vac.fechas_ocupadas(rh_id, fechas)
        fechas = [f for f in fechas if f not in ocupadas]
        if not fechas:
            flash('Ya tienes solicitudes o vacaciones en todas esas fechas.', 'warning')
            return redirect(url_for('vacaciones.mis_vacaciones'))

        if len(fechas) > saldo['vacaciones_libres']:
            flash('Pediste %d días y solo te quedan %d disponibles (ya descontando '
                  'lo que tienes pendiente).' % (len(fechas), saldo['vacaciones_libres']),
                  'warning')
            return redirect(url_for('vacaciones.mis_vacaciones'))

        vac.crear_solicitud_vacaciones(rh_id, fechas)
        omitidas = ' (%d fechas ya ocupadas se omitieron)' % len(ocupadas) if ocupadas else ''
        flash('Solicitaste %d día(s) de vacaciones%s. Quedan pendientes de '
              'autorización.' % (len(fechas), omitidas), 'success')

    except SinPermisoRH as e:
        _sin_permiso(e)
    except ValueError as e:
        flash(str(e), 'warning')
    except Exception as e:
        current_app.logger.error("vacaciones.solicitar: %s", e)
        flash('No se pudo registrar la solicitud.', 'danger')

    return redirect(url_for('vacaciones.mis_vacaciones'))


@bp.route('/cancelar/<tipo>/<int:reg_id>', methods=['POST'])
@login_required
def cancelar(tipo, reg_id):
    rh_id = _mi_rh_id()
    if not rh_id or tipo not in ('VACACION', 'MEDIO_DIA'):
        flash('Solicitud inválida.', 'danger')
        return redirect(url_for('vacaciones.mis_vacaciones'))

    try:
        if vac.cancelar_solicitud(reg_id, tipo, rh_id):
            flash('Solicitud cancelada.', 'success')
        else:
            flash('Esa solicitud ya no está pendiente.', 'warning')
    except SinPermisoRH as e:
        _sin_permiso(e)
    return redirect(url_for('vacaciones.mis_vacaciones'))


# ─────────────────────────────────────────────────────────────
# Equipo (supervisor)
# ─────────────────────────────────────────────────────────────
@bp.route('/equipo')
@login_required
def equipo():
    rh_id = _mi_rh_id()
    mis_subordinados = vac.subordinados(rh_id) if rh_id else []

    if not mis_subordinados and not _es_rh():
        flash('No tienes empleados asignados como supervisor.', 'warning')
        return redirect(url_for('vacaciones.mis_vacaciones'))

    anio, mes = _mes_pedido()
    inicio, fin = vac.rango_mes(anio, mes)

    eventos = vac.listar_vacaciones(rh_ids=mis_subordinados, desde=inicio, hasta=fin)
    # Los pendientes se listan completos, no solo los del mes que se está viendo
    pendientes = [s for s in vac.listar_vacaciones(rh_ids=mis_subordinados,
                                                   estatus='PENDIENTE')]
    pendientes.sort(key=lambda s: s['fecha'])

    saldos = {}
    for sub in mis_subordinados:
        s = vac.saldo_empleado(sub)
        if s:
            saldos[sub] = s

    return render_template(
        'vacaciones/equipo.html',
        semanas=_semanas_del_mes(anio, mes, eventos),
        nav=_navegacion_mes(anio, mes),
        pendientes=pendientes,
        saldos=sorted(saldos.values(), key=lambda s: s['nombre']),
        total_equipo=len(mis_subordinados),
        endpoint='vacaciones.equipo'
    )


@bp.route('/responder/<tipo>/<int:reg_id>', methods=['POST'])
@login_required
def responder(tipo, reg_id):
    rh_id = _mi_rh_id()
    destino = request.form.get('volver') or url_for('vacaciones.equipo')

    if tipo not in ('VACACION', 'MEDIO_DIA'):
        flash('Solicitud inválida.', 'danger')
        return redirect(destino)
    if not rh_id:
        flash('Tu usuario no está ligado a un empleado de RH, así que no puede autorizar.', 'danger')
        return redirect(destino)

    sol = vac.solicitud(reg_id, tipo)
    if not sol:
        flash('La solicitud ya no existe.', 'warning')
        return redirect(destino)

    # Autoriza quien supervisa a esa persona; RH y Administración, cualquiera.
    if not _es_rh() and sol['rhID'] not in vac.subordinados(rh_id):
        flash('Esa solicitud no es de alguien que supervises.', 'danger')
        return redirect(destino)

    autorizar = request.form.get('accion') == 'autorizar'
    try:
        if vac.responder_solicitud(reg_id, tipo, autorizar, rh_id):
            flash('Solicitud %s.' % ('autorizada' if autorizar else 'denegada'), 'success')
        else:
            flash('Esa solicitud ya había sido respondida.', 'warning')
    except SinPermisoRH as e:
        _sin_permiso(e)
    return redirect(destino)


# ─────────────────────────────────────────────────────────────
# Administración (RH)
# ─────────────────────────────────────────────────────────────
def _bloquear_si_no_es_rh():
    if not _es_rh():
        flash('Acceso denegado. Esta vista es para RH y Administración.', 'danger')
        return redirect(url_for('vacaciones.mis_vacaciones'))
    return None


@bp.route('/admin')
@login_required
def admin():
    bloqueo = _bloquear_si_no_es_rh()
    if bloqueo:
        return bloqueo

    anio, mes = _mes_pedido()
    inicio, fin = vac.rango_mes(anio, mes)

    estatus = (request.args.get('estatus') or '').strip().upper() or None
    if estatus not in (None,) + vac.ESTATUS:
        estatus = None

    eventos = vac.listar_vacaciones(desde=inicio, hasta=fin, estatus=estatus)
    pendientes = vac.listar_vacaciones(estatus='PENDIENTE')
    pendientes.sort(key=lambda s: s['fecha'])

    return render_template(
        'vacaciones/admin.html',
        semanas=_semanas_del_mes(anio, mes, eventos),
        nav=_navegacion_mes(anio, mes),
        eventos=eventos,
        pendientes=pendientes,
        empleados=vac.listar_empleados(),
        estatus=estatus,
        estatus_opciones=vac.ESTATUS,
        hoy=date.today().isoformat(),
        endpoint='vacaciones.admin'
    )


@bp.route('/admin/solicitar', methods=['POST'])
@login_required
def admin_solicitar():
    bloqueo = _bloquear_si_no_es_rh()
    if bloqueo:
        return bloqueo

    mi_rh_id = _mi_rh_id()
    if not mi_rh_id:
        flash('Tu usuario de RH debe estar ligado a un empleado para poder autorizar.', 'danger')
        return redirect(url_for('vacaciones.admin'))

    try:
        rh_id = int(request.form.get('rh_id') or 0)
    except (TypeError, ValueError):
        rh_id = 0
    if not rh_id:
        flash('Selecciona al empleado.', 'warning')
        return redirect(url_for('vacaciones.admin'))

    tipo = (request.form.get('tipo') or 'VACACION').strip()
    # RH captura vacaciones ya acordadas: nacen autorizadas por quien las carga.
    try:
        if tipo == 'MEDIO_DIA':
            fecha = _fecha(request.form.get('fecha_medio_dia'))
            momento = (request.form.get('momento') or '').strip()
            if not fecha or momento not in vac.TIPOS_MEDIO_DIA:
                flash('Indica la fecha y el momento del medio día.', 'warning')
                return redirect(url_for('vacaciones.admin'))
            vac.crear_solicitud_medio_dia(rh_id, fecha, momento, autorizar_con=mi_rh_id)
            flash('Medio día registrado y autorizado.', 'success')
            return redirect(url_for('vacaciones.admin'))

        desde = _fecha(request.form.get('desde'))
        hasta = _fecha(request.form.get('hasta')) or desde
        if not desde or hasta < desde:
            flash('Rango de fechas inválido.', 'warning')
            return redirect(url_for('vacaciones.admin'))

        fechas = vac.dias_habiles(desde, hasta, bool(request.form.get('incluir_fines')))
        ocupadas = vac.fechas_ocupadas(rh_id, fechas)
        fechas = [f for f in fechas if f not in ocupadas]
        if not fechas:
            flash('No quedaron fechas por registrar (ya estaban ocupadas o el rango '
                  'no tiene días hábiles).', 'warning')
            return redirect(url_for('vacaciones.admin'))

        vac.crear_solicitud_vacaciones(rh_id, fechas, autorizar_con=mi_rh_id)
        flash('Se registraron y autorizaron %d día(s).' % len(fechas), 'success')

    except SinPermisoRH as e:
        _sin_permiso(e)
    except ValueError as e:
        flash(str(e), 'warning')
    except Exception as e:
        current_app.logger.error("vacaciones.admin_solicitar: %s", e)
        flash('No se pudo registrar.', 'danger')

    return redirect(url_for('vacaciones.admin'))


# ─────────────────────────────────────────────────────────────
# Supervisores (RH)
# ─────────────────────────────────────────────────────────────
@bp.route('/supervisores')
@login_required
def supervisores():
    bloqueo = _bloquear_si_no_es_rh()
    if bloqueo:
        return bloqueo

    empleados = vac.listar_empleados()
    mapa = vac.mapa_supervisores()
    detalle = {e['rh_id']: vac.supervisores_de(e['rh_id']) for e in empleados} \
        if request.args.get('detalle') else {}

    filtro = (request.args.get('q') or '').strip().lower()
    if filtro:
        empleados = [e for e in empleados if filtro in e['nombre'].lower()
                     or filtro in (e['area'] or '').lower()]

    return render_template(
        'vacaciones/supervisores.html',
        empleados=empleados,
        todos=vac.listar_empleados(),
        mapa=mapa,
        detalle=detalle,
        sin_supervisor=[e for e in empleados if not mapa.get(e['rh_id'])],
        filtro=filtro
    )


@bp.route('/supervisores/asignar', methods=['POST'])
@login_required
def asignar_supervisor():
    bloqueo = _bloquear_si_no_es_rh()
    if bloqueo:
        return bloqueo

    mi_rh_id = _mi_rh_id() or 1
    try:
        rh_id = int(request.form.get('rh_id') or 0)
        sup_rh_id = int(request.form.get('sup_rh_id') or 0)
    except (TypeError, ValueError):
        rh_id = sup_rh_id = 0

    if not rh_id or not sup_rh_id:
        flash('Selecciona al empleado y a su supervisor.', 'warning')
        return redirect(url_for('vacaciones.supervisores'))

    try:
        if vac.asignar_supervisor(rh_id, sup_rh_id, mi_rh_id):
            flash('Supervisor asignado.', 'success')
        else:
            flash('Esa persona ya tiene asignado a ese supervisor.', 'info')
    except SinPermisoRH as e:
        _sin_permiso(e)
    except ValueError as e:
        flash(str(e), 'warning')
    return redirect(url_for('vacaciones.supervisores'))


@bp.route('/supervisores/quitar/<int:reg_id>', methods=['POST'])
@login_required
def quitar_supervisor(reg_id):
    bloqueo = _bloquear_si_no_es_rh()
    if bloqueo:
        return bloqueo

    try:
        if vac.quitar_supervisor(reg_id):
            flash('Se retiró la relación de supervisión.', 'success')
        else:
            flash('Esa relación ya no estaba activa.', 'warning')
    except SinPermisoRH as e:
        _sin_permiso(e)
    return redirect(url_for('vacaciones.supervisores'))


# ─────────────────────────────────────────────────────────────
# Feed del calendario
# ─────────────────────────────────────────────────────────────
@bp.route('/api/eventos')
@login_required
def api_eventos():
    """Eventos del mes en JSON, con el mismo alcance que la vista que lo pide."""
    anio, mes = _mes_pedido()
    inicio, fin = vac.rango_mes(anio, mes)
    rh_id = _mi_rh_id()

    if _es_rh() and request.args.get('alcance') == 'todos':
        rh_ids = None
    elif request.args.get('alcance') == 'equipo':
        rh_ids = vac.subordinados(rh_id) if rh_id else []
    else:
        rh_ids = [rh_id] if rh_id else []

    eventos = vac.listar_vacaciones(rh_ids=rh_ids, desde=inicio, hasta=fin)
    return jsonify([{
        'id': e['id'], 'tipo': e['tipo'], 'fecha': e['fecha'].isoformat(),
        'empleado': e['empleado'], 'area': e['area'],
        'estatus': e['estatus'], 'momento': e['momento'],
    } for e in eventos])

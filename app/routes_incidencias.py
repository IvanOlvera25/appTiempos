"""
Incidencias: informes de incidencia y su consolidación.

Dos niveles:
  · Informe de Incidencia — lo levanta cualquier perfil que no sea Empleado.
    Es el reporte "crudo": qué pasó, quién lo causó, a qué FP afecta y cómo
    repercutió.
  · Incidencia — la arman Administración y RH agrupando los informes que hablan
    del mismo evento, con su propia descripción, los FP reales, un responsable
    final y el costo.

Visibilidad de los informes (ver `informes_visibles`):
  · Administración y RH ven todo, incluidos los marcados como inválidos.
  · Los demás perfiles nunca ven un informe inválido, y solo alcanzan a ver los
    de autores de su mismo nivel o menor, los propios, y aquellos en los que se
    les señala como causantes (a ellos o a su área).
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from . import db
from .catalogs import get_area_names, get_clasificaciones
from .models import (Employee, Incident, IncidentClassification, IncidentProject,
                     IncidentReport, IncidentReportProject, Project, User)

bp = Blueprint('incidencias', __name__, url_prefix='/incidencias')


# ─────────────────────────────────────────────────────────────
# Permisos y alcance
# ─────────────────────────────────────────────────────────────
def _puede_reportar():
    return getattr(current_user, 'puede_reportar_incidencias', False)


def _administra():
    return getattr(current_user, 'administra_incidencias', False)


def _bloquear_sin_acceso():
    if not _puede_reportar():
        flash('Acceso denegado. Los informes de incidencia son para perfiles '
              'distintos de Empleado.', 'danger')
        return redirect(url_for('main.home'))
    return None


def informes_visibles():
    """Query de IncidentReport ya restringida a lo que el usuario puede ver."""
    q = IncidentReport.query

    if _administra():
        return q

    condiciones = [
        # Autores de su mismo nivel de perfil o menor
        IncidentReport.nivel_autor <= current_user.role_level,
        # Y siempre los propios
        IncidentReport.reporter_user_id == current_user.id,
    ]

    # Informes de perfiles superiores en los que se le señala como causante
    if current_user.employee_id:
        condiciones.append(IncidentReport.causante_employee_id == current_user.employee_id)
    if getattr(current_user, 'is_area_manager', False) and current_user.area_manager_department:
        condiciones.append(IncidentReport.causante_area == current_user.area_manager_department)

    # Un informe marcado como inválido queda oculto para el resto de perfiles
    return q.filter(IncidentReport.invalido.is_(False)).filter(or_(*condiciones))


def _informe_visible_o_404(report_id):
    informe = informes_visibles().filter(IncidentReport.id == report_id).first()
    if not informe:
        from flask import abort
        abort(404)
    return informe


# ─────────────────────────────────────────────────────────────
# Utilidades de formulario
# ─────────────────────────────────────────────────────────────
def _proyectos_activos():
    return Project.query.filter_by(active=True).order_by(Project.folio.asc()).all()


def _ids_del_form(campo):
    """Conjunto de enteros de un campo repetido del formulario."""
    ids = set()
    for c in request.form.getlist(campo):
        try:
            ids.add(int(c))
        except (TypeError, ValueError):
            continue
    return ids


def _ids_proyectos(campo='project_ids'):
    """IDs de proyecto del formulario, validados contra la tabla."""
    ids = _ids_del_form(campo)
    if not ids:
        return []
    return [p.id for p in Project.query.filter(Project.id.in_(ids)).all()]


def _causante_del_form():
    """(tipo, area, employee_id, texto) validado."""
    tipo = (request.form.get('causante_tipo') or 'AREA').strip().upper()
    if tipo not in IncidentReport.TIPOS_CAUSANTE:
        raise ValueError('Tipo de causante inválido.')

    area = employee_id = texto = None
    if tipo == 'AREA':
        area = (request.form.get('causante_area') or '').strip()
        if area not in get_area_names(solo_activas=False):
            raise ValueError('Selecciona un área válida como causante.')
    elif tipo == 'EMPLEADO':
        try:
            employee_id = int(request.form.get('causante_employee_id') or 0)
        except (TypeError, ValueError):
            employee_id = 0
        if not employee_id or not Employee.query.get(employee_id):
            raise ValueError('Selecciona un empleado válido como causante.')
    else:
        texto = (request.form.get('causante_texto') or '').strip()
        if not texto:
            raise ValueError('Escribe quién causó la incidencia.')
    return tipo, area, employee_id, texto


def _clasificacion_del_form():
    try:
        cid = int(request.form.get('clasificacion_id') or 0)
    except (TypeError, ValueError):
        return None
    return cid if cid and IncidentClassification.query.get(cid) else None


def _decimal(valor, defecto=Decimal('0')):
    try:
        return Decimal((valor or '0').strip() or '0')
    except (InvalidOperation, AttributeError):
        return defecto


# ─────────────────────────────────────────────────────────────
# Informes de incidencia
# ─────────────────────────────────────────────────────────────
@bp.route('/informes')
@login_required
def informes():
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo

    q = informes_visibles().options(
        joinedload(IncidentReport.reporter),
        joinedload(IncidentReport.clasificacion),
        joinedload(IncidentReport.causante_employee),
        joinedload(IncidentReport.incident),
    )

    estado = (request.args.get('estado') or '').strip()
    if estado == 'sueltos':
        q = q.filter(IncidentReport.incident_id.is_(None))
    elif estado == 'vinculados':
        q = q.filter(IncidentReport.incident_id.isnot(None))
    elif estado == 'invalidos' and _administra():
        q = q.filter(IncidentReport.invalido.is_(True))

    clasificacion = request.args.get('clasificacion_id', type=int)
    if clasificacion:
        q = q.filter(IncidentReport.clasificacion_id == clasificacion)

    return render_template(
        'incidencias/informes.html',
        informes=q.order_by(IncidentReport.created_at.desc()).all(),
        clasificaciones=get_clasificaciones(solo_activas=False),
        estado=estado,
        clasificacion_id=clasificacion,
        administra=_administra()
    )


@bp.route('/informes/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_informe():
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo

    if request.method == 'POST':
        motivo = (request.form.get('motivo') or '').strip()
        repercusion = (request.form.get('repercusion') or '').strip()

        if not motivo:
            flash('Describe el motivo de la incidencia.', 'warning')
            return redirect(url_for('incidencias.nuevo_informe'))

        try:
            tipo, area, employee_id, texto = _causante_del_form()
        except ValueError as e:
            flash(str(e), 'warning')
            return redirect(url_for('incidencias.nuevo_informe'))

        informe = IncidentReport(
            reporter_user_id=current_user.id,
            # Foto del nivel del autor: define quién podrá verlo de aquí en adelante
            nivel_autor=current_user.role_level,
            created_at=datetime.utcnow(),
            motivo=motivo,
            repercusion=repercusion or None,
            clasificacion_id=_clasificacion_del_form(),
            causante_tipo=tipo,
            causante_area=area,
            causante_employee_id=employee_id,
            causante_texto=texto,
        )
        db.session.add(informe)
        db.session.flush()

        for pid in _ids_proyectos():
            db.session.add(IncidentReportProject(report_id=informe.id, project_id=pid))

        try:
            db.session.commit()
            flash('Informe de incidencia registrado.', 'success')
            return redirect(url_for('incidencias.ver_informe', report_id=informe.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("incidencias.nuevo_informe: %s", e)
            flash('No se pudo guardar el informe.', 'danger')
            return redirect(url_for('incidencias.nuevo_informe'))

    return render_template(
        'incidencias/informe_form.html',
        informe=None,
        clasificaciones=get_clasificaciones(),
        areas=get_area_names(),
        empleados=Employee.query.filter_by(active=True).order_by(Employee.nompropio).all(),
        proyectos=_proyectos_activos(),
        seleccionados=[]
    )


@bp.route('/informes/<int:report_id>')
@login_required
def ver_informe(report_id):
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo
    informe = _informe_visible_o_404(report_id)
    return render_template(
        'incidencias/informe_detalle.html',
        informe=informe,
        administra=_administra(),
        puede_editar=(informe.reporter_user_id == current_user.id and not informe.incident_id)
                     or _administra()
    )


@bp.route('/informes/<int:report_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_informe(report_id):
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo

    informe = _informe_visible_o_404(report_id)

    # El autor puede corregir su informe mientras no se haya consolidado;
    # después solo Administración o RH, para no alterar una incidencia cerrada.
    if not (_administra() or (informe.reporter_user_id == current_user.id
                              and not informe.incident_id)):
        flash('Este informe ya no se puede editar.', 'warning')
        return redirect(url_for('incidencias.ver_informe', report_id=report_id))

    if request.method == 'POST':
        motivo = (request.form.get('motivo') or '').strip()
        if not motivo:
            flash('Describe el motivo de la incidencia.', 'warning')
            return redirect(url_for('incidencias.editar_informe', report_id=report_id))

        try:
            tipo, area, employee_id, texto = _causante_del_form()
        except ValueError as e:
            flash(str(e), 'warning')
            return redirect(url_for('incidencias.editar_informe', report_id=report_id))

        informe.motivo = motivo
        informe.repercusion = (request.form.get('repercusion') or '').strip() or None
        informe.clasificacion_id = _clasificacion_del_form()
        informe.causante_tipo = tipo
        informe.causante_area = area
        informe.causante_employee_id = employee_id
        informe.causante_texto = texto

        IncidentReportProject.query.filter_by(report_id=informe.id).delete(
            synchronize_session=False)
        for pid in _ids_proyectos():
            db.session.add(IncidentReportProject(report_id=informe.id, project_id=pid))

        try:
            db.session.commit()
            flash('Informe actualizado.', 'success')
            return redirect(url_for('incidencias.ver_informe', report_id=informe.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("incidencias.editar_informe: %s", e)
            flash('No se pudo actualizar el informe.', 'danger')

    return render_template(
        'incidencias/informe_form.html',
        informe=informe,
        clasificaciones=get_clasificaciones(),
        areas=get_area_names(solo_activas=False),
        empleados=Employee.query.filter_by(active=True).order_by(Employee.nompropio).all(),
        proyectos=_proyectos_activos(),
        seleccionados=[p.project_id for p in informe.projects]
    )


@bp.route('/informes/<int:report_id>/invalidar', methods=['POST'])
@login_required
def invalidar_informe(report_id):
    if not _administra():
        flash('Solo Administración y RH pueden invalidar informes.', 'danger')
        return redirect(url_for('incidencias.informes'))

    informe = IncidentReport.query.get_or_404(report_id)
    informe.invalido = not informe.invalido
    # Un informe inválido no debe seguir contando dentro de una incidencia
    if informe.invalido:
        informe.incident_id = None

    try:
        db.session.commit()
        flash('Informe marcado como %s.' % ('inválido' if informe.invalido else 'válido'),
              'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("incidencias.invalidar_informe: %s", e)
        flash('No se pudo cambiar el estado del informe.', 'danger')

    return redirect(request.form.get('volver')
                    or url_for('incidencias.ver_informe', report_id=report_id))


# ─────────────────────────────────────────────────────────────
# Incidencias consolidadas
# ─────────────────────────────────────────────────────────────
def _bloquear_si_no_administra():
    if not _administra():
        flash('Solo Administración y RH administran incidencias.', 'danger')
        return redirect(url_for('incidencias.informes'))
    return None


@bp.route('/')
@login_required
def lista():
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo

    q = Incident.query.options(
        joinedload(Incident.clasificacion),
        joinedload(Incident.responsable_employee),
        joinedload(Incident.created_by),
    )
    if not _administra():
        # Un perfil no administrador solo ve las incidencias que agrupan
        # informes que él mismo alcanza a ver.
        visibles = [i.incident_id for i in informes_visibles()
                    .filter(IncidentReport.incident_id.isnot(None)).all()]
        if not visibles:
            return render_template('incidencias/lista.html', incidencias=[],
                                   administra=False, total_costo=0)
        q = q.filter(Incident.id.in_(visibles))

    incidencias = q.order_by(Incident.created_at.desc()).all()
    return render_template(
        'incidencias/lista.html',
        incidencias=incidencias,
        administra=_administra(),
        total_costo=sum((i.costo or 0) for i in incidencias)
    )


def _responsable_del_form():
    tipo = (request.form.get('responsable_tipo') or 'AREA').strip().upper()
    if tipo not in Incident.TIPOS_RESPONSABLE:
        raise ValueError('Tipo de responsable inválido.')

    area = employee_id = texto = None
    if tipo == 'AREA':
        area = (request.form.get('responsable_area') or '').strip()
        if area not in get_area_names(solo_activas=False):
            raise ValueError('Selecciona un área válida como responsable.')
    elif tipo == 'EMPLEADO':
        try:
            employee_id = int(request.form.get('responsable_employee_id') or 0)
        except (TypeError, ValueError):
            employee_id = 0
        if not employee_id or not Employee.query.get(employee_id):
            raise ValueError('Selecciona un trabajador válido como responsable.')
    else:
        texto = (request.form.get('responsable_texto') or '').strip()
        if not texto:
            raise ValueError('Escribe el nombre del cliente responsable.')
    return tipo, area, employee_id, texto


def _guardar_incidencia(incidencia, es_alta):
    """Aplica el formulario sobre la incidencia. Devuelve None o un mensaje."""
    descripcion = (request.form.get('descripcion') or '').strip()
    if not descripcion:
        return 'Escribe la descripción de la incidencia.'

    try:
        tipo, area, employee_id, texto = _responsable_del_form()
    except ValueError as e:
        return str(e)

    incidencia.descripcion = descripcion
    incidencia.clasificacion_id = _clasificacion_del_form()
    incidencia.responsable_tipo = tipo
    incidencia.responsable_area = area
    incidencia.responsable_employee_id = employee_id
    incidencia.responsable_texto = texto
    incidencia.costo = _decimal(request.form.get('costo'))

    estado = (request.form.get('estado') or 'ABIERTA').strip().upper()
    incidencia.estado = estado if estado in Incident.ESTADOS else 'ABIERTA'

    if es_alta:
        db.session.add(incidencia)
    db.session.flush()

    # FP reales de la incidencia
    IncidentProject.query.filter_by(incident_id=incidencia.id).delete(
        synchronize_session=False)
    for pid in _ids_proyectos():
        db.session.add(IncidentProject(incident_id=incidencia.id, project_id=pid))

    # Informes: `candidatos` es la lista completa de los que se mostraron en el
    # formulario. Se necesita para poder DESmarcar como inválido: sin ella solo
    # se sabría qué casillas quedaron marcadas, no cuáles se desmarcaron.
    candidatos = _ids_del_form('candidatos')
    elegidos = _ids_del_form('report_ids') & candidatos
    invalidos = _ids_del_form('invalidos') & candidatos

    if candidatos:
        # Marcar/desmarcar inválidos en una sola pasada sobre los candidatos
        (IncidentReport.query
         .filter(IncidentReport.id.in_(candidatos - invalidos))
         .update({'invalido': False}, synchronize_session=False))
        if invalidos:
            (IncidentReport.query
             .filter(IncidentReport.id.in_(invalidos))
             .update({'invalido': True, 'incident_id': None}, synchronize_session=False))

    # Un informe inválido nunca queda vinculado
    vinculados = elegidos - invalidos
    IncidentReport.query.filter_by(incident_id=incidencia.id).update(
        {'incident_id': None}, synchronize_session=False)
    if vinculados:
        (IncidentReport.query
         .filter(IncidentReport.id.in_(vinculados))
         .update({'incident_id': incidencia.id}, synchronize_session=False))

    return None


def _contexto_incidencia(incidencia):
    """Informes que se pueden vincular: los sueltos más los ya vinculados."""
    disponibles = (IncidentReport.query
                   .options(joinedload(IncidentReport.reporter),
                            joinedload(IncidentReport.causante_employee))
                   .filter(or_(
                       IncidentReport.incident_id.is_(None),
                       IncidentReport.incident_id == (incidencia.id if incidencia else -1)))
                   .order_by(IncidentReport.created_at.desc())
                   .all())
    return {
        'incidencia': incidencia,
        'clasificaciones': get_clasificaciones(),
        'areas': get_area_names(solo_activas=False),
        'empleados': Employee.query.filter_by(active=True).order_by(Employee.nompropio).all(),
        'proyectos': _proyectos_activos(),
        'informes_disponibles': disponibles,
        'seleccionados': [p.project_id for p in incidencia.projects] if incidencia else [],
        'vinculados': [r.id for r in incidencia.reports] if incidencia else [],
        'estados': Incident.ESTADOS,
    }


@bp.route('/nueva', methods=['GET', 'POST'])
@login_required
def nueva():
    bloqueo = _bloquear_si_no_administra()
    if bloqueo:
        return bloqueo

    if request.method == 'POST':
        incidencia = Incident(created_by_user_id=current_user.id,
                              created_at=datetime.utcnow())
        error = _guardar_incidencia(incidencia, es_alta=True)
        if error:
            db.session.rollback()
            flash(error, 'warning')
            return redirect(url_for('incidencias.nueva'))
        try:
            db.session.commit()
            flash('Incidencia registrada.', 'success')
            return redirect(url_for('incidencias.ver', incident_id=incidencia.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("incidencias.nueva: %s", e)
            flash('No se pudo guardar la incidencia.', 'danger')
            return redirect(url_for('incidencias.nueva'))

    return render_template('incidencias/incidencia_form.html',
                           **_contexto_incidencia(None))


@bp.route('/<int:incident_id>')
@login_required
def ver(incident_id):
    bloqueo = _bloquear_sin_acceso()
    if bloqueo:
        return bloqueo

    incidencia = Incident.query.get_or_404(incident_id)
    informes = list(incidencia.reports)
    if not _administra():
        visibles = {i.id for i in informes_visibles().all()}
        if not any(r.id in visibles for r in informes):
            from flask import abort
            abort(404)
        informes = [r for r in informes if r.id in visibles]

    return render_template('incidencias/incidencia_detalle.html',
                           incidencia=incidencia, informes=informes,
                           administra=_administra())


@bp.route('/<int:incident_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(incident_id):
    bloqueo = _bloquear_si_no_administra()
    if bloqueo:
        return bloqueo

    incidencia = Incident.query.get_or_404(incident_id)

    if request.method == 'POST':
        error = _guardar_incidencia(incidencia, es_alta=False)
        if error:
            db.session.rollback()
            flash(error, 'warning')
            return redirect(url_for('incidencias.editar', incident_id=incident_id))
        try:
            db.session.commit()
            flash('Incidencia actualizada.', 'success')
            return redirect(url_for('incidencias.ver', incident_id=incidencia.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error("incidencias.editar: %s", e)
            flash('No se pudo actualizar la incidencia.', 'danger')

    return render_template('incidencias/incidencia_form.html',
                           **_contexto_incidencia(incidencia))


@bp.route('/<int:incident_id>/eliminar', methods=['POST'])
@login_required
def eliminar(incident_id):
    bloqueo = _bloquear_si_no_administra()
    if bloqueo:
        return bloqueo

    incidencia = Incident.query.get_or_404(incident_id)
    try:
        # Los informes sobreviven a la incidencia: solo se sueltan.
        IncidentReport.query.filter_by(incident_id=incidencia.id).update(
            {'incident_id': None}, synchronize_session=False)
        db.session.delete(incidencia)
        db.session.commit()
        flash('Incidencia eliminada. Sus informes quedaron sin agrupar.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("incidencias.eliminar: %s", e)
        flash('No se pudo eliminar la incidencia.', 'danger')

    return redirect(url_for('incidencias.lista'))


# ─────────────────────────────────────────────────────────────
# Catálogo de clasificaciones (administradores)
# ─────────────────────────────────────────────────────────────
@bp.route('/clasificaciones', methods=['GET', 'POST'])
@login_required
def clasificaciones():
    if not current_user.is_admin:
        flash('Acceso denegado. Solo administradores.', 'danger')
        return redirect(url_for('incidencias.informes'))

    if request.method == 'POST':
        from .catalogs import next_clasificacion_order
        nombre = (request.form.get('nombre') or '').strip()
        if not nombre:
            flash('Escribe el nombre de la clasificación.', 'warning')
            return redirect(url_for('incidencias.clasificaciones'))
        try:
            db.session.add(IncidentClassification(
                nombre=nombre, activa=True, orden=next_clasificacion_order()))
            db.session.commit()
            flash('Clasificación agregada.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('No se pudo agregar (¿ya existe?): %s' % e, 'danger')
        return redirect(url_for('incidencias.clasificaciones'))

    catalogo = get_clasificaciones(solo_activas=False)
    usos = dict(db.session.query(IncidentReport.clasificacion_id,
                                 db.func.count(IncidentReport.id))
                .group_by(IncidentReport.clasificacion_id).all())
    return render_template('incidencias/clasificaciones.html',
                           clasificaciones=catalogo, usos=usos)


@bp.route('/clasificaciones/<int:clasificacion_id>/toggle', methods=['POST'])
@login_required
def toggle_clasificacion(clasificacion_id):
    if not current_user.is_admin:
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('incidencias.informes'))

    c = IncidentClassification.query.get_or_404(clasificacion_id)
    c.activa = not c.activa
    db.session.commit()
    flash('Clasificación %s.' % ('activada' if c.activa else 'desactivada'), 'success')
    return redirect(url_for('incidencias.clasificaciones'))

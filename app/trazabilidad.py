"""
Trazabilidad de los registros de tiempo: dónde se inició y se finalizó cada uno,
y por qué Administración lo dio de alta o lo modificó desde Costos.

Las dos tablas son nuevas (migración e7c2a1f9b4d0). Si el código llega al
servidor antes que la migración, iniciar y finalizar tiempos sigue funcionando:
lo nuevo no se guarda y queda un error en el log. Por eso toda lectura y
escritura va dentro de un SAVEPOINT y nunca tumba la petición que la llama.
"""
import math
from datetime import datetime

from flask import current_app, request
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from . import db
from .models import TimeRecordChange, TimeRecordLocation

MSG_SIN_UBICACION = (
    'Para registrar tu tiempo es obligatorio compartir tu ubicación. Activa la '
    'ubicación del dispositivo, permite el acceso en el navegador y vuelve a intentarlo.')

MOTIVOS = TimeRecordChange.MOTIVOS
_aviso_migracion = {'dado': False}


def _fallo(que, error):
    """
    Si faltan las tablas (no se ha migrado) se avisa una sola vez por proceso,
    para no llenar el log en cada registro; cualquier otro error, siempre.
    """
    texto = str(error).split('\n')[0]
    if 'no such table' in texto or "doesn't exist" in texto:
        if _aviso_migracion['dado']:
            current_app.logger.debug("trazabilidad: no se pudo %s: %s", que, texto)
            return
        _aviso_migracion['dado'] = True
        current_app.logger.error(
            "trazabilidad: no se pudo %s; falta correr `flask db upgrade e7c2a1f9b4d0`: %s",
            que, texto)
    else:
        current_app.logger.error("trazabilidad: no se pudo %s: %s", que, texto)


# ─────────────────────────────────────────────────────────────
# Ubicación
# ─────────────────────────────────────────────────────────────
def _numero(valor):
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def ubicacion_del_form(datos=None):
    """
    {'latitude', 'longitude', 'precision_m'} que mandó el navegador, o None si
    faltan o no son coordenadas válidas. (0, 0) es lo que guardaba el registro
    anterior cuando no había ubicación: no cuenta.
    """
    datos = request.form if datos is None else datos
    lat, lng = _numero(datos.get('latitude')), _numero(datos.get('longitude'))
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    if lat == 0 and lng == 0:
        return None
    precision = _numero(datos.get('accuracy'))
    return {'latitude': lat, 'longitude': lng,
            'precision_m': precision if precision is not None and precision >= 0 else None}


def guardar_ubicacion(record_id, momento, ubicacion):
    """Agrega la ubicación de INICIO o FIN a la sesión (la confirma quien llama)."""
    if not ubicacion or not record_id:
        return False
    try:
        with db.session.begin_nested():
            db.session.add(TimeRecordLocation(
                time_record_id=record_id, momento=momento,
                latitude=ubicacion['latitude'], longitude=ubicacion['longitude'],
                precision_m=ubicacion.get('precision_m'), registrada_en=datetime.utcnow()))
        return True
    except SQLAlchemyError as e:
        _fallo('guardar la ubicación de %s del registro %s' % (momento, record_id), e)
        return False


def ubicaciones_de(registros):
    """
    {record_id: {'INICIO': {...}, 'FIN': {...}}} para pintar mapas.

    Los registros anteriores a esta tabla solo tienen la ubicación de inicio, en
    `time_records.latitude/longitude`; se usa esa cuando no hay otra.
    """
    registros = list(registros)
    resultado = {}
    ids = [r.id for r in registros]
    filas = []
    if ids:
        try:
            with db.session.begin_nested():
                filas = TimeRecordLocation.query.filter(
                    TimeRecordLocation.time_record_id.in_(ids)).all()
        except SQLAlchemyError as e:
            _fallo('leer ubicaciones', e)
    for f in filas:
        resultado.setdefault(f.time_record_id, {})[f.momento] = {
            'lat': f.latitude, 'lng': f.longitude, 'precision': f.precision_m,
            'cuando': f.registrada_en}
    for r in registros:
        if r.latitude and r.longitude and 'INICIO' not in resultado.get(r.id, {}):
            resultado.setdefault(r.id, {})['INICIO'] = {
                'lat': r.latitude, 'lng': r.longitude, 'precision': None, 'cuando': r.start_time}
    return resultado


# ─────────────────────────────────────────────────────────────
# Motivo de los cambios hechos desde Costos
# ─────────────────────────────────────────────────────────────
def motivo_del_form(datos=None):
    """El motivo elegido, o None si no es uno de la lista."""
    datos = request.form if datos is None else datos
    motivo = (datos.get('motivo') or '').strip()
    return motivo if motivo in MOTIVOS else None


def registrar_cambio(record_id, accion, motivo, detalle=None):
    """Agrega el cambio a la sesión (lo confirma quien llama)."""
    try:
        with db.session.begin_nested():
            db.session.add(TimeRecordChange(
                time_record_id=record_id, accion=accion, motivo=motivo,
                detalle=detalle or None, creado_en=datetime.utcnow(),
                user_id=current_user.id if current_user.is_authenticated else None))
        return True
    except SQLAlchemyError as e:
        _fallo('guardar el motivo del cambio del registro %s' % record_id, e)
        return False


def cambios_de(record_id):
    """Historial de un registro, del más reciente al más antiguo."""
    try:
        with db.session.begin_nested():
            return (TimeRecordChange.query
                    .options(joinedload(TimeRecordChange.usuario))
                    .filter_by(time_record_id=record_id)
                    .order_by(TimeRecordChange.creado_en.desc(), TimeRecordChange.id.desc())
                    .all())
    except SQLAlchemyError as e:
        _fallo('leer el historial del registro %s' % record_id, e)
        return []


def ultimo_cambio_de(ids):
    """{record_id: último cambio} para marcar en la tabla de Costos."""
    ids = list(ids)
    if not ids:
        return {}
    try:
        with db.session.begin_nested():
            filas = (TimeRecordChange.query
                     .options(joinedload(TimeRecordChange.usuario))
                     .filter(TimeRecordChange.time_record_id.in_(ids))
                     .order_by(TimeRecordChange.creado_en, TimeRecordChange.id)
                     .all())
    except SQLAlchemyError as e:
        _fallo('leer los motivos de cambio', e)
        return {}
    return {f.time_record_id: f for f in filas}

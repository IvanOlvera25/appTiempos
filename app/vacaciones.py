"""
Vacaciones y medios días: acceso a las tablas de AD17_RH.

Todo el estado de vacaciones vive en RH (tablas `Vacaciones`, `MediosDias`,
`Supervisores` y las reglas), no en la base de la app. Las vistas `registro` y
`empleados_activos` ya calculan el saldo, así que aquí no se replica esa lógica:

    num_vacaciones          días que le tocan por antigüedad (ReglasVacaciones)
    vacaciones_tomadas      COUNT de Vacaciones AUTORIZADAS dentro del periodo
    vacaciones_disponibles  num_vacaciones - vacaciones_tomadas

Ojo con un detalle de ese cálculo: **solo cuenta lo AUTORIZADO**. Una solicitud
PENDIENTE no baja el saldo, así que la app descuenta los pendientes por su
cuenta antes de dejar pedir más (ver `saldo_empleado`).

Cada fila de `Vacaciones` es UN día. Un rango se guarda como N filas.
"""
from datetime import date, timedelta

import pymysql
from flask import current_app

from .rh import rh_conn

ESTATUS = ('PENDIENTE', 'AUTORIZADO', 'DENEGADO')
TIPOS_MEDIO_DIA = ('INICIAL', 'FINAL')


class SinPermisoRH(RuntimeError):
    """
    El usuario de MySQL solo tiene SELECT sobre AD17_RH.

    Se traduce en un mensaje accionable en la UI en vez de un error 500: lo que
    falta es un GRANT, no código.
    """


def _ejecutar_escritura(sql, params):
    """INSERT/UPDATE sobre AD17_RH, convirtiendo el error de permisos."""
    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            afectadas = cur.rowcount
        conn.commit()
        return afectadas
    except pymysql.err.OperationalError as e:
        conn.rollback()
        # 1142 = comando denegado sobre la tabla; 1044 = acceso denegado a la BD
        if e.args and e.args[0] in (1142, 1044):
            raise SinPermisoRH(str(e.args[1] if len(e.args) > 1 else e)) from e
        raise
    finally:
        conn.close()


def _consultar(sql, params=()):
    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# Personal y saldos
# ─────────────────────────────────────────────────────────────
_CAMPOS_EMPLEADO = """
    id                     AS rh_id,
    nomPropio              AS nombre,
    id_area                AS area_id,
    titulo_area            AS area,
    titulo_posicion        AS puesto,
    antiguedad,
    fecha_ingreso,
    inicio_periodo_actual,
    proximo_aniversario,
    num_vacaciones,
    vacaciones_tomadas,
    vacaciones_disponibles,
    num_mediodia,
    mediodias_tomados,
    mediodias_disponibles
"""


def _normaliza_empleado(f):
    return {
        'rh_id': f['rh_id'],
        'nombre': (f['nombre'] or '').strip() or 'RH %s' % f['rh_id'],
        'area_id': f['area_id'],
        'area': (f['area'] or '').strip(),
        'puesto': (f['puesto'] or '').strip(),
        'antiguedad': int(f['antiguedad'] or 0),
        'fecha_ingreso': f['fecha_ingreso'],
        'inicio_periodo': f['inicio_periodo_actual'],
        'proximo_aniversario': f['proximo_aniversario'],
        'num_vacaciones': int(f['num_vacaciones'] or 0),
        'vacaciones_tomadas': int(f['vacaciones_tomadas'] or 0),
        'vacaciones_disponibles': int(f['vacaciones_disponibles'] or 0),
        'num_mediodia': int(f['num_mediodia'] or 0),
        'mediodias_tomados': int(f['mediodias_tomados'] or 0),
        'mediodias_disponibles': int(f['mediodias_disponibles'] or 0),
    }


def listar_empleados(solo_activos=True):
    """Personal con su saldo de vacaciones, ordenado por nombre."""
    vista = 'empleados_activos' if solo_activos else 'registro'
    filas = _consultar("SELECT %s FROM %s ORDER BY nomPropio" % (_CAMPOS_EMPLEADO, vista))
    return [_normaliza_empleado(f) for f in filas]


def empleado(rh_id):
    """Un empleado con su saldo, o None. Usa `registro` para no perder bajas."""
    filas = _consultar(
        "SELECT %s FROM registro WHERE id = %%s LIMIT 1" % _CAMPOS_EMPLEADO, (rh_id,))
    return _normaliza_empleado(filas[0]) if filas else None


def _pendientes(rh_id, inicio, fin):
    """Días PENDIENTES dentro del periodo (la vista de RH no los descuenta)."""
    if not inicio or not fin:
        return 0, 0
    vac = _consultar("""
        SELECT COUNT(*) AS n FROM Vacaciones
         WHERE rhID = %s AND estatus_autorizacion = 'PENDIENTE'
           AND fecha >= %s AND fecha < %s
    """, (rh_id, inicio, fin))[0]['n']
    med = _consultar("""
        SELECT COUNT(*) AS n FROM MediosDias
         WHERE rhID = %s AND estatus_autorizacion = 'PENDIENTE'
           AND fecha >= %s AND fecha < %s
    """, (rh_id, inicio, fin))[0]['n']
    return int(vac), int(med)


def saldo_empleado(rh_id):
    """
    Saldo de un empleado, con los pendientes ya descontados.

    `vacaciones_disponibles` viene de RH y solo resta lo autorizado; se expone
    además `vacaciones_libres` = disponibles - pendientes, que es lo que de
    verdad puede pedir sin pasarse.
    """
    datos = empleado(rh_id)
    if not datos:
        return None

    vac_pend, med_pend = _pendientes(
        rh_id, datos['inicio_periodo'], datos['proximo_aniversario'])

    datos['vacaciones_pendientes'] = vac_pend
    datos['mediodias_pendientes'] = med_pend
    datos['vacaciones_libres'] = max(0, datos['vacaciones_disponibles'] - vac_pend)
    datos['mediodias_libres'] = max(0, datos['mediodias_disponibles'] - med_pend)
    return datos


# ─────────────────────────────────────────────────────────────
# Supervisores
# ─────────────────────────────────────────────────────────────
def subordinados(sup_rh_id):
    """rhIDs que supervisa esta persona (relaciones activas)."""
    filas = _consultar(
        "SELECT DISTINCT rhID FROM Supervisores WHERE supRhID = %s AND activo = 1",
        (sup_rh_id,))
    return [f['rhID'] for f in filas]


def supervisores_de(rh_id):
    """Supervisores activos de un empleado, con nombre."""
    return _consultar("""
        SELECT s.regID, s.supRhID AS rh_id, r.nomPropio AS nombre, s.timestamp
          FROM Supervisores s
          LEFT JOIN registro r ON r.id = s.supRhID
         WHERE s.rhID = %s AND s.activo = 1
         ORDER BY r.nomPropio
    """, (rh_id,))


def mapa_supervisores():
    """{rhID empleado: [{rh_id, nombre}, ...]} para toda la plantilla."""
    filas = _consultar("""
        SELECT s.rhID, s.supRhID, r.nomPropio AS nombre
          FROM Supervisores s
          LEFT JOIN registro r ON r.id = s.supRhID
         WHERE s.activo = 1
         ORDER BY r.nomPropio
    """)
    mapa = {}
    for f in filas:
        mapa.setdefault(f['rhID'], []).append({
            'rh_id': f['supRhID'],
            'nombre': (f['nombre'] or '').strip() or 'RH %s' % f['supRhID']
        })
    return mapa


def asignar_supervisor(rh_id, sup_rh_id, registrado_por):
    """Alta de la relación supervisor→empleado. Idempotente si ya está activa."""
    if int(rh_id) == int(sup_rh_id):
        raise ValueError('Un empleado no puede ser su propio supervisor.')

    ya = _consultar("""
        SELECT regID FROM Supervisores
         WHERE rhID = %s AND supRhID = %s AND activo = 1 LIMIT 1
    """, (rh_id, sup_rh_id))
    if ya:
        return 0

    return _ejecutar_escritura("""
        INSERT INTO Supervisores (rhID, supRhID, regRhID, activo)
        VALUES (%s, %s, %s, 1)
    """, (rh_id, sup_rh_id, registrado_por))


def quitar_supervisor(reg_id):
    """Desactiva la relación en vez de borrarla: conserva el historial."""
    return _ejecutar_escritura(
        "UPDATE Supervisores SET activo = 0 WHERE regID = %s", (reg_id,))


# ─────────────────────────────────────────────────────────────
# Consulta de vacaciones y medios días
# ─────────────────────────────────────────────────────────────
def _marcadores(valores):
    return ','.join(['%s'] * len(valores))


def listar_vacaciones(rh_ids=None, desde=None, hasta=None, estatus=None):
    """
    Vacaciones y medios días de un conjunto de personas, en un rango.

    Devuelve una sola lista con `tipo` = 'VACACION' | 'MEDIO_DIA', que es lo que
    consume el calendario.
    """
    if rh_ids is not None and not rh_ids:
        return []

    filtros, params = [], []
    if rh_ids is not None:
        filtros.append("v.rhID IN (%s)" % _marcadores(rh_ids))
        params.extend(rh_ids)
    if desde:
        filtros.append("v.fecha >= %s")
        params.append(desde)
    if hasta:
        filtros.append("v.fecha <= %s")
        params.append(hasta)
    if estatus:
        filtros.append("v.estatus_autorizacion = %s")
        params.append(estatus)
    where = (' WHERE ' + ' AND '.join(filtros)) if filtros else ''

    def _consulta(tabla, tipo, extra_col):
        return """
            SELECT v.regID, v.rhID, v.fecha, v.estatus_autorizacion AS estatus,
                   v.rh_autorizacion, v.fecha_respuesta, v.fecha_solicitud,
                   %s AS tipo, %s,
                   r.nomPropio AS empleado, r.titulo_area AS area,
                   a.nomPropio AS autorizador
              FROM %s v
              LEFT JOIN registro r ON r.id = v.rhID
              LEFT JOIN registro a ON a.id = v.rh_autorizacion
            %s
        """ % ("'%s'" % tipo, extra_col, tabla, where)

    filas = _consultar(
        _consulta('Vacaciones', 'VACACION', "NULL AS momento")
        + " UNION ALL " +
        _consulta('MediosDias', 'MEDIO_DIA', "v.tipo AS momento")
        + " ORDER BY fecha, empleado",
        params + params
    )

    return [{
        'id': f['regID'],
        'rh_id': f['rhID'],
        'fecha': f['fecha'],
        'estatus': f['estatus'],
        'tipo': f['tipo'],
        'momento': f['momento'],
        'empleado': (f['empleado'] or '').strip() or 'RH %s' % f['rhID'],
        'area': (f['area'] or '').strip(),
        'autorizador': (f['autorizador'] or '').strip() or None,
        'fecha_respuesta': f['fecha_respuesta'],
        'fecha_solicitud': f['fecha_solicitud'],
    } for f in filas]


def solicitud(reg_id, tipo):
    """Una solicitud concreta, para validar permisos antes de responderla."""
    tabla = 'Vacaciones' if tipo == 'VACACION' else 'MediosDias'
    filas = _consultar(
        "SELECT regID, rhID, fecha, estatus_autorizacion AS estatus "
        "FROM %s WHERE regID = %%s LIMIT 1" % tabla, (reg_id,))
    return filas[0] if filas else None


# ─────────────────────────────────────────────────────────────
# Alta y respuesta de solicitudes
# ─────────────────────────────────────────────────────────────
def dias_habiles(desde, hasta, incluir_fines=False):
    """Lista de fechas del rango; por defecto sin sábados ni domingos."""
    dias, actual = [], desde
    while actual <= hasta:
        if incluir_fines or actual.weekday() < 5:
            dias.append(actual)
        actual += timedelta(days=1)
    return dias


def fechas_ocupadas(rh_id, fechas):
    """Fechas del conjunto que ya tienen vacación o medio día no denegado."""
    if not fechas:
        return set()
    m = _marcadores(fechas)
    filas = _consultar("""
        SELECT fecha FROM Vacaciones
         WHERE rhID = %%s AND estatus_autorizacion <> 'DENEGADO' AND fecha IN (%s)
        UNION
        SELECT fecha FROM MediosDias
         WHERE rhID = %%s AND estatus_autorizacion <> 'DENEGADO' AND fecha IN (%s)
    """ % (m, m), [rh_id] + list(fechas) + [rh_id] + list(fechas))
    return {f['fecha'] for f in filas}


def crear_solicitud_vacaciones(rh_id, fechas, autorizar_con=None):
    """
    Da de alta una fila de Vacaciones por cada fecha.

    `autorizar_con` es el rhID de quien autoriza: si viene, el alta nace ya
    AUTORIZADA (es lo que hace RH al capturar por otro empleado).
    """
    if not fechas:
        raise ValueError('No se indicaron fechas.')

    if autorizar_con:
        sql = ("INSERT INTO Vacaciones (rhID, fecha, estatus_autorizacion, "
               "rh_autorizacion, fecha_respuesta) VALUES (%s, %s, 'AUTORIZADO', %s, CURDATE())")
        params = [(rh_id, f, autorizar_con) for f in fechas]
    else:
        sql = "INSERT INTO Vacaciones (rhID, fecha, estatus_autorizacion) VALUES (%s, %s, 'PENDIENTE')"
        params = [(rh_id, f) for f in fechas]

    return _ejecutar_muchas(sql, params)


def crear_solicitud_medio_dia(rh_id, fecha, momento, autorizar_con=None):
    if momento not in TIPOS_MEDIO_DIA:
        raise ValueError('Tipo de medio día inválido.')

    if autorizar_con:
        return _ejecutar_escritura(
            "INSERT INTO MediosDias (rhID, fecha, tipo, estatus_autorizacion, "
            "rh_autorizacion, fecha_respuesta) VALUES (%s, %s, %s, 'AUTORIZADO', %s, CURDATE())",
            (rh_id, fecha, momento, autorizar_con))
    return _ejecutar_escritura(
        "INSERT INTO MediosDias (rhID, fecha, tipo, estatus_autorizacion) "
        "VALUES (%s, %s, %s, 'PENDIENTE')", (rh_id, fecha, momento))


def _ejecutar_muchas(sql, secuencia):
    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, secuencia)
            afectadas = cur.rowcount
        conn.commit()
        return afectadas
    except pymysql.err.OperationalError as e:
        conn.rollback()
        if e.args and e.args[0] in (1142, 1044):
            raise SinPermisoRH(str(e.args[1] if len(e.args) > 1 else e)) from e
        raise
    finally:
        conn.close()


def responder_solicitud(reg_id, tipo, autorizado, autorizador_rh_id):
    """
    Autoriza o deniega una solicitud pendiente.

    El WHERE exige que siga PENDIENTE: si dos supervisores responden a la vez,
    la segunda respuesta no pisa a la primera (devuelve 0 filas afectadas).
    """
    tabla = 'Vacaciones' if tipo == 'VACACION' else 'MediosDias'
    estatus = 'AUTORIZADO' if autorizado else 'DENEGADO'
    return _ejecutar_escritura("""
        UPDATE %s
           SET estatus_autorizacion = %%s,
               rh_autorizacion = %%s,
               fecha_respuesta = CURDATE()
         WHERE regID = %%s AND estatus_autorizacion = 'PENDIENTE'
    """ % tabla, (estatus, autorizador_rh_id, reg_id))


def cancelar_solicitud(reg_id, tipo, rh_id):
    """
    Un empleado retira su propia solicitud pendiente.

    Se marca DENEGADO en lugar de borrar: la tabla es el historial de RH y no
    tenemos por qué perder el rastro de lo que se pidió.
    """
    tabla = 'Vacaciones' if tipo == 'VACACION' else 'MediosDias'
    return _ejecutar_escritura("""
        UPDATE %s SET estatus_autorizacion = 'DENEGADO', fecha_respuesta = CURDATE()
         WHERE regID = %%s AND rhID = %%s AND estatus_autorizacion = 'PENDIENTE'
    """ % tabla, (reg_id, rh_id))


# ─────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────
def rh_id_de(employee):
    """
    rhID a partir de un Employee local.

    `n_empleado` es el rhID; se usa en vez de `Employee.id` para que esto
    funcione igual antes y después de convertir `employees` en vista de RH.
    """
    if not employee:
        return None
    try:
        return int(str(employee.n_empleado).strip())
    except (TypeError, ValueError):
        current_app.logger.warning(
            "vacaciones: n_empleado %r del empleado %s no es un rhID",
            getattr(employee, 'n_empleado', None), getattr(employee, 'id', None))
        return None


def rango_mes(anio, mes):
    """Primer y último día del mes indicado."""
    inicio = date(anio, mes, 1)
    fin = date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)
    return inicio, fin

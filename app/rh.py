"""
Acceso de solo lectura a las bases de RH (AD17_RH y AD17_General).

RH es la fuente de verdad del personal y del catalogo de areas; esta app nunca
escribe ahi. Todo lo que la app necesita saber de un empleado sale de la vista
`AD17_RH.empleados_activos`, de modo que un cambio de contrato en RH se resuelve
ajustando la vista y no el codigo de la aplicacion.
"""
import unicodedata

import pymysql
from flask import current_app


def rh_conn():
    """Conexion a la instancia MySQL que hospeda AD17_RH y AD17_General."""
    cfg = current_app.config
    return pymysql.connect(
        host=cfg.get('RH_DB_HOST', 'ad17solutions.dscloud.me'),
        port=int(cfg.get('RH_DB_PORT', 3307)),
        user=cfg.get('RH_DB_USER', 'IvanUriel'),
        password=cfg.get('RH_DB_PASSWORD', 'iuOp20!!25'),
        database=cfg.get('RH_DB_NAME', 'AD17_RH'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=25
    )


def _general_db():
    return current_app.config.get('GENERAL_DB_NAME', 'AD17_General')


def listar_areas():
    """
    Catalogo de areas de la empresa (AD17_General.Areas).

    Devuelve [{'id': regID, 'nombre': area}, ...]. Es la lista contra la que el
    administrador elige que areas habilita para registrar tiempos.
    """
    sql = "SELECT regID AS id, area AS nombre FROM `%s`.Areas ORDER BY area" % _general_db()
    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [{'id': r['id'], 'nombre': (r['nombre'] or '').strip()} for r in cur.fetchall()]
    finally:
        conn.close()


def listar_areas_seguro():
    """
    listar_areas() tolerante a fallos: si RH no responde devuelve lista vacia.

    Las pantallas de administracion deben seguir siendo usables aunque el
    servidor de RH este caido, por eso el catalogo remoto es opcional.
    """
    try:
        return listar_areas()
    except Exception as e:
        current_app.logger.warning("rh.listar_areas: no se pudo leer el catalogo de areas: %s", e)
        return []


def listar_empleados(area_id=None):
    """
    Personal vigente segun RH (vista AD17_RH.empleados_activos).

    Devuelve dicts con rh_id, nompropio, area_id, area y adicional.
    """
    sql = """
        SELECT id          AS rh_id,
               nomPropio   AS nompropio,
               id_area     AS area_id,
               titulo_area AS area,
               adicional   AS adicional
          FROM empleados_activos
    """
    params = []
    if area_id is not None:
        sql += " WHERE id_area = %s"
        params.append(area_id)
    sql += " ORDER BY nomPropio"

    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = cur.fetchall()
    finally:
        conn.close()

    return [{
        'rh_id': f['rh_id'],
        'nompropio': (f['nompropio'] or '').strip() or 'RH %s' % f['rh_id'],
        'area_id': f['area_id'],
        'area': (f['area'] or '').strip(),
        'adicional': float(f['adicional'] or 0)
    } for f in filas]


def listar_personal_completo():
    """
    Todo el personal que RH conoce, activo o no, con su ultimo dato de contrato.

    Es el mismo SELECT que arma la vista `employees` de la migracion
    c3f81b6e4a72; se replica aqui para que la sincronizacion por copia y la vista
    produzcan exactamente lo mismo el dia que esa migracion se pueda aplicar.
    """
    rh = current_app.config.get('RH_DB_NAME', 'AD17_RH')
    gen = _general_db()
    sql = """
        SELECT i.regID                  AS rh_id,
               COALESCE(d.nombre, '')   AS nombre,
               COALESCE(d.paterno, '')  AS paterno,
               COALESCE(d.materno, '')  AS materno,
               hp.areaID                AS area_id,
               COALESCE(a.area, '')     AS area,
               COALESCE(p.posicion, '') AS puesto,
               EXISTS (SELECT 1 FROM `{rh}`.empleados_activos ea
                        WHERE ea.id = i.regID) AS activo
          FROM `{rh}`.ID AS i
          LEFT JOIN `{rh}`.Datos AS d
                 ON d.rhID = i.regID
                AND d.regID = (SELECT MAX(d2.regID) FROM `{rh}`.Datos d2 WHERE d2.rhID = i.regID)
          LEFT JOIN `{rh}`.HistorialPosiciones AS hp
                 ON hp.rhID = i.regID
                AND hp.regID = (SELECT MAX(h2.regID) FROM `{rh}`.HistorialPosiciones h2 WHERE h2.rhID = i.regID)
          LEFT JOIN `{gen}`.Areas     AS a ON a.regID = hp.areaID
          LEFT JOIN `{rh}`.Posiciones AS p ON p.regID = hp.posicionID
         ORDER BY i.regID
    """.format(rh=rh, gen=gen)
    conn = rh_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            filas = cur.fetchall()
    finally:
        conn.close()
    return [{
        'rh_id': int(f['rh_id']),
        'nombre': (f['nombre'] or '').strip(),
        'paterno': (f['paterno'] or '').strip(),
        'materno': (f['materno'] or '').strip(),
        'area_id': f['area_id'],
        'area': (f['area'] or '').strip(),
        'puesto': (f['puesto'] or '').strip(),
        'activo': bool(f['activo']),
    } for f in filas]


def _palabras(nombre):
    """Palabras del nombre, sin acentos ni mayusculas, para comparar identidades."""
    plano = unicodedata.normalize('NFKD', nombre or '').encode('ascii', 'ignore').decode()
    return {t for t in plano.lower().split() if len(t) >= 3}


def sincronizar_empleados(dry_run=False):
    """
    Alinea la tabla local `employees` con el personal de RH.

    Sustituye a la migracion c3f81b6e4a72 mientras esta no se pueda aplicar
    (ver BUG_IMPRESION_ANALITICA.md): hace por copia lo que la vista haria en
    vivo. La llave del cruce es `n_empleado`, que guarda el rhID. Los ids
    locales no se tocan, asi que registros de tiempo y usuarios siguen
    apuntando a donde apuntaban.

    - Da de alta a quien RH tiene activo y aqui no existe.
    - Actualiza nombre, area, puesto y estado de quien ya existe.
    - No borra a nadie: una baja en RH solo pasa a inactivo aqui.

    Si RH no responde o devuelve vacio no se toca nada: una caida del servidor
    de RH no debe desactivar a todo el personal.

    Devuelve {'altas': [...], 'cambios': [...], 'bajas': [...],
    'reactivados': [...], 'conflictos': [...]} con nombres, para mostrarlo en
    pantalla. Un conflicto es un empleado local cuyo n_empleado apunta a otra
    persona en RH; se deja intacto para que alguien lo revise. Con dry_run=True
    calcula lo mismo pero no guarda.
    """
    from .models import db, Employee, AreaConfig

    personal = listar_personal_completo()
    if not personal:
        raise RuntimeError('RH no devolvio personal; no se sincroniza nada.')

    # El nombre del area lo pone areas_config, igual que en la vista: RH escribe
    # "Staging" y la app etiqueta "Stagging".
    mapa_areas = {
        a.rh_area_id: a.nombre
        for a in AreaConfig.query.filter(AreaConfig.rh_area_id.isnot(None)).all()
    }

    locales = {}
    for e in Employee.query.all():
        if (e.n_empleado or '').strip().isdigit():
            locales[int(e.n_empleado)] = e

    resumen = {'altas': [], 'cambios': [], 'bajas': [], 'reactivados': [], 'conflictos': []}
    vistos = set()

    for p in personal:
        rh_id = p['rh_id']
        vistos.add(rh_id)
        nompropio = ' '.join(x for x in (p['nombre'], p['paterno'], p['materno']) if x)
        datos = {
            'nompropio': nompropio[:150],
            'nombre': p['nombre'][:50],
            'apellido_paterno': p['paterno'][:50],
            'apellido_materno': p['materno'][:50],
            'departamento': (mapa_areas.get(p['area_id']) or p['area'] or 'N/A')[:100],
            'puesto': p['puesto'][:100],
        }

        e = locales.get(rh_id)
        if e is None:
            # Ex-empleados que nunca registraron tiempo aqui no hacen falta.
            if not p['activo']:
                continue
            resumen['altas'].append(nompropio)
            if not dry_run:
                # qr_code es unico; los ids locales viejos ya ocupan qr_<id>.png
                db.session.add(Employee(
                    n_empleado=str(rh_id), qr_code='qr_rh%d.png' % rh_id,
                    active=True, **datos))
            continue

        # Si el nombre no comparte ni una palabra con el de RH, ese rhID es de
        # otra persona (n_empleado capturado a mano y mal). Renombrarlo le
        # regalaria a esa otra persona todo el historial de tiempos.
        if e.nompropio and not (_palabras(e.nompropio) & _palabras(nompropio)):
            resumen['conflictos'].append('%s (rhID %d es %s en RH)' % (e.nompropio, rh_id, nompropio))
            continue

        cambios = [k for k, v in datos.items() if (getattr(e, k) or '') != v]
        if cambios:
            resumen['cambios'].append('%s (%s)' % (e.nompropio, ', '.join(cambios)))
            if not dry_run:
                for k, v in datos.items():
                    setattr(e, k, v)
        if bool(e.active) != p['activo']:
            resumen['reactivados' if p['activo'] else 'bajas'].append(e.nompropio)
            if not dry_run:
                e.active = p['activo']

    # Gente que RH ya no tiene ni en su catalogo: baja.
    for rh_id, e in locales.items():
        if rh_id not in vistos and e.active:
            resumen['bajas'].append(e.nompropio)
            if not dry_run:
                e.active = False

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return resumen

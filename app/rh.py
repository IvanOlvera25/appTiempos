"""
Acceso de solo lectura a las bases de RH (AD17_RH y AD17_General).

RH es la fuente de verdad del personal y del catalogo de areas; esta app nunca
escribe ahi. Todo lo que la app necesita saber de un empleado sale de la vista
`AD17_RH.empleados_activos`, de modo que un cambio de contrato en RH se resuelve
ajustando la vista y no el codigo de la aplicacion.
"""
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

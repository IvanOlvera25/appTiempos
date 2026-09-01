#!/usr/bin/env python3
"""
Verificación previa a la migración c3f81b6e4a72 (employees -> vista de AD17_RH).

Es de SOLO LECTURA: no modifica nada. Corre los mismos chequeos que hace la
migración antes de tocar datos, más una prueba del SELECT de la vista, para que
sepas si la migración va a pasar limpia antes de ejecutarla.

    python verificarMigracionRH.py

Sal con código 0 = listo para migrar; 1 = hay que corregir algo primero.
"""
import sys

import pymysql

APP_DB = 'AD17_Pruebas'
RH_DB = 'AD17_RH'
GENERAL_DB = 'AD17_General'

CONEXION = {
    'host': 'ad17solutions.dscloud.me',
    'port': 3307,
    'user': 'IvanUriel',
    'password': 'iuOp20!!25',
    'charset': 'utf8mb4',
}

# Mismo SELECT que publica la migración como vista `employees`.
SELECT_VISTA = """
SELECT
    i.regID                                   AS id,
    CAST(i.regID AS CHAR(20))                 AS n_empleado,
    TRIM(CONCAT(COALESCE(d.nombre, ''), ' ',
                COALESCE(d.paterno, ''), ' ',
                COALESCE(d.materno, '')))     AS nompropio,
    COALESCE(d.nombre, '')                    AS nombre,
    COALESCE(d.paterno, '')                   AS apellido_paterno,
    COALESCE(d.materno, '')                   AS apellido_materno,
    COALESCE(ac.nombre, a.area, 'N/A')        AS departamento,
    COALESCE(p.posicion, '')                  AS puesto,
    CONCAT('qr_', i.regID, '.png')            AS qr_code,
    CASE WHEN EXISTS (
        SELECT 1 FROM `{rh}`.empleados_activos ea WHERE ea.id = i.regID
    ) THEN 1 ELSE 0 END                       AS active
FROM `{rh}`.ID AS i
LEFT JOIN `{rh}`.Datos AS d
       ON d.rhID = i.regID
      AND d.regID = (SELECT MAX(d2.regID) FROM `{rh}`.Datos d2 WHERE d2.rhID = i.regID)
LEFT JOIN `{rh}`.HistorialPosiciones AS hp
       ON hp.rhID = i.regID
      AND hp.regID = (SELECT MAX(h2.regID) FROM `{rh}`.HistorialPosiciones h2 WHERE h2.rhID = i.regID)
LEFT JOIN `{gen}`.Areas     AS a ON a.regID = hp.areaID
LEFT JOIN `{rh}`.Posiciones AS p ON p.regID = hp.posicionID
{areas}
""".format(rh=RH_DB, gen=GENERAL_DB, app=APP_DB,
           areas='LEFT JOIN `%s`.areas_config AS ac ON ac.rh_area_id = a.regID' % APP_DB)

# Mismo SELECT, pero con un sustituto de areas_config para poder validar los
# joins contra AD17_RH antes de que corra la migración que crea esa tabla.
SELECT_VISTA_SIN_AREAS = SELECT_VISTA.replace(
    'LEFT JOIN `%s`.areas_config AS ac ON ac.rh_area_id = a.regID' % APP_DB,
    'LEFT JOIN (SELECT NULL AS nombre, NULL AS rh_area_id) AS ac ON ac.rh_area_id = a.regID')


def titulo(texto):
    print("\n" + "=" * 68)
    print(texto)
    print("=" * 68)


def main():
    problemas = []
    avisos = []

    conn = pymysql.connect(database=APP_DB, cursorclass=pymysql.cursors.DictCursor, **CONEXION)
    cur = conn.cursor()

    titulo("1. Versión de MySQL")
    cur.execute("SELECT VERSION() AS v")
    version = cur.fetchone()['v']
    print("  ", version)
    print("   La vista usa subconsultas correlacionadas (no derivadas en el FROM),")
    print("   así que es válida también en MySQL 5.7.")

    titulo("2. ¿`employees` sigue siendo tabla?")
    cur.execute("""
        SELECT TABLE_TYPE FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'employees'
    """, (APP_DB,))
    fila = cur.fetchone()
    if not fila:
        problemas.append("No existe `employees` en %s." % APP_DB)
        print("   NO EXISTE")
    elif fila['TABLE_TYPE'] == 'VIEW':
        print("   Ya es una VISTA: la migración ya se aplicó.")
        cur.execute("SELECT COUNT(*) AS n FROM employees")
        print("   Empleados visibles:", cur.fetchone()['n'])
        conn.close()
        return 0
    else:
        print("   Es tabla (BASE TABLE). Se puede migrar.")

    titulo("3. Empleados locales mapeables a rhID")
    cur.execute("SELECT COUNT(*) AS n FROM employees")
    print("   Empleados locales:", cur.fetchone()['n'])

    cur.execute("""
        SELECT id, n_empleado, nompropio FROM employees
         WHERE n_empleado IS NULL OR n_empleado = '' OR n_empleado NOT REGEXP '^[0-9]+$'
    """)
    filas = cur.fetchall()
    if filas:
        problemas.append("%d empleados con n_empleado no numérico." % len(filas))
        print("   n_empleado NO numérico:")
        for f in filas:
            print("     id=%s n_empleado=%r  %s" % (f['id'], f['n_empleado'], f['nompropio']))
    else:
        print("   Todos los n_empleado son numéricos. OK")

    cur.execute("""
        SELECT e.id, e.n_empleado, e.nompropio
          FROM employees e
         WHERE e.n_empleado REGEXP '^[0-9]+$'
           AND NOT EXISTS (SELECT 1 FROM `%s`.ID i WHERE i.regID = CAST(e.n_empleado AS UNSIGNED))
    """ % RH_DB)
    filas = cur.fetchall()
    if filas:
        problemas.append("%d empleados locales no existen en %s.ID." % (len(filas), RH_DB))
        print("   NO existen en %s.ID:" % RH_DB)
        for f in filas:
            print("     id=%s rhID=%s  %s" % (f['id'], f['n_empleado'], f['nompropio']))
    else:
        print("   Todos existen en %s.ID. OK" % RH_DB)

    cur.execute("""
        SELECT n_empleado, COUNT(*) AS n FROM employees
         GROUP BY n_empleado HAVING COUNT(*) > 1
    """)
    filas = cur.fetchall()
    if filas:
        problemas.append("%d n_empleado repetidos." % len(filas))
        print("   n_empleado REPETIDO:", [(f['n_empleado'], f['n']) for f in filas])
    else:
        print("   Sin n_empleado repetidos. OK")

    titulo("4. Integridad de los registros de tiempo")
    cur.execute("""
        SELECT COUNT(*) AS n FROM time_records tr
         WHERE NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = tr.employee_id)
    """)
    huerfanos = cur.fetchone()['n']
    if huerfanos:
        problemas.append("%d registros de tiempo huérfanos." % huerfanos)
        print("   Registros huérfanos:", huerfanos)
    else:
        print("   Sin registros huérfanos. OK")

    cur.execute("""
        SELECT COUNT(*) AS n FROM users u
         WHERE u.employee_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = u.employee_id)
    """)
    usuarios = cur.fetchone()['n']
    if usuarios:
        problemas.append("%d usuarios ligados a un empleado inexistente." % usuarios)
        print("   Usuarios huérfanos:", usuarios)
    else:
        print("   Sin usuarios huérfanos. OK")

    titulo("5. El SELECT de la vista se ejecuta")
    cur.execute("""
        SELECT COUNT(*) AS n FROM information_schema.TABLES
         WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'areas_config'
    """, (APP_DB,))
    hay_areas_config = bool(cur.fetchone()['n'])
    select = SELECT_VISTA if hay_areas_config else SELECT_VISTA_SIN_AREAS
    if not hay_areas_config:
        avisos.append("Todavía no existe %s.areas_config: corre antes "
                      "`flask db upgrade b7a2c9f14d30`. Los joins contra AD17_RH "
                      "sí se verificaron." % APP_DB)
        print("   areas_config aún no existe; se verifica con un sustituto.")

    try:
        cur.execute(select + " ORDER BY id LIMIT 5")
        muestra = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS n FROM (%s) v" % select)
        total = cur.fetchone()['n']
        print("   Filas que devolvería la vista:", total)
        for f in muestra:
            print("     #%s %-28s | %-16s | %-18s | activo=%s"
                  % (f['id'], f['nompropio'][:28], f['departamento'][:16],
                     f['puesto'][:18], f['active']))
    except Exception as e:
        problemas.append("El SELECT de la vista falla: %s" % e)
        print("   ERROR:", e)
        total = None

    titulo("6. Cobertura: cada empleado local debe aparecer en la vista")
    if total is not None:
        try:
            cur.execute("""
                SELECT e.id, e.n_empleado, e.nompropio
                  FROM employees e
                 WHERE NOT EXISTS (
                       SELECT 1 FROM (%s) v WHERE v.id = CAST(e.n_empleado AS UNSIGNED))
            """ % select)
            filas = cur.fetchall()
            if filas:
                problemas.append("%d empleados locales no aparecerían en la vista." % len(filas))
                print("   NO aparecen en la vista:")
                for f in filas:
                    print("     id=%s rhID=%s  %s" % (f['id'], f['n_empleado'], f['nompropio']))
            else:
                print("   Todos aparecen en la vista. OK")
        except Exception as e:
            avisos.append("No se pudo comprobar la cobertura: %s" % e)
            print("   No se pudo comprobar:", e)

    titulo("7. Áreas: enlace areas_config.rh_area_id -> AD17_General.Areas")
    if not hay_areas_config:
        print("   Pendiente: la tabla se crea en la migración b7a2c9f14d30.")
        areas, sin_enlace = [], []
    else:
        cur.execute("SELECT id, nombre, rh_area_id, activa FROM areas_config ORDER BY orden")
        areas = cur.fetchall()
        sin_enlace = [a['nombre'] for a in areas if a['rh_area_id'] is None]
        for a in areas:
            print("   %-18s rh_area_id=%-6s activa=%s"
                  % (a['nombre'], a['rh_area_id'] if a['rh_area_id'] is not None else '—',
                     a['activa']))
        if sin_enlace:
            avisos.append(
                "Áreas sin enlazar a RH (%s): la vista mostrará el nombre literal de "
                "AD17_General.Areas para esa gente." % ', '.join(sin_enlace))

    titulo("8. Permiso para crear vistas")
    try:
        cur.execute("SHOW GRANTS")
        grants = [list(g.values())[0] for g in cur.fetchall()]
        texto = " ".join(grants)
        if 'ALL PRIVILEGES' in texto or 'CREATE VIEW' in texto:
            print("   El usuario puede crear vistas. OK")
        else:
            avisos.append("No se detectó el privilegio CREATE VIEW en %s." % APP_DB)
            print("   No se detectó CREATE VIEW. Grants:")
            for g in grants:
                print("    ", g)
    except Exception as e:
        avisos.append("No se pudieron leer los grants: %s" % e)
        print("   No se pudieron leer:", e)

    conn.close()

    titulo("RESULTADO")
    for a in avisos:
        print("   AVISO:", a)
    if problemas:
        print("\n   NO migrar todavía. Hay que corregir:")
        for p in problemas:
            print("     -", p)
        return 1

    print("\n   Listo para migrar.")
    print("   Respalda primero:")
    print("     mysqldump -h %s -P %s -u %s -p %s > respaldo.sql"
          % (CONEXION['host'], CONEXION['port'], CONEXION['user'], APP_DB))
    print("   Y luego:  flask db upgrade")
    return 0


if __name__ == '__main__':
    sys.exit(main())

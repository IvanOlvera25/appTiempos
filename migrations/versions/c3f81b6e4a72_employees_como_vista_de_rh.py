"""employees deja de ser tabla y pasa a ser una vista sobre AD17_RH

RH es la fuente de verdad del personal. Hasta ahora la app mantenía una copia en
`employees` que había que reimportar a mano; a partir de aquí `employees` es una
vista de solo lectura y `employee_id` guarda directamente el rhID.

La migración es destructiva (reescribe employee_id en time_records y users), así
que hace una verificación previa y aborta si algo no cuadra. La tabla original
NO se borra: se conserva como `employees_legacy` y el downgrade la restaura.

Va al final de la cadena a propósito: todo lo demás (áreas, perfiles nuevos e
incidencias) es aditivo y se puede aplicar sin tocar los datos, con
`flask db upgrade d4e19a7c5b83`. Esta se corre aparte, cuando se decida.

PRUÉBALA SOBRE UNA COPIA DE LA BASE ANTES DE CORRERLA EN PRODUCCIÓN.

Revision ID: c3f81b6e4a72
Revises: d4e19a7c5b83
Create Date: 2026-09-01 10:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f81b6e4a72'
down_revision = 'd4e19a7c5b83'
branch_labels = None
depends_on = None

RH_DB = 'AD17_RH'
GENERAL_DB = 'AD17_General'


# La vista usa subconsultas correlacionadas en lugar de derivadas en el FROM
# porque MySQL no permite subconsultas en el FROM de una vista antes de 8.0.14.
#
# `departamento` se resuelve contra areas_config: así el nombre del área que ve
# la app es el que el administrador configuró (y con el que están etiquetados los
# registros históricos), no el literal de AD17_General.Areas.
_VIEW_SQL = """
CREATE SQL SECURITY INVOKER VIEW employees AS
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
LEFT JOIN areas_config      AS ac ON ac.rh_area_id = a.regID
""".format(rh=RH_DB, gen=GENERAL_DB)


def _fks(bind, tabla, columna):
    """Nombres de los FK de `tabla.columna` que apuntan a employees."""
    insp = sa.inspect(bind)
    return [
        fk['name'] for fk in insp.get_foreign_keys(tabla)
        if fk.get('referred_table') == 'employees'
        and columna in (fk.get('constrained_columns') or [])
        and fk.get('name')
    ]


def _verificar(bind):
    """
    Aborta la migración si los datos locales no se pueden mapear a rhID.

    Sin esto, un empleado dado de alta a mano (con un n_empleado inventado) haría
    que sus registros de tiempo apuntaran a un rhID que no existe o, peor, al de
    otra persona.
    """
    problemas = []

    no_numericos = bind.execute(sa.text("""
        SELECT id, n_empleado, nompropio FROM employees
         WHERE n_empleado IS NULL OR n_empleado = '' OR n_empleado NOT REGEXP '^[0-9]+$'
    """)).fetchall()
    if no_numericos:
        problemas.append(
            "Empleados cuyo n_empleado no es un rhID numérico:\n" +
            "\n".join("  id=%s n_empleado=%r %s" % (r[0], r[1], r[2]) for r in no_numericos)
        )

    ausentes = bind.execute(sa.text("""
        SELECT e.id, e.n_empleado, e.nompropio
          FROM employees e
         WHERE e.n_empleado REGEXP '^[0-9]+$'
           AND NOT EXISTS (SELECT 1 FROM `%s`.ID i WHERE i.regID = CAST(e.n_empleado AS UNSIGNED))
    """ % RH_DB)).fetchall()
    if ausentes:
        problemas.append(
            "Empleados que no existen en %s.ID:\n" % RH_DB +
            "\n".join("  id=%s rhID=%s %s" % (r[0], r[1], r[2]) for r in ausentes)
        )

    duplicados = bind.execute(sa.text("""
        SELECT n_empleado, COUNT(*) FROM employees
         GROUP BY n_empleado HAVING COUNT(*) > 1
    """)).fetchall()
    if duplicados:
        problemas.append(
            "n_empleado repetido (el remapeo fusionaría personas distintas):\n" +
            "\n".join("  rhID=%s x%s" % (r[0], r[1]) for r in duplicados)
        )

    huerfanos = bind.execute(sa.text("""
        SELECT COUNT(*) FROM time_records tr
         WHERE NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = tr.employee_id)
    """)).scalar()
    if huerfanos:
        problemas.append(
            "%d registros de tiempo apuntan a un empleado inexistente; "
            "límpialos antes de migrar." % huerfanos
        )

    # Un usuario huérfano no lo reescribiría el JOIN y se quedaría apuntando a
    # un id local que después significa otra persona.
    usuarios = bind.execute(sa.text("""
        SELECT COUNT(*) FROM users u
         WHERE u.employee_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = u.employee_id)
    """)).scalar()
    if usuarios:
        problemas.append(
            "%d usuarios están ligados a un empleado inexistente; "
            "corrige su employee_id antes de migrar." % usuarios
        )

    if problemas:
        raise RuntimeError(
            "No se puede convertir `employees` en vista todavía.\n\n"
            + "\n\n".join(problemas)
            + "\n\nCorrige estos casos en AD17_RH (o en la tabla local) y vuelve a intentar."
        )


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table('employees'):
        # Ya migrado: `employees` es la vista, no aparece como tabla.
        return

    _verificar(bind)

    # 1) Quitar los FK: una vista no puede ser destino de una llave foránea.
    for tabla, columna in (('time_records', 'employee_id'), ('users', 'employee_id')):
        for nombre in _fks(bind, tabla, columna):
            op.drop_constraint(nombre, tabla, type_='foreignkey')

    # 2) Reescribir employee_id: id local -> rhID.
    #
    # `users.employee_id` tiene índice ÚNICO y MySQL actualiza fila por fila, así
    # que el mapeo directo choca en cuanto un usuario recibe un rhID que otro
    # usuario todavía trae como id local. Se pasa primero por valores negativos,
    # que no pueden colisionar con los positivos, y luego se les quita el signo.
    bind.execute(sa.text("""
        UPDATE users u
          JOIN employees e ON e.id = u.employee_id
           SET u.employee_id = -CAST(e.n_empleado AS SIGNED)
    """))
    bind.execute(sa.text("""
        UPDATE users SET employee_id = -employee_id WHERE employee_id < 0
    """))

    # time_records.employee_id no es único, así que aquí sí basta una pasada.
    bind.execute(sa.text("""
        UPDATE time_records tr
          JOIN employees e ON e.id = tr.employee_id
           SET tr.employee_id = CAST(e.n_empleado AS UNSIGNED)
    """))

    # 3) Conservar la tabla original como respaldo y publicar la vista.
    if insp.has_table('employees_legacy'):
        op.execute("DROP TABLE employees_legacy")
    op.execute("RENAME TABLE employees TO employees_legacy")
    op.execute(_VIEW_SQL)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table('employees_legacy'):
        raise RuntimeError(
            "No existe employees_legacy: no hay cómo reconstruir la tabla original."
        )

    op.execute("DROP VIEW IF EXISTS employees")
    op.execute("RENAME TABLE employees_legacy TO employees")

    # rhID -> id local, usando el mapeo que la propia tabla conserva. Mismo
    # rodeo por negativos que en upgrade(), por el índice único de users.
    bind.execute(sa.text("""
        UPDATE users u
          JOIN employees e ON CAST(e.n_empleado AS SIGNED) = u.employee_id
           SET u.employee_id = -e.id
    """))
    bind.execute(sa.text("""
        UPDATE users SET employee_id = -employee_id WHERE employee_id < 0
    """))
    bind.execute(sa.text("""
        UPDATE time_records tr
          JOIN employees e ON CAST(e.n_empleado AS UNSIGNED) = tr.employee_id
           SET tr.employee_id = e.id
    """))

    op.create_foreign_key('fk_time_records_employee_id', 'time_records', 'employees',
                          ['employee_id'], ['id'])
    op.create_foreign_key('fk_users_employee_id', 'users', 'employees',
                          ['employee_id'], ['id'])

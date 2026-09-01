"""
Catalogos configurables de la app: areas que registran tiempo y sus actividades.

Antes ambos vivian hardcodeados (listas en routes.py, botones en las plantillas).
Aqui quedan en base de datos para que un administrador pueda dar de alta areas
nuevas y editar sus actividades sin tocar codigo.
"""
from flask import current_app
from sqlalchemy import asc, func
from sqlalchemy.exc import OperationalError, ProgrammingError

from . import db
from .models import AreaConfig, DepartmentActivity

# Las actividades del proyecto especial FP 0 se guardan en la misma tabla que
# las de area, bajo un departamento centinela que ningun area puede usar.
GENERAL_KEY = '__GENERAL__'
GENERAL_LABEL = 'Generales (FP 0)'


# ─────────────────────────────────────────────────────────────
# Areas
# ─────────────────────────────────────────────────────────────
_AREAS_SEED = [
    ('Metal',          'estandar'),
    ('Costura',        'estandar'),
    ('Impresion',      'impresion'),
    ('Stagging',       'estandar'),
    ('Montaje',        'estandar'),
    ('Transporte',     'estandar'),
    ('Administración', 'estandar'),
]


def ensure_seed_areas():
    """Siembra las areas historicas la primera vez que se consulta la tabla."""
    if db.session.query(AreaConfig.id).first():
        return
    db.session.bulk_save_objects([
        AreaConfig(nombre=nombre, flujo=flujo, activa=True, orden=idx)
        for idx, (nombre, flujo) in enumerate(_AREAS_SEED)
    ])
    db.session.commit()


def _areas_de_respaldo():
    """
    Las areas historicas, en memoria y sin tocar la base.

    Solo se usan si `areas_config` todavia no existe (falta correr
    `flask db upgrade`). Sin este respaldo la app se quedaria sin ninguna area y
    nadie podria registrar tiempos, que es peor que seguir con las de siempre.
    """
    return [AreaConfig(id=None, nombre=nombre, flujo=flujo, activa=True, orden=idx)
            for idx, (nombre, flujo) in enumerate(_AREAS_SEED)]


def get_areas(solo_activas=True):
    """Areas configuradas, en el orden en que deben mostrarse."""
    try:
        ensure_seed_areas()
        q = AreaConfig.query
        if solo_activas:
            q = q.filter(AreaConfig.activa.is_(True))
        return q.order_by(asc(AreaConfig.orden), asc(AreaConfig.nombre)).all()
    except (OperationalError, ProgrammingError) as e:
        db.session.rollback()
        current_app.logger.error(
            "areas_config no esta disponible (%s). Se usan las areas historicas; "
            "corre `flask db upgrade` para poder administrarlas.",
            str(e).split('\n')[0])
        return _areas_de_respaldo()


def get_area_names(solo_activas=True):
    return [a.nombre for a in get_areas(solo_activas=solo_activas)]


def get_area(nombre):
    """Area por nombre exacto (el valor guardado en TimeRecord.departamento)."""
    if not nombre:
        return None
    objetivo = nombre.strip()
    # Se resuelve sobre get_areas() para heredar su respaldo cuando la tabla
    # todavia no existe.
    for area in get_areas(solo_activas=False):
        if area.nombre == objetivo:
            return area
    return None


def area_usa_flujo_impresion(nombre):
    """True si el area usa el flujo multi-registro que estrenó Impresion."""
    area = get_area(nombre)
    return bool(area and area.flujo == 'impresion')


def next_area_order():
    return (db.session.query(func.max(AreaConfig.orden)).scalar() or 0) + 1


# ─────────────────────────────────────────────────────────────
# Actividades
# ─────────────────────────────────────────────────────────────
_ACTIVIDADES_SEED = {
    "Metal": [
        "Revisión de planos e información del proyecto",
        "Solicitud de material a almacén",
        "Medidas", "Corte", "Swaging", "Rolado",
        "Barrido y pulido", "Soldadura", "Armado"
    ],
    "Costura": [
        "Revisión de planos, artes e información del proyecto",
        "Solicitud de material a almacén",
        "Corte", "Limpieza de estructura",
        "Medición de lienzos en estructura", "Costura",
        "Prueba en estructura", "Despunte y over", "Doblar y empacar"
    ],
    "Impresion": [
        "Revisión de orden de impresión, artes e información del proyecto",
        "Solicitud de material a almacén",
        "Ripeo", "Acomodo de gráficos en plotter",
        "Impresión de papel en plotter Stitch",
        "Impresión de papel en plotter papyrus",
        "Impresión de papel en plotter 570",
        "Sublimado de tela", "Entrega de gráficos a LP"
    ],
    "Stagging": [
        "Revisión de planos, ordenes de costura e información del proyecto",
        "Revisión de estructuras piezas de metal", "Marcado de estructuras",
        "Revisión de fundas", "Solicitud de material a almacén",
        "Empaque", "Documentación", "Carga/Entrega"
    ],
    "Montaje": [
        "Montaje", "Desmontaje", "Recoleccion de Materiales y Herramientas",
        "Cargar Transporte", "Translado",
        "Retorno de Materiales y Herramientas", "En espera de acceso"
    ],
    "Transporte": [
        "Carga", "Descarga",
        "Translado para Entrega/Montaje/Desmontaje", "Translado para Compras",
        "Esperando permiso de acceso", "Esperando entrega de material de proveedor",
        "Preparacion para Translado", "Mantenimiento de Vehiculos"
    ],
    # Actividades que aparecen ademas de las del area al registrar sobre el FP 0.
    GENERAL_KEY: [
        "Limpieza de taller", "Escombrar y acomodar", "Gestión de materiales",
        "Reciclado", "Mantenimiento", "Fabricar accesorios",
        "Construcción y obra", "Administración y coordinación", "Job costing",
        "Apoyo a comercialización", "Preparación de maquinaria"
    ],
}


def ensure_seed_activities():
    """
    Siembra el catalogo de actividades.

    Se siembra grupo por grupo: asi las actividades generales del FP 0 aparecen
    tambien en instalaciones que ya tenian sembradas las de area.
    """
    existentes = {
        d for (d,) in db.session.query(DepartmentActivity.department).distinct()
    }
    faltantes = [d for d in _ACTIVIDADES_SEED if d not in existentes]
    if not faltantes:
        return

    db.session.bulk_save_objects([
        DepartmentActivity(department=dept, name=name, is_active=True, sort_order=idx)
        for dept in faltantes
        for idx, name in enumerate(_ACTIVIDADES_SEED[dept])
    ])
    db.session.commit()


def get_department_activities(dept):
    """Nombres de las actividades activas de un area, en su orden configurado."""
    if not dept:
        return []
    rows = (DepartmentActivity.query
            .filter_by(department=dept, is_active=True)
            .order_by(asc(DepartmentActivity.sort_order), asc(DepartmentActivity.id))
            .all())
    return [r.name for r in rows]


def get_general_activities():
    """Actividades adicionales que se ofrecen al registrar sobre el FP 0."""
    ensure_seed_activities()
    return get_department_activities(GENERAL_KEY)


def activity_departments():
    """
    Opciones validas del selector de departamento en el admin de actividades:
    las areas configuradas mas el grupo de actividades generales del FP 0.
    """
    opciones = [(a.nombre, a.nombre) for a in get_areas(solo_activas=False)]
    opciones.append((GENERAL_KEY, GENERAL_LABEL))
    return opciones


def department_label(dept):
    return GENERAL_LABEL if dept == GENERAL_KEY else dept


# ─────────────────────────────────────────────────────────────
# Clasificaciones de incidencia
# ─────────────────────────────────────────────────────────────
_CLASIFICACIONES_SEED = [
    'Retrabajo',
    'Material defectuoso',
    'Falta de material',
    'Error de medidas o planos',
    'Retraso en entrega',
    'Daño en montaje',
    'Cambio solicitado por el cliente',
    'Falla de equipo o maquinaria',
    'Accidente o incidente de seguridad',
    'Otro',
]


def ensure_seed_clasificaciones():
    from .models import IncidentClassification
    if db.session.query(IncidentClassification.id).first():
        return
    db.session.bulk_save_objects([
        IncidentClassification(nombre=nombre, activa=True, orden=idx)
        for idx, nombre in enumerate(_CLASIFICACIONES_SEED)
    ])
    db.session.commit()


def get_clasificaciones(solo_activas=True):
    from .models import IncidentClassification
    try:
        ensure_seed_clasificaciones()
        q = IncidentClassification.query
        if solo_activas:
            q = q.filter(IncidentClassification.activa.is_(True))
        return q.order_by(asc(IncidentClassification.orden),
                          asc(IncidentClassification.nombre)).all()
    except (OperationalError, ProgrammingError) as e:
        db.session.rollback()
        current_app.logger.error(
            "incident_classifications no esta disponible (%s); corre "
            "`flask db upgrade`.", str(e).split('\n')[0])
        return []


def next_clasificacion_order():
    from .models import IncidentClassification
    return (db.session.query(func.max(IncidentClassification.orden)).scalar() or 0) + 1

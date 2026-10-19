"""
Menú de la aplicación, definido una sola vez.

La barra lateral y la paleta de comandos (Ctrl/⌘ + K) se construyen con lo que
devuelve `menu_para`, así que un permiso se cambia en un solo lugar. Las reglas
de visibilidad son las mismas que tenía la barra de navegación anterior.
"""
from flask import request, url_for
from flask_login import current_user


def _item(etiqueta, icono, endpoint, activos=(), **kwargs):
    actual = request.endpoint or ''
    return {
        'label': etiqueta,
        'icon': icono,
        'url': url_for(endpoint, **kwargs),
        'active': actual == endpoint or actual in activos,
    }


def menu_para(user):
    """Secciones del menú lateral visibles para `user`."""
    autenticado = user.is_authenticated
    admin_priv = autenticado and user.has_admin_privileges
    es_admin = autenticado and user.is_admin
    jefe_area = autenticado and getattr(user, 'is_area_manager', False)
    es_rh = autenticado and getattr(user, 'is_rh', False)

    secciones = []

    general = [_item('Registro de tiempos', 'bi-stopwatch', 'main.home',
                     activos=('main.register_employee', 'main.register_project',
                              'main.register_project_imp'))]
    if admin_priv:
        general.insert(0, _item('Dashboard', 'bi-grid-1x2', 'main.admin_dashboard'))
    if not (autenticado and user.is_employee):
        general.append(_item('Mapa en vivo', 'bi-geo-alt', 'main.map'))
    secciones.append({'title': None, 'items': general})

    if admin_priv:
        operacion = [
            _item('Empleados', 'bi-people', 'main.manage_employees'),
            _item('Adicionales', 'bi-calendar2-plus', 'main.adicionales_admin'),
        ]
        if es_admin:
            operacion.append(_item('Costos y registros', 'bi-receipt', 'main.costs_dashboard',
                                   activos=('main.create_time_record', 'main.edit_time_record')))
        secciones.append({'title': 'Operación', 'items': operacion})

        secciones.append({'title': 'Proyectos', 'items': [
            _item('Proyectos', 'bi-kanban', 'main.project_page', activos=('main.edit_project',)),
            _item('Análisis de proyecto', 'bi-graph-up-arrow', 'main.project_analysis'),
            _item('Agregar proyecto', 'bi-plus-square', 'main.add_project'),
        ]})

    if jefe_area:
        mi_area = [
            _item('Estado del área', 'bi-activity', 'main.area_status'),
            _item('Registros del área', 'bi-clock-history', 'main.area_records'),
        ]
        if not admin_priv:
            mi_area.append(_item('Adicionales del área', 'bi-calendar2-plus', 'main.adicionales_admin'))
        secciones.append({'title': 'Mi área', 'items': mi_area})

    if autenticado and not admin_priv and not jefe_area:
        personal = [_item('Mi panel', 'bi-person-circle', 'main.my_dashboard')]
        if user.employee_id:
            personal.append(_item('Mis adicionales', 'bi-calendar2-plus', 'main.my_adicionales'))
        secciones.append({'title': 'Personal', 'items': personal})

    if autenticado:
        vacaciones = [
            _item('Mis vacaciones', 'bi-sun', 'vacaciones.mis_vacaciones'),
            _item('Mi equipo', 'bi-people-fill', 'vacaciones.equipo'),
        ]
        if es_admin or es_rh:
            vacaciones += [
                _item('Toda la plantilla', 'bi-calendar3', 'vacaciones.admin'),
                _item('Supervisores', 'bi-diagram-2', 'vacaciones.supervisores'),
            ]
        secciones.append({'title': 'Vacaciones', 'items': vacaciones})

    if autenticado and user.puede_reportar_incidencias:
        incidencias = [
            _item('Informes', 'bi-clipboard-check', 'incidencias.informes',
                  activos=('incidencias.nuevo_informe', 'incidencias.ver_informe',
                           'incidencias.editar_informe')),
            _item('Incidencias', 'bi-exclamation-triangle', 'incidencias.lista',
                  activos=('incidencias.nueva', 'incidencias.ver', 'incidencias.editar')),
        ]
        if es_admin:
            incidencias.append(_item('Clasificaciones', 'bi-tags', 'incidencias.clasificaciones'))
        secciones.append({'title': 'Incidencias', 'items': incidencias})

    if es_admin:
        secciones.append({'title': 'Configuración', 'items': [
            _item('Áreas de registro', 'bi-diagram-3', 'main.areas_admin'),
            _item('Actividades', 'bi-list-check', 'main.activities_admin'),
            _item('Usuarios y accesos', 'bi-shield-lock', 'main.manage_users'),
        ]})

    return secciones


def acciones_para(user):
    """Atajos de la paleta de comandos que no son una página del menú."""
    if not user.is_authenticated:
        return [
            {'label': 'Iniciar sesión', 'icon': 'bi-box-arrow-in-right', 'url': url_for('main.login')},
            {'label': 'Registrar usuario', 'icon': 'bi-person-plus', 'url': url_for('main.register')},
        ]

    acciones = []
    if user.puede_reportar_incidencias:
        acciones.append({'label': 'Nuevo informe de incidencia', 'icon': 'bi-plus-circle',
                         'url': url_for('incidencias.nuevo_informe')})
    if user.administra_incidencias:
        acciones.append({'label': 'Nueva incidencia', 'icon': 'bi-plus-square',
                         'url': url_for('incidencias.nueva')})
    if user.has_admin_privileges:
        acciones.append({'label': 'Agregar proyecto', 'icon': 'bi-folder-plus',
                         'url': url_for('main.add_project')})
    if user.is_admin:
        acciones.append({'label': 'Crear registro de tiempo', 'icon': 'bi-clock',
                         'url': url_for('main.create_time_record')})
    acciones.append({'label': 'Solicitar vacaciones', 'icon': 'bi-sun',
                     'url': url_for('vacaciones.mis_vacaciones')})
    acciones.append({'label': 'Cerrar sesión', 'icon': 'bi-box-arrow-right',
                     'url': url_for('main.logout')})
    return acciones


def barra_inferior(user, secciones):
    """
    Accesos de la barra inferior en celulares: los 3 destinos más usados por
    el perfil (siempre visibles para él en el menú), más Buscar y Menú.
    """
    visibles = {i['url']: i for s in secciones for i in s['items']}
    actual = request.endpoint or ''

    def tomar(endpoint, etiqueta, icono, activos=()):
        try:
            url = url_for(endpoint)
        except Exception:
            return None
        if url not in visibles:
            return None
        return {'label': etiqueta, 'icon': icono, 'url': url,
                'active': actual == endpoint or actual in activos}

    candidatos = [
        tomar('main.home', 'Registro', 'bi-stopwatch',
              ('main.register_employee', 'main.register_project', 'main.register_project_imp')),
    ]
    if user.has_admin_privileges:
        candidatos.append(tomar('main.admin_dashboard', 'Dashboard', 'bi-grid-1x2'))
    elif getattr(user, 'is_area_manager', False):
        candidatos.append(tomar('main.area_status', 'Mi área', 'bi-activity', ('main.area_records',)))
    else:
        candidatos.append(tomar('main.my_dashboard', 'Mi panel', 'bi-person-circle', ('main.my_adicionales',)))
    if user.employee_id:
        candidatos.append(tomar('vacaciones.mis_vacaciones', 'Vacaciones', 'bi-sun',
                                ('vacaciones.equipo', 'vacaciones.admin', 'vacaciones.supervisores')))
    elif user.is_admin or getattr(user, 'is_rh', False):
        candidatos.append(tomar('vacaciones.admin', 'Vacaciones', 'bi-calendar3'))
    else:
        candidatos.append(tomar('vacaciones.equipo', 'Equipo', 'bi-people'))
    return [c for c in candidatos if c][:3]


def migas(secciones=None):
    """(sección, página) de la página actual según el menú, para la barra superior."""
    if not current_user.is_authenticated:
        return None, None
    for seccion in (secciones if secciones is not None else menu_para(current_user)):
        for item in seccion['items']:
            if item['active']:
                return seccion['title'], item['label']
    return None, None


def iniciales(texto):
    partes = [p for p in (texto or '').replace('@', ' ').replace('.', ' ').split() if p]
    if not partes:
        return '?'
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[1][0]).upper()

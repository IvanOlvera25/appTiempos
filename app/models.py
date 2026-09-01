from . import db
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import text


# =========================
# Employee
# =========================
class Employee(db.Model):
    """
    Personal, proyectado desde AD17_RH.

    En base de datos `employees` es una VISTA de solo lectura sobre AD17_RH
    (ver migración c3f81b6e4a72): `id` es el rhID y las altas, bajas y cambios
    de área o puesto se hacen en el sistema de RH, no aquí. Las claves foráneas
    hacia esta "tabla" ya no existen en la base — se conservan en el modelo
    porque son las que SQLAlchemy usa para armar los joins.
    """
    __tablename__ = 'employees'

    id               = db.Column(db.Integer, primary_key=True)
    nompropio        = db.Column(db.String(150), nullable=False)
    n_empleado       = db.Column(db.String(20), unique=True, nullable=False)
    nombre           = db.Column(db.String(50),  nullable=False)
    apellido_paterno = db.Column(db.String(50),  nullable=False)
    apellido_materno = db.Column(db.String(50),  nullable=False)
    departamento     = db.Column(db.String(100), nullable=False, server_default=text("'N/A'"))
    puesto           = db.Column(db.String(100), nullable=False)
    qr_code          = db.Column(db.String(100), unique=True, nullable=False)
    active           = db.Column(db.Boolean, default=True, nullable=False, server_default=text("1"))

    # 1-N con TimeRecord. Sin cascada de borrado: los registros de tiempo son
    # locales y sobreviven a que alguien cause baja en RH.
    records = db.relationship(
        'TimeRecord',
        backref='employee',
        lazy=True
    )

    # 1-1 con User (única relación entre Employee<->User)
    user = db.relationship(
        'User',
        back_populates='employee',
        uselist=False
    )

    def __repr__(self):
        return f'<Employee {self.nompropio}>'


# =========================
# Project
# =========================
class Project(db.Model):
    __tablename__ = 'projects'

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False, unique=True)
    # Alineado como Integer para evitar difs constantes en migraciones y permitir folio=0 especial
    folio         = db.Column(db.Integer, nullable=True, index=True)
    client        = db.Column(db.String(100), nullable=False)
    delivery_date = db.Column(db.DateTime, nullable=True)
    due_date      = db.Column(db.DateTime, nullable=True)
    active        = db.Column(db.Boolean, nullable=False, server_default=text("1"))

    records = db.relationship('TimeRecord', backref='project', lazy=True)

    def __repr__(self):
        return f"<Project {self.name}>"


# =========================
# TimeRecord
# =========================
class TimeRecord(db.Model):
    __tablename__ = 'time_records'

    id           = db.Column(db.Integer, primary_key=True)
    employee_id  = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    project_id   = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    start_time   = db.Column(db.DateTime, nullable=False)
    end_time     = db.Column(db.DateTime, nullable=True)
    latitude     = db.Column(db.Float, nullable=True)
    longitude    = db.Column(db.Float, nullable=True)
    departamento = db.Column(db.String(100), nullable=False, server_default=text("'N/A'"))
    actividad    = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return (
            f"<TimeRecord {self.id} - Emp {self.employee_id} - Proj {self.project_id} "
            f"- Depto {self.departamento} - Act {self.actividad}>"
        )


# =========================
# User
# =========================
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id               = db.Column(db.Integer, primary_key=True)
    username         = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password         = db.Column(db.String(255), nullable=False)
    is_admin         = db.Column(db.Boolean, default=False, nullable=False)
    is_project_leader = db.Column(db.Boolean, default=False, nullable=False)
    is_area_manager  = db.Column(db.Boolean, default=False, nullable=False)
    is_rh            = db.Column(db.Boolean, default=False, nullable=False, server_default=text("0"))
    is_ejecutivo     = db.Column(db.Boolean, default=False, nullable=False, server_default=text("0"))
    area_manager_department = db.Column(db.String(100), nullable=True)
    employee_id      = db.Column(db.Integer, db.ForeignKey('employees.id'), unique=True, nullable=True, index=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    # Relación 1-1 con Employee usando back_populates (sin backref extra)
    employee = db.relationship(
        'Employee',
        back_populates='user',
        uselist=False
    )

    @property
    def is_employee(self):
        """True si el usuario es un empleado raso, con employee_id asignado."""
        return (
            not self.is_admin
            and not self.is_project_leader
            and not self.is_area_manager
            and not self.is_rh
            and not self.is_ejecutivo
            and self.employee_id is not None
        )

    @property
    def has_admin_privileges(self):
        """
        True para los perfiles con acceso administrativo general.

        RH se pidió explícitamente "como el de LP" (líder de proyecto), así que
        comparte este permiso; lo propio de RH (vacaciones e incidencias) se
        controla aparte con `is_rh`.
        """
        return self.is_admin or self.is_project_leader or self.is_rh

    # ── Jerarquía de perfiles ────────────────────────────────────────────
    # El nivel ordena los perfiles: un usuario ve los informes de incidencia
    # de su mismo nivel o menor. Es un orden de visibilidad, no de permisos.
    ROLE_EMPLEADO   = 0
    ROLE_EJECUTIVO  = 1
    ROLE_JEFE_AREA  = 2
    ROLE_LIDER      = 3
    ROLE_RH         = 4
    ROLE_ADMIN      = 5

    ROLE_LABELS = {
        ROLE_ADMIN:     'Administrador',
        ROLE_RH:        'RH',
        ROLE_LIDER:     'Líder de Proyecto',
        ROLE_JEFE_AREA: 'Jefe de Área',
        ROLE_EJECUTIVO: 'Ejecutivo',
        ROLE_EMPLEADO:  'Empleado',
    }

    @property
    def role_level(self):
        """Nivel del perfil más alto que tiene el usuario."""
        if self.is_admin:
            return self.ROLE_ADMIN
        if self.is_rh:
            return self.ROLE_RH
        if self.is_project_leader:
            return self.ROLE_LIDER
        if self.is_area_manager:
            return self.ROLE_JEFE_AREA
        if self.is_ejecutivo:
            return self.ROLE_EJECUTIVO
        return self.ROLE_EMPLEADO

    @property
    def role_label(self):
        return self.ROLE_LABELS[self.role_level]

    @property
    def puede_reportar_incidencias(self):
        """Cualquier perfil que no sea 'Empleado' puede levantar informes."""
        return self.role_level > self.ROLE_EMPLEADO

    @property
    def administra_incidencias(self):
        """Solo Administradores y RH consolidan informes en incidencias."""
        return self.is_admin or self.is_rh

    def __repr__(self):
        return f'<User {self.username}>'


# =========================
# DepartmentActivity
# =========================
class DepartmentActivity(db.Model):
    __tablename__ = 'department_activities'

    id         = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False, index=True)
    name       = db.Column(db.String(200), nullable=False)
    is_active  = db.Column(db.Boolean, nullable=False, server_default=text("1"))
    sort_order = db.Column(db.Integer,  nullable=False, server_default=text("0"))

    __table_args__ = (
        db.UniqueConstraint('department', 'name', name='uq_department_activity'),
    )

    def __repr__(self):
        return f"<DepartmentActivity {self.department}:{self.name}>"


# =========================
# AreaConfig
# =========================
class AreaConfig(db.Model):
    """
    Areas que pueden registrar tiempos en la plataforma.

    `nombre` es el valor que se guarda en TimeRecord.departamento y en
    DepartmentActivity.department, por lo que cambiarlo reetiqueta el historial:
    la edicion lo propaga en una sola transaccion.

    `rh_area_id` enlaza con AD17_General.Areas.regID y evita tener que adivinar
    la correspondencia por nombre (ver _ALIAS_AREAS en routes.py).
    """
    __tablename__ = 'areas_config'

    id         = db.Column(db.Integer, primary_key=True)
    nombre     = db.Column(db.String(100), nullable=False, unique=True)
    rh_area_id = db.Column(db.Integer, nullable=True, index=True)
    activa     = db.Column(db.Boolean, nullable=False, server_default=text("1"))
    flujo      = db.Column(db.String(20), nullable=False, server_default=text("'estandar'"))
    orden      = db.Column(db.Integer, nullable=False, server_default=text("0"))

    FLUJOS = ('estandar', 'impresion')

    def __repr__(self):
        return f"<AreaConfig {self.nombre} ({self.flujo})>"


# =========================
# Incidencias
# =========================
class IncidentClassification(db.Model):
    """Catálogo de clasificaciones de incidencia (editable por administradores)."""
    __tablename__ = 'incident_classifications'

    id     = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False, unique=True)
    activa = db.Column(db.Boolean, nullable=False, server_default=text("1"))
    orden  = db.Column(db.Integer, nullable=False, server_default=text("0"))

    def __repr__(self):
        return f"<IncidentClassification {self.nombre}>"


class Incident(db.Model):
    """
    Incidencia consolidada: un evento real, armado por Administración o RH a
    partir de uno o varios Informes de Incidencia.
    """
    __tablename__ = 'incidents'

    id                   = db.Column(db.Integer, primary_key=True)
    created_by_user_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    descripcion          = db.Column(db.Text, nullable=False)
    clasificacion_id     = db.Column(db.Integer, db.ForeignKey('incident_classifications.id'), nullable=True)

    # Responsable final: cliente, área o trabajador
    responsable_tipo     = db.Column(db.String(20), nullable=False, server_default=text("'AREA'"))
    responsable_area     = db.Column(db.String(100), nullable=True)
    responsable_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    responsable_texto    = db.Column(db.String(200), nullable=True)

    costo                = db.Column(db.Numeric(12, 2), nullable=False, server_default=text("0"))
    estado               = db.Column(db.String(20), nullable=False, server_default=text("'ABIERTA'"))

    TIPOS_RESPONSABLE = ('CLIENTE', 'AREA', 'EMPLEADO')
    ESTADOS = ('ABIERTA', 'CERRADA')

    created_by = db.relationship('User', foreign_keys=[created_by_user_id])
    clasificacion = db.relationship('IncidentClassification')
    responsable_employee = db.relationship('Employee', foreign_keys=[responsable_employee_id])
    reports = db.relationship('IncidentReport', back_populates='incident', lazy='select')
    projects = db.relationship('IncidentProject', cascade='all, delete-orphan',
                               back_populates='incident', lazy='select')

    @property
    def responsable_label(self):
        if self.responsable_tipo == 'EMPLEADO':
            return self.responsable_employee.nompropio if self.responsable_employee else 'Trabajador'
        if self.responsable_tipo == 'AREA':
            return self.responsable_area or 'Área'
        return self.responsable_texto or 'Cliente'

    def __repr__(self):
        return f"<Incident {self.id}>"


class IncidentProject(db.Model):
    """FP al que realmente pertenece la incidencia."""
    __tablename__ = 'incident_projects'

    id          = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=False, index=True)
    project_id  = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('incident_id', 'project_id', name='uq_incident_project'),
    )

    incident = db.relationship('Incident', back_populates='projects')
    project  = db.relationship('Project')


class IncidentReport(db.Model):
    """
    Informe de Incidencia: lo levanta cualquier perfil que no sea Empleado.

    `nivel_autor` guarda el nivel del perfil del autor en el momento del alta.
    Es una foto, no un cálculo en vivo: si a alguien lo ascienden, sus informes
    viejos no deben cambiar de visibilidad de golpe.
    """
    __tablename__ = 'incident_reports'

    id               = db.Column(db.Integer, primary_key=True)
    reporter_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    nivel_autor      = db.Column(db.Integer, nullable=False, server_default=text("0"), index=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    motivo           = db.Column(db.Text, nullable=False)
    repercusion      = db.Column(db.Text, nullable=True)
    clasificacion_id = db.Column(db.Integer, db.ForeignKey('incident_classifications.id'), nullable=True)

    # Área o empleado causante
    causante_tipo        = db.Column(db.String(20), nullable=False, server_default=text("'AREA'"))
    causante_area        = db.Column(db.String(100), nullable=True, index=True)
    causante_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    causante_texto       = db.Column(db.String(200), nullable=True)

    # Marcado por Administración/RH; queda oculto para los demás perfiles
    invalido    = db.Column(db.Boolean, nullable=False, server_default=text("0"), index=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), nullable=True, index=True)

    TIPOS_CAUSANTE = ('AREA', 'EMPLEADO', 'CLIENTE', 'OTRO')

    reporter      = db.relationship('User', foreign_keys=[reporter_user_id])
    clasificacion = db.relationship('IncidentClassification')
    causante_employee = db.relationship('Employee', foreign_keys=[causante_employee_id])
    incident      = db.relationship('Incident', back_populates='reports')
    projects      = db.relationship('IncidentReportProject', cascade='all, delete-orphan',
                                    back_populates='report', lazy='select')

    @property
    def causante_label(self):
        if self.causante_tipo == 'EMPLEADO':
            return self.causante_employee.nompropio if self.causante_employee else 'Empleado'
        if self.causante_tipo == 'AREA':
            return self.causante_area or 'Área'
        return self.causante_texto or self.causante_tipo.capitalize()

    def __repr__(self):
        return f"<IncidentReport {self.id}>"


class IncidentReportProject(db.Model):
    """FP que el autor del informe señala como afectado."""
    __tablename__ = 'incident_report_projects'

    id         = db.Column(db.Integer, primary_key=True)
    report_id  = db.Column(db.Integer, db.ForeignKey('incident_reports.id'), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('report_id', 'project_id', name='uq_incident_report_project'),
    )

    report  = db.relationship('IncidentReport', back_populates='projects')
    project = db.relationship('Project')

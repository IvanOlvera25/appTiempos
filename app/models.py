from . import db
from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import text


# =========================
# Employee
# =========================
class Employee(db.Model):
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

    # 1-N con TimeRecord
    records = db.relationship(
        'TimeRecord',
        backref='employee',
        lazy=True,
        cascade='all, delete-orphan'
    )

    # 1-1 con User (única relación entre Employee<->User)
    user = db.relationship(
        'User',
        back_populates='employee',
        uselist=False,
        cascade='all, delete-orphan',
        single_parent=True  # requerido si usas delete-orphan en 1-1
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
        """True si el usuario es un empleado (no admin ni líder) con employee_id asignado."""
        return not self.is_admin and not self.is_project_leader and self.employee_id is not None

    @property
    def has_admin_privileges(self):
        """True si es admin o líder de proyecto."""
        return self.is_admin or self.is_project_leader

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

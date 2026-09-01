from flask_wtf import FlaskForm
from wtforms import (
    StringField, SelectField, SubmitField, DateField,
    HiddenField, PasswordField, BooleanField
)
from wtforms.validators import (
    DataRequired, Length, Optional, EqualTo, ValidationError
)
from .models import User, Employee
from flask_login import current_user
from datetime import date

# ╭─────────────────────────────╮
#  1. Formularios auxiliares
# ╰─────────────────────────────╯
class QRForm(FlaskForm):
    qr_code    = StringField('Código QR', validators=[DataRequired(), Length(max=100)])
    project_id = SelectField('Proyecto', coerce=int, validators=[DataRequired()])
    iniciar    = SubmitField('Iniciar')
    finalizar  = SubmitField('Finalizar')


class ProjectForm(FlaskForm):
    folio         = StringField('Folio (FP)', validators=[DataRequired(), Length(max=50)])
    delivery_date = DateField('Fecha de Entrega', validators=[Optional()], format='%Y-%m-%d')
    client        = StringField('Cliente', validators=[DataRequired(), Length(max=100)])
    name          = StringField('Nombre del Proyecto', validators=[DataRequired(), Length(max=200)])
    submit        = SubmitField('Agregar Proyecto')


# ╭─────────────────────────────╮
#  2. Registro de Usuario
# ╰─────────────────────────────╯
class RegistrationForm(FlaskForm):
    # Se establece via JS (empleado | administrador)
    user_type         = HiddenField('Tipo de Usuario', validators=[DataRequired()])

    # (Solo empleado) -> se llena con IDs de Employee
    employee_name     = SelectField('Nombre del Empleado',
                                    coerce=int,
                                    validators=[Optional()],
                                    choices=[])

    username          = StringField('Correo / Usuario',
                                    validators=[DataRequired(), Length(min=4, max=120)])
    password          = PasswordField('Contraseña',
                                      validators=[DataRequired(), Length(min=6)])
    confirm_password  = PasswordField('Confirmar Contraseña',
                                      validators=[DataRequired(),
                                                  EqualTo('password')])

    # (Solo administrador)
    verification_code = StringField('Código de Verificación', validators=[Optional()])

    submit            = SubmitField('Registrar')

    # ──────────────────────────────────────────
    # Validaciones personalizadas
    # ──────────────────────────────────────────
    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError('Este correo ya está en uso.')

    def validate(self, *args, **kwargs):
        rv = super().validate(*args, **kwargs)
        if not rv:
            return False

        utype = self.user_type.data
        if utype not in ('empleado', 'administrador', 'lider_proyecto',
                         'jefe_area', 'rh', 'ejecutivo'):
            self.user_type.errors.append('Debes seleccionar el tipo de usuario.')
            return False

        # ▸ Empleado
        if utype == 'empleado':
            if not self.employee_name.data:
                self.employee_name.errors.append('Selecciona tu nombre de la lista.')
                return False
            # Verificar que exista el Employee
            if not Employee.query.get(self.employee_name.data):
                self.employee_name.errors.append('Empleado no encontrado.')
                return False
            # Código admin no requerido
            self.verification_code.data = ''

        # ▸ Resto de perfiles: todos requieren su clave de verificación.
        #   `employee_name` es opcional aquí y sirve para ligar la cuenta a un
        #   empleado de RH (necesario para que tenga saldo de vacaciones).
        else:
            if not self.verification_code.data:
                self.verification_code.errors.append('Debes ingresar la clave de verificación.')
                return False

        return True


# ╭─────────────────────────────╮
#  3. Inicio de Sesión
# ╰─────────────────────────────╯
class LoginForm(FlaskForm):
    # Oculto: JS lo setea pero no es obligatorio para validar
    user_type = HiddenField('Tipo de Usuario')

    username = StringField('Usuario / Correo', validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    remember = BooleanField('Recordarme')
    submit = SubmitField('Iniciar Sesión')

# ╭─────────────────────────────╮
#  4. Registro de Tiempo
# ╰─────────────────────────────╯
class RegisterTimeForm(FlaskForm):
    # Si el usuario es empleado, employee_id vendrá pre‑seleccionado
    employee_id = SelectField('Empleado', coerce=int, validators=[Optional()])

    qr_code     = StringField('Código QR', validators=[Optional()])
    project_id  = SelectField('Proyecto',  coerce=int,
                              validators=[DataRequired()], choices=[])

    iniciar     = SubmitField('Iniciar')
    finalizar   = SubmitField('Finalizar')

    # Validación: solo admins necesitan elegir empleado/QR
    def validate(self, *args, **kwargs):
        if not super().validate(*args, **kwargs):
            return False

        # Si el usuario autenticado es empleado, omitimos la dualidad
        if current_user.is_authenticated and getattr(current_user, 'is_employee', False):
            return True

        qr_code_data = (self.qr_code.data or '').strip()

        if not self.employee_id.data and not qr_code_data:
            err = 'Selecciona un empleado o usa un código QR.'
            self.employee_id.errors.append(err)
            self.qr_code.errors.append(err)
            return False

        if self.employee_id.data and qr_code_data:
            err = 'Usa solo un método: empleado manual o QR.'
            self.employee_id.errors.append(err)
            self.qr_code.errors.append(err)
            return False

        return True


# ╭─────────────────────────────╮
#  5. Formulario de Empleado
# ╰─────────────────────────────╯

# Eliminado EmployeeForm: el personal se administra en AD17_RH. La tabla
# `employees` es una vista de solo lectura, así que la app ya no da de alta ni
# edita empleados.

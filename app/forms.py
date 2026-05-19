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
        if utype not in ('empleado', 'administrador'):
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

        # ▸ Administrador
        else:
            if not self.verification_code.data:
                self.verification_code.errors.append('Debes ingresar la clave de administrador.')
                return False
            # employee_name NO debe estar presente
            self.employee_name.data = None

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

class EmployeeForm(FlaskForm):
    # Número de empleado - cambiado a mínimo 3 dígitos
    n_empleado = StringField(
        'Número de Empleado',
        validators=[
            DataRequired(message="El número de empleado es obligatorio"),
            Length(min=3, max=10, message="El número debe tener entre 3 y 10 dígitos")
        ]
    )

    # Nombre propio (campo que faltaba en tu plantilla)
    nompropio = StringField(
        'Nombre Completo',
        validators=[
            DataRequired(message="El nombre completo es obligatorio"),
            Length(min=2, max=100, message="El nombre debe tener entre 2 y 100 caracteres")
        ]
    )

    # Nombre
    nombre = StringField(
        'Nombre',
        validators=[
            DataRequired(message="El nombre es obligatorio"),
            Length(min=2, max=50, message="El nombre debe tener entre 2 y 50 caracteres")
        ]
    )

    # Apellido paterno
    apellido_paterno = StringField(
        'Apellido Paterno',
        validators=[
            DataRequired(message="El apellido paterno es obligatorio"),
            Length(min=2, max=50, message="El apellido debe tener entre 2 y 50 caracteres")
        ]
    )

    # Apellido materno (opcional)
    apellido_materno = StringField(
        'Apellido Materno',
        validators=[
            Length(max=50, message="El apellido materno no puede exceder 50 caracteres")
        ]
    )

    # Departamento
    departamento = SelectField('Departamento', choices=[
        ('Metal', 'Metal'),
        ('Costura', 'Costura'),
        ('Impresion', 'Impresión'),
        ('Stagging', 'Stagging'),
        ('Montaje', 'Montaje'),
        ('Transporte', 'Transporte')
    ], validators=[DataRequired()])


    # Puesto
    puesto = StringField(
        'Puesto',
        validators=[
            DataRequired(message="El puesto es obligatorio"),
            Length(min=2, max=100, message="El puesto debe tener entre 2 y 100 caracteres")
        ]
    )

    # Código QR
    qr_code = StringField(
        'Código QR',
        validators=[
            DataRequired(message="El código QR es obligatorio"),
            Length(min=3, max=20, message="El código QR debe tener entre 3 y 20 caracteres")
        ]
    )

    submit = SubmitField('Guardar Empleado')

    def __init__(self, *args, **kwargs):
        # Obtener el empleado actual si estamos editando
        self.original_employee = kwargs.pop('obj', None)
        super(EmployeeForm, self).__init__(*args, **kwargs)

    def validate_n_empleado(self, field):
        """Validar que el número de empleado sea único"""
        from .models import Employee

        # Si estamos editando y el número no cambió, no validar
        if (self.original_employee and
            self.original_employee.n_empleado == field.data):
            return

        # Verificar que solo contenga dígitos
        if not field.data.isdigit():
            raise ValidationError('El número de empleado debe contener solo dígitos.')

        # Verificar que sea único
        existing = Employee.query.filter_by(n_empleado=field.data).first()
        if existing:
            raise ValidationError('Este número de empleado ya existe.')

    def validate_qr_code(self, field):
        """Validar que el código QR sea único"""
        from .models import Employee

        # Si estamos editando y el código no cambió, no validar
        if (self.original_employee and
            self.original_employee.qr_code == field.data):
            return

        # Verificar que sea único
        existing = Employee.query.filter_by(qr_code=field.data).first()
        if existing:
            raise ValidationError('Este código QR ya está en uso.')

    def validate_nompropio(self, field):
        """Validar el formato del nombre completo"""
        if not field.data.replace(' ', '').replace('-', '').isalpha():
            raise ValidationError('El nombre solo puede contener letras, espacios y guiones.')
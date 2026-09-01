# Despliegue

Pasos para actualizar la app en PythonAnywhere después de un `git pull`.

## 1. Permisos sobre AD17_RH — LISTO

RH ya otorgó a `IvanUriel` los permisos de escritura a nivel de tabla:

```
AD17_RH.Vacaciones    SELECT, INSERT, UPDATE
AD17_RH.MediosDias    SELECT, INSERT, UPDATE
AD17_RH.Supervisores  SELECT, INSERT, UPDATE
AD17_RH.ReglasMediosDias  SELECT, INSERT, UPDATE
```

Verificado contra el servidor: las seis operaciones que usa la app (crear
solicitud, autorizar, denegar, cancelar, asignar y quitar supervisor) funcionan.
El flujo completo se probó de punta a punta con `ROLLBACK`, sin dejar rastro.

Nota: son permisos **por tabla**, así que no aparecen en la línea
`GRANT ... ON \`AD17_RH\`.*`. Para verlos:

```sql
SELECT TABLE_NAME, PRIVILEGE_TYPE FROM information_schema.TABLE_PRIVILEGES
 WHERE TABLE_SCHEMA = 'AD17_RH';
```

## 2. El despliegue va en DOS fases

El código nuevo **no funciona sin migrar**: espera la tabla `areas_config` y las
columnas `users.is_rh` / `users.is_ejecutivo`. Si haces `git pull` y recargas sin
correr `flask db upgrade`, la app pierde los botones de área y falla el login.

La cadena está partida a propósito para que puedas dejar la parte destructiva
para después:

| Fase | Comando | Qué hace |
|---|---|---|
| **1 — aditiva** | `flask db upgrade d4e19a7c5b83` | Crea `areas_config` con las 7 áreas de siempre, agrega los perfiles RH/Ejecutivo y las tablas de incidencias. **No toca ningún dato existente.** |
| **2 — destructiva** | `flask db upgrade` | Convierte `employees` en vista sobre `AD17_RH` y remapea `employee_id` a `rhID`. |

Para volver a operar basta la fase 1. La fase 2 puede esperar al momento que
elijas.

## 3. Fase 1 (aditiva)

```bash
git pull
pip install -r requirements.txt          # no hay dependencias nuevas
flask db upgrade d4e19a7c5b83
```

Recarga la web app. Con esto vuelven los botones de área, el login y quedan
disponibles vacaciones e incidencias, con `employees` intacta como tabla.

## 4. Fase 2 (employees como vista) — cuando decidas

Respalda antes:

```bash
mysqldump -h ad17solutions.dscloud.me -P 3307 -u IvanUriel -p \
  AD17_Pruebas > respaldo_$(date +%Y%m%d).sql
```

Verificación previa, de solo lectura:

```bash
python verificarMigracionRH.py
```

Sale con 0 si todo cuadra. Si algo falla, la migración aborta sola sin tocar
datos. Luego:

```bash
flask db upgrade
```

La migración conserva la tabla original como `employees_legacy`, y
`flask db downgrade` la restaura junto con los `employee_id` anteriores.

## 4b. Si `flask db` falla en la consola de PythonAnywhere

Síntoma:

```
ImportError: cannot import name '_app_ctx_stack' from 'flask'
Error: No such command 'db'.
```

No es un problema de la migración. La consola está tomando `flask` del
directorio del usuario (Flask 3.x) pero `flask_sqlalchemy` del sistema
(2.x, que todavía pide `_app_ctx_stack`, eliminado en Flask 2.3). Se ve en las
rutas del propio traceback:

```
flask            -> /home/<usuario>/.local/lib/python3.10/site-packages/
flask_sqlalchemy -> /usr/local/lib/python3.10/site-packages/
```

La web app corre en un virtualenv; la consola arranca sin él. **Actívalo antes
de migrar**, con el mismo que aparece en el campo *Virtualenv* de la pestaña
*Web*:

```bash
ls ~/.virtualenvs/                       # ver cuál es
source ~/.virtualenvs/<nombre>/bin/activate
cd ~/appTiempos
python -c "import flask, flask_sqlalchemy; print(flask.__version__, flask_sqlalchemy.__version__)"
```

Debe imprimir `3.1.0 3.1.1`. Con eso ya corre:

```bash
FLASK_SKIP_SCHEDULER=1 flask db upgrade d4e19a7c5b83
```

`FLASK_SKIP_SCHEDULER=1` evita que APScheduler arranque en la consola; no afecta
a la web app.

Si de verdad no hay virtualenv, instala las dependencias en el directorio del
usuario para que tapen a las del sistema:

```bash
pip3.10 install --user -r requirements.txt
```

## 5. Qué cambia al terminar la fase 2

- **Ya no se dan de alta ni se editan empleados desde la app.** Todo eso se hace
  en el sistema de RH. Las rutas `/add`, `/employee/edit`, `/employee/delete` y
  `/employee/toggle_active` se eliminaron.
- **RH decide quién está activo.** Hoy la app tiene 71 empleados activos y RH
  reporta 80. Al migrar manda RH: aparecen 9 personas que la app tenía como
  inactivas, y `Isaias García Morales` (rhID 121) pasa a inactivo porque RH lo
  tiene como baja. Sus 14 registros de tiempo se conservan; solo deja de salir
  en las listas para registrar tiempo.
- **El nombre del área lo pone `areas_config`.** RH escribe "Staging" y
  "Administracion"; la app usa "Stagging" y "Administración". El enlace
  `areas_config.rh_area_id` traduce, para que el historial siga cuadrando. Si
  das de alta un área nueva, enlázala en *Administración → Áreas de registro*.

## 6. Códigos de registro de los perfiles nuevos

Configurables por variable de entorno; valores por omisión:

| Perfil | Variable | Valor |
|---|---|---|
| RH | `RH_CODE` | `RH71D2` |
| Ejecutivo | `EJECUTIVO_CODE` | `EJ38F6` |

Se muestran en *Administración → Usuarios*.

## Notas

- Para que una cuenta tenga saldo de vacaciones propio debe estar **ligada a un
  empleado** (`employee_id`), aunque su perfil no sea "Empleado". Se hace en
  *Administración → Usuarios*, con el botón **Editar** de cada renglón (también
  al dar de alta el usuario). Ahí mismo se cambia el rol.

  Los usuarios sin vínculo salen marcados en amarillo con "Sin empleado ligado".
  Hay 18 así en producción, entre ellos 9 jefes de área: **hay que ligarlos para
  que puedan autorizar vacaciones y vean "Mi equipo"**, porque el árbol de
  supervisión de `AD17_RH.Supervisores` se resuelve por el rhID del empleado.
- Quién ve el calendario de equipo lo define `AD17_RH.Supervisores`, no el perfil
  de la app.
- Si `areas_config` llegara a faltar, la app cae en las 7 áreas históricas y deja
  registrar tiempos igual, dejando un error en el log. Es una red de seguridad,
  no un modo de operación: sin la tabla no se pueden administrar las áreas.
- `AD17_RH.MediosDias` está vacía en producción, pero el flujo de medio día ya
  se ejerció contra el esquema real (crear, autorizar y bloquear duplicados en
  la misma fecha).

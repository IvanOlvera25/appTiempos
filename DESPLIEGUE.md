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

## 2. Respaldo

La migración `c3f81b6e4a72` reescribe `employee_id` en `time_records` y `users`,
y convierte `employees` en una vista. Respalda antes:

```bash
mysqldump -h ad17solutions.dscloud.me -P 3307 -u IvanUriel -p \
  AD17_Pruebas > respaldo_$(date +%Y%m%d).sql
```

La migración además conserva la tabla original como `employees_legacy`, y
`flask db downgrade` la restaura junto con los `employee_id` anteriores.

## 3. Verificación previa (solo lectura, no modifica nada)

```bash
python verificarMigracionRH.py
```

Sale con 0 si todo cuadra. Revisa que no reporte empleados sin `rhID` válido,
`n_empleado` repetidos, ni registros o usuarios huérfanos. Si algo falla, la
migración aborta sola sin tocar datos.

## 4. Actualizar

```bash
git pull
pip install -r requirements.txt          # no hay dependencias nuevas
flask db upgrade
```

La cadena aplica, en orden:

| Revisión | Qué hace |
|---|---|
| `b7a2c9f14d30` | Crea `areas_config`, siembra las 7 áreas y las enlaza con `AD17_General.Areas` |
| `c3f81b6e4a72` | Convierte `employees` en vista sobre `AD17_RH` y remapea `employee_id` a `rhID` |
| `d4e19a7c5b83` | Agrega los perfiles RH/Ejecutivo y las tablas de incidencias |

Después, recarga la web app desde el panel de PythonAnywhere.

## 5. Qué cambia al quedar `employees` como vista

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
  empleado** (`employee_id`), aunque su perfil no sea "Empleado". Se hace al
  crear el usuario en *Administración → Usuarios*.
- Quién ve el calendario de equipo lo define `AD17_RH.Supervisores`, no el perfil
  de la app.
- `AD17_RH.MediosDias` está vacía en producción, pero el flujo de medio día ya
  se ejerció contra el esquema real (crear, autorizar y bloquear duplicados en
  la misma fecha).

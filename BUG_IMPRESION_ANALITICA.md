# Impresion: no se pueden editar registros de tiempo

## Sintoma

Desde Costos (`/costs/edit/<id>`), al guardar un registro del area **Impresion**
salia "Error al actualizar el registro. Verifica los datos ingresados." y el
registro no cambiaba. En el resto de las areas no pasa.

## Causa

No es la app. `AD17_Pruebas.time_records` tiene tres triggers instalados por el
equipo de analitica (DEFINER `root@%` / `BrandonViNu@%`):

| Trigger | Evento | Que hace |
|---|---|---|
| `trg_time_records_AfterInsert_Autocierre` | AFTER INSERT | `CALL AD17_Analytics_DEV.sp_autocierre_areas(...)` |
| `trg_time_records_impresion_ai` | AFTER INSERT | solo si `areaID = 16`: `CALL AD17_Analytics_DEV.sp_impresion_recalcular_dia(rhID, fecha_local)` |
| `trg_time_records_impresion_au` | **AFTER UPDATE** | igual, solo si `areaID = 16` |

`areaID = 16` es Impresion segun `AD17_General.Correccion_Departamento`, por eso
el problema es exclusivo de esa area.

`sp_impresion_recalcular_dia` recalcula **el dia nuevo** e inserta un evento con
clave `time_records-<id>-I`. Ese evento ya existe apuntando al **dia viejo** (lo
creo el trigger de INSERT) y nadie lo borra, asi que el INSERT choca contra el
indice unico `uk_evento`:

```
(1062, "Duplicate entry 'time_records-31202-I' for key 'uk_evento'")
```

MySQL aborta el UPDATE completo, SQLAlchemy hace rollback y la edicion se pierde.

## Que falla exactamente (probado con rollback contra AD17_Pruebas)

Sobre un registro de Impresion:

| Cambio | Resultado |
|---|---|
| solo la actividad | OK |
| hora de inicio dentro del mismo dia | OK |
| hora de fin | OK |
| proyecto | OK |
| **fecha de inicio a otro dia** | **ERROR 1062 uk_evento** |
| **cambiar de empleado** | **ERROR 1062 uk_evento** |
| Impresion -> otra area | OK (pero deja la analitica desfasada, ver abajo) |

Los mismos cambios sobre Metal, Costura o Stagging siempre funcionan.

Esto explica el "solo algunos registros": fallan justo las correcciones que mas
hace Costos, mover un registro de dia o reasignarlo de persona.

## Lo que se cambio en la app

La app no puede arreglar esto: el usuario `IvanUriel` ni siquiera tiene acceso a
`AD17_Analytics_DEV`. Lo unico que se corrigio aqui es el mensaje, que mandaba a
Costos a revisar un formulario que estaba bien. Ver `_rechazado_por_analitica()`
en `app/routes.py`, usado en `edit_time_record` y `create_time_record`.

## Arreglo pendiente (equipo de analitica / DBA)

1. **Hacer idempotente el alta del evento** en `sp_impresion_recalcular_dia`:
   `INSERT ... ON DUPLICATE KEY UPDATE`, o borrar los eventos de ese
   `origen_id` antes de insertarlos.

2. **Recalcular tambien el estado anterior** en el trigger de UPDATE. Aunque se
   arregle el 1062, mover un registro de dia o de empleado deja el dia viejo con
   datos que ya no corresponden:

```sql
DROP TRIGGER IF EXISTS trg_time_records_impresion_au;
DELIMITER $$
CREATE TRIGGER trg_time_records_impresion_au AFTER UPDATE ON time_records
FOR EACH ROW
BEGIN
    DECLARE v_rhID_old, v_rhID_new, v_area_old, v_area_new INT;

    SELECT CAST(e.n_empleado AS UNSIGNED) INTO v_rhID_old
      FROM AD17_Pruebas.employees e WHERE e.id = OLD.employee_id LIMIT 1;
    SELECT CAST(e.n_empleado AS UNSIGNED) INTO v_rhID_new
      FROM AD17_Pruebas.employees e WHERE e.id = NEW.employee_id LIMIT 1;

    SELECT areaID INTO v_area_old FROM AD17_General.Correccion_Departamento
     WHERE TRIM(departamento_string) = TRIM(OLD.departamento) LIMIT 1;
    SELECT areaID INTO v_area_new FROM AD17_General.Correccion_Departamento
     WHERE TRIM(departamento_string) = TRIM(NEW.departamento) LIMIT 1;

    -- el dia que el registro deja de ocupar
    IF v_area_old = 16 AND v_rhID_old IS NOT NULL
       AND (v_rhID_old <> v_rhID_new OR OLD.fecha_local <> NEW.fecha_local
            OR v_area_new <> 16 OR v_area_new IS NULL) THEN
        CALL AD17_Analytics_DEV.sp_impresion_recalcular_dia(v_rhID_old, OLD.fecha_local);
    END IF;

    -- el dia al que se mueve
    IF v_area_new = 16 AND v_rhID_new IS NOT NULL THEN
        CALL AD17_Analytics_DEV.sp_impresion_recalcular_dia(v_rhID_new, NEW.fecha_local);
    END IF;
END$$
DELIMITER ;
```

3. **Falta el trigger de DELETE.** Hoy, borrar un registro de Impresion desde
   `/costs/delete/<id>` deja el dia cuadrado con un registro que ya no existe.

4. `SELECT ... INTO` sin `LIMIT 1` (como esta hoy en los dos triggers de
   Impresion) revienta con ERROR 1172 si `employees` llegara a devolver mas de
   una fila por `id`. La fase 2 del despliegue convierte `employees` en vista
   sobre `AD17_RH`, y una vista no garantiza unicidad. Conviene el `LIMIT 1`
   antes de esa migracion.

## Segundo efecto: el trigger bloquea la migracion a `employees` como vista

El 2026-09-04 se intento aplicar la fase 2 (`flask db upgrade`, migracion
`c3f81b6e4a72`). La verificacion previa paso limpia, pero la migracion aborto en
el paso que remapea `employee_id` de id local a rhID:

```
sqlalchemy.exc.IntegrityError: (1062, "Duplicate entry 'time_records-16848-I' for key 'uk_evento'")
[SQL: UPDATE time_records tr JOIN employees e ON e.id = tr.employee_id
         SET tr.employee_id = CAST(e.n_empleado AS UNSIGNED)]
```

Es el mismo defecto. El UPDATE masivo cambia `employee_id` en cada fila; para las
de Impresion el trigger recalcula un dia distinto al que ya tiene el evento y
choca contra `uk_evento`.

Es peor de lo que parece: mientras dura el UPDATE, `employees` sigue siendo la
tabla vieja, asi que el trigger resuelve `WHERE e.id = NEW.employee_id` con el
rhID recien escrito y cae en **otra persona**. Aunque no reventara, estaria
recalculando la analitica de quien no es.

Estado tras el intento: **los datos quedaron intactos** (alembic siguio en
`d4e19a7c5b83`, `employees` siguio siendo tabla, cero filas remapeadas), pero el
DDL de MySQL no es transaccional y la migracion alcanzo a soltar las FK
`time_records_ibfk_1` y `users_ibfk_1`. Se restauraron a mano.

**La fase 2 no se puede aplicar hasta que se corrija el punto 1** (hacer
idempotente el alta del evento en `sp_impresion_recalcular_dia`). Mientras tanto,
las altas de RH hay que meterlas a mano en `employees` con `n_empleado` = rhID;
asi se hizo con las 6 que faltaban (ids locales 143-148).

## Estado al 2026-09-04: el trigger de UPDATE esta BORRADO

Tras el intento fallido de migrar, regresar los registros de Impresion a su area
volvio a fallar y en un caso (id 1297) **reinicio el servidor MariaDB**, no solo
la conexion. Con `employees` como vista, 4 filas pasaron y 1 tumbo el servidor;
el crash parece depender de la fila, no de la vista, pero no hay forma de
saberlo sin leer el procedimiento.

Se decidio borrar el trigger:

```sql
DROP TRIGGER AD17_Pruebas.trg_time_records_impresion_au;
```

Consecuencias, hoy:

- Editar registros de Impresion desde Costos **ya funciona**, incluido cambiar
  la fecha o el empleado. Verificado.
- La analitica de Impresion **ya no se refresca al editar** un registro. Las
  altas si la siguen alimentando: eso lo hace `trg_time_records_impresion_ai`,
  que sigue en su lugar.
- La migracion a `employees` como vista ya no esta bloqueada por este trigger.

Su definicion exacta quedo guardada en `scripts_restaurar_trigger_impresion.sql`.
Recrearla exige `SUPER` (DEFINER=root@%), que el usuario de la app no tiene.

### Advertencia antes de recrearlo o de migrar

`trg_time_records_impresion_ai` (INSERT) llama al **mismo** procedimiento. Si lo
que reinicio el servidor es algo que el procedimiento hace tambien en el camino
del INSERT, entonces despues de la fase 2 un trabajador iniciando un registro de
Impresion podria tumbar el servidor. Hoy no pasa porque `employees` es tabla y
las altas llevan meses funcionando, pero conviene tenerlo presente:

**arreglar `sp_impresion_recalcular_dia` antes de recrear el trigger o de migrar.**

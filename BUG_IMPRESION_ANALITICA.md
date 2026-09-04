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

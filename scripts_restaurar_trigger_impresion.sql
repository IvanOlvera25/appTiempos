-- Definicion EXACTA de trg_time_records_impresion_au, capturada antes de tocarlo.
-- Recrearla exige SUPER (DEFINER=root@%); IvanUriel no puede.

DELIMITER $$
CREATE DEFINER=`root`@`%` TRIGGER AD17_Pruebas.trg_time_records_impresion_au
AFTER UPDATE
ON AD17_Pruebas.time_records
FOR EACH ROW
BEGIN

    DECLARE v_rhID INT;
    DECLARE v_areaID INT;

    SELECT
        CAST(e.n_empleado AS UNSIGNED)
    INTO v_rhID
    FROM AD17_Pruebas.employees e
    WHERE e.id = NEW.employee_id;

    SELECT
        areaID
    INTO v_areaID
    FROM AD17_General.Correccion_Departamento
    WHERE TRIM(departamento_string) = TRIM(NEW.departamento)
    LIMIT 1;

    IF v_areaID = 16 THEN

        CALL AD17_Analytics_DEV.sp_impresion_recalcular_dia
        (
            v_rhID,
            NEW.fecha_local
        );
        
        INSERT INTO AD17_Analytics_DEV.Trigger_Log
		(
		    trigger_name,
		    accion,
		    rhID,
		    detalle
		)
		VALUES
		(
		    'trg_time_records_impresion_au',
		    'UPDATE',
		    v_rhID,
		    CONCAT(
		        'time_record id=',
		        NEW.id
		    )
		);

    END IF;

END$$
DELIMITER ;

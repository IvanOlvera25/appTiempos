import mysql.connector
from datetime import datetime
from .models import db, TimeRecord  # Modelos locales
from flask import current_app

def sync_with_remote_db():
    """
    Sincroniza los registros locales de TimeRecord con la base de datos remota
    insertándolos o actualizándolos en la tabla Tiempos_RH.
    """
    try:
        # 1. Conectarse a la BD remota
        remote_conn = mysql.connector.connect(
            host="ad17solutions.dscloud.me",
            port=3307,
            user="IvanUriel",
            password="iuOp20!!25",
            database="AD17_Costos",  # Asumimos que la base es la misma; solo cambia la tabla destino
            charset='utf8mb4'
        )
        remote_cursor = remote_conn.cursor()

        # 2. Leer datos de la BD local (todos los registros de TimeRecord)
        local_records = TimeRecord.query.all()

        # 3. Insertar o actualizar cada registro en la BD remota, en la tabla Tiempos_RH
        insert_query = """
            INSERT INTO Tiempos_RH
                (id, employee_id, project_id, start_time, end_time, latitude, longitude, departamento, actividad)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                employee_id = VALUES(employee_id),
                project_id = VALUES(project_id),
                start_time = VALUES(start_time),
                end_time = VALUES(end_time),
                latitude = VALUES(latitude),
                longitude = VALUES(longitude),
                departamento = VALUES(departamento),
                actividad = VALUES(actividad)
        """

        for record in local_records:
            remote_cursor.execute(insert_query, (
                record.id,
                record.employee_id,
                record.project_id,
                record.start_time,
                record.end_time,
                record.latitude,
                record.longitude,
                record.departamento,
                record.actividad
            ))

        remote_conn.commit()
        remote_cursor.close()
        remote_conn.close()

        current_app.logger.info("Sincronización con la BD remota (Tiempos_RH) completada exitosamente.")

    except mysql.connector.Error as err:
        current_app.logger.error(f"Error en la sincronización con BD remota: {err}")
    except Exception as e:
        current_app.logger.error(f"Error general en la sincronización: {e}")
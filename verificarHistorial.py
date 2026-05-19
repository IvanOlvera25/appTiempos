import pymysql

# Tu configuración de base de datos
DB_CONFIG = {
    'host': 'ad17solutions.dscloud.me',
    'port': 3307,
    'user': 'IvanUriel',
    'password': 'iuOp20!!25',
    'database': 'AD17_Pruebas',
    'charset': 'utf8mb4'
}

try:
    # Conectar directamente a MySQL
    connection = pymysql.connect(**DB_CONFIG)
    cursor = connection.cursor()

    print("=== DEPARTAMENTOS EN HISTORIAL DE REGISTROS ===")
    cursor.execute("SELECT departamento, COUNT(*) as count FROM time_records GROUP BY departamento ORDER BY count DESC")
    departamentos = cursor.fetchall()

    total = 0
    for dept, count in departamentos:
        print(f"- {dept}: {count} registros")
        total += count

    print(f"\nTotal registros: {total}")

    # Verificar registros específicos
    cursor.execute("SELECT COUNT(*) FROM time_records WHERE departamento = 'Metales'")
    metales_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM time_records WHERE departamento = 'Metal'")
    metal_count = cursor.fetchone()[0]

    print(f"\nRegistros con 'Metales': {metales_count}")
    print(f"Registros con 'Metal': {metal_count}")

    # Si hay registros con 'Metales', preguntar si actualizar
    if metales_count > 0:
        print(f"\n⚠️  ATENCIÓN: Tienes {metales_count} registros antiguos con 'Metales'")
        print("Esto puede causar problemas de visualización en reportes.")

        respuesta = input("\n¿Quieres actualizar estos registros a 'Metal'? (s/n): ")

        if respuesta.lower() == 's':
            cursor.execute("UPDATE time_records SET departamento = 'Metal' WHERE departamento = 'Metales'")
            connection.commit()
            print(f"✅ {metales_count} registros actualizados de 'Metales' a 'Metal'")
        else:
            print("❌ No se realizaron cambios")
    else:
        print("✅ No hay registros con 'Metales' - todo está correcto")

    cursor.close()
    connection.close()

except Exception as e:
    print(f"Error: {e}")
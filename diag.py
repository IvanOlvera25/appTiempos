#!/usr/bin/env python3
"""
Diagnóstico de Base de Datos AD17 Tiempos
Descubre la estructura real de las tablas
"""

import pymysql

db_config = {
    'host': 'ad17solutions.dscloud.me',
    'port': 3307,
    'user': 'IvanUriel',
    'password': 'iuOp20!!25',
    'database': 'AD17_Pruebas',
    'charset': 'utf8mb4'
}

def main():
    print("=" * 60)
    print("DIAGNÓSTICO DE BASE DE DATOS AD17_Pruebas")
    print("=" * 60)

    try:
        conn = pymysql.connect(**db_config, cursorclass=pymysql.cursors.DictCursor)
        cursor = conn.cursor()

        # 1. Listar todas las tablas
        print("\n📋 TABLAS DISPONIBLES:")
        print("-" * 40)
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()

        table_names = []
        for t in tables:
            table_name = list(t.values())[0]
            table_names.append(table_name)

            # Contar registros
            cursor.execute(f"SELECT COUNT(*) as count FROM `{table_name}`")
            count = cursor.fetchone()['count']
            print(f"  • {table_name}: {count} registros")

        # 2. Mostrar estructura de cada tabla
        print("\n" + "=" * 60)
        print("📊 ESTRUCTURA DE CADA TABLA:")
        print("=" * 60)

        for table_name in table_names:
            print(f"\n🔹 Tabla: {table_name}")
            print("-" * 40)

            cursor.execute(f"DESCRIBE `{table_name}`")
            columns = cursor.fetchall()

            for col in columns:
                nullable = "NULL" if col['Null'] == 'YES' else "NOT NULL"
                key = f" [{col['Key']}]" if col['Key'] else ""
                print(f"   {col['Field']:25} {col['Type']:20} {nullable}{key}")

            # Mostrar primeros 3 registros de ejemplo
            cursor.execute(f"SELECT * FROM `{table_name}` LIMIT 3")
            samples = cursor.fetchall()
            if samples:
                print(f"\n   Ejemplo de datos ({len(samples)} registros):")
                for i, row in enumerate(samples, 1):
                    # Mostrar solo algunos campos clave
                    preview = {k: str(v)[:50] for k, v in list(row.items())[:5]}
                    print(f"   {i}. {preview}")

        # 3. Buscar tablas relacionadas con tiempo/empleados/proyectos
        print("\n" + "=" * 60)
        print("🔍 ANÁLISIS DE RELACIONES:")
        print("=" * 60)

        # Buscar tabla de empleados
        emp_candidates = [t for t in table_names if any(x in t.lower() for x in ['employee', 'empleado', 'worker', 'trabajador', 'user'])]
        print(f"\n👥 Candidatos a tabla de empleados: {emp_candidates}")

        # Buscar tabla de proyectos
        proj_candidates = [t for t in table_names if any(x in t.lower() for x in ['project', 'proyecto', 'folio'])]
        print(f"📁 Candidatos a tabla de proyectos: {proj_candidates}")

        # Buscar tabla de registros de tiempo
        time_candidates = [t for t in table_names if any(x in t.lower() for x in ['time', 'tiempo', 'record', 'registro', 'hour', 'hora'])]
        print(f"⏱️  Candidatos a tabla de tiempos: {time_candidates}")

        # Buscar tabla de actividades
        act_candidates = [t for t in table_names if any(x in t.lower() for x in ['activity', 'actividad', 'department'])]
        print(f"📋 Candidatos a tabla de actividades: {act_candidates}")

        conn.close()
        print("\n✅ Diagnóstico completado")

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
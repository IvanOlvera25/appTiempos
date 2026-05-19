import os
import sys
from sqlalchemy import create_engine, text
from app.config import Config

# Crear conexión directa a la base de datos
config = Config()
engine = create_engine(config.SQLALCHEMY_DATABASE_URI)

try:
    with engine.connect() as connection:
        print("=== CONTENIDO DE TODAS LAS TABLAS ===\n")

        # 1. EMPLOYEES
        print("1. TABLA EMPLOYEES:")
        print("-" * 50)
        result = connection.execute(text("SELECT id, nompropio, n_empleado, departamento FROM employees LIMIT 10"))
        employees = result.fetchall()
        for emp in employees:
            print(f"ID: {emp[0]}, Nombre: {emp[1]}, #Emp: {emp[2]}, Dept: {emp[3]}")

        result = connection.execute(text("SELECT COUNT(*) FROM employees"))
        total = result.fetchone()[0]
        print(f"Total empleados: {total}")

        # 2. PROJECTS
        print("\n2. TABLA PROJECTS:")
        print("-" * 50)
        result = connection.execute(text("SELECT id, folio, name, client, active FROM projects LIMIT 10"))
        projects = result.fetchall()
        for proj in projects:
            print(f"ID: {proj[0]}, Folio: {proj[1]}, Nombre: {proj[2]}, Cliente: {proj[3]}, Activo: {proj[4]}")

        result = connection.execute(text("SELECT COUNT(*) FROM projects"))
        total = result.fetchone()[0]
        print(f"Total proyectos: {total}")

        # 3. TIME_RECORDS
        print("\n3. TABLA TIME_RECORDS:")
        print("-" * 50)
        result = connection.execute(text("SELECT id, employee_id, project_id, departamento, actividad, start_time, end_time FROM time_records ORDER BY id DESC LIMIT 5"))
        records = result.fetchall()
        for rec in records:
            status = "Activo" if rec[6] is None else "Finalizado"
            print(f"ID: {rec[0]}, Emp: {rec[1]}, Proj: {rec[2]}, Dept: {rec[3]}, Act: {rec[4]}, Status: {status}")

        result = connection.execute(text("SELECT COUNT(*) FROM time_records"))
        total = result.fetchone()[0]
        print(f"Total registros de tiempo: {total}")

        # 4. USERS
        print("\n4. TABLA USERS:")
        print("-" * 50)
        result = connection.execute(text("SELECT id, username, is_admin, is_project_leader, employee_id FROM users"))
        users = result.fetchall()
        for user in users:
            tipo = "Admin" if user[2] else ("Líder" if user[3] else "Empleado")
            print(f"ID: {user[0]}, Usuario: {user[1]}, Tipo: {tipo}, EmpID: {user[4]}")

        # 5. DEPARTAMENTOS CON CONTEO
        print("\n5. RESUMEN DE DEPARTAMENTOS:")
        print("-" * 50)
        result = connection.execute(text("SELECT departamento, COUNT(*) as count FROM employees GROUP BY departamento ORDER BY count DESC"))
        departamentos = result.fetchall()
        for dept in departamentos:
            print(f"{dept[0]}: {dept[1]} empleados")

except Exception as e:
    print(f"Error: {e}")
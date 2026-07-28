# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "clave-secreta-demo"
    ADMIN_CODE = os.environ.get("ADMIN_CODE") or "HI35C3"
    LEADER_CODE = os.environ.get("LEADER_CODE") or "LP92B4"
    AREA_MANAGER_CODE = os.environ.get("AREA_MANAGER_CODE") or "AR845C"
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://IvanUriel:iuOp20!!25@ad17solutions.dscloud.me:3307/AD17_Pruebas"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- Base remota de Adicionales (AD17_Adicionales) ----
    # La app solo consulta esta base; el usuario configurado no requiere permisos
    # de escritura. Las variables de entorno permiten apuntar a otro servidor.
    ADICIONALES_DB_HOST     = os.environ.get("ADICIONALES_DB_HOST") or "ad17solutions.dscloud.me"
    ADICIONALES_DB_PORT     = int(os.environ.get("ADICIONALES_DB_PORT") or 3307)
    ADICIONALES_DB_USER     = os.environ.get("ADICIONALES_DB_USER") or "IvanUriel"
    ADICIONALES_DB_PASSWORD = os.environ.get("ADICIONALES_DB_PASSWORD") or "iuOp20!!25"
    ADICIONALES_DB_NAME     = os.environ.get("ADICIONALES_DB_NAME") or "AD17_Adicionales"

    # Configuración de cookies de sesión
    SESSION_COOKIE_SECURE = True  # En producción usa True, desarrollo False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = 86400  # 1 día en segundos

# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "clave-secreta-demo"
    AREA_MANAGER_CODE = os.environ.get("AREA_MANAGER_CODE") or "12345"
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://IvanUriel:iuOp20!!25@ad17solutions.dscloud.me:3307/AD17_Pruebas"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuración de cookies de sesión
    SESSION_COOKIE_SECURE = True  # En producción usa True, desarrollo False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = 86400  # 1 día en segundos

# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "clave-secreta-demo"
    ADMIN_CODE = os.environ.get("ADMIN_CODE") or "HI35C3"
    LEADER_CODE = os.environ.get("LEADER_CODE") or "LP92B4"
    AREA_MANAGER_CODE = os.environ.get("AREA_MANAGER_CODE") or "AR845C"
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://IvanUriel:iuOp20!!25@ad17solutions.dscloud.me:3307/AD17_Pruebas"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuración de cookies de sesión
    SESSION_COOKIE_SECURE = True  # En producción usa True, desarrollo False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = 86400  # 1 día en segundos

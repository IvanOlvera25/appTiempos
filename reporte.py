# =============================================================================
# CONFIGURACIÓN
# =============================================================================

#!/usr/bin/env python3
"""
================================================================================
REPORTE DE PRODUCTIVIDAD AD17 SOLUTIONS - VERSIÓN 3.1 (EXPORTA PNGs + ZIP)
================================================================================
- Además del PDF/Excel:
  1) Crea carpeta: Reporte_Productividad_AD17_<timestamp>/
     - paginas/   (cada página completa del reporte en PNG)
     - graficas/  (cada gráfica/subplot por separado en PNG alta calidad)
  2) Genera un ZIP con todo lo anterior.
================================================================================

⚠️ SEGURIDAD:
No incluyo contraseñas en el código. Configura la conexión por variables de entorno.
Ejemplos:
export AD17_DB_HOST="..."
export AD17_DB_PORT="3307"
export AD17_DB_USER="..."
export AD17_DB_PASSWORD="..."
export AD17_DB_NAME="AD17_Pruebas"
"""

import os
import re
import zipfile
from pathlib import Path
from datetime import datetime, timedelta

import pymysql
import pymysql.cursors

import pandas as pd
import numpy as np

import matplotlib
matplotlib.use('Agg')  # Backend sin GUI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec

import seaborn as sns
import warnings

warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURACIÓN (por entorno)
# =============================================================================
DB_CONFIG = {
    'host': 'ad17solutions.dscloud.me',
    'port': 3307,
    'user': 'IvanUriel',
    'password': 'iuOp20!!25',
    'database': 'AD17_Pruebas',
    'charset': 'utf8mb4'
}



COLORS = {
    'primary': '#FF9800',
    'primary_dark': '#F57C00',
    'secondary': '#1976D2',
    'success': '#43A047',
    'danger': '#E53935',
    'warning': '#FDD835',
    'info': '#29B6F6',
    'purple': '#7B1FA2',
    'teal': '#00897B',
    'gray': '#757575',
    'light_gray': '#F5F5F5',
    'dark': '#212121'
}

DEPT_COLORS = {
    'Metal': '#FF5722',
    'Costura': '#E91E63',
    'Impresion': '#9C27B0',
    'Stagging': '#3F51B5',
    'Montaje': '#009688',
    'Transporte': '#795548',
    'Administración': '#607D8B',
    'Sin Departamento': '#9E9E9E'
}

plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'font.size': 10
})

# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================
def truncate_text(text, max_len=25):
    if pd.isna(text) or text is None:
        return 'N/A'
    text = str(text)
    return text[:max_len-3] + '...' if len(text) > max_len else text

def format_hours(hours):
    if pd.isna(hours) or hours is None:
        return '0h'
    hours = float(hours)
    if hours >= 1000:
        return f"{hours/1000:.1f}K h"
    return f"{hours:.1f}h"

def format_number(value):
    if pd.isna(value) or value is None:
        return '0'
    value = float(value)
    if value >= 1000000:
        return f"{value/1000000:.1f}M"
    if value >= 1000:
        return f"{value/1000:.1f}K"
    return f"{int(value)}"

def get_db_connection():
    """Obtiene conexión a la base de datos"""
    return pymysql.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database=DB_CONFIG['database'],
        charset=DB_CONFIG['charset'],
        cursorclass=pymysql.cursors.DictCursor
    )

# =============================================================================
# CLASE PRINCIPAL
# =============================================================================
class ReporteProductividadAD17:
    """Generador de reportes de productividad"""

    def __init__(self, fecha_inicio=None, fecha_fin=None):
        # Configurar fechas
        if fecha_fin is None:
            self.fecha_fin = datetime.now()
        else:
            self.fecha_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') if isinstance(fecha_fin, str) else fecha_fin

        if fecha_inicio is None:
            self.fecha_inicio = datetime(self.fecha_fin.year, 1, 1)
        else:
            self.fecha_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d') if isinstance(fecha_inicio, str) else fecha_inicio

        # Datos
        self.empleados = []
        self.proyectos = []
        self.registros = []
        self.metricas = {}

        # Export / timestamp único para PDF/Excel/Carpetas
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        self.export_root = None
        self.export_pages_dir = None
        self.export_charts_dir = None
        self._page_counter = 0
        self._init_export_folders()

        print("=" * 70)
        print("🚀 REPORTE DE PRODUCTIVIDAD AD17 SOLUTIONS")
        print("=" * 70)
        print(f"📅 Período: {self.fecha_inicio.strftime('%d/%m/%Y')} al {self.fecha_fin.strftime('%d/%m/%Y')}")
        dias = (self.fecha_fin - self.fecha_inicio).days + 1
        print(f"📊 Días de análisis: {dias}")
        print("=" * 70)

    # =========================
    # EXPORTACIÓN DE IMÁGENES
    # =========================
    def _init_export_folders(self):
        base = Path(f"Reporte_Productividad_AD17_{self.timestamp}")
        self.export_root = base
        self.export_pages_dir = base / "paginas"
        self.export_charts_dir = base / "graficas"
        self.export_pages_dir.mkdir(parents=True, exist_ok=True)
        self.export_charts_dir.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^a-z0-9_\-]+", "", s)
        return s[:80] if len(s) > 80 else s

    def _save_figure(self, fig, out_path: Path, dpi: int = 300):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=dpi, bbox_inches="tight", facecolor="white")

    def _save_axes(self, fig, ax, out_path: Path, dpi: int = 350, extra_artists=None, expand=(1.05, 1.10)):
        extra_artists = extra_artists or []
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        bbox = ax.get_tightbbox(renderer)
        for artist in extra_artists:
            try:
                bbox = bbox.union(artist.get_tightbbox(renderer))
            except Exception:
                pass

        bbox = bbox.expanded(expand[0], expand[1])
        bbox_inches = bbox.transformed(fig.dpi_scale_trans.inverted())

        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=dpi, bbox_inches=bbox_inches, facecolor="white")

    def _export_page_and_axes(self, fig, page_key: str,
                             axes=None, axes_names=None, axes_extra=None,
                             dpi_page=300, dpi_axes=350):
        """
        Guarda:
          - página completa (PNG) en /paginas
          - cada subplot (PNG) en /graficas
        """
        self._page_counter += 1
        pnum = f"{self._page_counter:02d}"
        page_key = self._safe_name(page_key)

        # Página completa
        self._save_figure(fig, self.export_pages_dir / f"{pnum}_{page_key}_page.png", dpi=dpi_page)

        if not axes:
            return

        if axes_names is None:
            axes_names = [f"chart_{i+1:02d}" for i in range(len(axes))]

        if axes_extra is None:
            axes_extra = [[] for _ in axes]

        for i, (ax, nm) in enumerate(zip(axes, axes_names), start=1):
            nm = self._safe_name(nm)
            extra = axes_extra[i-1] if i-1 < len(axes_extra) else []
            self._save_axes(
                fig, ax,
                self.export_charts_dir / f"{pnum}_{page_key}_{i:02d}_{nm}.png",
                dpi=dpi_axes,
                extra_artists=extra
            )

    def _zip_exports(self) -> str:
        zip_path = Path(f"{self.export_root}.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in self.export_root.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=p.relative_to(self.export_root.parent))
        return str(zip_path)

    # =============================================================================
    # EXTRACCIÓN / CÁLCULO
    # =============================================================================
    def extraer_datos(self):
        """Extrae todos los datos de la base de datos"""
        print("\n📥 EXTRAYENDO DATOS...")
        print("-" * 50)

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            print("👥 Extrayendo empleados...")
            cursor.execute("SELECT id, nompropio, departamento FROM employees ORDER BY nompropio")
            self.empleados = list(cursor.fetchall())
            print(f"   ✅ {len(self.empleados)} empleados")

            print("📁 Extrayendo proyectos...")
            cursor.execute("SELECT id, folio, name, client, active FROM projects ORDER BY folio DESC")
            self.proyectos = list(cursor.fetchall())
            print(f"   ✅ {len(self.proyectos)} proyectos")

            print("⏱️ Extrayendo registros de tiempo...")

            fecha_ini_str = self.fecha_inicio.strftime('%Y-%m-%d')
            fecha_fin_str = (self.fecha_fin + timedelta(days=1)).strftime('%Y-%m-%d')

            query = """
                SELECT
                    tr.id as registro_id,
                    tr.employee_id,
                    tr.project_id,
                    tr.start_time,
                    tr.end_time,
                    tr.departamento,
                    tr.actividad,
                    e.nompropio as empleado_nombre,
                    e.departamento as empleado_depto,
                    p.name as proyecto_nombre,
                    p.folio as proyecto_folio,
                    p.client as proyecto_cliente,
                    TIMESTAMPDIFF(SECOND, tr.start_time, tr.end_time) as segundos
                FROM time_records tr
                LEFT JOIN employees e ON tr.employee_id = e.id
                LEFT JOIN projects p ON tr.project_id = p.id
                WHERE DATE(tr.start_time) >= %s AND DATE(tr.start_time) < %s
                ORDER BY tr.start_time DESC
            """

            cursor.execute(query, (fecha_ini_str, fecha_fin_str))
            self.registros = list(cursor.fetchall())

            finalizados = sum(1 for r in self.registros if r['end_time'] is not None)
            print(f"   ✅ {len(self.registros):,} registros ({finalizados:,} finalizados)")

            cursor.close()
            conn.close()

            print("\n✅ Extracción completada")
            return True

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass
            return False

    def calcular_metricas(self):
        """Calcula todas las métricas"""
        print("\n📊 CALCULANDO MÉTRICAS...")
        print("-" * 50)

        if not self.registros:
            print("⚠️ No hay registros para analizar")
            return False

        registros_fin = [r for r in self.registros if r['end_time'] is not None and r['segundos'] and r['segundos'] > 0]
        if not registros_fin:
            print("⚠️ No hay registros finalizados")
            return False

        print(f"   📈 Procesando {len(registros_fin):,} registros finalizados...")

        total_segundos = sum(r['segundos'] for r in registros_fin if r['segundos'])
        total_horas = total_segundos / 3600.0

        empleados_unicos = set(r['employee_id'] for r in registros_fin if r['employee_id'])
        proyectos_unicos = set(r['project_id'] for r in registros_fin if r['project_id'])
        deptos_unicos = set(r['departamento'] for r in registros_fin if r['departamento'])

        fechas_unicas = set()
        for r in registros_fin:
            if r['start_time']:
                fechas_unicas.add(r['start_time'].date() if hasattr(r['start_time'], 'date') else r['start_time'])

        dias_periodo = (self.fecha_fin - self.fecha_inicio).days + 1
        dias_actividad = len(fechas_unicas)

        self.metricas['general'] = {
            'total_horas': total_horas,
            'total_registros': len(self.registros),
            'registros_finalizados': len(registros_fin),
            'registros_activos': len(self.registros) - len(registros_fin),
            'empleados_activos': len(empleados_unicos),
            'proyectos_activos': len(proyectos_unicos),
            'departamentos': len(deptos_unicos),
            'dias_periodo': dias_periodo,
            'dias_actividad': dias_actividad,
            'promedio_horas_dia': total_horas / dias_actividad if dias_actividad > 0 else 0,
            'promedio_horas_trabajador': total_horas / len(empleados_unicos) if empleados_unicos else 0,
            'tasa_finalizacion': len(registros_fin) / len(self.registros) * 100 if self.registros else 0
        }

        # POR DEPARTAMENTO
        print("🏢 Métricas por departamento...")
        dept_data = {}
        for r in registros_fin:
            dept = r['departamento'] or 'Sin Departamento'
            if dept not in dept_data:
                dept_data[dept] = {'horas': 0, 'registros': 0, 'empleados': set(), 'proyectos': set()}
            dept_data[dept]['horas'] += (r['segundos'] or 0) / 3600.0
            dept_data[dept]['registros'] += 1
            if r['employee_id']:
                dept_data[dept]['empleados'].add(r['employee_id'])
            if r['project_id']:
                dept_data[dept]['proyectos'].add(r['project_id'])

        dept_list = []
        for dept, data in dept_data.items():
            dept_list.append({
                'departamento': dept,
                'horas': data['horas'],
                'registros': data['registros'],
                'trabajadores': len(data['empleados']),
                'proyectos': len(data['proyectos']),
                'horas_por_trabajador': data['horas'] / len(data['empleados']) if data['empleados'] else 0
            })
        self.metricas['por_departamento'] = sorted(dept_list, key=lambda x: x['horas'], reverse=True)

        # POR TRABAJADOR
        print("👷 Métricas por trabajador...")
        worker_data = {}
        for r in registros_fin:
            emp_id = r['employee_id']
            if not emp_id:
                continue
            if emp_id not in worker_data:
                worker_data[emp_id] = {
                    'nombre': r['empleado_nombre'] or 'Desconocido',
                    'departamento': r['empleado_depto'] or r['departamento'] or 'N/A',
                    'horas': 0, 'registros': 0, 'proyectos': set(), 'dias': set()
                }
            worker_data[emp_id]['horas'] += (r['segundos'] or 0) / 3600.0
            worker_data[emp_id]['registros'] += 1
            if r['project_id']:
                worker_data[emp_id]['proyectos'].add(r['project_id'])
            if r['start_time']:
                fecha = r['start_time'].date() if hasattr(r['start_time'], 'date') else r['start_time']
                worker_data[emp_id]['dias'].add(fecha)

        worker_list = []
        for emp_id, data in worker_data.items():
            dias = len(data['dias'])
            worker_list.append({
                'employee_id': emp_id,
                'nombre': data['nombre'],
                'departamento': data['departamento'],
                'horas': data['horas'],
                'registros': data['registros'],
                'proyectos': len(data['proyectos']),
                'dias_trabajados': dias,
                'horas_por_dia': data['horas'] / dias if dias > 0 else 0
            })
        self.metricas['por_trabajador'] = sorted(worker_list, key=lambda x: x['horas'], reverse=True)

        # POR PROYECTO
        print("📁 Métricas por proyecto...")
        project_data = {}
        for r in registros_fin:
            proj_id = r['project_id']
            if not proj_id:
                continue
            if proj_id not in project_data:
                project_data[proj_id] = {
                    'nombre': r['proyecto_nombre'] or 'Sin Nombre',
                    'folio': r['proyecto_folio'] or 0,
                    'cliente': r['proyecto_cliente'] or 'Sin Cliente',
                    'horas': 0, 'registros': 0, 'empleados': set(), 'deptos': set()
                }
            project_data[proj_id]['horas'] += (r['segundos'] or 0) / 3600.0
            project_data[proj_id]['registros'] += 1
            if r['employee_id']:
                project_data[proj_id]['empleados'].add(r['employee_id'])
            if r['departamento']:
                project_data[proj_id]['deptos'].add(r['departamento'])

        project_list = []
        for proj_id, data in project_data.items():
            project_list.append({
                'project_id': proj_id,
                'nombre': data['nombre'],
                'folio': data['folio'],
                'cliente': data['cliente'],
                'horas': data['horas'],
                'registros': data['registros'],
                'trabajadores': len(data['empleados']),
                'departamentos': len(data['deptos'])
            })
        self.metricas['por_proyecto'] = sorted(project_list, key=lambda x: x['horas'], reverse=True)

        # POR CLIENTE
        print("🏢 Métricas por cliente...")
        client_data = {}
        for r in registros_fin:
            cliente = r['proyecto_cliente'] or 'Sin Cliente'
            if cliente not in client_data:
                client_data[cliente] = {'horas': 0, 'registros': 0, 'proyectos': set(), 'empleados': set()}
            client_data[cliente]['horas'] += (r['segundos'] or 0) / 3600.0
            client_data[cliente]['registros'] += 1
            if r['project_id']:
                client_data[cliente]['proyectos'].add(r['project_id'])
            if r['employee_id']:
                client_data[cliente]['empleados'].add(r['employee_id'])

        client_list = []
        for cliente, data in client_data.items():
            client_list.append({
                'cliente': cliente,
                'horas': data['horas'],
                'registros': data['registros'],
                'proyectos': len(data['proyectos']),
                'trabajadores': len(data['empleados'])
            })
        self.metricas['por_cliente'] = sorted(client_list, key=lambda x: x['horas'], reverse=True)

        # POR ACTIVIDAD
        print("📋 Métricas por actividad...")
        activity_data = {}
        for r in registros_fin:
            actividad = r['actividad'] or 'Sin Especificar'
            if actividad not in activity_data:
                activity_data[actividad] = {
                    'departamento': r['departamento'] or 'N/A',
                    'horas': 0, 'registros': 0, 'empleados': set()
                }
            activity_data[actividad]['horas'] += (r['segundos'] or 0) / 3600.0
            activity_data[actividad]['registros'] += 1
            if r['employee_id']:
                activity_data[actividad]['empleados'].add(r['employee_id'])

        activity_list = []
        for actividad, data in activity_data.items():
            registros = data['registros']
            activity_list.append({
                'actividad': actividad,
                'departamento': data['departamento'],
                'horas': data['horas'],
                'registros': registros,
                'trabajadores': len(data['empleados']),
                'horas_promedio': data['horas'] / registros if registros > 0 else 0
            })
        self.metricas['por_actividad'] = sorted(activity_list, key=lambda x: x['horas'], reverse=True)

        # TEMPORAL
        print("📅 Métricas temporales...")
        mes_data = {}
        dia_semana_data = {i: {'horas': 0, 'registros': 0} for i in range(7)}
        hora_data = {i: {'horas': 0, 'registros': 0} for i in range(24)}
        dia_data = {}

        for r in registros_fin:
            if not r['start_time']:
                continue
            st = r['start_time']
            segundos = r['segundos'] or 0
            horas = segundos / 3600.0

            mes_key = st.strftime('%Y-%m')
            if mes_key not in mes_data:
                mes_data[mes_key] = {'horas': 0, 'registros': 0, 'empleados': set(), 'proyectos': set()}
            mes_data[mes_key]['horas'] += horas
            mes_data[mes_key]['registros'] += 1
            if r['employee_id']:
                mes_data[mes_key]['empleados'].add(r['employee_id'])
            if r['project_id']:
                mes_data[mes_key]['proyectos'].add(r['project_id'])

            dow = st.weekday()
            dia_semana_data[dow]['horas'] += horas
            dia_semana_data[dow]['registros'] += 1

            hora = st.hour
            hora_data[hora]['horas'] += horas
            hora_data[hora]['registros'] += 1

            dia_key = st.strftime('%Y-%m-%d')
            if dia_key not in dia_data:
                dia_data[dia_key] = {'horas': 0, 'registros': 0}
            dia_data[dia_key]['horas'] += horas
            dia_data[dia_key]['registros'] += 1

        mes_list = [{'mes': k, 'horas': v['horas'], 'registros': v['registros'],
                    'trabajadores': len(v['empleados']), 'proyectos': len(v['proyectos'])}
                   for k, v in sorted(mes_data.items())]

        dia_semana_nombres = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        dia_semana_list = [{'dia_semana': i, 'dia_nombre': dia_semana_nombres[i],
                           'horas': dia_semana_data[i]['horas'], 'registros': dia_semana_data[i]['registros']}
                          for i in range(7)]

        hora_list = [{'hora': i, 'horas': hora_data[i]['horas'], 'registros': hora_data[i]['registros']}
                    for i in range(24)]

        dia_list = [{'fecha': k, 'horas': v['horas'], 'registros': v['registros']}
                   for k, v in sorted(dia_data.items())]

        self.metricas['temporal'] = {
            'por_mes': mes_list,
            'por_dia_semana': dia_semana_list,
            'por_hora': hora_list,
            'por_dia': dia_list
        }

        gen = self.metricas['general']
        print("\n" + "=" * 50)
        print("📊 RESUMEN DEL PERÍODO")
        print("=" * 50)
        print(f"   Total Horas: {format_hours(gen['total_horas'])}")
        print(f"   Total Registros: {format_number(gen['total_registros'])}")
        print(f"   Trabajadores: {gen['empleados_activos']}")
        print(f"   Proyectos: {gen['proyectos_activos']}")
        print(f"   Departamentos: {gen['departamentos']}")
        print(f"   Días con Actividad: {gen['dias_actividad']}")

        return True

    # =============================================================================
    # GENERACIÓN PDF / EXCEL
    # =============================================================================
    def generar_pdf(self):
        """Genera el reporte PDF (y exporta imágenes PNG por separado + ZIP)"""
        filename = f"Reporte_Productividad_AD17_{self.timestamp}.pdf"

        print(f"\n📄 GENERANDO PDF: {filename}")
        print("-" * 50)

        with PdfPages(filename) as pdf:
            self._pagina_portada(pdf)
            self._pagina_resumen(pdf)
            self._pagina_departamentos(pdf)
            self._pagina_trabajadores(pdf)
            self._pagina_proyectos(pdf)
            self._pagina_clientes(pdf)
            self._pagina_actividades(pdf)
            self._pagina_temporal(pdf)
            self._pagina_temporal2(pdf)
            self._pagina_rankings(pdf)
            self._pagina_final(pdf)

            d = pdf.infodict()
            d['Title'] = 'Reporte de Productividad AD17'
            d['Author'] = 'Sistema AD17'
            d['CreationDate'] = datetime.now()

        zip_file = self._zip_exports()

        print(f"\n✅ PDF generado: {filename}")
        print(f"🖼️  Imágenes guardadas en: {self.export_root}/ (paginas/ y graficas/)")
        print(f"📦 ZIP generado: {zip_file}")
        return filename, zip_file

    def generar_excel(self):
        """Genera Excel con datos"""
        filename = f"Datos_Productividad_AD17_{self.timestamp}.xlsx"
        print(f"\n📊 GENERANDO EXCEL: {filename}")

        with pd.ExcelWriter(filename, engine='xlsxwriter') as writer:
            gen = self.metricas['general']
            pd.DataFrame([gen]).T.to_excel(writer, sheet_name='Resumen')
            pd.DataFrame(self.metricas['por_departamento']).to_excel(writer, sheet_name='Departamentos', index=False)
            pd.DataFrame(self.metricas['por_trabajador']).to_excel(writer, sheet_name='Trabajadores', index=False)
            pd.DataFrame(self.metricas['por_proyecto']).to_excel(writer, sheet_name='Proyectos', index=False)
            pd.DataFrame(self.metricas['por_cliente']).to_excel(writer, sheet_name='Clientes', index=False)
            pd.DataFrame(self.metricas['por_actividad']).to_excel(writer, sheet_name='Actividades', index=False)
            pd.DataFrame(self.metricas['temporal']['por_mes']).to_excel(writer, sheet_name='Mensual', index=False)

        print(f"✅ Excel generado: {filename}")
        return filename

    # =============================================================================
    # PÁGINAS DEL PDF (cada una ahora exporta PNGs)
    # =============================================================================
    def _pagina_portada(self, pdf):
        print("   📄 Portada...")
        fig = plt.figure(figsize=(11, 8.5))

        header = plt.Rectangle((0, 0.85), 1, 0.15, transform=fig.transFigure,
                               facecolor=COLORS['primary'], edgecolor='none')
        fig.patches.append(header)
        fig.text(0.5, 0.91, 'AD17 SOLUTIONS', fontsize=32, fontweight='bold',
                ha='center', color='white')

        fig.text(0.5, 0.72, 'REPORTE DE PRODUCTIVIDAD', fontsize=28, fontweight='bold',
                ha='center', color=COLORS['dark'])
        fig.text(0.5, 0.65, 'Y ANÁLISIS DE TIEMPOS', fontsize=24, ha='center', color=COLORS['gray'])

        periodo = f"{self.fecha_inicio.strftime('%d/%m/%Y')} - {self.fecha_fin.strftime('%d/%m/%Y')}"
        fig.text(0.5, 0.55, periodo, fontsize=16, ha='center', color=COLORS['secondary'])

        gen = self.metricas['general']
        metricas = [
            ('Total Horas', format_hours(gen['total_horas'])),
            ('Registros', format_number(gen['total_registros'])),
            ('Trabajadores', str(gen['empleados_activos'])),
            ('Proyectos', str(gen['proyectos_activos']))
        ]

        box_w, box_h = 0.18, 0.12
        start_x = 0.5 - (len(metricas) * box_w + (len(metricas)-1) * 0.03) / 2

        for i, (label, value) in enumerate(metricas):
            x = start_x + i * (box_w + 0.03)
            y = 0.30

            shadow = plt.Rectangle((x+0.004, y-0.004), box_w, box_h, transform=fig.transFigure,
                                   facecolor='#E0E0E0', edgecolor='none')
            fig.patches.append(shadow)
            rect = plt.Rectangle((x, y), box_w, box_h, transform=fig.transFigure,
                                 facecolor='white', edgecolor=COLORS['primary'], linewidth=2)
            fig.patches.append(rect)
            top = plt.Rectangle((x, y+box_h-0.015), box_w, 0.015, transform=fig.transFigure,
                               facecolor=COLORS['primary'])
            fig.patches.append(top)

            fig.text(x+box_w/2, y+box_h*0.55, value, fontsize=18, fontweight='bold',
                    ha='center', va='center', color=COLORS['dark'])
            fig.text(x+box_w/2, y+box_h*0.2, label, fontsize=9, ha='center', color=COLORS['gray'])

        fig.text(0.5, 0.08, f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")}',
                fontsize=10, ha='center', color=COLORS['gray'])

        plt.axis('off')

        # Exporta PNG de página (sin axes)
        self._export_page_and_axes(fig, "portada", axes=None)

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_resumen(self, pdf):
        print("   📊 Resumen ejecutivo...")
        fig = plt.figure(figsize=(11, 8.5))

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure,
                               facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'RESUMEN EJECUTIVO', fontsize=20, fontweight='bold',
                ha='center', color='white')

        gen = self.metricas['general']
        kpis = [
            ('Total Horas', format_hours(gen['total_horas']), COLORS['primary'], '⏱️'),
            ('Total Registros', format_number(gen['total_registros']), COLORS['secondary'], '📝'),
            ('Finalizados', format_number(gen['registros_finalizados']), COLORS['success'], '✅'),
            ('Activos', format_number(gen['registros_activos']), COLORS['warning'], '🔄'),
            ('Trabajadores', str(gen['empleados_activos']), COLORS['info'], '👷'),
            ('Proyectos', str(gen['proyectos_activos']), COLORS['purple'], '📁'),
            ('Departamentos', str(gen['departamentos']), COLORS['teal'], '🏢'),
            ('Días Activos', str(gen['dias_actividad']), COLORS['danger'], '📅'),
            ('Hrs/Día', format_hours(gen['promedio_horas_dia']), COLORS['primary'], '📈'),
            ('Hrs/Trabajador', format_hours(gen['promedio_horas_trabajador']), COLORS['success'], '👤'),
            ('Finalización', f"{gen['tasa_finalizacion']:.1f}%", COLORS['secondary'], '🎯'),
            ('Período', f"{gen['dias_periodo']} días", COLORS['info'], '📆')
        ]

        cols, rows = 4, 3
        box_w, box_h = 0.2, 0.18
        margin_x = 0.08

        for i, (label, value, color, icon) in enumerate(kpis):
            row = i // cols
            col = i % cols
            x = margin_x + col * (box_w + 0.04)
            y = 0.68 - row * (box_h + 0.06)

            shadow = plt.Rectangle((x+0.003, y-0.003), box_w, box_h, transform=fig.transFigure,
                                   facecolor='#E0E0E0')
            fig.patches.append(shadow)
            rect = plt.Rectangle((x, y), box_w, box_h, transform=fig.transFigure,
                                 facecolor='white', edgecolor='#E0E0E0', linewidth=1)
            fig.patches.append(rect)
            top = plt.Rectangle((x, y+box_h-0.012), box_w, 0.012, transform=fig.transFigure,
                               facecolor=color)
            fig.patches.append(top)

            fig.text(x+0.02, y+box_h*0.7, icon, fontsize=14, ha='left')
            fig.text(x+box_w/2, y+box_h*0.5, value, fontsize=15, fontweight='bold',
                    ha='center', color=COLORS['dark'])
            fig.text(x+box_w/2, y+box_h*0.18, label, fontsize=8, ha='center', color=COLORS['gray'])

        plt.axis('off')

        self._export_page_and_axes(fig, "resumen_ejecutivo", axes=None)

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_departamentos(self, pdf):
        print("   🏢 Departamentos...")
        dept_data = self.metricas['por_departamento']
        if not dept_data:
            return

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure,
                               facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS POR DEPARTAMENTO', fontsize=20, fontweight='bold',
                ha='center', color='white')

        df = pd.DataFrame(dept_data)

        ax1 = fig.add_subplot(gs[0, 0])
        colors = [DEPT_COLORS.get(d, '#9E9E9E') for d in df['departamento']]
        wedges, _, _ = ax1.pie(df['horas'], labels=None,
                               autopct=lambda p: f'{p:.1f}%' if p > 5 else '',
                               colors=colors, wedgeprops=dict(width=0.6, edgecolor='white'))
        ax1.set_title('Distribución de Horas', fontweight='bold', pad=10)
        legend_labels = [f"{truncate_text(d, 12)} ({format_hours(h)})" for d, h in zip(df['departamento'], df['horas'])]
        leg1 = ax1.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        ax2 = fig.add_subplot(gs[0, 1])
        colors2 = [DEPT_COLORS.get(d, '#9E9E9E') for d in df['departamento']]
        bars = ax2.barh(range(len(df)), df['horas'], color=colors2, edgecolor='white', height=0.7)
        ax2.set_yticks(range(len(df)))
        ax2.set_yticklabels([truncate_text(d, 15) for d in df['departamento']], fontsize=9)
        ax2.invert_yaxis()
        ax2.set_xlabel('Horas')
        ax2.set_title('Horas por Departamento', fontweight='bold', pad=10)
        for bar, val in zip(bars, df['horas']):
            ax2.text(bar.get_width() + max(df['horas'])*0.02, bar.get_y()+bar.get_height()/2,
                    format_hours(val), va='center', fontsize=8)

        ax3 = fig.add_subplot(gs[1, 0])
        colors3 = [DEPT_COLORS.get(d, '#9E9E9E') for d in df['departamento']]
        bars3 = ax3.bar(range(len(df)), df['trabajadores'], color=colors3, edgecolor='white')
        ax3.set_xticks(range(len(df)))
        ax3.set_xticklabels([truncate_text(d, 8) for d in df['departamento']], rotation=45, ha='right', fontsize=8)
        ax3.set_ylabel('Trabajadores')
        ax3.set_title('Trabajadores por Departamento', fontweight='bold', pad=10)
        for bar, val in zip(bars3, df['trabajadores']):
            ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.3, str(int(val)), ha='center', fontsize=9)

        ax4 = fig.add_subplot(gs[1, 1])
        df_sorted = df.sort_values('horas_por_trabajador', ascending=True)
        colors4 = [DEPT_COLORS.get(d, '#9E9E9E') for d in df_sorted['departamento']]
        bars4 = ax4.barh(range(len(df_sorted)), df_sorted['horas_por_trabajador'], color=colors4,
                         edgecolor='white', height=0.7)
        ax4.set_yticks(range(len(df_sorted)))
        ax4.set_yticklabels([truncate_text(d, 15) for d in df_sorted['departamento']], fontsize=9)
        ax4.set_xlabel('Horas/Trabajador')
        ax4.set_title('Eficiencia por Departamento', fontweight='bold', pad=10)
        for bar, val in zip(bars4, df_sorted['horas_por_trabajador']):
            ax4.text(bar.get_width()+max(df_sorted['horas_por_trabajador'])*0.02, bar.get_y()+bar.get_height()/2,
                    format_hours(val), va='center', fontsize=8)

        self._export_page_and_axes(
            fig, "departamentos",
            axes=[ax1, ax2, ax3, ax4],
            axes_names=["donut_horas", "barras_horas", "barras_trabajadores", "eficiencia_horas_por_trabajador"],
            axes_extra=[[leg1], [], [], []]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_trabajadores(self, pdf):
        print("   👷 Trabajadores...")
        worker_data = self.metricas['por_trabajador']
        if not worker_data:
            return

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS DE TRABAJADORES', fontsize=20, fontweight='bold', ha='center', color='white')

        df = pd.DataFrame(worker_data)

        ax1 = fig.add_subplot(gs[0, 0])
        top15 = df.nlargest(15, 'horas')
        colors1 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15['departamento']]
        bars1 = ax1.barh(range(len(top15)), top15['horas'], color=colors1, height=0.7)
        ax1.set_yticks(range(len(top15)))
        ax1.set_yticklabels([truncate_text(n, 20) for n in top15['nombre']], fontsize=8)
        ax1.invert_yaxis()
        ax1.set_xlabel('Horas')
        ax1.set_title('Top 15 - Horas Trabajadas', fontweight='bold', pad=10)
        for bar, val in zip(bars1, top15['horas']):
            ax1.text(bar.get_width()+max(top15['horas'])*0.02, bar.get_y()+bar.get_height()/2,
                     format_hours(val), va='center', fontsize=7)

        ax2 = fig.add_subplot(gs[0, 1])
        top15_reg = df.nlargest(15, 'registros')
        colors2 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15_reg['departamento']]
        bars2 = ax2.barh(range(len(top15_reg)), top15_reg['registros'], color=colors2, height=0.7)
        ax2.set_yticks(range(len(top15_reg)))
        ax2.set_yticklabels([truncate_text(n, 20) for n in top15_reg['nombre']], fontsize=8)
        ax2.invert_yaxis()
        ax2.set_xlabel('Registros')
        ax2.set_title('Top 15 - Cantidad de Registros', fontweight='bold', pad=10)
        for bar, val in zip(bars2, top15_reg['registros']):
            ax2.text(bar.get_width()+max(top15_reg['registros'])*0.02, bar.get_y()+bar.get_height()/2,
                     str(int(val)), va='center', fontsize=7)

        ax3 = fig.add_subplot(gs[1, 0])
        ax3.hist(df['horas'], bins=20, color=COLORS['primary'], edgecolor='white', alpha=0.8)
        l1 = ax3.axvline(df['horas'].mean(), color=COLORS['danger'], linestyle='--', linewidth=2,
                         label=f'Media: {format_hours(df["horas"].mean())}')
        l2 = ax3.axvline(df['horas'].median(), color=COLORS['success'], linestyle='--', linewidth=2,
                         label=f'Mediana: {format_hours(df["horas"].median())}')
        ax3.set_xlabel('Horas')
        ax3.set_ylabel('Frecuencia')
        ax3.set_title('Distribución de Horas', fontweight='bold', pad=10)
        leg3 = ax3.legend(fontsize=8)

        ax4 = fig.add_subplot(gs[1, 1])
        top15_proy = df.nlargest(15, 'proyectos')
        colors4 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15_proy['departamento']]
        bars4 = ax4.barh(range(len(top15_proy)), top15_proy['proyectos'], color=colors4, height=0.7)
        ax4.set_yticks(range(len(top15_proy)))
        ax4.set_yticklabels([truncate_text(n, 20) for n in top15_proy['nombre']], fontsize=8)
        ax4.invert_yaxis()
        ax4.set_xlabel('Proyectos')
        ax4.set_title('Top 15 - Versatilidad', fontweight='bold', pad=10)
        for bar, val in zip(bars4, top15_proy['proyectos']):
            ax4.text(bar.get_width()+max(top15_proy['proyectos'])*0.02, bar.get_y()+bar.get_height()/2,
                     str(int(val)), va='center', fontsize=7)

        patches = [mpatches.Patch(color=c, label=d) for d, c in DEPT_COLORS.items() if d in df['departamento'].values]
        fig.legend(handles=patches, loc='lower center', ncol=min(7, len(patches)), fontsize=8,
                   frameon=False, bbox_to_anchor=(0.5, 0.01))

        self._export_page_and_axes(
            fig, "trabajadores",
            axes=[ax1, ax2, ax3, ax4],
            axes_names=["top15_horas", "top15_registros", "hist_horas", "top15_proyectos"],
            axes_extra=[[], [], [leg3], []]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_proyectos(self, pdf):
        print("   📁 Proyectos...")
        proj_data = self.metricas['por_proyecto']
        if not proj_data:
            return

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS DE PROYECTOS', fontsize=20, fontweight='bold', ha='center', color='white')

        df = pd.DataFrame(proj_data)

        ax1 = fig.add_subplot(gs[0, 0])
        top15 = df.nlargest(15, 'horas')
        colors1 = plt.cm.Blues(np.linspace(0.4, 0.9, len(top15)))[::-1]
        bars1 = ax1.barh(range(len(top15)), top15['horas'], color=colors1, height=0.7)
        ax1.set_yticks(range(len(top15)))
        labels1 = [f"FP:{f} {truncate_text(n, 15)}" for n, f in zip(top15['nombre'], top15['folio'])]
        ax1.set_yticklabels(labels1, fontsize=7)
        ax1.invert_yaxis()
        ax1.set_xlabel('Horas')
        ax1.set_title('Top 15 Proyectos - Horas', fontweight='bold', pad=10)
        for bar, val in zip(bars1, top15['horas']):
            ax1.text(bar.get_width()+max(top15['horas'])*0.02, bar.get_y()+bar.get_height()/2,
                     format_hours(val), va='center', fontsize=7)

        ax2 = fig.add_subplot(gs[0, 1])
        top15_team = df.nlargest(15, 'trabajadores')
        colors2 = plt.cm.Oranges(np.linspace(0.4, 0.9, len(top15_team)))[::-1]
        bars2 = ax2.barh(range(len(top15_team)), top15_team['trabajadores'], color=colors2, height=0.7)
        ax2.set_yticks(range(len(top15_team)))
        labels2 = [f"FP:{f} {truncate_text(n, 15)}" for n, f in zip(top15_team['nombre'], top15_team['folio'])]
        ax2.set_yticklabels(labels2, fontsize=7)
        ax2.invert_yaxis()
        ax2.set_xlabel('Trabajadores')
        ax2.set_title('Top 15 - Tamaño de Equipo', fontweight='bold', pad=10)
        for bar, val in zip(bars2, top15_team['trabajadores']):
            ax2.text(bar.get_width()+max(top15_team['trabajadores'])*0.02, bar.get_y()+bar.get_height()/2,
                     str(int(val)), va='center', fontsize=7)

        ax3 = fig.add_subplot(gs[1, 0])
        df_sorted = df.nlargest(30, 'horas')
        total = df_sorted['horas'].sum()
        cumsum = df_sorted['horas'].cumsum() / total * 100 if total > 0 else df_sorted['horas'].cumsum()

        ax3_bar = ax3
        ax3_line = ax3.twinx()
        ax3_bar.bar(range(len(df_sorted)), df_sorted['horas'], color=COLORS['primary'], alpha=0.7)
        ax3_line.plot(range(len(df_sorted)), cumsum, color=COLORS['danger'], marker='o',
                      markersize=3, linewidth=2)
        ax3_line.axhline(80, color=COLORS['success'], linestyle='--', alpha=0.7)
        ax3_bar.set_xticks(range(len(df_sorted)))
        ax3_bar.set_xticklabels([str(f)[:5] for f in df_sorted['folio']], rotation=45, ha='right', fontsize=6)
        ax3_bar.set_ylabel('Horas')
        ax3_line.set_ylabel('% Acumulado')
        ax3_line.set_ylim(0, 105)
        ax3.set_title('Análisis Pareto (80/20)', fontweight='bold', pad=10)

        ax4 = fig.add_subplot(gs[1, 1])
        ax4.hist(df['horas'], bins=25, color=COLORS['secondary'], edgecolor='white', alpha=0.8)
        ax4.axvline(df['horas'].mean(), color=COLORS['danger'], linestyle='--', linewidth=2,
                    label=f'Media: {format_hours(df["horas"].mean())}')
        ax4.set_xlabel('Horas')
        ax4.set_ylabel('Frecuencia')
        ax4.set_title('Distribución de Horas', fontweight='bold', pad=10)
        leg4 = ax4.legend(fontsize=8)

        self._export_page_and_axes(
            fig, "proyectos",
            axes=[ax1, ax2, ax3_bar, ax4],
            axes_names=["top15_horas", "top15_equipo", "pareto_8020", "hist_horas"],
            axes_extra=[[], [], [ax3_line], [leg4]]  # incluye eje twin y la leyenda
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_clientes(self, pdf):
        print("   🏢 Clientes...")
        client_data = self.metricas['por_cliente']
        if not client_data:
            return

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS POR CLIENTE', fontsize=20, fontweight='bold', ha='center', color='white')

        df = pd.DataFrame(client_data)

        ax1 = fig.add_subplot(gs[0, 0])
        top15 = df.nlargest(15, 'horas')
        colors1 = plt.cm.Purples(np.linspace(0.4, 0.9, len(top15)))[::-1]
        bars1 = ax1.barh(range(len(top15)), top15['horas'], color=colors1, height=0.7)
        ax1.set_yticks(range(len(top15)))
        ax1.set_yticklabels([truncate_text(c, 22) for c in top15['cliente']], fontsize=8)
        ax1.invert_yaxis()
        ax1.set_xlabel('Horas')
        ax1.set_title('Top 15 Clientes - Horas', fontweight='bold', pad=10)
        for bar, val in zip(bars1, top15['horas']):
            ax1.text(bar.get_width()+max(top15['horas'])*0.02, bar.get_y()+bar.get_height()/2,
                     format_hours(val), va='center', fontsize=7)

        ax2 = fig.add_subplot(gs[0, 1])
        top15_proj = df.nlargest(15, 'proyectos')
        colors2 = plt.cm.Greens(np.linspace(0.4, 0.9, len(top15_proj)))[::-1]
        bars2 = ax2.barh(range(len(top15_proj)), top15_proj['proyectos'], color=colors2, height=0.7)
        ax2.set_yticks(range(len(top15_proj)))
        ax2.set_yticklabels([truncate_text(c, 22) for c in top15_proj['cliente']], fontsize=8)
        ax2.invert_yaxis()
        ax2.set_xlabel('Proyectos')
        ax2.set_title('Top 15 - Cantidad de Proyectos', fontweight='bold', pad=10)
        for bar, val in zip(bars2, top15_proj['proyectos']):
            ax2.text(bar.get_width()+max(top15_proj['proyectos'])*0.02, bar.get_y()+bar.get_height()/2,
                     str(int(val)), va='center', fontsize=7)

        ax3 = fig.add_subplot(gs[1, 0])
        top10 = df.nlargest(10, 'horas')
        otros = df['horas'].sum() - top10['horas'].sum()
        if otros > 0:
            labels = list(top10['cliente']) + ['Otros']
            sizes = list(top10['horas']) + [otros]
        else:
            labels = list(top10['cliente'])
            sizes = list(top10['horas'])
        colors3 = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        wedges, _, _ = ax3.pie(sizes, labels=None, autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
                               colors=colors3, wedgeprops=dict(width=0.6, edgecolor='white'))
        ax3.set_title('Distribución (Top 10 + Otros)', fontweight='bold', pad=10)
        legend_labels = [f"{truncate_text(l, 12)} ({format_hours(s)})" for l, s in zip(labels, sizes)]
        leg3 = ax3.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=7)

        ax4 = fig.add_subplot(gs[1, 1])
        ax4.axis('off')
        total_horas = df['horas'].sum()
        top5_pct = df.nlargest(5, 'horas')['horas'].sum() / total_horas * 100 if total_horas > 0 else 0
        top10_pct = df.nlargest(10, 'horas')['horas'].sum() / total_horas * 100 if total_horas > 0 else 0

        stats = f"""
ESTADÍSTICAS DE CLIENTES

Total de Clientes: {len(df)}

Concentración:
• Top 5: {top5_pct:.1f}% del total
• Top 10: {top10_pct:.1f}% del total

Promedios:
• Horas/Cliente: {format_hours(df['horas'].mean())}
• Proyectos/Cliente: {df['proyectos'].mean():.1f}
"""
        ax4.text(0.1, 0.9, stats, transform=ax4.transAxes, fontsize=10, va='top', fontfamily='monospace',
                 bbox=dict(boxstyle='round', facecolor=COLORS['light_gray'], alpha=0.8))

        self._export_page_and_axes(
            fig, "clientes",
            axes=[ax1, ax2, ax3, ax4],
            axes_names=["top15_horas", "top15_proyectos", "donut_top10_mas_otros", "stats"],
            axes_extra=[[], [], [leg3], []]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_actividades(self, pdf):
        print("   📋 Actividades...")
        act_data = self.metricas['por_actividad']
        if not act_data:
            return

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS DE ACTIVIDADES', fontsize=20, fontweight='bold', ha='center', color='white')

        df = pd.DataFrame(act_data)

        ax1 = fig.add_subplot(gs[0, 0])
        top15 = df.nlargest(15, 'horas')
        colors1 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15['departamento']]
        bars1 = ax1.barh(range(len(top15)), top15['horas'], color=colors1, height=0.7)
        ax1.set_yticks(range(len(top15)))
        ax1.set_yticklabels([truncate_text(a, 28) for a in top15['actividad']], fontsize=7)
        ax1.invert_yaxis()
        ax1.set_xlabel('Horas')
        ax1.set_title('Top 15 Actividades - Horas', fontweight='bold', pad=10)
        for bar, val in zip(bars1, top15['horas']):
            ax1.text(bar.get_width()+max(top15['horas'])*0.02, bar.get_y()+bar.get_height()/2,
                     format_hours(val), va='center', fontsize=7)

        ax2 = fig.add_subplot(gs[0, 1])
        top15_freq = df.nlargest(15, 'registros')
        colors2 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15_freq['departamento']]
        bars2 = ax2.barh(range(len(top15_freq)), top15_freq['registros'], color=colors2, height=0.7)
        ax2.set_yticks(range(len(top15_freq)))
        ax2.set_yticklabels([truncate_text(a, 28) for a in top15_freq['actividad']], fontsize=7)
        ax2.invert_yaxis()
        ax2.set_xlabel('Registros')
        ax2.set_title('Top 15 - Frecuencia', fontweight='bold', pad=10)
        for bar, val in zip(bars2, top15_freq['registros']):
            ax2.text(bar.get_width()+max(top15_freq['registros'])*0.02, bar.get_y()+bar.get_height()/2,
                     str(int(val)), va='center', fontsize=7)

        ax3 = fig.add_subplot(gs[1, 0])
        top15_dur = df.nlargest(15, 'horas_promedio')
        colors3 = [DEPT_COLORS.get(d, '#9E9E9E') for d in top15_dur['departamento']]
        bars3 = ax3.barh(range(len(top15_dur)), top15_dur['horas_promedio'], color=colors3, height=0.7)
        ax3.set_yticks(range(len(top15_dur)))
        ax3.set_yticklabels([truncate_text(a, 28) for a in top15_dur['actividad']], fontsize=7)
        ax3.invert_yaxis()
        ax3.set_xlabel('Horas (promedio)')
        ax3.set_title('Duración Promedio', fontweight='bold', pad=10)
        for bar, val in zip(bars3, top15_dur['horas_promedio']):
            ax3.text(bar.get_width()+max(top15_dur['horas_promedio'])*0.02, bar.get_y()+bar.get_height()/2,
                     format_hours(val), va='center', fontsize=7)

        ax4 = fig.add_subplot(gs[1, 1])
        dept_hours = df.groupby('departamento')['horas'].sum().sort_values(ascending=False)
        colors4 = [DEPT_COLORS.get(d, '#9E9E9E') for d in dept_hours.index]
        wedges, _, _ = ax4.pie(dept_hours.values, labels=None,
                               autopct=lambda p: f'{p:.1f}%' if p > 5 else '',
                               colors=colors4, wedgeprops=dict(width=0.6, edgecolor='white'))
        ax4.set_title('Horas por Departamento', fontweight='bold', pad=10)
        legend_labels = [f"{d} ({format_hours(h)})" for d, h in zip(dept_hours.index, dept_hours.values)]
        leg4 = ax4.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)

        self._export_page_and_axes(
            fig, "actividades",
            axes=[ax1, ax2, ax3, ax4],
            axes_names=["top15_horas", "top15_frecuencia", "top15_duracion_promedio", "donut_horas_por_departamento"],
            axes_extra=[[], [], [], [leg4]]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_temporal(self, pdf):
        print("   📅 Temporal (1)...")
        temporal = self.metricas['temporal']

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3,
                     left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS TEMPORAL', fontsize=20, fontweight='bold', ha='center', color='white')

        ax1 = fig.add_subplot(gs[0, :])
        mes_data = temporal['por_mes']
        if mes_data:
            df_mes = pd.DataFrame(mes_data)
            x = range(len(df_mes))
            ax1.bar(x, df_mes['horas'], color=COLORS['primary'], alpha=0.7)
            ax1.set_xticks(x)
            ax1.set_xticklabels(df_mes['mes'], rotation=45, ha='right')
            ax1.set_ylabel('Horas')
            ax1.set_title('Evolución Mensual', fontweight='bold', pad=10)
            for i, h in enumerate(df_mes['horas']):
                ax1.text(i, h + max(df_mes['horas'])*0.02, format_hours(h), ha='center', fontsize=8)

        ax2 = fig.add_subplot(gs[1, 0])
        dow_data = temporal['por_dia_semana']
        if dow_data:
            df_dow = pd.DataFrame(dow_data)
            colors2 = [COLORS['danger'] if d >= 5 else COLORS['primary'] for d in df_dow['dia_semana']]
            bars = ax2.bar(df_dow['dia_nombre'], df_dow['horas'], color=colors2, edgecolor='white')
            ax2.set_ylabel('Horas')
            ax2.set_title('Horas por Día de Semana', fontweight='bold', pad=10)
            ax2.tick_params(axis='x', rotation=45)
            for bar, val in zip(bars, df_dow['horas']):
                ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+max(df_dow['horas'])*0.02,
                         format_hours(val), ha='center', fontsize=8)

        ax3 = fig.add_subplot(gs[1, 1])
        hora_data = temporal['por_hora']
        leg3 = None
        if hora_data:
            df_hora = pd.DataFrame(hora_data)
            ax3.fill_between(df_hora['hora'], df_hora['registros'], alpha=0.3, color=COLORS['secondary'])
            ax3.plot(df_hora['hora'], df_hora['registros'], color=COLORS['secondary'], linewidth=2,
                     marker='o', markersize=4)
            ax3.set_xlabel('Hora')
            ax3.set_ylabel('Registros')
            ax3.set_title('Actividad por Hora', fontweight='bold', pad=10)
            ax3.set_xticks(range(0, 24, 2))
            if len(df_hora) > 0:
                hora_pico = df_hora.loc[df_hora['registros'].idxmax(), 'hora']
                ax3.axvline(hora_pico, color=COLORS['danger'], linestyle='--', alpha=0.7,
                            label=f'Pico: {int(hora_pico)}:00')
                leg3 = ax3.legend(fontsize=8)

        self._export_page_and_axes(
            fig, "temporal_1",
            axes=[ax1, ax2, ax3],
            axes_names=["evolucion_mensual", "horas_por_dia_semana", "actividad_por_hora"],
            axes_extra=[[], [], [leg3] if leg3 else []]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_temporal2(self, pdf):
        print("   📅 Temporal (2)...")
        temporal = self.metricas['temporal']

        fig = plt.figure(figsize=(11, 8.5))
        gs = GridSpec(2, 1, figure=fig, hspace=0.35, left=0.08, right=0.92, top=0.88, bottom=0.08)

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'ANÁLISIS TEMPORAL (CONT.)', fontsize=20, fontweight='bold', ha='center', color='white')

        ax1 = fig.add_subplot(gs[0])
        dia_data = temporal['por_dia']
        leg1 = None
        if dia_data:
            df_dia = pd.DataFrame(dia_data)
            df_dia['fecha'] = pd.to_datetime(df_dia['fecha'])
            ax1.fill_between(df_dia['fecha'], df_dia['horas'], alpha=0.3, color=COLORS['primary'])
            ax1.plot(df_dia['fecha'], df_dia['horas'], color=COLORS['primary'], linewidth=1)
            if len(df_dia) > 7:
                df_dia['ma7'] = df_dia['horas'].rolling(window=7, min_periods=1).mean()
                ax1.plot(df_dia['fecha'], df_dia['ma7'], color=COLORS['danger'], linewidth=2, label='Promedio 7 días')
                leg1 = ax1.legend(fontsize=8)
            ax1.set_xlabel('Fecha')
            ax1.set_ylabel('Horas')
            ax1.set_title('Evolución Diaria', fontweight='bold', pad=10)
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

        ax2 = fig.add_subplot(gs[1])
        registros_fin = [r for r in self.registros if r['end_time'] is not None and r['start_time']]
        if registros_fin:
            heatmap_data = {}
            for r in registros_fin:
                dow = r['start_time'].weekday()
                hora = r['start_time'].hour
                key = (dow, hora)
                heatmap_data[key] = heatmap_data.get(key, 0) + 1

            matrix = np.zeros((7, 24))
            for (dow, hora), count in heatmap_data.items():
                matrix[dow, hora] = count

            sns.heatmap(matrix, cmap='YlOrRd', ax=ax2, cbar_kws={'label': 'Registros'})
            ax2.set_yticklabels(['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'], rotation=0)
            ax2.set_xlabel('Hora')
            ax2.set_ylabel('Día')
            ax2.set_title('Mapa de Calor: Día vs Hora', fontweight='bold', pad=10)

        self._export_page_and_axes(
            fig, "temporal_2",
            axes=[ax1, ax2],
            axes_names=["evolucion_diaria", "heatmap_dia_hora"],
            axes_extra=[[leg1] if leg1 else [], []]
        )

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_rankings(self, pdf):
        print("   🏆 Rankings...")
        fig = plt.figure(figsize=(11, 8.5))

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'RANKINGS Y RECONOCIMIENTOS', fontsize=20, fontweight='bold', ha='center', color='white')

        workers = self.metricas['por_trabajador']
        projects = self.metricas['por_proyecto']

        y = 0.85
        fig.text(0.08, y, '🏆 TOP 10 - HORAS TRABAJADAS', fontsize=12, fontweight='bold')
        for i, w in enumerate(workers[:10]):
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i+1}.'
            fig.text(0.08, y - 0.025 - i*0.022,
                     f"  {medal} {truncate_text(w['nombre'], 25)} - {format_hours(w['horas'])} ({w['departamento']})",
                     fontsize=9)

        workers_vers = sorted(workers, key=lambda x: x['proyectos'], reverse=True)
        fig.text(0.55, y, '🌟 TOP 10 - VERSATILIDAD', fontsize=12, fontweight='bold')
        for i, w in enumerate(workers_vers[:10]):
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i+1}.'
            fig.text(0.55, y - 0.025 - i*0.022,
                     f"  {medal} {truncate_text(w['nombre'], 25)} - {w['proyectos']} proyectos",
                     fontsize=9)

        y2 = 0.52
        fig.text(0.08, y2, '📁 TOP 10 PROYECTOS - HORAS', fontsize=12, fontweight='bold')
        for i, p in enumerate(projects[:10]):
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i+1}.'
            fig.text(0.08, y2 - 0.025 - i*0.022,
                     f"  {medal} FP:{p['folio']} {truncate_text(p['nombre'], 18)} - {format_hours(p['horas'])} ({p['trabajadores']} pers.)",
                     fontsize=9)

        workers_eff = sorted([w for w in workers if w['dias_trabajados'] >= 5],
                             key=lambda x: x['horas_por_dia'], reverse=True)
        fig.text(0.55, y2, '⚡ TOP 10 - EFICIENCIA (≥5 días)', fontsize=12, fontweight='bold')
        for i, w in enumerate(workers_eff[:10]):
            medal = '🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else f'{i+1}.'
            fig.text(0.55, y2 - 0.025 - i*0.022,
                     f"  {medal} {truncate_text(w['nombre'], 25)} - {w['horas_por_dia']:.1f}h/día",
                     fontsize=9)

        fig.text(0.5, 0.05, '* Rankings basados en registros finalizados', fontsize=9,
                 ha='center', color=COLORS['gray'], style='italic')

        plt.axis('off')

        self._export_page_and_axes(fig, "rankings", axes=None)

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    def _pagina_final(self, pdf):
        print("   📊 Resumen final...")
        fig = plt.figure(figsize=(11, 8.5))

        header = plt.Rectangle((0, 0.92), 1, 0.08, transform=fig.transFigure, facecolor=COLORS['primary'])
        fig.patches.append(header)
        fig.text(0.5, 0.96, 'RESUMEN FINAL', fontsize=20, fontweight='bold', ha='center', color='white')

        gen = self.metricas['general']
        dept = self.metricas['por_departamento'][:5]
        proj = self.metricas['por_proyecto'][:5]

        resumen = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                        INDICADORES CLAVE DEL PERÍODO                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║   📅 Período: {self.fecha_inicio.strftime('%d/%m/%Y')} - {self.fecha_fin.strftime('%d/%m/%Y')} ({gen['dias_periodo']} días)                      ║
║                                                                               ║
║   ⏱️  PRODUCTIVIDAD                                                           ║
║       • Total Horas: {format_hours(gen['total_horas']):>20}                                    ║
║       • Total Registros: {format_number(gen['total_registros']):>17}                                    ║
║       • Promedio Horas/Día: {format_hours(gen['promedio_horas_dia']):>14}                                    ║
║       • Días con Actividad: {gen['dias_actividad']:>14}                                    ║
║                                                                               ║
║   👥 EQUIPO                                                                   ║
║       • Trabajadores Activos: {gen['empleados_activos']:>12}                                    ║
║       • Horas/Trabajador: {format_hours(gen['promedio_horas_trabajador']):>16}                                    ║
║       • Departamentos: {gen['departamentos']:>19}                                    ║
║                                                                               ║
║   📁 PROYECTOS                                                                ║
║       • Proyectos Trabajados: {gen['proyectos_activos']:>12}                                    ║
║       • Tasa Finalización: {gen['tasa_finalizacion']:>14.1f}%                                    ║
║                                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                          TOP 5 DEPARTAMENTOS                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣"""
        for i, d in enumerate(dept):
            resumen += f"\n║   {i+1}. {truncate_text(d['departamento'], 18):18} │ {format_hours(d['horas']):>10} │ {d['trabajadores']:>3} pers. │ {d['registros']:>5} reg.  ║"

        resumen += f"""
╠══════════════════════════════════════════════════════════════════════════════╣
║                           TOP 5 PROYECTOS                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣"""
        for i, p in enumerate(proj):
            resumen += f"\n║   {i+1}. FP:{p['folio']:>5} {truncate_text(p['nombre'], 16):16} │ {format_hours(p['horas']):>10} │ {p['trabajadores']:>3} pers.    ║"

        resumen += """
╚══════════════════════════════════════════════════════════════════════════════╝"""

        fig.text(0.5, 0.5, resumen, fontsize=8, ha='center', va='center', fontfamily='monospace')
        fig.text(0.5, 0.03, f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")} - AD17 Solutions',
                fontsize=9, ha='center', color=COLORS['gray'], style='italic')

        plt.axis('off')

        self._export_page_and_axes(fig, "resumen_final", axes=None)

        pdf.savefig(fig, bbox_inches='tight')
        plt.close()

    # =============================================================================
    # EJECUCIÓN
    # =============================================================================
    def ejecutar(self):
        if not self.extraer_datos():
            return None, None, None

        if not self.calcular_metricas():
            return None, None, None

        pdf_file, zip_file = self.generar_pdf()
        excel_file = self.generar_excel()

        print("\n" + "=" * 70)
        print("✅ PROCESO COMPLETADO")
        print("=" * 70)
        print(f"📄 PDF: {pdf_file}")
        print(f"📊 Excel: {excel_file}")
        print(f"📦 ZIP: {zip_file}")
        print(f"📁 Carpeta: {self.export_root}/")

        return pdf_file, excel_file, zip_file


# =============================================================================
# MAIN
# =============================================================================
def main():
    import sys

    if len(sys.argv) >= 3:
        fecha_inicio = sys.argv[1]
        fecha_fin = sys.argv[2]
    elif len(sys.argv) == 2:
        year = int(sys.argv[1])
        fecha_inicio = f'{year}-01-01'
        fecha_fin = datetime.now().strftime('%Y-%m-%d')
    else:
        fecha_inicio = None
        fecha_fin = None

    reporte = ReporteProductividadAD17(fecha_inicio, fecha_fin)
    reporte.ejecutar()


if __name__ == "__main__":
    main()
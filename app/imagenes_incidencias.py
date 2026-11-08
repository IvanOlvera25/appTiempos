"""
Imagen de un informe de incidencia: una por informe, tomada con la cámara o
elegida de la galería.

Se guarda en disco (`instance/incidencias/informe_<id>.jpg`) y no en la base:
así no hace falta una migración. Queda fuera de `static/` para que solo la vea
quien puede ver el informe (la sirve `incidencias.imagen_informe`).

Toda imagen se vuelve a codificar como JPEG: se gira según la cámara, se reduce
a un tamaño razonable y pierde sus metadatos, entre ellos la ubicación GPS que
guardan los celulares.
"""
import io
import os
import re
import tempfile
from contextlib import suppress

from flask import current_app
from PIL import Image, ImageOps

TAMANO_MAX = 15 * 1024 * 1024    # lo que se acepta recibir
LADO_MAX = 1920                  # lo que se guarda
PIXELES_MAX = 60_000_000         # evita imágenes hechas para agotar la memoria
_NOMBRE = re.compile(r'informe_(\d+)\.jpg')


class ImagenInvalida(ValueError):
    """El mensaje es para el usuario."""


def carpeta():
    return (current_app.config.get('INCIDENCIAS_IMAGENES_DIR')
            or os.path.join(current_app.instance_path, 'incidencias'))


def ruta(report_id):
    return os.path.join(carpeta(), 'informe_%d.jpg' % int(report_id))


def version(report_id):
    """Marca para la URL de la imagen (cambia al reemplazarla), o None si no tiene."""
    try:
        return int(os.stat(ruta(report_id)).st_mtime)
    except OSError:
        return None


def con_imagen():
    """ids de los informes que tienen imagen, con una sola lectura de la carpeta."""
    try:
        nombres = os.listdir(carpeta())
    except OSError:
        return set()
    return {int(m.group(1)) for m in map(_NOMBRE.fullmatch, nombres) if m}


def preparar(archivo):
    """JPEG listo para guardar a partir del archivo subido; ImagenInvalida si no sirve."""
    datos = archivo.stream.read(TAMANO_MAX + 1)
    if not datos:
        raise ImagenInvalida('La imagen está vacía. Elige otra.')
    if len(datos) > TAMANO_MAX:
        raise ImagenInvalida('La imagen pesa más de 15 MB. Elige otra o tómala de nuevo.')
    try:
        with Image.open(io.BytesIO(datos)) as original:
            if original.width * original.height > PIXELES_MAX:
                raise ImagenInvalida('La imagen es demasiado grande. Elige otra.')
            img = ImageOps.exif_transpose(original)
            if img.mode in ('RGBA', 'LA') or 'transparency' in img.info:
                # JPEG no tiene transparencia: lo transparente queda en blanco
                img = img.convert('RGBA')
                fondo = Image.new('RGB', img.size, 'white')
                fondo.paste(img, mask=img.getchannel('A'))
                img = fondo
            else:
                img = img.convert('RGB')
            img.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
            salida = io.BytesIO()
            img.save(salida, 'JPEG', quality=85, optimize=True, progressive=True)
    except ImagenInvalida:
        raise
    except Exception as e:
        raise ImagenInvalida('Ese archivo no es una imagen que se pueda usar. '
                             'Elige una foto JPG o PNG.') from e
    return salida.getvalue()


def guardar(report_id, datos):
    """Escribe la imagen completa o nada: un corte a medias no deja un archivo roto."""
    destino = ruta(report_id)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=os.path.dirname(destino), suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(datos)
        os.replace(temporal, destino)
    except BaseException:
        with suppress(OSError):
            os.remove(temporal)
        raise


def borrar(report_id):
    with suppress(FileNotFoundError):
        os.remove(ruta(report_id))

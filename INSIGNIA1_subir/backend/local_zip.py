"""
Soporte para armar expedientes a partir de acuses descargados MANUALMENTE
(por ejemplo desde otro portal que exige captcha), sin pasar por el
Portal de Acuses 4-72 ni por PortalClient.

El usuario puede entregar:
  a) Una CARPETA que contiene uno o varios archivos .zip (cada .zip es un
     acuse individual, con la misma estructura que descarga el portal:
     RegisteredReceipt*.eml -> Htmlreceipt.pdf -> <hash>.eml -> adjuntos).
     Tambien se buscan .zip dentro de subcarpetas (por si vienen organizados
     en carpetas por fecha, etc).
  b) Un unico ZIP "maestro" que a su vez contiene varios .zip de acuses
     adentro (lo que se arma al comprimir la carpeta de descargas).
  c) Un unico ZIP que YA es un acuse individual (mismo caso de uso que
     "Individual", pero sin tener que pegar el ID y sin conexion al portal).
  d) Una CARPETA (la misma de (a), o distinta) con archivos .pdf SUELTOS
     directamente adentro -- el caso de acuses descargados uno por uno,
     manualmente, desde otro portal que no entrega un .zip. Tambien se
     buscan .pdf en subcarpetas. Un unico .pdf individual tambien es valido.

collect_zip_sources() normaliza los casos (a)-(c) a una lista de
(nombre_origen, zip_bytes) lista para pasarle una por una a
extractor.process_zip() / extractor.extract_acuse(), exactamente igual que
si vinieran del portal.

collect_pdf_sources() hace lo mismo para el caso (d): devuelve una lista de
(nombre_origen, pdf_bytes) lista para pasarle a
extractor.extract_acuse_from_pdf().

Quien llama (main.py) normalmente combina ambas listas para que una misma
carpeta pueda traer .zip del portal Y .pdf sueltos de otro portal a la vez.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path


class LocalZipError(Exception):
    """La carpeta/zip de entrada no trae ningun acuse reconocible."""


def _is_probable_acuse_zip(zip_bytes: bytes) -> bool:
    """Heuristica rapida: un acuse individual (el que ya procesa
    extractor.process_zip) siempre trae al menos un .eml en su interior."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            return any(n.lower().endswith(".eml") for n in zf.namelist())
    except Exception:
        return False


def _expand_master_zip(zip_bytes: bytes, origen: str) -> list[tuple[str, bytes]]:
    """Un .zip que el usuario entrego directamente (no una carpeta).

    Puede ser: (a) ya un acuse individual, o (b) un zip que por dentro trae
    varios .zip de acuses (por ejemplo, al comprimir toda la carpeta de
    descargas para subirla aqui)."""
    if _is_probable_acuse_zip(zip_bytes):
        return [(origen, zip_bytes)]

    out: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            nested = [n for n in zf.namelist() if n.lower().endswith(".zip")]
            for name in nested:
                data = zf.read(name)
                out.append((f"{origen}/{name}", data))
    except Exception:
        pass
    return out


def collect_zip_sources(path: str | Path) -> list[tuple[str, bytes]]:
    """Devuelve [(nombre_origen, zip_bytes), ...] a partir de una carpeta o
    un archivo .zip elegido por el usuario.

    Si `path` es una CARPETA y simplemente no trae ningun .zip adentro (por
    ejemplo, porque todo lo que tiene son .pdf sueltos -- ver
    collect_pdf_sources), esto devuelve una lista vacia en silencio: es
    tarea de quien llama (main.py) combinar esto con collect_pdf_sources()
    y decidir si el total combinado esta vacio. Solo se lanza LocalZipError
    cuando `path` es un .zip especifico que no trae ningun acuse reconocible
    adentro, o cuando la ruta no es ni carpeta ni .zip."""
    p = Path(path)
    sources: list[tuple[str, bytes]] = []

    if p.is_dir():
        zip_files = sorted(p.rglob("*.zip"))
        for zp in zip_files:
            try:
                data = zp.read_bytes()
            except Exception:
                continue
            rel = zp.relative_to(p)
            if _is_probable_acuse_zip(data):
                sources.append((str(rel), data))
            else:
                # tambien podria ser, dentro de la carpeta, un zip-maestro
                # con otros zips adentro
                sources.extend(_expand_master_zip(data, str(rel)))
        return sources
    elif p.is_file() and p.suffix.lower() == ".zip":
        data = p.read_bytes()
        sources = _expand_master_zip(data, p.name)
    else:
        raise LocalZipError("La ruta elegida no es ni una carpeta ni un archivo .zip.")

    if not sources:
        raise LocalZipError(
            "No se encontro ningun acuse reconocible dentro del .zip elegido."
        )
    return sources


def collect_pdf_sources(path: str | Path) -> list[tuple[str, bytes]]:
    """Devuelve [(nombre_origen, pdf_bytes), ...] a partir de una carpeta
    (busca .pdf tambien en subcarpetas) o un archivo .pdf individual. A
    diferencia de collect_zip_sources(), NO lanza error si no encuentra
    nada -- se usa como fuente complementaria (ver el modulo main.py, que
    combina esto con collect_zip_sources() para una misma carpeta)."""
    p = Path(path)
    sources: list[tuple[str, bytes]] = []

    if p.is_dir():
        for pdf in sorted(p.rglob("*.pdf")):
            try:
                data = pdf.read_bytes()
            except Exception:
                continue
            sources.append((str(pdf.relative_to(p)), data))
    elif p.is_file() and p.suffix.lower() == ".pdf":
        try:
            sources.append((p.name, p.read_bytes()))
        except Exception:
            pass

    return sources

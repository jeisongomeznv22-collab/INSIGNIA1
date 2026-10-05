"""
Visor de PDF dentro de Insignia (pedido de Andres, 30-sep): en 'Revisar
memorando' se ve la PETICION (lo que pidieron) al lado del resumen de la
respuesta, con scroll, para aprobar ahi mismo con mas certeza. Tambien se
puede ver el adjunto (expediente PDF, o cada PDF dentro del ZIP de una
masiva).

Las paginas se dibujan como imagenes PNG con pypdfium2 (ya viene en el .exe:
lo usa pdfplumber, que lee las peticiones). Si no se puede dibujar, el
dialogo ofrece abrir el archivo con el visor de Windows.
"""
from __future__ import annotations

import glob
import io
import os
import zipfile
from pathlib import Path
from typing import Optional

ANCHO_PX = 900        # nitidez de la pagina (se escala al ancho del panel)
MAX_PAGINAS = 40
_cache: dict = {}


def ruta_peticion(carpeta_peticiones: Path, radicado: str) -> Optional[Path]:
    """La peticion descargada de ese radicado (la mas reciente si hay varias):
    peticiones_descargadas\\<radicado>-Comunicacion interna - ....pdf"""
    rad = (radicado or "").strip()
    if not rad:
        return None
    candidatos = [Path(p) for p in glob.glob(str(Path(carpeta_peticiones) / f"{glob.escape(rad)}*.pdf"))]
    candidatos = [p for p in candidatos if p.is_file()]
    return max(candidatos, key=lambda p: p.stat().st_mtime) if candidatos else None


def documentos_de_adjunto(ruta: Optional[str]) -> list:
    """[(etiqueta, fuente)] para ver el adjunto: el PDF tal cual, o cada PDF
    de adentro si es un ZIP (fuente = (ruta_zip, nombre_interno))."""
    if not ruta:
        return []
    p = Path(ruta)
    if not p.is_file():
        return []
    if p.suffix.lower() == ".pdf":
        return [(f"Adjunto: {p.name}", str(p))]
    if p.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(p) as zf:
                nombres = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
        except (OSError, zipfile.BadZipFile):
            return []
        return [(f"ZIP {i}/{len(nombres)}: {Path(n).name}", (str(p), n)) for i, n in enumerate(nombres, start=1)]
    return []


def _leer_bytes(fuente) -> bytes:
    if isinstance(fuente, tuple):
        ruta_zip, interno = fuente
        with zipfile.ZipFile(ruta_zip) as zf:
            return zf.read(interno)
    return Path(fuente).read_bytes()


def _clave(fuente) -> tuple:
    ruta = fuente[0] if isinstance(fuente, tuple) else fuente
    try:
        mtime = os.path.getmtime(ruta)
    except OSError:
        mtime = 0
    return (repr(fuente), mtime)


def renderizar(fuente, ancho_px: int = ANCHO_PX, max_paginas: int = MAX_PAGINAS) -> tuple:
    """(lista de PNG en bytes, total_paginas). Lanza excepcion si no se puede."""
    clave = _clave(fuente) + (ancho_px, max_paginas)
    if clave in _cache:
        return _cache[clave]
    import pypdfium2 as pdfium

    datos = _leer_bytes(fuente)
    pdf = pdfium.PdfDocument(datos)
    try:
        total = len(pdf)
        imagenes = []
        for i in range(min(total, max_paginas)):
            pagina = pdf[i]
            try:
                escala = ancho_px / max(pagina.get_width(), 1)
                bitmap = pagina.render(scale=escala)
                img = bitmap.to_pil()
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                imagenes.append(buf.getvalue())
            finally:
                pagina.close()
    finally:
        pdf.close()
    if len(_cache) > 12:
        _cache.pop(next(iter(_cache)))
    _cache[clave] = (imagenes, total)
    return imagenes, total


def abrir_con_windows(fuente) -> Optional[str]:
    """Abre el PDF con el visor predeterminado. Si esta dentro de un ZIP, se
    extrae a una carpeta temporal. Devuelve un mensaje de error o None."""
    try:
        if isinstance(fuente, tuple):
            import tempfile
            destino = Path(tempfile.gettempdir()) / "insignia_visor" / Path(fuente[1]).name
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(_leer_bytes(fuente))
            ruta = str(destino)
        else:
            ruta = str(fuente)
        os.startfile(ruta)  # type: ignore[attr-defined]  (solo Windows)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"No se pudo abrir el archivo: {exc}"

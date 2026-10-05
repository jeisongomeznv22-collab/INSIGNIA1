"""
Franja del 1 al 16 de junio de 2026 (regla de Andrés): esos acuses NO están en
ningún portal; se arman a mano con tres piezas que Andrés baja sueltas
(evidencia 30-sep, Res. 15330 de Alexandra Romero López, que él unió con
iLovePDF en 'ilovepdf_merged.pdf'):
  1. el acto:           R_015330_05062026.pdf   (o AA_<n>_<ddmmaaaa>.pdf)
  2. el acta:           A1605210_R_015330_05062026.pdf   (A<ticket>_ + nombre del acto)
  3. el acuse de contingencia (bitácora del Ironport del MEN):
                        15330_ciudadano4@example.com.pdf
Insignia las reconoce y las une en ese orden (acto + acta + acuse), con el
nombre de siempre. Nunca se adivina: el acto debe tener el número (Resolución)
o el titular (Auto) y la fecha del Cuadro; el acta debe ser la de ESE acto; y el
acuse debe ser del Ironport y traer el correo del destinatario.
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import Optional

RE_ACTO = re.compile(r"^(R|AA)_0*(\d+)_(\d{2})(\d{2})(\d{4})\.pdf$", re.IGNORECASE)


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip().lower()


def _texto(ruta: Path, paginas: int = 3) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(ruta))
        return "\n".join((p.extract_text() or "") for p in r.pages[:paginas])
    except Exception:
        return ""


def _pdfs(carpetas: list) -> list:
    vistos, out = set(), []
    for c in carpetas:
        c = Path(c)
        if not c.is_dir():
            continue
        try:
            for p in sorted(c.iterdir()):
                if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith("~$"):
                    clave = (p.name.lower(), p.stat().st_size)
                    if clave not in vistos:
                        vistos.add(clave)
                        out.append(p)
        except OSError:
            continue
    return out


def piezas(carpetas: list, tipo: str, numero, fecha: str, titular: str, correos: list) -> Optional[tuple]:
    """(acto, acta, acuse) como rutas, o None si falta alguna pieza."""
    try:
        dd, mm, aaaa = (fecha or "").split("/")
    except ValueError:
        return None
    prefijo = "R" if tipo == "Resolucion" else "AA" if tipo == "Auto" else None
    if prefijo is None:
        return None
    n = str(numero or "").strip().lstrip("0")
    tit = _norm(titular)
    correos = [c.strip().lower() for c in correos if c]
    todos = _pdfs(carpetas)
    actos = []
    for p in todos:
        m = RE_ACTO.match(p.name)
        if not m or m.group(1).upper() != prefijo or (m.group(3), m.group(4), m.group(5)) != (dd, mm, aaaa):
            continue
        if tipo == "Resolucion" and m.group(2).lstrip("0") != n:
            continue
        if tipo == "Auto" and (not tit or tit not in _norm(_texto(p))):
            continue   # el AA_ trae la numeracion SIGAA: se exige el titular dentro del documento
        actos.append(p)
    for acto in actos:
        actas = [p for p in todos if p.name.lower().endswith("_" + acto.name.lower())
                 and re.match(r"^A\d+_", p.name, re.IGNORECASE)]
        actas = [p for p in actas if not tit or tit in _norm(_texto(p, 1))]
        if not actas:
            continue
        acuses = []
        for p in todos:
            nombre = p.name.lower()
            if not (any(c in nombre for c in correos) or (n and nombre.startswith(n + "_"))):
                continue
            t = _norm(_texto(p, 2))
            if ("ironport" in t or "secure email gateway" in t) and any(c in t for c in correos):
                acuses.append(p)
        if acuses:
            return acto, actas[0], acuses[0]
    return None


def unir(rutas: list) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for r in rutas:
        for pag in PdfReader(str(r)).pages:
            w.add_page(pag)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()

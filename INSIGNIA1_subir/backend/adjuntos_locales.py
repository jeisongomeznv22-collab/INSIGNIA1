"""
Ubicar en el PC el PDF (expediente) de un acto que Andres ya bajo a mano.

Evidencia (29-sep): '2026_24208.pdf' (Res. 24208 de 2026-IE-035664) y
'Auto 2128 del 08 09 2026.pdf' (2026-IE-036231) estaban en la carpeta
Descargas, pero Insignia solo miraba adjuntos_manuales\\<radicado>, y los
dos casos siguieron detenidos.

Reglas (nunca se adivina):
  - En adjuntos_manuales\\<radicado> (carpeta del caso), basta el NUMERO
    del acto en el nombre, o el unico PDF si el caso tiene un solo acto.
  - En Descargas (carpeta general, con muchos archivos) se exige mas:
      Resolucion: '<año>_<numero>' ('2026_24208', '2026_024208'), o
                  'Resolucion <numero>' / '<numero> <fecha> <nombre>' con la
                  FECHA del acto en el nombre.
      Auto:       la palabra 'auto' + la FECHA del acto ('08 09 2026') y
                  ademas el numero ('2128') o el nombre del titular.
    Si hay varios que calzan y son copias del mismo archivo ('x.pdf',
    'x (2).pdf') se toma el mas reciente; si son archivos distintos, no se
    elige ninguno.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _numero(n) -> str:
    s = str(n or "").strip()
    return str(int(s)) if s.isdigit() else s.lstrip("0")


def _fecha_partes(fecha: str) -> Optional[tuple]:
    partes = (fecha or "").split("/")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return None
    return int(partes[0]), int(partes[1]), partes[2]


_MESES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun", 7: "jul", 8: "ago",
          9: "(?:sep|set)", 10: "oct", 11: "nov", 12: "dic"}


def _re_fecha(fecha: str) -> Optional[re.Pattern]:
    """'08 09 2026', '8_09_2026' y tambien con el mes en letras (30-sep: Andres
    nombra 'AUTO DE 17 SEP 2026 NOMBRE.pdf', 'AUTO 1471 DEL 25 DE JUN 2026.pdf',
    '25 de junio de 2026')."""
    fp = _fecha_partes(fecha)
    if fp is None:
        return None
    d, m, a = fp
    mes = _MESES.get(m)
    letras = rf"|(?<!\d)0?{d}[\s._-]*(?:de[\s._-]*)?{mes}[a-z]*\.?[\s._-]*(?:del?[\s._-]*)?{a}(?!\d)" if mes else ""
    return re.compile(rf"(?<!\d)0?{d}[\s._-]+0?{m}[\s._-]+{a}(?!\d){letras}")


def calza_en_descargas(nombre_archivo: str, tipo: str, numero, fecha: str, titular: str = "") -> bool:
    stem = _norm(Path(nombre_archivo).stem)
    n = _numero(numero)
    re_fecha = _re_fecha(fecha)
    fp = _fecha_partes(fecha)
    if not n and not re_fecha:
        return False
    if tipo == "Resolucion":
        if fp and n and re.search(rf"(?<!\d){fp[2]}[\s_-]+0*{n}(?!\d)", stem):
            return True
        if n and re_fecha and re_fecha.search(stem):
            # 'Resolucion 24208 del 02 09 2026' o '16232 6_05_2025 NOMBRE' (asi nombra Andres)
            if re.search(rf"resolucion\D{{0,6}}0*{n}(?!\d)", stem) or re.match(rf"0*{n}(?!\d)", stem):
                return True
        return False
    if tipo == "Auto":
        if "auto" not in stem or re_fecha is None or not re_fecha.search(stem):
            return False
        if n and re.search(rf"(?<!\d)0*{n}(?!\d)", re_fecha.sub(" ", stem)):
            return True
        palabras = [w for w in _norm(titular).split() if len(w) > 2]
        return bool(palabras) and all(w in stem for w in palabras)
    return False


def _base_copia(p: Path) -> str:
    return re.sub(r"\s*\(\d+\)$", "", _norm(p.stem))


def buscar_en_descargas(carpetas: list, tipo: str, numero, fecha: str, titular: str = "") -> tuple:
    """(ruta | None, nota). Solo mira el primer nivel de cada carpeta."""
    candidatos = []
    for carpeta in carpetas:
        carpeta = Path(carpeta)
        if not carpeta.is_dir():
            continue
        try:
            archivos = [p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
        except OSError:
            continue
        candidatos += [p for p in archivos if calza_en_descargas(p.name, tipo, numero, fecha, titular)]
    if not candidatos:
        return None, ""
    bases = {_base_copia(p) for p in candidatos}
    if len(bases) > 1:
        return None, (f"{tipo} {_numero(numero)}: hay varios PDF distintos que podrían ser en Descargas "
                      f"({', '.join(sorted(p.name for p in candidatos)[:5])}) -- no se elige ninguno")
    elegido = max(candidatos, key=lambda p: p.stat().st_mtime)
    return elegido, f"{tipo} {_numero(numero)}: tomado de Descargas ({elegido.name})"


# Mensajes de 'Adjunto pendiente' -> actos que faltan ("Auto 2128 del 08/09/2026").
_RE_ACTO_EN_MENSAJE = re.compile(r"(Resolucion|Auto)\s+(\d+)\s+del\s+(\d{2}/\d{2}/\d{4})")


def actos_en_mensaje(mensaje: str) -> list:
    vistos = []
    for m in _RE_ACTO_EN_MENSAJE.finditer(mensaje or ""):
        if (mensaje or "")[max(0, m.start() - 20):m.start()].rstrip().endswith("es el acuse de"):
            continue  # "<archivo> es el acuse de Auto 020094 del ..., no de Auto 2115": el ajeno no falta
        t = (m.group(1), m.group(2), m.group(3))
        if t not in vistos:
            vistos.append(t)
    return vistos

"""
Adjuntos armados desde una LISTA DE IDs del portal nuevo de 4-72.

Cuando sirve (Andres, 29-sep):
  - El acuse no aparece en EstadoMensajes ni en Reporte_Envios, pero Andres
    si tiene el ID de mensaje.
  - Andres ya ubico los IDs a mano. Caso 2026-IE-036323 (pruebas de entrega):
    las resoluciones se ubicaron en Cuadro_2026 por el radicado interno y,
    con el correo, Reporte_Envios dio 109 IDs.

Como se usa: Andres deja en dist\\adjuntos_manuales\\<radicado>\\ un .txt con
un ID por linea (o un .xlsx que tenga los IDs en cualquier celda). Insignia
baja cada ID (con cache: un reintento no vuelve a bajar lo ya bajado), agrupa
los acuses por acto (tipo + numero que trae el propio acuse), arma un
expediente por acto y, si es masiva, los comprime en un solo ZIP.
Nunca se adivina: si a un acto de la respuesta no le llega ningun acuse, no
se arma nada y se dice cual falta.
"""
from __future__ import annotations

import asyncio
import re
import zipfile
from pathlib import Path
from typing import Callable

RE_ID_PORTAL_NUEVO = re.compile(r"\b[0-9A-F]{40}\b")


def leer_ids(carpeta: Path) -> tuple:
    """(ids en orden y sin repetir, nombres de los archivos de donde salieron)."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        return [], ""
    ids: list = []
    fuentes: list = []
    for f in sorted(carpeta.iterdir()):
        if not f.is_file() or f.name.startswith("~$"):
            continue
        try:
            if f.suffix.lower() == ".txt":
                textos = [f.read_text(encoding="utf-8", errors="ignore")]
            elif f.suffix.lower() == ".xlsx":
                import openpyxl
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                textos = [str(v) for ws in wb for fila in ws.iter_rows(values_only=True) for v in fila if v]
                wb.close()
            else:
                continue
        except Exception:
            continue
        nuevos = [m.group(0) for t in textos for m in RE_ID_PORTAL_NUEVO.finditer(t.upper())]
        if nuevos:
            fuentes.append(f.name)
            ids.extend(nuevos)
    return list(dict.fromkeys(ids)), ", ".join(fuentes)


def _numero(n) -> str:
    s = str(n or "").strip()
    return str(int(s)) if s.isdigit() else s


async def preparar_desde_ids(
    ids: list,
    fuente: str,
    actos: list,
    carpeta_expedientes: Path,
    descargar: Callable[[str], bytes],
    extraer: Callable[[bytes], object],
    fusionar: Callable[[list], object],
    errores_no_encontrado: tuple,
    errores_otros: tuple,
    avisos: list,
    log: Callable[[str], None] = print,
    pausa_s: float = 0.3,
) -> tuple:
    """Devuelve (rutas_de_expedientes | None, motivo, requiere_manual).
    `descargar(id) -> bytes del ZIP`, `extraer(bytes) -> Acuse`,
    `fusionar([Acuse]) -> Expediente` (con final_filename y pdf_bytes)."""
    carpeta_expedientes = Path(carpeta_expedientes)
    cache = carpeta_expedientes / "acuses_por_id"
    cache.mkdir(parents=True, exist_ok=True)
    log(f"usando {len(ids)} ID(s) de {fuente}.")
    por_acto: dict = {}
    fallos: list = []
    for i, mid in enumerate(ids, start=1):
        archivo = cache / f"{mid}.zip"
        try:
            if archivo.is_file():
                zb = archivo.read_bytes()
            else:
                zb = await asyncio.to_thread(descargar, mid)
                archivo.write_bytes(zb)
                if pausa_s:
                    await asyncio.sleep(pausa_s)
            ac = await asyncio.to_thread(extraer, zb)
        except errores_no_encontrado as exc:
            fallos.append(f"{mid[:10]}…: el portal aún no lo tiene ({exc})")
            continue
        except errores_otros as exc:
            fallos.append(f"{mid[:10]}…: {exc}")
            continue
        por_acto.setdefault((ac.tipo, _numero(ac.numero)), []).append(ac)
        if i % 10 == 0 or i == len(ids):
            log(f"{i}/{len(ids)} acuses listos.")
    if fallos:
        resto = f" (y {len(fallos) - 5} más)" if len(fallos) > 5 else ""
        return None, f"{len(fallos)} ID(s) no se pudieron bajar: " + "; ".join(fallos[:5]) + resto, False

    claves = [(a.tipo_final, _numero(a.numero_final)) for a in actos]
    faltan = [f"{t} {n}" for t, n in claves if (t, n) not in por_acto]
    if faltan:
        return None, (
            f"con los IDs de {fuente} no hay acuse para {len(faltan)} acto(s) de la respuesta: "
            f"{faltan[:10]}{' ...' if len(faltan) > 10 else ''} -- agrega sus IDs y pulsa 'Reintentar automático'"
        ), True
    sobran = [f"{t} {n}" for (t, n) in por_acto if (t, n) not in set(claves)]
    if sobran:
        avisos.append(f"{len(sobran)} ID(s) de {fuente} son de actos que no están en la tabla "
                      f"(no se incluyeron en el ZIP): {sobran[:10]}")
    rutas = []
    vistos = set()
    for clave in claves:
        if clave in vistos:
            continue
        vistos.add(clave)
        exp = await asyncio.to_thread(fusionar, por_acto[clave])
        destino = carpeta_expedientes / exp.final_filename
        destino.write_bytes(exp.pdf_bytes)
        rutas.append(destino)
    return rutas, "", False


def comprimir(rutas: list, destino: Path) -> tuple:
    """ZIP con cada PDF por su nombre (sin repetir). (ruta, n_archivos, megas)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    nombres = set()
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rutas:
            nombre = Path(r).name
            if nombre in nombres:
                continue
            nombres.add(nombre)
            zf.write(r, arcname=nombre)
    return destino, len(nombres), destino.stat().st_size / 1_000_000

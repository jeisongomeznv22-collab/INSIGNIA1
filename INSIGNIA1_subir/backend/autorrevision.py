"""
Revision automatica de errores (pedido de Andres, 29-sep): en cada barrido,
antes de gestionar, Insignia revisa los casos detenidos, reconoce el tipo de
error con lo aprendido hasta ahora y, si la causa ya se resolvio, los vuelve
a poner en la cola SOLO. Lo que necesita una decision de Andres se queda
quieto y se dice que decision falta.

Lo aprendido (cada regla sale de un caso real):
  ADJUNTO   'Adjunto pendiente' / 'no aparece en EstadoMensajes|Reporte_Envios'
            / 'portal ... aún no lo tiene' / IDs que faltan.
            Se reintenta cuando: aparece el PDF (en adjuntos_manuales o en
            Descargas: 2026_24208.pdf, 'Auto 2128 del 08 09 2026.pdf'), aparece
            un ids.txt, llega un reporte de envios mas nuevo que el ultimo
            intento, o ya paso la fecha en que el portal nuevo publica el acuse
            ('aprox. desde el dd/mm/aaaa', ~1 mes de retraso).
  CATEGORIA 'sin plantilla automática': se reintenta si la categoria ya se
            automatizo (2026-IE-036323, pruebas de entrega).
  SGDEA     fallas pasajeras de SGDEA (timeouts, capas que tapan el editor,
            'Ver documentos' que no abre, avisos, revision final): se
            reintenta 4 minutos despues, hasta 5 veces.
  CODIGO    errores que una version nueva de Insignia ya corrige: se
            reintenta una vez cuando cambia la version.
  DECISION  Doctor/Doctora dudoso, otro destinatario ya asignado, acto que no
            se identifica en el Cuadro, categoria desconocida, asunto largo:
            NO se toca; queda 'necesita tu decision'.
Tope: cada caso se reencola solo MAX_REVISIONES veces; despues queda quieto
con la nota de por que.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
from pathlib import Path
from typing import Callable, Optional

MAX_REVISIONES = 6
ESPERA_SGDEA_MIN = 4           # Andres (29-sep): como mucho 4 minutos, no 45
MAX_REINTENTOS_SGDEA = 5
MAX_HISTORIAL = 80

CLASE_DECISION = "decision"
CLASE_ADJUNTO = "adjunto"
CLASE_CATEGORIA = "categoria"
CLASE_SGDEA = "sgdea"
CLASE_DESCONOCIDA = "codigo"

_PATRONES = [
    (CLASE_DECISION, (
        "No se pudo saber si es Doctor o Doctora", "otro destinatario asignado", "Actos que no se pudieron identificar",
        "No se pudo determinar la categoría", "hay que acortarlo", "No se pudo leer quién firma",
        "ninguna calza exacto con la firma", "no tiene ningún acto en el Cuadro", "ninguno de los radicados internos",
        "ya está radicado", "PEDIR A MAGDA", "CONTEO:", "no se toca el memorando", "resoluciones posibles",
        "Carpeta del caso en Descargas", "No se pudo rehacer",
    )),
    (CLASE_ADJUNTO, (
        "Adjunto pendiente", "No se pudo preparar el adjunto", "no aparece en EstadoMensajes",
        "no aparece en Reporte_Envios", "aún no lo tiene", "no hay acuse para", "ID(s) no se pudieron bajar",
        "portal nuevo de 4-72 no está conectado", "portal antiguo de 4-72 no está conectado",
    )),
    (CLASE_CATEGORIA, ("sin plantilla automática",)),
    (CLASE_SGDEA, (
        "Timeout", "TargetClosedError", "no se llego a la vista 'Ver documentos'", "Espere por favor",
        "sweet-overlay", "SGDEA no acepto", "SGDEA mostro un aviso", "Revision final", "capa modal",
        "no aparecio el modal", "no se cerro en", "tapa el documento", "coincidencias para",
        "no mostro a", "no aparecio su tarjeta", "no aparecio la opcion", "supero el tope",
        "no termino de cargar", "No se encontro visible el icono", "Error inesperado",
    )),
]

_RE_DESDE = re.compile(r"aprox\. desde el (\d{2}/\d{2}/\d{4})")


def clasificar(mensaje: str) -> str:
    m = mensaje or ""
    # 1-oct: "Adjunto pendiente: PEDIR A MAGDA ..." espera los PDF (carpeta del caso
    # en Descargas) y se reintenta solo cuando aparecen: es de la clase ADJUNTO.
    if m.lstrip().lower().startswith("adjunto pendiente"):
        return CLASE_ADJUNTO
    for clase, patrones in _PATRONES:
        if any(p.lower() in m.lower() for p in patrones):
            return clase
    return CLASE_DESCONOCIDA


@dataclasses.dataclass
class Decision:
    radicado: str
    clase: str
    accion: str            # "reencolar" | "esperar" | "decision" | "tope"
    nota: str
    fecha: str = ""


@dataclasses.dataclass
class Contexto:
    """Lo que la revision necesita saber del mundo (lo inyecta main.py)."""
    hoy: dt.date
    ahora: dt.datetime
    version_app: str
    adjunto_disponible: Callable[[object], tuple]        # caso -> (bool, nota)
    reportes_actualizados_desde: Callable[[Optional[str]], bool]  # iso ultimo intento -> hay reporte mas nuevo
    categoria_automatizable: Callable[[object], bool]
    cuadro_actualizado_desde: Callable[[Optional[str]], bool] = lambda _iso: False


def _parse_iso(s: Optional[str]) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def revisar_caso(c, ctx: Contexto, max_intentos: int) -> Optional[Decision]:
    """Decision para UN caso detenido, o None si no aplica (esta en curso,
    listo, archivado o fuera de la bandeja)."""
    if getattr(c, "archivado", False) or not getattr(c, "en_sgdea", True):
        return None
    estado = getattr(c, "auto_estado", "")
    agotado = estado == "reintentar" and getattr(c, "auto_intentos", 0) >= max_intentos
    if estado != "requiere_manual" and not agotado:
        return None
    msg = getattr(c, "auto_mensaje", "") or ""
    clase = clasificar(msg)
    rad = c.radicado
    revisiones = getattr(c, "auto_revisiones", 0) or 0

    if clase == CLASE_DECISION:
        # Actos sin identificar: se reintenta solo si hay un Cuadro mas nuevo
        # (actos recientes que el viejo no tenia) o una version nueva de
        # Insignia (29-sep: la lectura de tablas nuevas resolvio 2026-IE-036658).
        if "Actos que no se pudieron identificar" in msg and revisiones < MAX_REVISIONES:
            if ctx.cuadro_actualizado_desde(getattr(c, "auto_ultimo_intento", None)):
                return Decision(rad, clase, "reencolar", "Hay un Cuadro más nuevo que el último intento: se reintenta.")
            if getattr(c, "auto_version", "") != ctx.version_app:
                return Decision(rad, clase, "reencolar",
                                f"Insignia {ctx.version_app} lee mejor las peticiones: se reintenta.")
        return Decision(rad, clase, "decision", "Necesita tu decisión: " + msg[:200])
    if clase == CLASE_ADJUNTO:
        res = ctx.adjunto_disponible(c)
        hay, nota = res[0], res[1]
        nuevo = bool(res[2]) if len(res) > 2 else False
        # 30-sep (2026-IE-036696, masiva de 42 actos): el tope de 6 se agotaba con
        # reintentos que SI avanzaban (cada uno con acuses nuevos que dejo Andres)
        # y el caso quedaba quieto. Un archivo NUEVO siempre reencola: cada archivo
        # dispara una sola vez (despues ya esta en la carpeta del caso y es mas
        # viejo que el intento), asi que no hay bucle.
        if hay and (nuevo or revisiones < MAX_REVISIONES):
            return Decision(rad, clase, "reencolar", nota)
    if revisiones >= MAX_REVISIONES:
        return Decision(rad, clase, "tope", f"Ya se reintentó solo {revisiones} veces; revísalo a mano: {msg[:160]}")

    if clase == CLASE_ADJUNTO:
        if "NO UBICADOS en el Cuadro" in msg and ctx.cuadro_actualizado_desde(getattr(c, "auto_ultimo_intento", None)):
            return Decision(rad, clase, "reencolar", "Hay un Cuadro más nuevo que el último intento: se reintenta.")
        if ctx.reportes_actualizados_desde(getattr(c, "auto_ultimo_intento", None)):
            return Decision(rad, clase, "reencolar", "Hay un reporte de envíos más nuevo que el último intento.")
        fechas = [dt.datetime.strptime(f, "%d/%m/%Y").date() for f in _RE_DESDE.findall(msg)]
        if fechas and max(fechas) <= ctx.hoy:
            return Decision(rad, clase, "reencolar",
                            f"El portal nuevo ya debería tener el acuse (desde el {max(fechas):%d/%m/%Y}).")
        espera = f" (el portal lo publica aprox. desde el {max(fechas):%d/%m/%Y})" if fechas else ""
        return Decision(rad, clase, "esperar", "Esperando el adjunto: PDF en Descargas o en adjuntos_manuales, "
                                               f"ids.txt, o un reporte de envíos nuevo{espera}.")
    if clase == CLASE_CATEGORIA:
        if ctx.categoria_automatizable(c):
            return Decision(rad, clase, "reencolar", "La categoría del caso ya tiene plantilla automática.")
        return Decision(rad, clase, "esperar", "Categoría sin plantilla automática: se responde a mano.")
    if clase == CLASE_SGDEA:
        ultimo = _parse_iso(getattr(c, "auto_ultimo_intento", None))
        if revisiones >= MAX_REINTENTOS_SGDEA:
            return Decision(rad, clase, "tope", f"Falla de SGDEA repetida ({revisiones} reintentos): {msg[:160]}")
        if ultimo is None or ctx.ahora - ultimo >= dt.timedelta(minutes=ESPERA_SGDEA_MIN):
            return Decision(rad, clase, "reencolar", "Falla pasajera de SGDEA: se reintenta.")
        return Decision(rad, clase, "esperar", f"Falla pasajera de SGDEA: se reintenta {ESPERA_SGDEA_MIN} min después del último intento.")
    # CODIGO / desconocida: se reintenta una vez por version nueva de Insignia.
    if getattr(c, "auto_version", "") != ctx.version_app:
        return Decision(rad, clase, "reencolar", f"Insignia {ctx.version_app} trae correcciones nuevas: se reintenta.")
    return Decision(rad, clase, "esperar", "Error no reconocido con esta versión; revísalo a mano: " + msg[:160])


def guardar_historial(decisiones: list, path: Path) -> None:
    """Deja las ultimas decisiones (solo las que cambian algo o las nuevas
    esperas) para el panel 'Revisión automática' del Dashboard."""
    try:
        previas = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        previas = []
    ultimas = {(d["radicado"]): d for d in previas}
    for d in decisiones:
        ultimas[d.radicado] = dataclasses.asdict(d)
    datos = sorted(ultimas.values(), key=lambda d: d.get("fecha", ""), reverse=True)[:MAX_HISTORIAL]
    try:
        path.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def leer_historial(path: Path) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []

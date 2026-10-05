"""
Cruce entre un acto administrativo (Resolucion/Auto, ya identificado via
backend.cuadro_lookup contra el Expediente EE-XXXXXX de una peticion) y el
ID de mensaje del PORTAL ANTIGUO (4-72) que hace falta para bajar su acuse
con backend.legacy_portal_client.LegacyPortalClient.buscar_y_descargar_testigo.

Por que hace falta este modulo (pedido explicito de Andres, sesion
2026-09-24, caso 2026-IE-035458: "cotejando con los cuadros disponibles,
descargas el acuse de 472 antiguo"): Cuadro_2026 (backend/cuadro_lookup.py)
identifica CUAL Resolucion/Auto corresponde a un Expediente, pero no trae
el ID de mensaje del portal antiguo -- ese ID vive en un reporte aparte que
exporta el propio sistema de correo/notificaciones ("EstadoMensajes...csv",
compartido por Andres). Este modulo lee ESE reporte y arma un indice
(tipo, numero, fecha) -> lista de IDs candidatos, para poder ir de "Auto
000123 DE 05 MAY 2026" directamente al ID que hay que buscar en el portal
antiguo, sin que Andres tenga que hacerlo a mano.

Formato observado del CSV (separador ';', UTF-8 con BOM, exportado del
sistema de estado de mensajes): columnas relevantes -- 'Asunto' (trae el
tipo+numero+fecha+nombre, ver _parse_asunto), 'Id' (el identificador que
pide 'Identificador del mensaje' en el portal antiguo), 'Evento' (Lectura
del mensaje / Acuse de recibo / El destinatario abrio la notificacion /
etc -- un mismo acto puede tener VARIAS filas, una por cada evento
registrado, cada una con su propio 'Id' -- ver nota en buscar_id_por_acto
sobre por que esto no es un problema para bajar el acuse).

Dos formas de 'Asunto' observadas:
  - "[1463002] Acta de notificación electrónica JOSE RAMOS GUEVARA ARIAS -
    Resolución 000003 DE 02 ENE 2026"  (notificacion al CIUDADANO -- trae
    el nombre completo del notificado)
  - "[1463166] Constancia de Comunicacion Acto administrativo Resolución
    000094 DE 02 ENE 2026"  (copia/comunicacion INTERNA -- sin nombre)
Se prefieren siempre las filas CON nombre (mas faciles de verificar contra
el 'nombre' que ya trae ActoPorExpediente), y solo se usan las filas sin
nombre como respaldo si no aparece ninguna con nombre para ese
tipo+numero+fecha.

Como con Cuadro_2026, este modulo es completamente opcional (si Andres no
configura una ruta, el resto del programa sigue igual) y NUNCA elige un ID
a ciegas cuando hay ambiguedad real (ej. dos nombres distintos para el
mismo tipo+numero+fecha, algo que no deberia pasar pero se verifica de
todas formas) -- en ese caso devuelve la lista completa de candidatos para
que se revise a mano en vez de adivinar.
"""
from __future__ import annotations

import csv
import dataclasses
import datetime as _dt
import functools
import re
from pathlib import Path
from typing import Optional


class EstadoMensajesError(Exception):
    """No se pudo cargar o leer el reporte de estado de mensajes con la
    estructura esperada."""


@dataclasses.dataclass
class CandidatoMensaje:
    message_id: str
    nombre: str            # "" si la fila era de tipo "Constancia..." (sin nombre)
    evento: str
    fecha_texto: str       # tal como aparece en el Asunto, ej. "02 ENE 2026"
    email: str = ""        # correo del destinatario del envio (en minusculas)
    fecha_envio: Optional[_dt.date] = None  # dia en que salio el correo


@dataclasses.dataclass
class ResultadoBusquedaId:
    encontrado: bool
    message_id: Optional[str] = None
    candidatos: list = dataclasses.field(default_factory=list)  # list[CandidatoMensaje], para revision si hay ambiguedad
    advertencia: Optional[str] = None


@dataclasses.dataclass
class EstadoMensajesIndex:
    # (tipo_norm, numero_key, fecha_key) -> list[CandidatoMensaje]
    por_acto: dict

    def buscar(self, tipo: str, numero, fecha_ddmmyyyy: str, nombre_esperado: str = "",
               correo_esperado: str = "", solo_correo: bool = False) -> ResultadoBusquedaId:
        """`fecha_ddmmyyyy` en formato 'dd/mm/aaaa' (misma convencion que
        ActoPorExpediente.fecha, ver backend/cuadro_lookup.py)."""
        tipo_norm = _norm_tipo(tipo)
        numero_key = _numero_key(numero)
        fecha_key = _fecha_key_desde_ddmmyyyy(fecha_ddmmyyyy)
        if tipo_norm is None or numero_key is None or fecha_key is None:
            return ResultadoBusquedaId(
                encontrado=False,
                advertencia=(
                    f"Datos insuficientes para buscar en el reporte de estado de mensajes "
                    f"(tipo={tipo!r}, numero={numero!r}, fecha={fecha_ddmmyyyy!r})."
                ),
            )
        candidatos = self.por_acto.get((tipo_norm, numero_key, fecha_key), [])
        if not candidatos and tipo_norm == "auto":
            # El Reporte de Envios escribe los Autos SIN numero ("AUTO  DE 02
            # JUL 2026"): se ubican por fecha + CORREO (o nombre) de la persona.
            # Sin coincidencia de correo/nombre NO se elige ninguno.
            sin_numero = self.por_acto.get((tipo_norm, "", fecha_key), [])
            correo = (correo_esperado or "").strip().lower()
            candidatos = [c for c in sin_numero if correo and c.email == correo]
            if not candidatos and nombre_esperado and not solo_correo:
                candidatos = [c for c in sin_numero if _norm_nombre(c.nombre) == _norm_nombre(nombre_esperado)]
        aviso_fecha = None
        if not candidatos and numero_key and (correo_esperado or "").strip():
            # 1-oct (Res. 12041, 2026-IE-036694): el Cuadro dice 04/05/2026 y el
            # envio dice "Resolución 012041 DE 05 MAY 2026". Con el MISMO tipo, el
            # MISMO numero y el MISMO correo del Cuadro se acepta hasta 3 dias de
            # diferencia en la fecha (y se avisa). Sin correo no se acepta nada.
            correo = correo_esperado.strip().lower()
            base = _fecha_de_key(fecha_key)
            cercanos = []
            for (t, n, f), lista in self.por_acto.items():
                if t != tipo_norm or n != numero_key or f == fecha_key:
                    continue
                otra = _fecha_de_key(f)
                if base and otra and abs((otra - base).days) <= 3:
                    cercanos += [c for c in lista if c.email == correo]
            if cercanos:
                candidatos = cercanos
                aviso_fecha = (f"la fecha del envío ({cercanos[0].fecha_texto}) no coincide con la del Cuadro "
                               f"({fecha_ddmmyyyy}); sí coinciden tipo, número y correo -- revisar la fecha en el Cuadro")
        if not candidatos:
            return ResultadoBusquedaId(
                encontrado=False,
                advertencia=(
                    f"No se encontro ninguna fila en el reporte de estado de mensajes para "
                    f"{tipo} {numero} del {fecha_ddmmyyyy}."
                ),
            )

        # Preferir filas CON nombre (notificacion al ciudadano) sobre las
        # de "Constancia..." (sin nombre, copia interna) -- son mas faciles
        # de verificar y son las que de verdad traen el acuse de
        # notificacion al titular.
        con_nombre = [c for c in candidatos if c.nombre]
        universo = con_nombre or candidatos

        # Criterio de Andres (28-sep): ubicar por CORREO ELECTRONICO + numero
        # del acto. El correo sale del Cuadro (columna 'DIRECCIÓN
        # ELECTRÓNICA' de la persona notificada).
        correo = (correo_esperado or "").strip().lower()
        por_correo = [c for c in candidatos if correo and c.email == correo]
        if solo_correo and not por_correo:
            # Varios destinatarios del mismo acto (Andres, 29-sep): cada correo
            # busca SU mensaje; si ese correo no aparece no se toma el de otro.
            return ResultadoBusquedaId(
                encontrado=False,
                advertencia=f"El correo {correo!r} no aparece en el reporte para {tipo} {numero} del {fecha_ddmmyyyy}.",
            )
        if por_correo:
            universo = por_correo
        elif nombre_esperado:
            nombre_norm = _norm_nombre(nombre_esperado)
            coincide_nombre = [c for c in universo if _norm_nombre(c.nombre) == nombre_norm]
            if coincide_nombre:
                universo = coincide_nombre

        ids_unicos = sorted({c.message_id for c in universo})
        if len(ids_unicos) == 1:
            aviso_correo = None
            if correo and not por_correo and universo[0].email and universo[0].email != correo:
                # Visto en 2026-IE-036323: el Cuadro tiene la Res. 22352 con el
                # correo de Anzá y la 22353 con el de Apartadó; el envio real fue
                # al reves. Se usa el unico envio del acto, pero se avisa.
                aviso_correo = (f"el correo del Cuadro ({correo}) no coincide con el del envío "
                                f"({universo[0].email}) -- se usó el único envío de este acto; revisar el Cuadro")
            return ResultadoBusquedaId(encontrado=True, message_id=ids_unicos[0], candidatos=universo,
                                       advertencia="; ".join(x for x in (aviso_correo, aviso_fecha) if x) or None)

        # Mas de un ID distinto, pero TODOS para el mismo nombre (visto en
        # datos reales: un mismo acto puede quedar con 2 IDs de mensaje
        # distintos -- reenvios/eventos duplicados del sistema de correo,
        # no dos personas distintas). Aqui SI se elige uno en vez de
        # bloquear -- de lo contrario casi ningun caso real se resolveria
        # solo -- pero se avisa igual, y se prioriza 'Acuse de recibo'
        # (evento que confirma la entrega) sobre el resto; si no hay
        # ninguno de ese evento, se usa el ultimo por orden de aparicion en
        # el reporte (mas reciente).
        nombres_unicos = {_norm_nombre(c.nombre) for c in universo if c.nombre}
        if len(nombres_unicos) <= 1:
            con_acuse = [c for c in universo if c.evento.strip().lower() == "acuse de recibo"]
            elegido = con_acuse[-1] if con_acuse else universo[-1]
            motivo_nombre = f"mismo nombre ({next(iter(nombres_unicos))})" if nombres_unicos else "ninguna fila trae nombre"
            return ResultadoBusquedaId(
                encontrado=True,
                message_id=elegido.message_id,
                candidatos=universo,
                advertencia=(
                    (f"{aviso_fecha}; " if aviso_fecha else "") +
                    f"Este acto tiene {len(ids_unicos)} IDs de mensaje distintos en el reporte "
                    f"({motivo_nombre}) -- probablemente reenvios/eventos duplicados. Se eligio "
                    f"{elegido.message_id!r}" + (" (evento 'Acuse de recibo')" if con_acuse else " (el mas reciente)")
                    + "; revisar si el acuse descargado no corresponde."
                ),
            )

        # Mas de un ID distinto para el mismo tipo+numero+fecha (nombres
        # distintos, o de verdad ambiguo) -- no se adivina cual usar.
        return ResultadoBusquedaId(
            encontrado=False,
            candidatos=universo,
            advertencia=(
                f"Se encontraron {len(ids_unicos)} IDs distintos en el reporte de estado de "
                f"mensajes para {tipo} {numero} del {fecha_ddmmyyyy}"
                + (f" (se esperaba el nombre '{nombre_esperado}')" if nombre_esperado else "")
                + " -- revisar manualmente cual corresponde antes de descargar un acuse."
            ),
        )


_MES_ABREV = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

# "[1463002] Acta de notificación electrónica JOSE RAMOS GUEVARA ARIAS -
#  Resolución 000003 DE 02 ENE 2026"
_PATRON_ASUNTO_CON_NOMBRE = re.compile(
    r"^\[\d+\]\s*Acta de notificaci[oó]n electr[oó]nica\s+(?:Administrativo\s+)?(?P<nombre>.+?)\s*-\s*"
    r"(?P<tipo>Resoluci[oó]n|Auto)\s+(?:(?P<numero>\d\S*)\s+)?DE\s+(?P<fecha>\d{1,2}\s+[A-ZÑ]{3,4}\s+\d{4})",
    re.IGNORECASE,
)
# "[1463166] Constancia de Comunicacion Acto administrativo Resolución
#  000094 DE 02 ENE 2026"  (sin nombre)
_PATRON_ASUNTO_SIN_NOMBRE = re.compile(
    r"^\[\d+\]\s*Constancia de Comunicaci[oó]n Acto administrativo\s+"
    r"(?P<tipo>Resoluci[oó]n|Auto)\s+(?:(?P<numero>\d\S*)\s+)?DE\s+(?P<fecha>\d{1,2}\s+[A-ZÑ]{3,4}\s+\d{4})",
    re.IGNORECASE,
)


def _norm_tipo(tipo: str) -> Optional[str]:
    t = (tipo or "").strip().lower()
    t = t.replace("ó", "o")
    if t.startswith("resoluc"):
        return "resolucion"
    if t.startswith("auto"):
        return "auto"
    return None


def _numero_key(v) -> Optional[str]:
    """Mismo criterio que cuadro_lookup._numero_key."""
    if v is None or v == "":
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        s = str(v).strip()
        if not s:
            return None
        stripped = s.lstrip("0")
        return stripped or "0"


def _norm_nombre(v: str) -> str:
    return " ".join((v or "").strip().upper().split())


def _fecha_key_desde_ddmmyyyy(fecha: str) -> Optional[str]:
    """'02/01/2026' (dd/mm/aaaa) -> '2-1-2026' (misma clave canonica que
    _fecha_key_desde_texto_csv, para poder comparar)."""
    partes = (fecha or "").split("/")
    if len(partes) != 3:
        return None
    dd, mm, aaaa = partes
    if not (dd.isdigit() and mm.isdigit() and aaaa.isdigit()):
        return None
    return f"{int(dd)}-{int(mm)}-{int(aaaa)}"


def _fecha_de_key(clave: Optional[str]) -> Optional[_dt.date]:
    """'2-1-2026' -> date(2026, 1, 2)."""
    try:
        d, m, a = (int(x) for x in (clave or "").split("-"))
        return _dt.date(a, m, d)
    except (TypeError, ValueError):
        return None


def _fecha_key_desde_texto_csv(fecha_texto: str) -> Optional[str]:
    """'02 ENE 2026' -> '2-1-2026'. None si el mes no se reconoce."""
    partes = fecha_texto.strip().split()
    if len(partes) != 3:
        return None
    dd_s, mes_s, aaaa_s = partes
    mes_num = _MES_ABREV.get(mes_s.strip().upper()[:3])
    if mes_num is None or not (dd_s.isdigit() and aaaa_s.isdigit()):
        return None
    return f"{int(dd_s)}-{mes_num}-{int(aaaa_s)}"


def _parse_asunto(asunto: str) -> Optional[dict]:
    m = _PATRON_ASUNTO_CON_NOMBRE.match(asunto.strip())
    if m:
        return {"nombre": m.group("nombre").strip(), "tipo": m.group("tipo"), "numero": m.group("numero") or "", "fecha_texto": m.group("fecha")}
    m = _PATRON_ASUNTO_SIN_NOMBRE.match(asunto.strip())
    if m:
        return {"nombre": "", "tipo": m.group("tipo"), "numero": m.group("numero") or "", "fecha_texto": m.group("fecha")}
    return None


@functools.lru_cache(maxsize=2)
def _load_cached(path: str, mtime: float) -> EstadoMensajesIndex:
    por_acto: dict = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        # sniff no es confiable aqui (el archivo ya viene con ';' fijo,
        # confirmado contra el reporte real que compartio Andres) -- se usa
        # el delimitador fijo en vez de arriesgar una deteccion erronea.
        reader = csv.DictReader(f, delimiter=";")
        if reader.fieldnames is None or "Asunto" not in reader.fieldnames or "Id" not in reader.fieldnames:
            raise EstadoMensajesError(
                "El archivo no tiene las columnas esperadas (se esperaba, entre otras, "
                "'Asunto' e 'Id'; revisar que sea el reporte 'EstadoMensajes' correcto)."
            )
        for row in reader:
            asunto = (row.get("Asunto") or "").strip()
            message_id = (row.get("Id") or "").strip()
            evento = (row.get("Evento") or "").strip()
            if not asunto or not message_id:
                continue
            parsed = _parse_asunto(asunto)
            if parsed is None:
                continue
            tipo_norm = _norm_tipo(parsed["tipo"])
            numero_key = _numero_key(parsed["numero"]) or ""
            fecha_key = _fecha_key_desde_texto_csv(parsed["fecha_texto"])
            if tipo_norm is None or fecha_key is None:
                continue
            key = (tipo_norm, numero_key, fecha_key)
            candidato = CandidatoMensaje(
                message_id=message_id,
                nombre=parsed["nombre"],
                evento=evento,
                fecha_texto=parsed["fecha_texto"],
                email=_extraer_correo(row.get("Nombres - Email") or ""),
                fecha_envio=_fecha_iso_inicio(row.get("Fecha") or ""),
            )
            por_acto.setdefault(key, []).append(candidato)
    return EstadoMensajesIndex(por_acto=por_acto)


def load_estado_mensajes(path: str | Path) -> EstadoMensajesIndex:
    """Carga (con cache por ruta+fecha de modificacion) el indice de
    tipo+numero+fecha -> IDs del portal antiguo, desde el reporte
    'EstadoMensajes...csv'. Lanza EstadoMensajesError si el archivo no
    existe o no tiene la estructura esperada."""
    p = Path(path)
    if not p.exists():
        raise EstadoMensajesError(f"No se encontro el archivo: {p}")
    mtime = p.stat().st_mtime
    return _load_cached(str(p), mtime)


_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _extraer_correo(texto: str) -> str:
    """'nombreusuario (ciudadano3@example.com)' -> 'ciudadano3@example.com'."""
    m = _RE_CORREO.search(texto or "")
    return m.group(0).lower() if m else ""


def _fecha_iso_inicio(texto: str) -> Optional[_dt.date]:
    """'2026-01-02 13:06:12 / 2026-01-05 19:18:29' -> date(2026, 1, 2)."""
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", texto or "")
    return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _fecha_mdy(v) -> Optional[_dt.date]:
    """Celda 'Fecha Envío (Local)' del Reporte de Envios: '06/17/2026'
    (mes/dia/año) o un datetime."""
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return _dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


@functools.lru_cache(maxsize=2)
def _load_reporte_cached(path: str, mtime: float) -> EstadoMensajesIndex:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        filas = wb.worksheets[0].iter_rows(values_only=True)
        cols: dict = {}
        for fila in filas:
            nombres = [str(c or "").strip().lower() for c in fila]
            if "id mensaje" in nombres and "asunto" in nombres:
                cols = {n: i for i, n in enumerate(nombres)}
                break
        if not cols:
            raise EstadoMensajesError(
                "El archivo no tiene las columnas esperadas ('ID Mensaje', 'Asunto'); revisar que sea el "
                "'Reporte de Envíos' correcto."
            )
        i_id, i_asunto = cols["id mensaje"], cols["asunto"]
        i_dest = cols.get("destinatario")
        i_estado = cols.get("estado entrega")
        i_fecha = next((i for n, i in cols.items() if n.startswith("fecha env")), None)
        por_acto: dict = {}
        for fila in filas:
            if not fila or i_asunto >= len(fila):
                continue
            asunto = str(fila[i_asunto] or "").strip()
            message_id = str(fila[i_id] or "").strip() if i_id < len(fila) else ""
            if not asunto or not message_id:
                continue
            parsed = _parse_asunto(asunto)
            if parsed is None:
                continue
            tipo_norm = _norm_tipo(parsed["tipo"])
            numero_key = _numero_key(parsed["numero"]) or ""
            fecha_key = _fecha_key_desde_texto_csv(parsed["fecha_texto"])
            if tipo_norm is None or fecha_key is None:
                continue
            por_acto.setdefault((tipo_norm, numero_key, fecha_key), []).append(CandidatoMensaje(
                message_id=message_id,
                nombre=parsed["nombre"],
                evento=str(fila[i_estado] or "").strip() if i_estado is not None and i_estado < len(fila) else "",
                fecha_texto=parsed["fecha_texto"],
                email=_extraer_correo(str(fila[i_dest] or "")) if i_dest is not None and i_dest < len(fila) else "",
                fecha_envio=_fecha_mdy(fila[i_fecha]) if i_fecha is not None and i_fecha < len(fila) else None,
            ))
        return EstadoMensajesIndex(por_acto=por_acto)
    finally:
        wb.close()


def load_reporte_envios(path: str | Path) -> EstadoMensajesIndex:
    """Indice tipo+numero+fecha -> IDs del PORTAL NUEVO (columna 'ID
    Mensaje', hexadecimal) desde el 'Reporte_Envios_AAAA-MM-DD.xlsx' --
    fuente de Andres para los actos del 17 de junio de 2026 en adelante."""
    p = Path(path)
    if not p.exists():
        raise EstadoMensajesError(f"No se encontro el archivo: {p}")
    return _load_reporte_cached(str(p), p.stat().st_mtime)

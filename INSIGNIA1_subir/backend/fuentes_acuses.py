"""
De donde sale el acuse 4-72 de cada acto, segun su FECHA.

Reglas de Andres (sesion 2026-09-28), textuales:
  - Actos hasta el 31 de mayo de 2026: el ID se consulta en el Excel
    "EstadoMensajes" (filtrando por correo electronico y numero de acto) y
    el acuse se baja del PORTAL ANTIGUO.
  - Actos del 17 de junio de 2026 en adelante: el ID sale del
    "Reporte_Envios" (se notificaron por ese aplicativo) y el acuse se baja
    del PORTAL NUEVO.
  - Franja intermedia, 1 al 16 de junio de 2026: descarga MANUAL.
  - El portal nuevo publica los acuses con ~1 mes de retraso (el 28-sep se
    encuentran los del 27-ago, los del 29-ago probablemente no): lo enviado
    hace menos de un mes tambien es MANUAL, por ahora.

"Manual" no bloquea para siempre: Andres descarga el acuse y lo deja en
adjuntos_manuales\\<radicado>\\ (ver main.py); el siguiente intento lo toma.
Este modulo no descarga nada: solo decide la fuente y ubica el ID.
"""
from __future__ import annotations

import calendar
import dataclasses
import datetime as dt
from typing import Optional

FIN_ESTADO_MENSAJES = dt.date(2026, 5, 31)
INICIO_REPORTE_ENVIOS = dt.date(2026, 6, 17)

FUENTE_ESTADO_MENSAJES = "estado_mensajes"   # portal antiguo
FUENTE_REPORTE_ENVIOS = "reporte_envios"     # portal nuevo
FUENTE_MANUAL = "manual"


@dataclasses.dataclass
class UbicacionAcuse:
    fuente: str
    message_id: Optional[str] = None
    motivo: str = ""                  # por que es manual / que no se encontro
    advertencia: Optional[str] = None


def _parse_ddmmyyyy(fecha: str) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime((fecha or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def mas_un_mes(d: dt.date) -> dt.date:
    """Mismo dia del mes siguiente (o el ultimo dia si no existe)."""
    anio, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return dt.date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def disponible_en_portal_nuevo(fecha_envio: dt.date, hoy: dt.date) -> bool:
    """Con ~1 mes de retraso: el 28-sep SI esta lo del 27-ago (27-sep < 28-sep)
    y NO lo del 28 o 29-ago."""
    return mas_un_mes(fecha_envio) < hoy


def fuente_por_fecha(fecha_acto: dt.date) -> str:
    if fecha_acto <= FIN_ESTADO_MENSAJES:
        return FUENTE_ESTADO_MENSAJES
    if fecha_acto < INICIO_REPORTE_ENVIOS:
        return FUENTE_MANUAL
    return FUENTE_REPORTE_ENVIOS


def ubicar_acuse(tipo: str, numero: str, fecha_ddmmyyyy: str, nombre: str, correo: str,
                 estado_idx, reporte_idx, hoy: Optional[dt.date] = None,
                 solo_correo: bool = False) -> UbicacionAcuse:
    hoy = hoy or dt.date.today()
    etiqueta = f"{tipo} {numero} del {fecha_ddmmyyyy}"
    fecha = _parse_ddmmyyyy(fecha_ddmmyyyy)
    if fecha is None:
        return UbicacionAcuse(FUENTE_MANUAL, motivo=f"{etiqueta}: el Cuadro no trae una fecha legible")

    fuente = fuente_por_fecha(fecha)
    if fuente == FUENTE_MANUAL:
        return UbicacionAcuse(FUENTE_MANUAL, motivo=f"{etiqueta}: está en la franja del 1 al 16 de junio (descarga manual)")

    idx = estado_idx if fuente == FUENTE_ESTADO_MENSAJES else reporte_idx
    nombre_archivo = "EstadoMensajes" if fuente == FUENTE_ESTADO_MENSAJES else "Reporte_Envios"
    if idx is None:
        return UbicacionAcuse(FUENTE_MANUAL, motivo=f"{etiqueta}: falta cargar el archivo {nombre_archivo} en Configuración")

    r = idx.buscar(tipo, numero, fecha_ddmmyyyy, nombre, correo_esperado=correo, solo_correo=solo_correo)
    if not r.encontrado:
        return UbicacionAcuse(
            FUENTE_MANUAL,
            motivo=f"{etiqueta}: no aparece en {nombre_archivo} ({r.advertencia or 'sin coincidencias'}) -- "
                   "actualiza el archivo o descárgalo a mano",
        )

    if fuente == FUENTE_REPORTE_ENVIOS:
        elegido = next((c for c in r.candidatos if c.message_id == r.message_id), None)
        fecha_envio = (elegido.fecha_envio if elegido and elegido.fecha_envio else fecha)
        if not disponible_en_portal_nuevo(fecha_envio, hoy):
            desde = mas_un_mes(fecha_envio) + dt.timedelta(days=1)
            return UbicacionAcuse(
                FUENTE_MANUAL,
                motivo=(f"{etiqueta}: enviado el {fecha_envio:%d/%m/%Y}; el portal nuevo lo publica con ~1 mes de "
                        f"retraso (aprox. desde el {desde:%d/%m/%Y}) -- descarga manual por ahora"),
            )
    return UbicacionAcuse(fuente, message_id=r.message_id, advertencia=r.advertencia)


def partir_correos(texto: str) -> list:
    """Una celda de 'DIRECCIÓN ELECTRÓNICA' puede traer varios correos."""
    import re
    return [c.lower() for c in re.split(r"[;,\s/]+", texto or "") if "@" in c]


def ubicar_acuses_de_acto(tipo: str, numero: str, fecha_ddmmyyyy: str, nombre: str, correos: list,
                          estado_idx, reporte_idx, hoy: Optional[dt.date] = None) -> tuple:
    """Regla de Andres (29-sep): un acto con VARIOS destinatarios (p.ej.
    municipios de Recaudo: alcaldia, hacienda, personeria, concejo) se arma
    con el acuse de CADA correo que traiga el Cuadro, en orden cronologico.
    Cada correo busca su propio mensaje (solo_correo=True).
    Devuelve (ubicaciones_encontradas, correos_sin_mensaje, motivo_manual):
      - si ningun correo se encuentra: ([], [...], motivo) -> manual
      - si alguno se encuentra: ([UbicacionAcuse...], [correos no hallados], '')."""
    correos = list(dict.fromkeys(c for c in correos if c))
    encontradas: list = []
    sin_mensaje: list = []
    primer_motivo = ""
    for correo in correos:
        ub = ubicar_acuse(tipo, numero, fecha_ddmmyyyy, nombre, correo, estado_idx, reporte_idx, hoy,
                          solo_correo=True)
        if ub.fuente == FUENTE_MANUAL:
            sin_mensaje.append(correo)
            primer_motivo = primer_motivo or ub.motivo
            # franja manual / portal con retraso / falta el archivo: aplica a TODO el acto
            if "no aparece en" not in ub.motivo:
                return [], correos, ub.motivo
            continue
        if all(u.message_id != ub.message_id for u in encontradas):
            encontradas.append(ub)
    if not encontradas:
        return [], sin_mensaje, primer_motivo
    return encontradas, sin_mensaje, ""

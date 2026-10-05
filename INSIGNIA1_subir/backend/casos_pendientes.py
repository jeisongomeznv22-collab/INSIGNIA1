"""
Cola local de "casos pendientes de revision": memorandos respuesta que ya
se dejaron listos en SGDEA (carta pegada, adjunto cargado, Ema seleccionada
como revisora -- ver backend/sgdea_automation.py) pero a los que TODAVIA
les falta el paso final, manual y deliberado, de que Andres los revise y
decida enviarlos a aprobacion.

Este modulo NO toca el navegador ni SGDEA -- es solo el almacenamiento
local (un JSON junto a config_472.json) de lo que ya se genero para cada
caso, para poder listarlo/revisarlo en el aplicativo sin tener que volver
a abrir el navegador. La verificacion "en vivo" (reabrir el caso en SGDEA
para confirmar que el adjunto sigue ahi, etc.) se descarto a proposito --
Andres pidio que el panel de revision muestre el resumen ya guardado, no
que dispare una verificacion en vivo cada vez.

Ciclo de vida de un CasoPendiente.estado:
  "pendiente" -- se genero la carta y se dejo lista en SGDEA; esperando
                 que Andres la revise en el aplicativo y decida aprobarla.
  "enviado"   -- Andres le dio "Aprobar y enviar" en el aplicativo y la
                 automatizacion confirmo que el ciclo de aprobacion quedo
                 iniciado en SGDEA (ver ejecutar_flujo_aprobacion en
                 sgdea_automation.py).
  "error"     -- se intento enviar pero la automatizacion no pudo
                 completar el flujo (ver notas_error); Andres puede
                 reintentar o terminarlo el mismo directamente en SGDEA.

IMPORTANTE: "enviado" lo pone UNICAMENTE la automatizacion, despues de
confirmar el envio -- nunca se marca un caso como enviado solo porque se
agrego a la cola.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


def _base_dir() -> Path:
    """Misma convencion que main.py: junto al .exe si esta empaquetado, o
    junto a este archivo (backend/..) en desarrollo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


CASOS_PATH = _base_dir() / "casos_pendientes.json"

MENSAJE_APROBACION_DEFAULT = (
    "Buen día Doctora, Envío respuesta a memorando interno, para su "
    "aprobación y posterior envío a firma. muchas gracias"
)
# ^ Texto exacto dictado por Andres (sesion 2026-09-24) para el recuadro
# de "Inicio ciclo de aprobación" en SGDEA -- NO cambiar la puntuacion
# sin que el lo pida de nuevo (incluye el punto antes de "muchas" y la
# falta de punto final, tal como lo escribio).

ESTADOS_VALIDOS = {"pendiente", "enviado", "error"}


@dataclasses.dataclass
class CasoPendiente:
    """Un memorando respuesta ya dejado listo en SGDEA (carta + adjunto +
    revisor Ema), esperando la revision/aprobacion final de Andres desde
    el aplicativo. Los campos de la carta espejan 1 a 1 a
    backend.sgdea_carta.Carta -- pensado para poder construirse
    directamente desde un Carta ya generado (ver desde_carta())."""

    radicado: str
    tratamiento: str
    destinatario_nombre: str
    destinatario_cargo: str
    destinatario_subdireccion: str
    asunto: str
    saludo: str
    cuerpo_parrafo: str
    adjunto_nombre: str
    adjunto_path: str = ""
    tabla: Optional[list] = None
    es_masiva: bool = False
    estado: str = "pendiente"
    mensaje_aprobacion: str = MENSAJE_APROBACION_DEFAULT
    fecha_generado: str = dataclasses.field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    fecha_enviado: Optional[str] = None
    notas_error: Optional[str] = None
    warnings: list = dataclasses.field(default_factory=list)

    @staticmethod
    def desde_carta(radicado: str, carta, adjunto_path: str = "") -> "CasoPendiente":
        """Arma un CasoPendiente directamente desde un backend.sgdea_carta.Carta
        ya generado (y ya pegado/confirmado en SGDEA)."""
        return CasoPendiente(
            radicado=radicado,
            tratamiento=carta.tratamiento,
            destinatario_nombre=carta.destinatario_nombre,
            destinatario_cargo=carta.destinatario_cargo,
            destinatario_subdireccion=carta.destinatario_subdireccion,
            asunto=carta.asunto,
            saludo=carta.saludo,
            cuerpo_parrafo=carta.cuerpo_parrafo,
            # El nombre REAL del archivo subido (el de la carta puede venir vacio
            # -- 'Adjunto:' salia en blanco en la revision de 2026-IE-036295).
            adjunto_nombre=(adjunto_path.replace("\\", "/").rsplit("/", 1)[-1] if adjunto_path else carta.adjunto_nombre),
            adjunto_path=adjunto_path,
            tabla=carta.tabla,
            es_masiva=carta.es_masiva,
            warnings=list(carta.warnings),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CasoPendiente":
        campos_validos = {f.name for f in dataclasses.fields(CasoPendiente)}
        limpio = {k: v for k, v in d.items() if k in campos_validos}
        return CasoPendiente(**limpio)


class CasosPendientesError(Exception):
    pass


def cargar_casos(path: Path = CASOS_PATH) -> list[CasoPendiente]:
    """Lee la cola completa del disco. Si el archivo no existe todavia,
    devuelve una lista vacia (no es un error: es el estado inicial)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CasosPendientesError(f"No se pudo leer {path.name}: {exc}") from exc
    return [CasoPendiente.from_dict(d) for d in data]


def guardar_casos(casos: list[CasoPendiente], path: Path = CASOS_PATH) -> None:
    data = [c.to_dict() for c in casos]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def agregar_caso(caso: CasoPendiente, path: Path = CASOS_PATH) -> list[CasoPendiente]:
    """Agrega (o reemplaza, si el radicado ya estaba) un caso a la cola y
    guarda. Devuelve la cola completa ya actualizada."""
    casos = cargar_casos(path)
    casos = [c for c in casos if c.radicado != caso.radicado]
    casos.append(caso)
    guardar_casos(casos, path)
    return casos


def obtener_caso(radicado: str, path: Path = CASOS_PATH) -> Optional[CasoPendiente]:
    for c in cargar_casos(path):
        if c.radicado == radicado:
            return c
    return None


def _actualizar_estado(radicado: str, estado: str, path: Path = CASOS_PATH, **campos) -> CasoPendiente:
    if estado not in ESTADOS_VALIDOS:
        raise CasosPendientesError(f"Estado invalido: {estado!r}")
    casos = cargar_casos(path)
    actualizado = None
    for c in casos:
        if c.radicado == radicado:
            c.estado = estado
            for k, v in campos.items():
                setattr(c, k, v)
            actualizado = c
            break
    if actualizado is None:
        raise CasosPendientesError(f"No hay ningun caso pendiente con radicado {radicado!r}")
    guardar_casos(casos, path)
    return actualizado


def marcar_enviado(radicado: str, path: Path = CASOS_PATH) -> CasoPendiente:
    return _actualizar_estado(
        radicado, "enviado", path,
        fecha_enviado=datetime.now().isoformat(timespec="seconds"),
        notas_error=None,
    )


def marcar_error(radicado: str, mensaje: str, path: Path = CASOS_PATH) -> CasoPendiente:
    return _actualizar_estado(radicado, "error", path, notas_error=mensaje)


def marcar_pendiente(radicado: str, path: Path = CASOS_PATH) -> CasoPendiente:
    """Para reintentar: vuelve un caso en 'error' a 'pendiente'."""
    return _actualizar_estado(radicado, "pendiente", path, notas_error=None)


def eliminar_caso(radicado: str, path: Path = CASOS_PATH) -> list[CasoPendiente]:
    casos = cargar_casos(path)
    restantes = [c for c in casos if c.radicado != radicado]
    if len(restantes) == len(casos):
        raise CasosPendientesError(f"No hay ningun caso pendiente con radicado {radicado!r}")
    guardar_casos(restantes, path)
    return restantes

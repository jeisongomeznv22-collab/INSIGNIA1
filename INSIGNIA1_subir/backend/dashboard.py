"""
Registro local del "Dashboard" (Insignia): casos que backend.sgdea_automation
.detectar_casos_nuevos() encontro en la lista 'Gestionar' de SGDEA y que
todavia no se conocian localmente. Este modulo NO toca el navegador -- es
solo el almacenamiento (un JSON junto a config_472.json, mismo patron que
casos_pendientes.py) y la clasificacion manual que Andres le da a cada uno
desde el aplicativo:

  - prioridad: "normal" | "urgente" -- la pone Andres a mano en el panel;
    nunca se infiere sola de las columnas crudas de SGDEA (esas columnas
    todavia no estan confirmadas en vivo, ver advertencia en
    sgdea_automation.listar_casos_gestionar).
  - estado_gestion: "en_gestion" | "espera_tercero" | "gestionado" -- idem,
    lo marca Andres cuando un caso queda esperando una gestion de un
    tercero, o lo pone la automatizacion misma ("gestionado") cuando
    "Gestionar caso completo (automático)" termina en exito (ver
    _gestionar_caso_completo en main.py) -- para distinguir a simple
    vista, en el Dashboard, los casos que ya quedaron diligenciados en
    SGDEA y en la cola de Memorandos esperando aprobacion.
  - termino_fecha_limite: fecha limite opcional (YYYY-MM-DD) que Andres
    puede fijar a mano para que el caso aparezca en "Terminos por vencer"
    -- no se calcula sola porque todavia no hay una columna de SGDEA
    confirmada de donde sacarla en automatico.

Ciclo de vida: un caso se auto-registra (estado_gestion="en_gestion",
prioridad="normal") la primera vez que aparece en
detectar_casos_nuevos(); despues Andres lo reclasifica desde el
Dashboard. `archivado=True` lo saca de los conteos/listas activas sin
borrar el historial.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, date


def _base_dir() -> Path:
    """Misma convencion que casos_pendientes.py / main.py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


DASHBOARD_PATH = _base_dir() / "dashboard_casos.json"

PRIORIDADES_VALIDAS = {"normal", "urgente"}
ESTADOS_GESTION_VALIDOS = {"en_gestion", "espera_tercero", "gestionado"}


@dataclasses.dataclass
class CasoDashboard:
    radicado: str
    columnas_crudas: list = dataclasses.field(default_factory=list)
    prioridad: str = "normal"
    estado_gestion: str = "en_gestion"
    termino_fecha_limite: Optional[str] = None  # "YYYY-MM-DD", puesto a mano por Andres
    notas: str = ""
    archivado: bool = False
    fecha_detectado: str = dataclasses.field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    fecha_actualizado: str = dataclasses.field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    # --- Gestion automatica (barrido en segundo plano, sesion 2026-09-27) ---
    # auto_estado: "" (sin intentar) | "reintentar" | "listo_revision"
    #              | "requiere_manual"
    auto_estado: str = ""
    auto_intentos: int = 0
    auto_pasos: list = dataclasses.field(default_factory=list)   # pasos ya hechos (se omiten al reintentar)
    auto_mensaje: str = ""
    auto_ultimo_intento: Optional[str] = None
    tratamiento_manual: Optional[str] = None  # "Doctor"/"Doctora" elegido por Andres en el dialogo del caso
    en_sgdea: bool = True  # False si el caso ya no aparece en la lista 'Gestionar' de SGDEA
    # --- Revision automatica de errores (v1.5.6, ver backend/autorrevision.py) ---
    auto_version: str = ""          # version de Insignia que hizo el ultimo intento
    auto_revisiones: int = 0        # veces que la revision automatica lo volvio a la cola
    auto_revision_nota: str = ""    # que vio/decidio la revision automatica

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CasoDashboard":
        campos_validos = {f.name for f in dataclasses.fields(CasoDashboard)}
        limpio = {k: v for k, v in d.items() if k in campos_validos}
        return CasoDashboard(**limpio)


class DashboardError(Exception):
    pass


def cargar_casos(path: Path = DASHBOARD_PATH) -> list[CasoDashboard]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DashboardError(f"No se pudo leer {path.name}: {exc}") from exc
    return [CasoDashboard.from_dict(d) for d in data]


def guardar_casos(casos: list[CasoDashboard], path: Path = DASHBOARD_PATH) -> None:
    data = [c.to_dict() for c in casos]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def radicados_conocidos(path: Path = DASHBOARD_PATH) -> set[str]:
    """Para pasarle a sgdea_automation.detectar_casos_nuevos() -- el
    conjunto de radicados que el Dashboard ya tiene registrados (en
    cualquier estado, incluidos los archivados: un caso archivado no debe
    volver a aparecer como 'nuevo')."""
    return {c.radicado for c in cargar_casos(path)}


def registrar_casos_nuevos(casos_detectados: list[dict], path: Path = DASHBOARD_PATH) -> list[CasoDashboard]:
    """Recibe la salida de sgdea_automation.detectar_casos_nuevos()
    (lista de dicts {"radicado", "columnas"}) y agrega al registro local
    solo los que todavia no existian -- con prioridad/estado por
    defecto, listos para que Andres los reclasifique desde el Dashboard.
    Devuelve SOLO los que efectivamente se agregaron en esta llamada
    (para poder, por ejemplo, mostrarle a Andres "3 casos nuevos
    detectados")."""
    casos = cargar_casos(path)
    ya_conocidos = {c.radicado for c in casos}
    agregados: list[CasoDashboard] = []
    for det in casos_detectados:
        radicado = det.get("radicado")
        if not radicado or radicado in ya_conocidos:
            continue
        nuevo = CasoDashboard(radicado=radicado, columnas_crudas=det.get("columnas", []))
        casos.append(nuevo)
        agregados.append(nuevo)
        ya_conocidos.add(radicado)
    if agregados:
        guardar_casos(casos, path)
    return agregados


def _actualizar(radicado: str, path: Path = DASHBOARD_PATH, **campos) -> CasoDashboard:
    casos = cargar_casos(path)
    actualizado = None
    for c in casos:
        if c.radicado == radicado:
            for k, v in campos.items():
                setattr(c, k, v)
            c.fecha_actualizado = datetime.now().isoformat(timespec="seconds")
            actualizado = c
            break
    if actualizado is None:
        raise DashboardError(f"No hay ningun caso en el Dashboard con radicado {radicado!r}")
    guardar_casos(casos, path)
    return actualizado


# ------------------------------------------------------------------
# Barrido automatico de TODOS los casos (sesion 2026-09-27, pedido de
# Andres: "que haga un barrido de TODOS LOS CASOS ... y los adelante hasta
# el punto donde queden para revision por mi"). Funciones puras sobre el
# registro local -- el navegador lo maneja main.py/sgdea_automation.py.
# ------------------------------------------------------------------

MAX_INTENTOS_AUTO = 3
VERSION_APP = ""  # la fija main.py al arrancar
ESTADOS_AUTO_FINALES = {"listo_revision", "requiere_manual"}


def sincronizar_lista(casos_detectados: list[dict], path: Path = DASHBOARD_PATH) -> tuple[list[CasoDashboard], set[str]]:
    """Recibe TODA la lista 'Gestionar' leida de SGDEA. Agrega los casos
    nuevos, refresca las columnas crudas de los ya conocidos y marca
    en_sgdea=False los que ya no aparecen (p.ej. ya enviados). Devuelve
    (nuevos, radicados_activos_en_sgdea)."""
    casos = cargar_casos(path)
    por_radicado = {c.radicado: c for c in casos}
    activos: set[str] = set()
    nuevos: list[CasoDashboard] = []
    for det in casos_detectados:
        radicado = det.get("radicado")
        if not radicado:
            continue
        activos.add(radicado)
        c = por_radicado.get(radicado)
        if c is None:
            c = CasoDashboard(radicado=radicado, columnas_crudas=det.get("columnas", []))
            casos.append(c)
            por_radicado[radicado] = c
            nuevos.append(c)
        else:
            if det.get("columnas"):
                c.columnas_crudas = det["columnas"]
            c.en_sgdea = True
    for c in casos:
        if c.radicado not in activos:
            c.en_sgdea = False
    guardar_casos(casos, path)
    return nuevos, activos


def debe_procesarse(c: CasoDashboard, activos: set[str], max_intentos: int = MAX_INTENTOS_AUTO) -> tuple[bool, str]:
    """Decide si el barrido debe intentar este caso. Devuelve (si/no, motivo)."""
    if c.radicado not in activos:
        return False, "ya no esta en la lista 'Gestionar' de SGDEA"
    if c.archivado:
        return False, "archivado"
    if c.estado_gestion != "en_gestion":
        return False, f"estado '{c.estado_gestion}'"
    if c.auto_estado in ESTADOS_AUTO_FINALES:
        return False, f"automatico: {c.auto_estado}"
    if c.auto_intentos >= max_intentos:
        return False, f"{c.auto_intentos} intentos agotados"
    return True, "pendiente"


def casos_para_barrido(activos: set[str], path: Path = DASHBOARD_PATH, max_intentos: int = MAX_INTENTOS_AUTO) -> list[CasoDashboard]:
    """Casos a intentar en este barrido: urgentes primero, luego por
    antiguedad de deteccion (los mas viejos primero -- vencen antes)."""
    candidatos = [c for c in cargar_casos(path) if debe_procesarse(c, activos, max_intentos)[0]]
    return sorted(candidatos, key=lambda c: (c.prioridad != "urgente", c.fecha_detectado))


def registrar_intento_auto(
    radicado: str, ok: bool, mensaje: str, pasos: list, requiere_manual: bool = False,
    path: Path = DASHBOARD_PATH, max_intentos: int = MAX_INTENTOS_AUTO,
) -> CasoDashboard:
    casos = cargar_casos(path)
    for c in casos:
        if c.radicado == radicado:
            c.auto_intentos += 1
            c.auto_ultimo_intento = datetime.now().isoformat(timespec="seconds")
            c.auto_mensaje = mensaje
            c.auto_version = VERSION_APP
            # los pasos se acumulan: lo que ya se hizo no se repite. Un paso con
            # '-' delante es uno que el documento NO muestra (verificado): se
            # olvida para rehacerlo.
            quitar = {p[1:] for p in (pasos or []) if p.startswith("-")}
            agregar = {p for p in (pasos or []) if not p.startswith("-")}
            c.auto_pasos = sorted((set(c.auto_pasos) - quitar) | agregar)
            if ok:
                c.auto_estado = "listo_revision"
                c.estado_gestion = "gestionado"
            elif requiere_manual or c.auto_intentos >= max_intentos:
                c.auto_estado = "requiere_manual"
            else:
                c.auto_estado = "reintentar"
            c.fecha_actualizado = c.auto_ultimo_intento
            guardar_casos(casos, path)
            return c
    raise DashboardError(f"No hay ningun caso en el Dashboard con radicado {radicado!r}")


def reiniciar_auto(radicado: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    """Vuelve a poner el caso en la cola del barrido (p.ej. despues de que
    Andres corrigio a mano lo que lo detenia)."""
    return _actualizar(radicado, path, auto_estado="", auto_intentos=0, auto_mensaje="")


def reiniciar_por_mensaje(fragmentos: tuple, path: Path = DASHBOARD_PATH) -> list:
    """Devuelve a la cola los casos cuyo ultimo intento automatico fallo por
    un error que ya se corrigio en el codigo (se reconocen por su mensaje).
    Devuelve los radicados reiniciados."""
    reiniciados = []
    for c in cargar_casos(path):
        if c.auto_estado in ("requiere_manual", "reintentar") and any(f in (c.auto_mensaje or "") for f in fragmentos):
            reiniciar_auto(c.radicado, path)
            reiniciados.append(c.radicado)
    return reiniciados


def set_tratamiento_manual(radicado: str, tratamiento: Optional[str], path: Path = DASHBOARD_PATH) -> CasoDashboard:
    if tratamiento not in (None, "Doctor", "Doctora"):
        raise DashboardError(f"Tratamiento invalido: {tratamiento!r}")
    return _actualizar(radicado, path, tratamiento_manual=tratamiento)


def set_prioridad(radicado: str, prioridad: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    if prioridad not in PRIORIDADES_VALIDAS:
        raise DashboardError(f"Prioridad invalida: {prioridad!r} (validas: {PRIORIDADES_VALIDAS})")
    return _actualizar(radicado, path, prioridad=prioridad)


def set_estado_gestion(radicado: str, estado_gestion: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    if estado_gestion not in ESTADOS_GESTION_VALIDOS:
        raise DashboardError(f"Estado de gestion invalido: {estado_gestion!r} (validos: {ESTADOS_GESTION_VALIDOS})")
    return _actualizar(radicado, path, estado_gestion=estado_gestion)


def set_termino(radicado: str, fecha_limite: Optional[str], path: Path = DASHBOARD_PATH) -> CasoDashboard:
    """`fecha_limite` en formato 'YYYY-MM-DD', o None para quitarlo."""
    if fecha_limite:
        try:
            date.fromisoformat(fecha_limite)
        except ValueError as exc:
            raise DashboardError(f"Fecha invalida (se espera YYYY-MM-DD): {fecha_limite!r}") from exc
    return _actualizar(radicado, path, termino_fecha_limite=fecha_limite)


def set_notas(radicado: str, notas: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    return _actualizar(radicado, path, notas=notas)


def archivar(radicado: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    return _actualizar(radicado, path, archivado=True)


def desarchivar(radicado: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    return _actualizar(radicado, path, archivado=False)


# ------------------------------------------------------------------
# Vistas/metricas para la pestaña Dashboard -- todas de solo lectura
# sobre lo ya guardado localmente, nunca disparan una consulta a SGDEA.
# ------------------------------------------------------------------

def _activos(casos: list[CasoDashboard]) -> list[CasoDashboard]:
    return [c for c in casos if not c.archivado]


def casos_urgentes(path: Path = DASHBOARD_PATH) -> list[CasoDashboard]:
    return [c for c in _activos(cargar_casos(path)) if c.prioridad == "urgente"]


def casos_en_espera_tercero(path: Path = DASHBOARD_PATH) -> list[CasoDashboard]:
    return [c for c in _activos(cargar_casos(path)) if c.estado_gestion == "espera_tercero"]


def casos_terminos_por_vencer(dias: int = 5, path: Path = DASHBOARD_PATH) -> list[CasoDashboard]:
    """Casos activos con `termino_fecha_limite` puesto y vencido o dentro
    de los proximos `dias` dias (incluye los ya vencidos -- esos son los
    mas urgentes de mostrar, no se ocultan)."""
    hoy = date.today()
    resultado = []
    for c in _activos(cargar_casos(path)):
        if not c.termino_fecha_limite:
            continue
        try:
            limite = date.fromisoformat(c.termino_fecha_limite)
        except ValueError:
            continue
        if (limite - hoy).days <= dias:
            resultado.append(c)
    resultado.sort(key=lambda c: c.termino_fecha_limite)
    return resultado


def metricas(path: Path = DASHBOARD_PATH) -> dict:
    """Los 3 numeros que van en las tarjetas del Dashboard."""
    casos = cargar_casos(path)
    return {
        "terminos_por_vencer": len(casos_terminos_por_vencer(path=path)),
        "casos_urgentes": len([c for c in _activos(casos) if c.prioridad == "urgente"]),
        "en_espera_tercero": len([c for c in _activos(casos) if c.estado_gestion == "espera_tercero"]),
        "total_activos": len(_activos(casos)),
    }


def aplicar_revision(radicado: str, accion: str, nota: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    """'reencolar': vuelve a la cola (conserva los pasos ya hechos) y suma una
    revision; cualquier otra accion solo deja la nota visible en el caso."""
    casos = cargar_casos(path)
    for c in casos:
        if c.radicado == radicado:
            c.auto_revision_nota = nota
            if accion == "reencolar":
                c.auto_estado = ""
                c.auto_intentos = 0
                c.auto_revisiones = (c.auto_revisiones or 0) + 1
            c.fecha_actualizado = datetime.now().isoformat(timespec="seconds")
            guardar_casos(casos, path)
            return c
    raise DashboardError(f"No hay ningun caso en el Dashboard con radicado {radicado!r}")


def reabrir_para_rehacer(radicado: str, nota: str, marca: str, path: Path = DASHBOARD_PATH) -> CasoDashboard:
    """1-oct (2026-IE-036987): un caso que ya quedo en revision vuelve a la cola
    del barrido para rehacer el cuadro y el adjunto de su memorando (la marca va
    en los pasos; el barrido la quita al terminar)."""
    casos = cargar_casos(path)
    for c in casos:
        if c.radicado == radicado:
            c.auto_estado = ""
            c.auto_intentos = 0
            c.estado_gestion = "en_gestion"
            c.auto_revision_nota = nota
            c.auto_revisiones = (c.auto_revisiones or 0) + 1
            c.auto_pasos = sorted(set(c.auto_pasos) | {marca})
            c.fecha_actualizado = datetime.now().isoformat(timespec="seconds")
            guardar_casos(casos, path)
            return c
    raise DashboardError(f"No hay ningun caso en el Dashboard con radicado {radicado!r}")

"""
Barrido automatico de TODOS los casos de la bandeja 'Gestionar' de SGDEA
(sesion 2026-09-27, pedido de Andres: "que haga un barrido de TODOS LOS
CASOS ... y los adelante hasta el punto donde queden para revision por mi").

Este modulo tiene SOLO la logica del barrido (que casos, en que orden, con
que candado, como se registra cada intento). No abre navegadores ni toca la
interfaz: todo eso se le inyecta desde main.py. Asi se puede probar solo,
con funciones falsas, sin SGDEA.

Reglas (las decisiones de "que caso toca" viven en backend/dashboard.py):
  - Una vuelta = leer TODA la bandeja -> registrar nuevos -> intentar cada
    caso pendiente, urgentes primero y luego los mas antiguos.
  - El candado de SGDEA se toma POR CASO: entre caso y caso los botones
    manuales de Insignia pueden usar SGDEA.
  - Cada intento queda registrado (pasos hechos, mensaje, intentos). Un caso
    que necesita una decision de Andres queda 'requiere_manual' y no se
    reintenta solo; los demas se reintentan hasta MAX_INTENTOS_AUTO.
  - NUNCA envia a aprobacion: el caso queda PARA APROBAR en Memorandos.
"""
from __future__ import annotations

import dataclasses
from typing import Awaitable, Callable, Optional

from backend import dashboard


@dataclasses.dataclass
class ResumenBarrido:
    en_bandeja: int = 0
    nuevos: int = 0
    pendientes: int = 0
    listos: int = 0
    reintentar: int = 0
    manuales: int = 0
    detenido: str = ""  # motivo si la vuelta se corto antes de terminar


async def ejecutar_barrido(
    *,
    listar_bandeja: Callable[[], Awaitable[list]],
    procesar_caso: Callable[..., Awaitable[tuple]],
    tomar_candado: Callable[[str, int], Awaitable[bool]],
    soltar_candado: Callable[[], None],
    puede_seguir: Callable[[], bool],
    informar: Callable[[str], None] = lambda _t: None,
    al_actualizar: Callable[[], None] = lambda: None,
    ruta_dashboard=None,
    max_intentos: int = dashboard.MAX_INTENTOS_AUTO,
    autorrevisar: Optional[Callable[[set], list]] = None,
) -> ResumenBarrido:
    kw = {"path": ruta_dashboard} if ruta_dashboard is not None else {}
    r = ResumenBarrido()

    # Mostrar el progreso NUNCA puede tumbar el barrido (evidencia 27-sep:
    # actualizar controles que no estan en pantalla lanza RuntimeError).
    _informar, _al_actualizar = informar, al_actualizar

    def informar(t):
        try:
            _informar(t)
        except Exception:
            pass

    def al_actualizar():
        try:
            _al_actualizar()
        except Exception:
            pass

    if not await tomar_candado("Barrido: leyendo la bandeja de SGDEA", 300):
        r.detenido = "SGDEA ocupado con otra tarea al empezar"
        informar(f"Barrido aplazado: {r.detenido}.")
        return r
    try:
        todos = await listar_bandeja()
    finally:
        soltar_candado()

    nuevos, activos = dashboard.sincronizar_lista(todos, **kw)
    if autorrevisar is not None:
        # Revision automatica de errores: los casos detenidos cuya causa ya se
        # resolvio vuelven a la cola ANTES de elegir que gestionar.
        try:
            for linea in autorrevisar(activos) or []:
                informar(linea)
        except Exception as exc:  # la revision nunca tumba el barrido
            informar(f"Revisión automática: no se pudo completar ({type(exc).__name__}: {exc}).")
    pendientes = dashboard.casos_para_barrido(activos, max_intentos=max_intentos, **kw)
    r.en_bandeja, r.nuevos, r.pendientes = len(activos), len(nuevos), len(pendientes)
    al_actualizar()
    informar(f"{r.en_bandeja} caso(s) en la bandeja, {r.nuevos} nuevo(s), {r.pendientes} por gestionar.")

    for i, caso in enumerate(pendientes, start=1):
        if not puede_seguir():
            r.detenido = "se apago la gestion automatica o se desconecto SGDEA"
            informar(f"Barrido detenido: {r.detenido}.")
            return r
        etiqueta = f"Barrido {i}/{len(pendientes)}: {caso.radicado}"
        if not await tomar_candado(etiqueta, 600):
            r.detenido = "SGDEA lleva 10 min ocupado con otra tarea"
            informar(f"Barrido aplazado: {r.detenido}.")
            return r
        informar(f"{etiqueta} -- gestionando (intento {caso.auto_intentos + 1})...")
        try:
            ok, mensaje, manual, pasos = await procesar_caso(
                caso.radicado, caso.columnas_crudas,
                omitir=set(caso.auto_pasos), tratamiento_manual=caso.tratamiento_manual,
            )
        except Exception as exc:  # un caso nunca tumba el barrido
            ok, mensaje, manual, pasos = False, f"Error inesperado ({type(exc).__name__}): {exc}", False, []
        finally:
            soltar_candado()
        reg = dashboard.registrar_intento_auto(
            caso.radicado, ok, mensaje, pasos, requiere_manual=manual, max_intentos=max_intentos, **kw
        )
        if reg.auto_estado == "listo_revision":
            r.listos += 1
        elif reg.auto_estado == "requiere_manual":
            r.manuales += 1
        else:
            r.reintentar += 1
        informar(f"{caso.radicado}: {reg.auto_estado} -- {mensaje}")
        al_actualizar()

    informar(
        f"{r.listos} listo(s) para tu revisión, {r.reintentar} se reintentan en la próxima vuelta, "
        f"{r.manuales} requieren revisión manual."
    )
    return r

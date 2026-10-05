"""
Prueba MANUAL SUPERVISADA de legacy_portal_client.py contra el portal
antiguo real. NO forma parte de Insignia (no se importa desde main.py) --
es solo para calibrar/verificar la automatizacion antes de conectarla al
flujo Masivo.

Como correrlo (en Windows, desde la carpeta del proyecto):
    python backend\\test_legacy_portal_manual.py

Pide usuario y clave por consola (la clave no se muestra en pantalla,
gracias a getpass) -- nunca se guardan en este script ni se envian a
ningun lado mas que al portal antiguo mismo. Abre un Chromium VISIBLE
(headless=False) para que puedas ver cada paso y avisar si algo no
coincide con lo esperado.

Prueba con el ID de mensaje 1363712 (confirmado por Andres, 2026-09-23).
Ya NO se queda solo en descargar el testigo -- ahora corre el MISMO
pipeline de extraer + unir expediente + renombrar que ya usa Insignia
para Masivo/CARGAR ZIP (extract_acuse_from_pdf + merge_acuses), y guarda
el PDF final ya renombrado (ej. "2026_<numero>.pdf" para una resolucion,
sin ceros a la izquierda en el numero) junto a este archivo.

Si tienes a la mano la ruta al Cuadro_2026 (para que el nombre/alertas de
mas-de-1-destinatario salgan igual que en Insignia), ponla en
CUADRO_2026_PATH abajo; si la dejas en None, igual arma el expediente
pero sin cruzar contra el cuadro.
"""
from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.legacy_portal_client import (  # noqa: E402
    LegacyPortalClient,
    LegacyLoginError,
    LegacyNotFoundError,
    LegacyPortalError,
)
from backend.extractor import (  # noqa: E402
    extract_acuse_from_pdf,
    merge_acuses,
    ExtractionError,
)

ID_DE_PRUEBA = "1363712"

# Opcional: ruta al Cuadro_2026 (.xlsx) para cruzar destinatarios/alertas de
# "mas de 1 destinatario", igual que ya hace Insignia. Dejar en None si no
# se quiere probar eso todavia.
CUADRO_2026_PATH: str | None = None


async def main() -> None:
    print("=== Prueba manual supervisada: portal antiguo 4-72 ===")
    usuario = input("Usuario del portal antiguo: ").strip()
    password = getpass.getpass("Contraseña (no se muestra en pantalla): ")

    if not usuario or not password:
        print("Usuario y clave son obligatorios. Cancelado.")
        return

    cliente = LegacyPortalClient(usuario=usuario, password=password, headless=False)

    try:
        print("\n[1/3] Iniciando navegador y haciendo login...")
        await cliente.iniciar()
        print("      Login OK.")

        print(f"\n[2/3] Buscando y descargando testigo del ID {ID_DE_PRUEBA!r}...")
        pdf_bytes = await cliente.buscar_y_descargar_testigo(ID_DE_PRUEBA)
        print(f"      Descarga OK: {len(pdf_bytes):,} bytes.")

        salida = Path(__file__).resolve().parent / f"testigo_{ID_DE_PRUEBA}.pdf"
        salida.write_bytes(pdf_bytes)
        print(f"      Testigo guardado en: {salida}")

        print("\n[3/4] Extrayendo el acuse del testigo (extract_acuse_from_pdf)...")
        acuse = extract_acuse_from_pdf(pdf_bytes, f"testigo_{ID_DE_PRUEBA}.pdf")
        print(f"      Tipo={acuse.tipo!r} Numero={acuse.numero!r} Fecha={acuse.fecha!r}")

        print("\n[4/4] Uniendo expediente y armando el nombre final...")
        cuadro_idx = None
        if CUADRO_2026_PATH:
            from backend.cuadro_lookup import load_cuadro

            cuadro_idx = load_cuadro(CUADRO_2026_PATH)
            print(f"      Cuadro_2026 cargado desde: {CUADRO_2026_PATH}")

        expediente = merge_acuses([acuse], cuadro_idx)
        salida_final = Path(__file__).resolve().parent / expediente.final_filename
        salida_final.write_bytes(expediente.pdf_bytes)
        print(f"      Nombre final: {expediente.final_filename}")
        print(f"      Guardado en: {salida_final}")
        print(
            "\n>>> Abre ese PDF final y confirma que el expediente y el "
            "nombre (sin el 0 de mas en 2026_<numero> para resoluciones) "
            "estan correctos. <<<"
        )

    except ExtractionError as exc:
        print(f"\n*** ERROR AL EXTRAER EL ACUSE: {exc}")
        print(
            "    (El testigo se descargo bien pero su estructura interna "
            "no coincide con lo que espera extract_acuse_from_pdf -- "
            f"revisa testigo_{ID_DE_PRUEBA}.pdf manualmente para ver que "
            "trae adentro.)"
        )
    except LegacyLoginError as exc:
        print(f"\n*** ERROR DE LOGIN: {exc}")
    except LegacyNotFoundError as exc:
        print(f"\n*** NO ENCONTRADO: {exc}")
    except LegacyPortalError as exc:
        print(f"\n*** ERROR EN EL FLUJO DE BUSQUEDA/DESCARGA: {exc}")
        print(
            "    (Esto es justo lo que necesitamos calibrar -- si el "
            "navegador quedo abierto, revisa en que paso se quedo y "
            "cuentame que ves en pantalla.)"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n*** ERROR INESPERADO ({type(exc).__name__}): {exc}")
    finally:
        input("\nPresiona ENTER para cerrar el navegador y terminar...")
        await cliente.cerrar()


if __name__ == "__main__":
    asyncio.run(main())

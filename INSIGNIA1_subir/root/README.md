# Insignia (Automatizador 472)

Aplicación de escritorio (Flet + Playwright) que recorre la bandeja "Gestionar" de SGDEA,
lee cada petición interna, arma el memorando de respuesta con su cuadro de actos y los
expedientes con acuse (PDF, o ZIP en las masivas) y lo deja PARA APROBAR.

**Versión actual: 1.5.15**

## Módulos principales (`backend/`)
- `sgdea_peticion.py`: lee la petición; conteo exacto de casos por lista y detección de duplicados.
- `sgdea_carta.py`: cruza con el Cuadro 2026 y redacta el cuerpo y el cuadro de la respuesta.
- `carpeta_caso.py`: lee `Descargas\<radicado>\` (PDF pedidos a Magda), identifica cada PDF por su contenido.
- `fuentes_acuses.py`, `estado_mensajes_lookup.py`, `centro_envios_client.py`, `contingencia.py`: fuentes de acuses enrutadas por fecha del acto.
- `sgdea_automation.py`: automatización de SGDEA (crear/rehacer memorando, adjuntar, dejar en revisión).
- `dashboard.py`, `autorrevision.py`: estado de cada caso, reintentos y clasificación de errores.

## Reglas clave
- Expediente anterior a 2025 -> alerta "PEDIR A MAGDA"; el caso espera los PDF en `Descargas\<radicado>\` y la respuesta los incluye.
- El cuadro lleva exactamente los casos pedidos; los duplicados aparecen una sola vez con aviso.

## Ejecutar / compilar (Windows)
`instalar_playwright.bat` -> `run_dev.bat` (desarrollo) o `build.bat` (genera `dist\Insignia.exe`).

> Las pruebas y los datos reales (peticiones, Cuadro, acuses) no se publican por contener datos personales.

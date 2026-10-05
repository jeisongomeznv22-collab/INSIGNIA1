"""
Cliente para el Portal de Acuses (proveedor 4-72 / almacenamiento472.verificaia.com).

Encapsula el flujo descubierto por ingenieria inversa del trafico de red:
  1. POST /api/auth/login    {email, password}  -> cookie de sesion (httpOnly)
  2. GET  /api/auth/me                            -> valida sesion activa
  3. GET  /api/files/search?q=<ID>                -> {results: [{key, name, ...}]}
  4. GET  /api/files/download?key=<key>           -> {url: <presigned S3 url>}
  5. GET  <url>                                    -> bytes del ZIP

No requiere navegador: todo es HTTP simple via requests.Session (cookies
se manejan automaticamente).
"""
from __future__ import annotations

import dataclasses
import time
from typing import Optional

import requests

BASE_URL = "https://almacenamiento472.verificaia.com"
# ^ SIN "www." a proposito: el 2026-09-24 el servidor volvio de una caida y
# desde entonces el certificado/enrutamiento de "www.almacenamiento472..."
# quedo dando "Hostname mismatch" (confirmado navegando directo desde el
# equipo de Andres), mientras que el dominio raiz (sin www) funciona bien.
# Si el proveedor vuelve a arreglar el subdominio www en el futuro, esto
# puede revertirse, pero por ahora el dominio raiz es el que sirve.
LOGIN_URL = f"{BASE_URL}/api/auth/login"
ME_URL = f"{BASE_URL}/api/auth/me"
SEARCH_URL = f"{BASE_URL}/api/files/search"
DOWNLOAD_URL = f"{BASE_URL}/api/files/download"

DEFAULT_TIMEOUT = 30


class PortalError(Exception):
    """Error generico de comunicacion con el portal."""


class LoginError(PortalError):
    """Credenciales invalidas o fallo de autenticacion."""


class NotFoundError(PortalError):
    """El ID buscado no arrojo resultados en el portal."""


@dataclasses.dataclass
class SearchResult:
    key: str
    name: str
    year: str = ""
    month: str = ""
    company: str = ""
    day: str = ""
    size: int = 0
    last_modified: str = ""


class PortalClient:
    """Cliente autenticado y reutilizable para el portal de acuses."""

    def __init__(self, email: str, password: str, timeout: int = DEFAULT_TIMEOUT):
        self.email = email
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "application/json",
            }
        )
        self._logged_in = False

    def login(self) -> None:
        """Autentica contra el portal. Lanza LoginError si falla."""
        try:
            resp = self.session.post(
                LOGIN_URL,
                json={"email": self.email, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise PortalError(f"No se pudo conectar al portal: {exc}") from exc

        if not resp.ok:
            try:
                detail = resp.json().get("error", resp.text)
            except Exception:
                detail = resp.text
            raise LoginError(f"Login fallido ({resp.status_code}): {detail}")

        self._logged_in = True

    def ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    def search(self, message_id: str) -> Optional[SearchResult]:
        """Busca un ID de correo en el portal. Devuelve None si no hay resultados."""
        self.ensure_login()
        message_id = (message_id or "").strip()
        if not message_id:
            raise ValueError("ID vacio")

        try:
            resp = self.session.get(
                SEARCH_URL, params={"q": message_id}, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise PortalError(f"Error de red buscando {message_id}: {exc}") from exc

        if resp.status_code == 401:
            # sesion expirada -> reintenta login una vez
            self._logged_in = False
            self.login()
            resp = self.session.get(
                SEARCH_URL, params={"q": message_id}, timeout=self.timeout
            )

        if not resp.ok:
            raise PortalError(f"Error buscando {message_id}: HTTP {resp.status_code}")

        data = resp.json()
        results = data.get("results") or []
        if not results:
            return None

        # preferir coincidencia exacta de nombre de archivo si hay varias
        best = results[0]
        for r in results:
            if r.get("name", "").upper().startswith(message_id.upper()):
                best = r
                break

        return SearchResult(
            key=best.get("key", ""),
            name=best.get("name", ""),
            year=best.get("year", ""),
            month=best.get("month", ""),
            company=best.get("company", ""),
            day=best.get("day", ""),
            size=best.get("size", 0),
            last_modified=best.get("lastModified", ""),
        )

    def get_download_url(self, key: str) -> str:
        self.ensure_login()
        try:
            resp = self.session.get(
                DOWNLOAD_URL, params={"key": key}, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise PortalError(f"Error de red pidiendo descarga: {exc}") from exc

        if not resp.ok:
            raise PortalError(f"Error pidiendo descarga: HTTP {resp.status_code}")

        data = resp.json()
        url = data.get("url")
        if not url:
            raise PortalError("El portal no devolvio URL de descarga")
        return url

    def download_zip_bytes(self, message_id: str, retries: int = 2) -> bytes:
        """Flujo completo: busca el ID y descarga los bytes del ZIP."""
        result = self.search(message_id)
        if result is None:
            raise NotFoundError(f"ID no encontrado en el portal: {message_id}")

        last_exc: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                url = self.get_download_url(result.key)
                # La URL firmada es de un origen distinto (S3); no requiere
                # las cookies de sesion, pero tampoco estorban.
                file_resp = requests.get(url, timeout=self.timeout)
                file_resp.raise_for_status()
                return file_resp.content
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise PortalError(f"No se pudo descargar el ZIP de {message_id}: {last_exc}")

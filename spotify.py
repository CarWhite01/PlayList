"""Inicio de sesión con Spotify (OAuth con PKCE) y lectura de playlists.

Desde febrero de 2026, las apps de Spotify en modo desarrollo solo pueden leer
las canciones de playlists que el usuario es dueño o colaborador, y solo para
las cuentas agregadas en el panel de la app (máximo 5).
"""

import base64
import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlencode

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "playlist-read-private playlist-read-collaborative"

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/spotify/callback")


class ErrorSpotify(Exception):
    """Error con un mensaje listo para mostrarse al usuario."""


class SpotifyNoConectado(ErrorSpotify):
    def __init__(self):
        super().__init__("Conecta tu cuenta de Spotify con el botón de arriba para usar playlists de Spotify.")


def configurado() -> bool:
    return bool(CLIENT_ID)


def conectado(session) -> bool:
    return "spotify" in session


def url_login(session) -> str:
    """Genera la URL de autorización y guarda en la sesión lo necesario para validar la vuelta."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    session["spotify_pkce"] = {"verifier": verifier, "state": state}

    return AUTH_URL + "?" + urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    })


def completar_login(session, code: str, state: str) -> None:
    pkce = session.pop("spotify_pkce", None)
    if not pkce or not secrets.compare_digest(state or "", pkce["state"]):
        raise ErrorSpotify("El inicio de sesión con Spotify expiró. Inténtalo de nuevo.")

    datos = _pedir_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": pkce["verifier"],
    })
    _guardar_token(session, datos)


def cerrar_sesion(session) -> None:
    session.pop("spotify", None)
    session.pop("spotify_pkce", None)


def _pedir_token(datos: dict) -> dict:
    try:
        r = requests.post(TOKEN_URL, data=datos, timeout=15)
    except requests.RequestException as e:
        raise ErrorSpotify("No se pudo contactar a Spotify. Intenta de nuevo.") from e
    if r.status_code != 200:
        raise ErrorSpotify("Spotify rechazó el inicio de sesión. Vuelve a conectar tu cuenta.")
    return r.json()


def _guardar_token(session, datos: dict) -> None:
    anterior = session.get("spotify", {})
    session["spotify"] = {
        "access_token": datos["access_token"],
        # Al refrescar, Spotify puede no mandar un refresh_token nuevo: se conserva el anterior.
        "refresh_token": datos.get("refresh_token") or anterior.get("refresh_token"),
        "expira": time.time() + int(datos.get("expires_in", 3600)),
    }


def _token_vigente(session) -> str:
    datos = session.get("spotify")
    if not datos:
        raise SpotifyNoConectado()

    if datos["expira"] - 60 < time.time():
        if not datos.get("refresh_token"):
            cerrar_sesion(session)
            raise SpotifyNoConectado()
        try:
            nuevo = _pedir_token({
                "grant_type": "refresh_token",
                "refresh_token": datos["refresh_token"],
                "client_id": CLIENT_ID,
            })
        except ErrorSpotify:
            cerrar_sesion(session)
            raise SpotifyNoConectado()
        _guardar_token(session, nuevo)

    return session["spotify"]["access_token"]


def extraer_playlist_id(url: str) -> str:
    """Acepta https://open.spotify.com/playlist/ID, .../intl-es/playlist/ID y spotify:playlist:ID."""
    match = re.search(r"playlist[/:]([A-Za-z0-9]+)", url)
    if not match:
        raise ErrorSpotify("Esa URL de Spotify no parece ser de una playlist.")
    return match.group(1)


def _get(session, url: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"Authorization": f"Bearer {_token_vigente(session)}"})
    except requests.RequestException as e:
        raise ErrorSpotify("No se pudo contactar a Spotify. Intenta de nuevo.") from e

    if r.status_code == 401:
        cerrar_sesion(session)
        raise SpotifyNoConectado()
    if r.status_code == 403:
        raise ErrorSpotify(
            "Spotify no deja leer esa playlist. Solo se pueden usar playlists tuyas o "
            "colaborativas, y tu cuenta debe estar agregada en la app de Spotify."
        )
    if r.status_code == 404:
        raise ErrorSpotify("No se encontró esa playlist de Spotify.")
    if r.status_code == 429:
        raise ErrorSpotify("Spotify está limitando las peticiones. Espera un momento e intenta de nuevo.")
    if not r.ok:
        raise ErrorSpotify(f"Spotify respondió con un error ({r.status_code}).")
    return r.json()


def obtener_playlist(session, url: str) -> tuple[str, list[dict]]:
    """Devuelve (nombre, canciones) donde cada canción es {"titulo", "artista"}."""
    playlist_id = extraer_playlist_id(url)
    nombre = _get(session, f"{API_URL}/playlists/{playlist_id}").get("name") or "Playlist de Spotify"

    canciones = []
    siguiente, params = f"{API_URL}/playlists/{playlist_id}/items", {"limit": 50}
    while siguiente:
        pagina = _get(session, siguiente, params)
        params = None  # la URL 'next' ya incluye offset y limit
        for fila in pagina.get("items") or []:
            # La API nueva usa 'item'; la anterior usaba 'track' (que ahora puede ser un booleano).
            item = fila.get("item")
            if not isinstance(item, dict):
                item = fila.get("track")
            if not isinstance(item, dict) or not item.get("name"):
                continue
            artistas = [a.get("name") for a in item.get("artists") or [] if a and a.get("name")]
            if not artistas and isinstance(item.get("show"), dict):  # episodios de podcast
                artistas = [item["show"].get("name") or ""]
            canciones.append({"titulo": item["name"], "artista": ", ".join(artistas)})
        siguiente = pagina.get("next")

    return nombre, canciones

from fastapi.testclient import TestClient

import main

cliente = TestClient(main.app)


def falsa_playlist(playlists):
    def get_playlist(playlist_id, limit):
        if playlist_id not in playlists:
            raise RuntimeError("no existe")
        return playlists[playlist_id]
    return get_playlist


def test_home():
    r = cliente.get("/")
    assert r.status_code == 200 and "Comparar dos playlists" in r.text


def test_analizar(monkeypatch):
    monkeypatch.setattr(main.ytmusic, "get_playlist", falsa_playlist({"PL1": {"tracks": [
        {"title": "Despacito", "artists": [{"name": "Luis Fonsi"}]},
        {"title": "despacito ", "artists": [{"name": "luis fonsi"}]},
        {"title": None, "artists": None},
    ]}}))
    r = cliente.post("/analizar", data={"url": "https://music.youtube.com/playlist?list=PL1&si=x"})
    assert r.json() == {"duplicados": [{"Título": "Despacito", "Artista": "Luis Fonsi", "Repeticiones": 2}], "total": 3}


def test_comparar(monkeypatch):
    monkeypatch.setattr(main.ytmusic, "get_playlist", falsa_playlist({
        "A": {"title": "Videos", "tracks": [
            {"title": "Bad Bunny - Me Porto Bonito (Official Video)", "artists": [{"name": "BadBunnyVEVO"}]},
            {"title": "Solo en A", "artists": None},
        ]},
        "B": {"title": "Canciones", "tracks": [
            {"title": "Me Porto Bonito", "artists": [{"name": "Bad Bunny"}, {"name": "Chencho Corleone"}]},
            {"title": "Solo en B", "artists": [{"name": "X"}]},
        ]},
    }))
    r = cliente.post("/comparar", data={"url_a": "https://www.youtube.com/playlist?list=A",
                                        "url_b": "https://music.youtube.com/playlist?list=B"}).json()
    assert r["a"] == {"nombre": "Videos", "total": 2}
    assert r["b"] == {"nombre": "Canciones", "total": 2}
    assert r["en_comun"] == 1
    assert [x["Título"] for x in r["faltan_en_b"]] == ["Solo en A"]
    assert [x["Título"] for x in r["faltan_en_a"]] == ["Solo en B"]


def test_playlist_inaccesible(monkeypatch):
    monkeypatch.setattr(main.ytmusic, "get_playlist", falsa_playlist({}))
    r = cliente.post("/comparar", data={"url_a": "list=nada", "url_b": "otra"})
    assert r.status_code == 400 and "pública o deslistada" in r.json()["error"]


def test_reintenta_si_youtube_falla_una_vez(monkeypatch):
    llamadas = []

    def get_playlist(playlist_id, limit):
        llamadas.append(playlist_id)
        if len(llamadas) == 1:
            raise ValueError("respuesta vacía")
        return {"tracks": [{"title": "Uno", "artists": []}]}

    monkeypatch.setattr(main.ytmusic, "get_playlist", get_playlist)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    r = cliente.post("/analizar", data={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 200 and r.json()["total"] == 1 and llamadas == ["PL1", "PL1"]


def test_misma_playlist_se_descarga_una_vez(monkeypatch):
    llamadas = []
    monkeypatch.setattr(main.ytmusic, "get_playlist",
                        lambda pid, limit: llamadas.append(pid) or {"title": "X", "tracks": [{"title": "Uno", "artists": []}]})
    r = cliente.post("/comparar", data={"url_a": "https://youtube.com/playlist?list=P", "url_b": "https://music.youtube.com/playlist?list=P"}).json()
    assert llamadas == ["P"] and r["en_comun"] == 1 and r["faltan_en_a"] == r["faltan_en_b"] == []


def test_boton_donaciones_solo_si_hay_link(monkeypatch):
    assert "Invítame un café" not in cliente.get("/").text
    monkeypatch.setattr(main, "DONACIONES_URL", "https://ko-fi.com/ejemplo")
    html = cliente.get("/").text
    assert "Invítame un café" in html and 'href="https://ko-fi.com/ejemplo"' in html

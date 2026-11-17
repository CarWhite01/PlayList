from analisis import buscar_duplicados, comparar


def c(titulo, artista=""):
    return {"titulo": titulo, "artista": artista}


def nombres(lista):
    return [x["Título"] for x in lista]


def test_duplicados_agrupa_variantes():
    dup = buscar_duplicados([c("Despacito", "Luis Fonsi"), c("despacito ", "luis fonsi"), c("Otra", "X")])
    assert dup == [{"Título": "Despacito", "Artista": "Luis Fonsi", "Repeticiones": 2}]


def test_videos_contra_canciones_de_youtube_music():
    youtube = [
        c("Tití Me Preguntó (Official Video)", "Bad Bunny"),
        c("Bad Bunny - Me Porto Bonito ft. Chencho Corleone", "BadBunnyVEVO"),
        c("La Bachata", "Manuel Turizo - Topic"),
        c("Shakira || BZRP Music Sessions #53 [Letra]", "Bizarrap"),
        c("Solo en YouTube", "Alguien"),
    ]
    music = [
        c("Titi Me Pregunto", "Bad Bunny"),
        c("Me Porto Bonito", "Bad Bunny, Chencho Corleone"),
        c("La Bachata", "Manuel Turizo"),
        c("Shakira: Bzrp Music Sessions, Vol. 53", "Bizarrap, Shakira"),
        c("Solo en YouTube Music", "Otra Persona"),
    ]
    r = comparar(youtube, music)
    assert r["en_comun"] == 4
    assert "Solo en YouTube" in nombres(r["faltan_en_b"])
    assert "Solo en YouTube Music" in nombres(r["faltan_en_a"])
    for t in ("Tití Me Preguntó (Official Video)", "La Bachata"):
        assert t not in nombres(r["faltan_en_b"])


def test_mismo_titulo_distinto_artista_no_coincide():
    r = comparar([c("Hello", "Adele")], [c("Hello", "Lionel Richie")])
    assert r["en_comun"] == 0
    assert nombres(r["faltan_en_b"]) == ["Hello"]


def test_listas_iguales_y_vacias():
    assert comparar([c("A", "x1x")], [c("a", "X1X")]) == {"faltan_en_b": [], "faltan_en_a": [], "en_comun": 1}
    assert comparar([], []) == {"faltan_en_b": [], "faltan_en_a": [], "en_comun": 0}


def test_faltantes_sin_repetir():
    r = comparar([c("Uno", "Art"), c("uno", "art")], [])
    assert len(r["faltan_en_b"]) == 1


def test_titulos_en_otros_idiomas():
    canciones = [c("聖誕星 (feat. 楊瑞代)", "Jay Chou"), c("Dynamite", "BTS"), c("소나기", "IU")]
    assert comparar(canciones, canciones) == {"faltan_en_b": [], "faltan_en_a": [], "en_comun": 3}
    r = comparar([c("聖誕星", "Jay Chou")], [c("稻香", "Jay Chou")])
    assert r["en_comun"] == 0

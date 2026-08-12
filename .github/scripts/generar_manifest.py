#!/usr/bin/env python3
"""
Genera manifest.json: el indice del catalogo que la app consulta al arrancar
para avisar si hay productos nuevos (globo sobre "Actualizar Productos") o una
lista de precios de accesorios nueva (cartel al abrir).

Lo corre solo el workflow publicar-manifest.yml en cada push a master. El
equivalente manual, por si hay que publicarlo a mano, es
generar-manifest-productos.ps1 en el repo de la app.

Del catalogo solo lista rutas, sin hashes: la app cuenta unicamente archivos
FALTANTES (no modificados), asi que del otro lado alcanza con File.Exists.

Aparte va la lista de BAJAS (bajas.txt), que si lleva huellas: ahi el cliente
borra, y borrar exige saber que lo que tiene es exactamente lo que publicamos.
"""

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timezone, datetime

# Carpetas que la app sabe mapear a una ruta local (GetLocalProductPath).
# Lo que este fuera de estas raices no se anuncia: el cliente no sabria
# donde ponerlo.
RAICES = [
    "Productos", "Mosquiteros", "Travesaños", "Parantes",
    "MarcosUnificados", "Acoples", "Contramarcos", "Premarcos",
    "Tableros", "AccesoriosPorProducto",
]

# Lineas exclusivas de UN cliente. Debe coincidir con
# DatabaseManager.LineasPrivadas en la app y con sync-package.ps1.
# No deberian estar en el repo publico; esto es la segunda barrera, para que
# un archivo filtrado por descuido no le anuncie al resto novedades que
# nunca van a poder descargar.
LINEAS_PRIVADAS = ["ALUPAL"]

# Lista oficial de precios de accesorios. Nombre y ruta FIJOS: la app baja
# exactamente este path del zip del repo, y cada lista nueva pisa la anterior.
PRECIOS = "Precios/accesorios.txt"

# Archivos dados de baja: la app los borra de la maquina del cliente.
BAJAS = "bajas.txt"

# SHA1 del contenido vacio. `git show <commit>:<ruta>` no falla siempre de la
# misma forma cuando la ruta no existe en ese commit, y un stdout vacio hashea
# a esto. Publicarlo seria decirle al cliente que borre cualquier archivo
# vacio que tenga en esa ruta.
SHA1_VACIO = hashlib.sha1(b"").hexdigest()

MANIFEST_PUBLICADO = ("https://github.com/germanroz/Asoftware-productos"
                      "/releases/latest/download/manifest.json")


def es_privado(partes):
    return any(p.upper() == lp.upper() for p in partes for lp in LINEAS_PRIVADAS)


def datos_precios():
    """Huella y fecha de publicacion de la lista de precios de accesorios.

    Se publica la HUELLA del contenido y no un numero de version: asi seguimos
    subiendo la lista pisando el .txt de siempre, sin nada que numerar a mano.

    La fecha es la del dia en que aparecio ESA huella, y se arrastra del
    manifest anterior mientras el archivo no cambie. Sin eso, cada push de
    productos volveria a fechar hoy una lista vieja y el cliente veria
    "publicada hoy" una lista que ya tiene.
    """
    if not os.path.isfile(PRECIOS):
        print(f"ATENCION: no hay {PRECIOS} en el repo: no se avisa de precios.")
        return "", ""

    with open(PRECIOS, "rb") as f:
        huella = hashlib.sha1(f.read()).hexdigest()

    fecha = date.today().isoformat()
    try:
        with urllib.request.urlopen(MANIFEST_PUBLICADO, timeout=20) as r:
            anterior = json.load(r)
        if (anterior.get("preciosAccesorios") == huella
                and anterior.get("preciosAccesoriosFecha")):
            fecha = anterior["preciosAccesoriosFecha"]
    except Exception as e:
        print(f"AVISO: no se pudo leer el manifest anterior ({e}). "
              f"La lista de precios queda fechada hoy.")

    print(f"Lista de precios: {huella} (publicada {fecha})")
    return huella, fecha


def huellas_publicadas(ruta):
    """SHA1 del contenido de TODAS las versiones que esa ruta tuvo en master.

    Son las unicas huellas con las que la app se anima a borrar. Si el archivo
    que tiene el cliente no coincide con ninguna, es suyo (lo modifico, o creo
    uno propio con el mismo nombre) y no se toca.

    Se recorre el historial y no la ultima version porque el archivo ya no
    existe: quien lo tenga puede haberlo bajado en cualquier momento, incluso
    de una version anterior a la ultima que publicamos.
    """
    log = subprocess.run(["git", "log", "--all", "--format=%H", "--", ruta],
                         capture_output=True, text=True)
    if log.returncode != 0:
        print(f"ATENCION: no se pudo leer el historial de {ruta}: {log.stderr.strip()}")
        return []

    huellas = []
    for commit in log.stdout.split():
        blob = subprocess.run(["git", "show", f"{commit}:{ruta}"],
                              capture_output=True)
        # El commit que la dio de baja tambien toca la ruta y ahi ya no existe.
        if blob.returncode != 0:
            continue
        huella = hashlib.sha1(blob.stdout).hexdigest()
        if huella == SHA1_VACIO:
            continue
        if huella not in huellas:
            huellas.append(huella)
    return huellas


def datos_bajas(archivos):
    """Lee bajas.txt y le pone a cada ruta sus huellas publicadas.

    Se saltea (ruidosamente) toda ruta que TODAVIA este en el repo: publicarla
    y darla de baja a la vez deja al cliente bajandola y borrandola en cada
    arranque.
    """
    if not os.path.isfile(BAJAS):
        return []

    presentes = set(archivos)
    bajas = []
    with open(BAJAS, encoding="utf-8") as f:
        for linea in f:
            ruta = linea.strip()
            if not ruta or ruta.startswith("#"):
                continue
            if ruta in presentes:
                print(f"ATENCION: {ruta} esta en bajas.txt pero sigue en el repo. "
                      f"No se da de baja: borrala del repo primero.")
                continue

            huellas = huellas_publicadas(ruta)
            if not huellas:
                # Sin huellas la app no borraria nada igual, pero publicar la
                # baja vacia esconde el problema (checkout sin historial, ruta
                # mal escrita) detras de un manifest que parece correcto.
                print(f"ATENCION: {ruta} no tiene ninguna version en el historial. "
                      f"Se omite (revisar la ruta, o el fetch-depth del checkout).")
                continue

            bajas.append({"ruta": ruta, "huellas": huellas})
            print(f"Baja: {ruta} ({len(huellas)} version/es publicada/s)")

    return bajas


def main():
    archivos = []
    privados = 0

    for raiz in RAICES:
        if not os.path.isdir(raiz):
            continue
        for dirpath, _dirnames, filenames in os.walk(raiz):
            for nombre in filenames:
                rel = os.path.join(dirpath, nombre).replace(os.sep, "/")
                if es_privado(rel.split("/")):
                    privados += 1
                    continue
                archivos.append(rel)

    archivos.sort()

    if not archivos:
        # Sin esto, un checkout roto publicaria un manifest vacio y todos los
        # clientes dejarian de ver novedades sin que nadie se entere.
        sys.exit("ERROR: no se encontro ningun archivo de catalogo. No se publica.")

    contables = [a for a in archivos
                 if a.startswith("Productos/") and a.lower().endswith(".json")]

    huella_precios, fecha_precios = datos_precios()
    bajas = datos_bajas(archivos)

    manifest = {
        "generado": date.today().isoformat(),
        "preciosAccesorios": huella_precios,
        "preciosAccesoriosFecha": fecha_precios,
        "archivos": archivos,
        "bajas": bajas,
    }
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Archivos de catalogo: {len(archivos)}")
    print(f"Productos contables (.json de Productos/): {len(contables)}")
    print(f"Bajas publicadas: {len(bajas)}")
    if privados:
        print(f"ATENCION: se saltearon {privados} archivos de lineas privadas "
              f"presentes en el repo publico.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Genera manifest.json: el indice del catalogo que la app consulta al arrancar
para avisar si hay productos nuevos (globo sobre "Actualizar Productos").

Lo corre solo el workflow publicar-manifest.yml en cada push a master. El
equivalente manual, por si hay que publicarlo a mano, es
generar-manifest-productos.ps1 en el repo de la app.

Solo lista rutas, sin hashes: la app cuenta unicamente archivos FALTANTES
(no modificados), asi que del otro lado alcanza con File.Exists.
"""

import json
import os
import sys
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


def es_privado(partes):
    return any(p.upper() == lp.upper() for p in partes for lp in LINEAS_PRIVADAS)


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

    manifest = {
        "generado": date.today().isoformat(),
        "archivos": archivos,
    }
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"Archivos de catalogo: {len(archivos)}")
    print(f"Productos contables (.json de Productos/): {len(contables)}")
    if privados:
        print(f"ATENCION: se saltearon {privados} archivos de lineas privadas "
              f"presentes en el repo publico.")


if __name__ == "__main__":
    main()

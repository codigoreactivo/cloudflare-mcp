"""
Registra el native messaging host ante los navegadores Chromium instalados
en macOS (Chrome, Brave, Edge, Chromium, Vivaldi — el que esté presente).

Uso:
    python3 install.py <EXTENSION_ID>

<EXTENSION_ID> es el ID que el navegador asigna a la extensión al cargarla en
modo desarrollador ("Cargar descomprimida"). Cópialo desde la tarjeta de la
extensión.

Nota: el ID de una extensión sin empaquetar se deriva determinísticamente de
la ruta absoluta de la carpeta `extension/` (SHA256 de la ruta, mapeado a
a-p). Por eso es el MISMO id en Chrome, Brave, etc. si la cargas desde esta
misma ruta en cada uno — no hace falta un id distinto por navegador.
"""

import json
import os
import stat
import sys

HOST_NAME = "com.jesusjhoel.chatgpt_bridge"

# Carpeta de perfil (Application Support) de cada navegador Chromium en
# macOS, relativa a la que cuelga NativeMessagingHosts/. Se usa /Applications
# para detectar cuáles están instalados.
BROWSERS = [
    ("Google Chrome.app", "Google/Chrome"),
    ("Brave Browser.app", "BraveSoftware/Brave-Browser"),
    ("Microsoft Edge.app", "Microsoft Edge"),
    ("Chromium.app", "Chromium"),
    ("Vivaldi.app", "Vivaldi"),
]


def installed_browsers():
    for app_name, profile_dir in BROWSERS:
        if os.path.isdir(f"/Applications/{app_name}"):
            yield app_name, profile_dir


def main() -> None:
    if len(sys.argv) != 2:
        print("Uso: python3 install.py <EXTENSION_ID>")
        sys.exit(1)

    ext_id = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    run_script = os.path.join(here, "run_host.sh")

    st = os.stat(run_script)
    os.chmod(run_script, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    manifest = {
        "name": HOST_NAME,
        "description": "Bridge nativo para automatizar ChatGPT desde Python",
        "path": run_script,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"],
    }

    found = list(installed_browsers())
    if not found:
        print(
            "No se detectó ningún navegador Chromium en /Applications "
            "(Chrome, Brave, Edge, Chromium, Vivaldi)."
        )
        sys.exit(1)

    touched = []
    for app_name, profile_dir in found:
        target_dir = os.path.expanduser(
            f"~/Library/Application Support/{profile_dir}/NativeMessagingHosts"
        )
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, f"{HOST_NAME}.json")
        with open(target_path, "w") as f:
            json.dump(manifest, f, indent=2)
        touched.append((app_name, target_path))

    print(f"path -> {run_script}\n")
    for app_name, target_path in touched:
        print(f"Host nativo registrado para {app_name}: {target_path}")
    print(
        "\nReinicia por completo (Cmd+Q) cada navegador donde hayas cargado "
        "la extensión, para que tome el nuevo host nativo."
    )


if __name__ == "__main__":
    main()

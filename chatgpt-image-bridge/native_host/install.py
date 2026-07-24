"""
Registra el native messaging host ante Chrome en macOS.

Uso:
    python3 install.py <EXTENSION_ID>

<EXTENSION_ID> es el ID que Chrome asigna a la extensión al cargarla en modo
desarrollador (chrome://extensions -> "Cargar descomprimida"). Cópialo desde
la tarjeta de la extensión.
"""

import json
import os
import stat
import sys

HOST_NAME = "com.jesusjhoel.chatgpt_bridge"


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

    target_dir = os.path.expanduser(
        "~/Library/Application Support/Google/Chrome/NativeMessagingHosts"
    )
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, f"{HOST_NAME}.json")

    with open(target_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Host nativo registrado en: {target_path}")
    print(f"path -> {run_script}")
    print("Reinicia Chrome por completo (Cmd+Q) para que tome el nuevo host nativo.")


if __name__ == "__main__":
    main()

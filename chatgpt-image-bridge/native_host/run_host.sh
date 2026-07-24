#!/bin/bash
# Chrome invoca este script (la ruta va registrada en el manifest del native
# messaging host). Debe ser ejecutable y no requerir interacción.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/host.py"

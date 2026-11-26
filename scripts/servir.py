"""Muestra el portal en tu navegador: python scripts/servir.py [puerto]

Hace falta un servidor local porque el navegador no deja leer los datos (fetch) si se
abre index.html con doble clic.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

SITIO = Path(__file__).resolve().parent.parent / "site"


def main() -> None:
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if not (SITIO / "data" / "meta.json").exists():
        print("Todavía no hay datos en site/data. Generalos con 'python main.py --demo' (ejemplo) o 'python main.py'.")
    manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITIO))
    with socketserver.ThreadingTCPServer(("127.0.0.1", puerto), manejador) as servidor:
        url = f"http://localhost:{puerto}/"
        print(f"Portal disponible en {url}  (Ctrl+C para cerrar)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor cerrado.")


if __name__ == "__main__":
    main()

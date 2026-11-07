"""Start BIM 5D Estimator: finds a free port, opens the browser when the app is ready.

Used by start-windows.bat and start-mac-linux.sh. You can also run: python run.py
"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def _check_install():
    missing = []
    for mod in ("ifcopenshell", "numpy", "fastapi", "uvicorn", "openpyxl", "manifold3d", "multipart"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001 - show any import problem in plain words
            missing.append(f"{mod} ({e.__class__.__name__}: {e})")
    if missing:
        print("\nSome parts are not installed correctly:\n  " + "\n  ".join(missing))
        print("\nFix: delete the .venv folder next to this file and start again (needs internet the first time).")
        print("Python 3.10 to 3.14 (64-bit) from python.org is supported.\n")
        sys.exit(1)


def _free_port(start=8000):
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found between 8000 and 8049.")


def _open_when_ready(url):
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "api/library", timeout=2)
            break
        except Exception:  # noqa: BLE001 - server not up yet
            time.sleep(0.5)
    print(f"\n  BIM 5D Estimator is running at {url}\n  Keep this window open while you work; close it to stop.\n")
    if os.environ.get("BIM5D_NO_BROWSER") != "1":
        webbrowser.open(url)


def main():
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    _check_install()
    import uvicorn

    port = int(os.environ.get("PORT") or _free_port())
    url = f"http://localhost:{port}/"
    threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

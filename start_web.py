"""Start/reuse the local website and open it without PowerShell policy changes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent


def ready(url):
    try:
        with urlopen(url+'/_stcore/health', timeout=2) as response:
            return response.status == 200 and response.read(16).strip() == b'ok'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description='Open the HUFS campus shade map')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535')
    url = f'http://127.0.0.1:{args.port}'
    if not ready(url):
        python = ROOT/('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
        if not python.is_file():
            raise SystemExit('Create .venv and install requirements.txt first. See README.md.')
        command = [str(python), '-m', 'streamlit', 'run', str(ROOT/'app.py'),
                   '--server.address', '127.0.0.1', '--server.port', str(args.port),
                   '--server.headless', 'true', '--browser.gatherUsageStats', 'false']
        with (ROOT/'web.stdout.log').open('ab') as out, (ROOT/'web.stderr.log').open('ab') as error:
            options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=error, **options)
        deadline = time.monotonic()+30
        while not ready(url):
            if process.poll() is not None or time.monotonic() >= deadline:
                raise SystemExit('The website did not start. Check web.stderr.log.')
            time.sleep(.5)
    print(f'HUFS shade map is running: {url}', flush=True)
    if not args.no_browser:
        webbrowser.open(url, new=2)


if __name__ == '__main__':
    main()

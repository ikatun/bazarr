"""Start a fresh isolated image, verify UI and its script assets, then remove it."""
import re
import subprocess
import sys
import time
from urllib.request import urlopen

image = sys.argv[1]
name = 'bazarr-ci-smoke'
subprocess.run(['docker', 'run', '-d', '--name', name, '-p', '127.0.0.1::6767',
                image, 'serve', '--no-tasks', '--no-signalr'], check=True)
try:
    address = subprocess.check_output(['docker', 'port', name, '6767/tcp'], text=True).strip()
    base = 'http://' + address
    for attempt in range(90):
        try:
            with urlopen(base + '/', timeout=3) as response:
                html = response.read().decode()
            if '<html' not in html.lower():
                raise ValueError('Missing UI HTML')
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
            if not scripts:
                raise ValueError('Missing UI scripts')
            for src in scripts:
                with urlopen(base + '/' + src.lstrip('./'), timeout=5) as response:
                    assert response.status == 200 and response.read(1)
            print('Fresh container UI and JavaScript assets returned HTTP 200')
            break
        except Exception:
            if attempt == 89:
                subprocess.run(['docker', 'logs', name], check=False)
                raise
            time.sleep(2)
    subprocess.run(['docker', 'kill', '--signal=SIGINT', name], check=True)
    result = subprocess.run(['docker', 'wait', name], capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == '0', 'Container did not shut down cleanly: ' + result.stdout
    print('SIGINT shutdown completed cleanly')
finally:
    subprocess.run(['docker', 'rm', '-f', name], check=False)

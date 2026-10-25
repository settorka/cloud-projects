import os
import signal
import subprocess
import sys
import threading
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Local opt-in live import scheduler; no cloud resources"

    def handle(self, *args, **o):
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            result = subprocess.run(
                [sys.executable, "manage.py", "import_elexon", "--dataset", "wind"],
                timeout=180,
                check=False,
            )
            if result.returncode:
                self.stderr.write("Import failed; inspect ImportRun and source status")
            stop.wait(int(os.getenv("IMPORT_INTERVAL_SECONDS", "300")))

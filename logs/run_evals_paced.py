"""Run the unchanged eval runner with at most 10 model requests/minute.

Pacing is outside the agent and applies equally to agent and judge calls.
No retries, grading changes, or dataset changes are made.
"""
import runpy
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'evals'))
from providers import Provider

original_complete = Provider.complete
last_request = None


def paced_complete(self, messages, schemas):
    global last_request
    if last_request is not None:
        time.sleep(max(0, 6 - (time.monotonic() - last_request)))
    last_request = time.monotonic()
    return original_complete(self, messages, schemas)


Provider.complete = paced_complete
runpy.run_path(str(ROOT / 'evals' / 'run_evals.py'), run_name='__main__')

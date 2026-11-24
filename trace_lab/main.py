"""uvicorn trace_lab.main:app"""

from trace_lab.app import create_app
from trace_lab.telemetry import build_provider

app = create_app(build_provider())

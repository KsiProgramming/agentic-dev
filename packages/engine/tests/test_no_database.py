import subprocess
import sys


def test_engine_does_not_import_a_database_driver() -> None:
    """The engine writes events through an `EventSink`; database code lives in `agentic_store`."""
    code = (
        "import sys, agentic_engine.events, agentic_engine.graph; "
        "print(sorted(m for m in ('sqlalchemy', 'asyncpg') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"

import os
import tempfile

# Isolated data directory for API tests (must be set before the app is imported).
os.environ.setdefault("SMT_DATA_DIR", tempfile.mkdtemp(prefix="smt-test-"))

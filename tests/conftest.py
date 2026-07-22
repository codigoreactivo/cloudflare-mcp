import sys
from pathlib import Path

# The cfmcp package lives at the repo root (repo_root/cfmcp/...), so tests need
# the repo root importable regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

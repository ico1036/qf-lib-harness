"""Make `import alpha_lab` resolve when pytest is run from any cwd."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]   # repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

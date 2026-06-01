"""Make `import alpha_lab` resolve when pytest is run from any cwd."""
import sys
from pathlib import Path

_RESEARCH_ROOT = Path(__file__).resolve().parents[2]   # research/us_universe/
if str(_RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_ROOT))

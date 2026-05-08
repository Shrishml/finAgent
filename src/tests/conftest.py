import sys
from pathlib import Path

# Ensure finagent package is importable from any test subfolder
sys.path.insert(0, str(Path(__file__).parent.parent))

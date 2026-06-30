"""Root conftest.py to configure pytest with src layout."""
import sys
import os

# Add src directory to Python path for imports
src_dir = os.path.join(os.path.dirname(__file__), "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

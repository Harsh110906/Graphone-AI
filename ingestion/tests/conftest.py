"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

# Add ingestion root to path so 'from src...' imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

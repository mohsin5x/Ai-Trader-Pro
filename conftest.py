"""
conftest.py
============
Pytest configuration for AI Trader Pro test suite.

Sets the project root in sys.path so all imports resolve correctly
from the tests/ directory without needing to install the package.
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

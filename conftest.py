"""
conftest.py — pytest configuration file loaded automatically before any test.

Why this file exists:
----------------------
When pytest runs, Python needs to know where to look for modules.
Without this, `from agents.orchestrator import ...` inside tests would
raise ModuleNotFoundError because Python doesn't know the root of the project.

Adding the project root to sys.path here fixes that for ALL tests automatically.
This is the standard pattern for src-layout or flat-layout Python projects.
"""

import sys
import os

# Add the project root directory to sys.path so all module imports work
sys.path.insert(0, os.path.dirname(__file__))

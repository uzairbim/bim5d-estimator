"""Tests never touch your own data folder (~/BIM5D): they get a fresh one."""
import os
import tempfile

os.environ["BIM5D_HOME"] = tempfile.mkdtemp(prefix="bim5d-test-home-")

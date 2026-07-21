#!/usr/bin/env python3
"""Test runner for MinecraftML brain tests."""

import sys
import os
import unittest

# Add brain directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'brain'))

# Import test modules
from tests.test_phase1 import ProtocolTests

def run_tests():
    """Run all tests."""
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(ProtocolTests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
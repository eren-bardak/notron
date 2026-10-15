"""Run backend unit tests with network access and dotenv loading disabled."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def main():
    tests = Path(__file__).resolve().parents[1] / "tests"
    with patch("dotenv.load_dotenv", return_value=False), \
         patch("socket.socket.connect", side_effect=RuntimeError("Network disabled in offline tests")), \
         patch("socket.socket.connect_ex", side_effect=RuntimeError("Network disabled in offline tests")):
        suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

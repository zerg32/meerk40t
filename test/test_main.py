import subprocess
import sys
import unittest


class TestMainStartup(unittest.TestCase):
    def test_import_without_stderr(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr = None; import meerk40t.main",
            ],
            stdout=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from unittest.mock import patch

from meerk40t.camera import composite_bed_photo_on_device_dc


class TestOptionalCamera(unittest.TestCase):
    def test_bed_photo_without_opencv(self):
        sys.modules.pop("meerk40t.camera.camera", None)
        with patch.dict(sys.modules, {"cv2": None}):
            result = composite_bed_photo_on_device_dc(None, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

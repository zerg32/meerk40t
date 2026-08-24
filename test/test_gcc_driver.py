import unittest

from PIL import Image

from meerk40t.core.cutcode.linecut import LineCut
from meerk40t.core.cutcode.rastercut import RasterCut
from meerk40t.core.laserjob import LaserJob
from meerk40t.gcc.driver import GCCDriver
from meerk40t.gcc.gccjob import ESC
from meerk40t.svgelements import Color


class GCCServiceStub:
    max_vector_speed = 100.0
    max_raster_speed = 100.0
    raster_dpi = 508
    ppi_enabled = True
    ppi = 400
    immediate_start = False
    legacy_header_value = 152500
    park_x = "617.3mm"
    park_y = "5mm"
    air_assist = False


def make_raster(settings=None):
    image = Image.new("L", (12, 2), 255)
    image.putdata([255] * 8 + [0] * 4 + [255] * 12)
    return RasterCut(
        image=image,
        offset_x=1200,
        offset_y=800,
        step_x=2,
        step_y=2,
        horizontal=True,
        bidirectional=True,
        start_minimum_y=True,
        settings=settings or {"speed": 50, "power": 600},
        color=Color("black"),
    )


class TestGCCDriver(unittest.TestCase):
    def build(self, cuts, outline):
        output = []
        driver = GCCDriver(GCCServiceStub(), output.append)
        job = LaserJob("capture.prn", [], driver=driver, outline=outline)
        driver.job_start(job)
        for cut in cuts:
            driver.plot(cut)
        driver.plot_start()
        driver.job_finish(job)
        self.assertEqual(len(output), 1)
        return output[0]

    def test_vector_uses_color_pen_and_relative_geometry(self):
        settings = {"speed": 50, "power": 200}
        line = LineCut(
            (400, 400),
            (800, 400),
            settings=settings,
            color=Color("red"),
        )
        data = self.build([line], [(400, 400), (800, 400)])
        self.assertIn(ESC + b"!v64V" + b"0500" + b"0500", data)
        self.assertIn(
            ESC + b"!m0S" + ESC + b"!s0S" + ESC + b"*r1A" + ESC + b"*rC",
            data,
        )
        self.assertIn(ESC + b"%1B;PR;SP2;PD400,0;PU;ZS0;RS0;", data)

    def test_mixed_job_writes_raster_then_color_vectors(self):
        raster = make_raster()
        red = LineCut(
            (400, 400),
            (800, 400),
            settings={"speed": 25, "power": 200},
            color=Color("red"),
        )
        blue = LineCut(
            (2000, 1200),
            (2400, 1200),
            settings={
                "speed": 75,
                "power": 800,
                "gcc_ppi": 800,
                "coolant": 1,
            },
            color=Color("blue"),
        )
        data = self.build(
            [red, raster, blue],
            [(400, 400), (2400, 400), (2400, 1200), (400, 1200)],
        )

        raster_start = data.index(ESC + b"*r1A")
        hpgl_start = data.index(ESC + b"%1B")
        self.assertLess(raster_start, hpgl_start)
        self.assertIn(
            ESC
            + b"*p1000A"
            + ESC
            + b"*p400B"
            + ESC
            + b"*p-400C"
            + ESC
            + b"*p-200D",
            data,
        )
        self.assertIn(ESC + b"*b8W\x01\x00\x01\xf0\x06\x00\x00\x00", data)
        self.assertIn(
            ESC
            + b"%1B;PR;PU-800,402;SP2;PD400,0;"
            + b"PU1200,-800;SP5;PD400,0;",
            data,
        )
        self.assertIn(
            ESC + b"!v16D" + b"\x00" * 4 + b"\x02" + b"\x00" * 11,
            data,
        )

    def test_rejects_unsupported_raster_direction(self):
        raster = make_raster()
        raster.horizontal = False
        driver = GCCDriver(GCCServiceStub())
        job = LaserJob("unsupported.prn", [], driver=driver)
        driver.job_start(job)
        driver.plot(raster)
        with self.assertRaisesRegex(ValueError, "horizontal raster"):
            driver.job_finish(job)

    def test_transport_receives_complete_job_and_name(self):
        class Transport:
            def __init__(self):
                self.calls = []

            def submit(self, data, name):
                self.calls.append((data, name))

        transport = Transport()
        driver = GCCDriver(GCCServiceStub(), transport=transport)
        job = LaserJob("C:/jobs/test gcc.prn", [], driver=driver)
        driver.job_start(job)
        driver.plot(
            LineCut(
                (400, 400),
                (800, 400),
                settings={"speed": 50, "power": 200},
                color=Color("red"),
            )
        )
        driver.job_finish(job)

        self.assertEqual(len(transport.calls), 1)
        data, name = transport.calls[0]
        self.assertTrue(data.startswith(b"\x1b%-12345X"))
        self.assertEqual(name, "test gcc.prn")

    def test_file_and_transport_receive_identical_bytes(self):
        class Transport:
            def __init__(self):
                self.data = None

            def submit(self, data, name):
                self.data = data

        file_data = []
        transport = Transport()
        driver = GCCDriver(
            GCCServiceStub(), output=file_data.append, transport=transport
        )
        job = LaserJob("same.prn", [], driver=driver)
        driver.job_start(job)
        driver.plot(
            LineCut(
                (400, 400),
                (800, 400),
                settings={"speed": 50, "power": 200},
                color=Color("red"),
            )
        )
        driver.job_finish(job)
        self.assertEqual(file_data, [transport.data])

    def test_transport_failure_clears_driver_state(self):
        class Transport:
            @staticmethod
            def submit(data, name):
                raise OSError("printer offline")

        driver = GCCDriver(GCCServiceStub(), transport=Transport())
        job = LaserJob("failed.prn", [], driver=driver)
        driver.job_start(job)
        driver.plot(
            LineCut(
                (400, 400),
                (800, 400),
                settings={"speed": 50, "power": 200},
                color=Color("red"),
            )
        )
        with self.assertRaisesRegex(OSError, "printer offline"):
            driver.job_finish(job)
        self.assertEqual(driver.queue, [])
        self.assertIsNone(driver._job)


if __name__ == "__main__":
    unittest.main()

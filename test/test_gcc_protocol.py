import unittest

from meerk40t.gcc.gccjob import (
    ESC,
    GCCJob,
    d4,
    d4_table,
    encode_job_name,
    gcc_rle_encode,
    pack_monochrome_row,
    transfer_width,
)


class TestGCCProtocolHelpers(unittest.TestCase):
    def test_d4_values_and_table(self):
        self.assertEqual(d4(0), b"0000")
        self.assertEqual(d4(250), b"0250")
        self.assertEqual(d4(500), b"0500")
        self.assertEqual(d4(1000), b"1000")
        table = d4_table(range(0, 16))
        self.assertEqual(len(table), 64)
        self.assertEqual(
            table,
            b"".join(("%04d" % n).encode("ascii") for n in range(16)),
        )
        with self.assertRaises(ValueError):
            d4(1001)
        with self.assertRaises(ValueError):
            d4_table([500] * 15)

    def test_job_name_utf8_and_safe_ellipsis(self):
        self.assertEqual(encode_job_name("laser"), b"laser")
        name = encode_job_name("a" * 28 + "\u20ac" + "tail")
        self.assertLessEqual(len(name), 32)
        self.assertTrue(name.endswith(b"..."))
        name.decode("utf-8")
        self.assertEqual(
            encode_job_name("C08-mixed-vector-raster-vector-extra"),
            b"C08-mixed-vector-raster-vecto...",
        )

    def test_pack_msb_first_and_pad_to_64_pixels(self):
        self.assertEqual(transfer_width(0), 0)
        self.assertEqual(transfer_width(1), 64)
        self.assertEqual(transfer_width(64), 64)
        self.assertEqual(transfer_width(65), 128)
        packed = pack_monochrome_row([1, 0, 1, 0, 0, 0, 0, 1])
        self.assertEqual(packed, b"\xa1" + b"\x00" * 7)
        with self.assertRaises(ValueError):
            pack_monochrome_row([255])

    def test_rle_boundaries_and_binary_values(self):
        self.assertEqual(gcc_rle_encode(b""), b"\x00\x00")
        self.assertEqual(
            gcc_rle_encode(b"\x00\x1b\xff"),
            b"\x01\x00\x01\x1b\x01\xff\x00\x00",
        )
        self.assertEqual(gcc_rle_encode(b"x" * 128), b"\x80x\x00\x00")
        self.assertEqual(gcc_rle_encode(b"x" * 129), b"\x80x\x01x\x00\x00")

    def test_exact_c06_packed_and_compressed_rows(self):
        row_0 = pack_monochrome_row([1] * 12)
        row_1 = pack_monochrome_row([0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1])
        self.assertEqual(row_0, b"\xff\xf0" + b"\x00" * 6)
        self.assertEqual(row_1, b"\x3c\x30" + b"\x00" * 6)
        self.assertEqual(
            gcc_rle_encode(row_0), b"\x01\xff\x01\xf0\x06\x00\x00\x00"
        )
        self.assertEqual(
            gcc_rle_encode(row_1), b"\x01\x3c\x01\x30\x06\x00\x00\x00"
        )


class TestGCCJob(unittest.TestCase):
    def test_original_driver_envelope_and_pen_tables(self):
        job = GCCJob()
        job.begin_job(
            b"", settings={"speed": 500, "power": 600, "ppi": 400}, dpi=508
        )
        expected_start = b"\x1b%-12345X\x1bE\x1b!r0A\x1b!m0N"
        self.assertTrue(job.getvalue().startswith(expected_start))
        table_fragment = (
            ESC + b"!v16R" + b"1" * 16
            + ESC + b"!v64I" + b"0400" * 16
            + ESC + b"!v64V" + b"0500" * 16
            + ESC + b"!v64P" + b"0600" * 16
            + ESC + b"!v16D" + b"\x00" * 16
        )
        self.assertIn(table_fragment, job.getvalue())
        self.assertTrue(
            job.getvalue().endswith(
                ESC
                + b"!h152500T"
                + ESC
                + b"*t508R"
                + ESC
                + b"&u508D"
                + ESC
                + b"!r0N"
                + ESC
                + b"!r0E"
                + ESC
                + b"%1A"
            )
        )

    def test_per_pen_settings_and_air_slots(self):
        pens = [dict(speed=500, power=500, ppi=400) for _ in range(16)]
        pens[1].update(speed=250, power=200)
        pens[4].update(speed=750, power=800, ppi=800, air=True)
        job = GCCJob()
        job.write_settings(pens)
        data = job.getvalue()
        self.assertIn(ESC + b"!v64V" + b"0500" + b"0250", data)
        self.assertIn(ESC + b"!v64I" + b"0400" * 4 + b"0800", data)
        self.assertTrue(
            data.endswith(
                ESC + b"!v16D" + b"\x00" * 4 + b"\x02" + b"\x00" * 11
            )
        )

    def test_vector_relative_commands(self):
        job = GCCJob()
        job.begin_vector(pen=2)
        job.vector_move(400, 0)
        job.vector_cut(400, 200)
        job.vector_cut_relative(400, 0)
        self.assertTrue(
            job.getvalue().endswith(
                ESC + b"%1B;PR;SP2;PU400,0;PD0,-200;PD400,0;"
            )
        )

    def test_immediate_start_policy_flows_from_job_envelope(self):
        job = GCCJob()
        job.begin_job(b"immediate", immediate=True)
        job.begin_vector()
        self.assertIn(ESC + b"!m1S" + ESC + b"!s0S", job.getvalue())

    def test_exact_c06_raster_frame_and_rows(self):
        job = GCCJob()
        job.write_raster_frame(12, 2, 400, 600)
        job.begin_raster(2, 12, speed=500, power=600, dpi=508)
        job.write_raster_row([1] * 12)
        job.write_raster_row([0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1])
        expected = (
            ESC
            + b"*p12A"
            + ESC
            + b"*p2B"
            + ESC
            + b"*p-0C"
            + ESC
            + b"*p-0D"
            + ESC
            + b"*p400E"
            + ESC
            + b"*p600F"
            + ESC
            + b"*p400X"
            + ESC
            + b"*p600Y"
            + ESC
            + b"*t1Y"
            + ESC
            + b"!r0B"
            + ESC
            + b"!r1M"
            + ESC
            + b"!r500I"
            + ESC
            + b"!r500K"
            + ESC
            + b"!r600P"
            + ESC
            + b"*t508R"
            + ESC
            + b"&u508D"
            + ESC
            + b"!m0S"
            + ESC
            + b"!s0S"
            + ESC
            + b"*r2T"
            + ESC
            + b"*r64S"
            + ESC
            + b"*b1M"
            + ESC
            + b"*r1A"
            + ESC
            + b"*b8W\x01\xff\x01\xf0\x06\x00\x00\x00"
            + ESC
            + b"*b8W\x01\x3c\x01\x30\x06\x00\x00\x00"
        )
        self.assertEqual(job.getvalue(), expected)

    def test_raster_band_transition_repeats_band_setup_not_job_start(self):
        job = GCCJob()
        job.begin_raster(2, 12, 500, 600)
        job.end_raster()
        job.move_raster_cursor(0, 399)
        job.begin_raster(2, 12, 500, 600)
        data = job.getvalue()
        self.assertIn(
            ESC + b"*rC" + ESC + b"%1A" + ESC + b"*p+0X" + ESC + b"*p+399Y",
            data,
        )
        self.assertEqual(data.count(ESC + b"!m0S"), 1)
        self.assertEqual(data.count(ESC + b"*t1Y"), 2)

    def test_trailer_has_configurable_raw_park(self):
        park = ESC + b"*p+11946X" + ESC + b"*p-501Y"
        job = GCCJob()
        job.finish_job(park=park)
        self.assertEqual(
            job.getvalue(),
            ESC + b"%1A" + park + ESC + b"*r1A" + ESC + b"*rC"
            + ESC + b"E" + ESC + b"%-12345X",
        )
        with self.assertRaises(TypeError):
            GCCJob().finish_job(park=(1, 2))


if __name__ == "__main__":
    unittest.main()

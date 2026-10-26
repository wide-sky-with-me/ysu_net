"""Pure byte-envelope tests; no rendering, binaries, or OS icon APIs."""
import importlib.util
from pathlib import Path
import struct
import unittest

SPEC = importlib.util.spec_from_file_location('tauri_icon_check', Path(__file__).parents[1] / 'packaging/tauri_icon_check.py')
icons = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(icons)


class IconEnvelopeTests(unittest.TestCase):
    def test_png_requires_square_bounded_ihdr(self):
        header = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR'
        self.assertEqual(icons.png_size(header + struct.pack('>II', 32, 32)), 32)
        for data in (b'', header + struct.pack('>II', 0, 0), header + struct.pack('>II', 32, 16), header + struct.pack('>II', 8192, 8192)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                icons.png_size(data)

    def test_ico_requires_small_and_large_bounded_images(self):
        directory = b''
        for index, size in enumerate((16, 32, 256)):
            directory += struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, 1, 54 + index)
        good = struct.pack('<HHH', 0, 1, 3) + directory + b'abc'
        self.assertEqual(icons.ico_sizes(good), [16, 32, 256])
        for data in (b'', good[:-1], struct.pack('<HHH', 0, 2, 3) + good[6:], struct.pack('<HHH', 0, 1, 1) + good[6:]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                icons.ico_sizes(data)

# SPDX-License-Identifier: GPL-2.0-or-later
import ctypes
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

class Spectrum(unittest.TestCase):
    def test_silence_and_frequency_bands_for_pcm_formats(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / 'spectrum.so'
            subprocess.run(['cc','-shared','-fPIC','-o',str(library),str(root/'cmuxr_spectrum.c'),'-lm','-pthread'],check=True)
            api = ctypes.CDLL(str(library))
            api.cmuxr_spectrum_feed.argtypes = [ctypes.c_char_p,ctypes.c_int,ctypes.c_uint]
            for bits,channels,bigendian,signed in [(16,1,False,True),(24,2,True,True),(32,2,False,True),(8,1,False,False)]:
                sf = channels << 24 | bits << 18 | 44100 << 2 | int(signed) << 1 | int(bigendian)
                def feed(tone):
                    data = bytearray()
                    midpoint = 1 << (bits-1)
                    for i in range(1024):
                        value = int(midpoint*.8*math.sin(2*math.pi*60*1.42**8*i/44100)) if tone else 0
                        if not signed:
                            value += midpoint
                        sample = value.to_bytes(bits//8,'big' if bigendian else 'little',signed=signed)
                        data.extend(sample*channels)
                    api.cmuxr_spectrum_feed(bytes(data),len(data),sf)
                    bands = (ctypes.c_float*16)()
                    api.cmuxr_spectrum_get(bands)
                    return list(bands)
                with self.subTest(bits=bits,channels=channels,bigendian=bigendian):
                    self.assertEqual(feed(False),[0.]*16)
                    bands = feed(True)
                    self.assertEqual(max(range(16),key=lambda n:bands[n]),8)
                    self.assertTrue(all(math.isfinite(x) and 0<=x<=1 for x in bands))

if __name__=='__main__':
    unittest.main()

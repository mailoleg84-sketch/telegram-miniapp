"""_looks_like_audio: magic-bytes гейт перед Whisper (анти cost-amplification)."""
import unittest

from webapp.routes_chat_voice import _looks_like_audio


class AudioMagicTests(unittest.TestCase):
    def test_accepts_known_audio(self):
        cases = {
            "webm": b"\x1a\x45\xdf\xa3" + b"\x00" * 20,
            "ogg": b"OggS" + b"\x00" * 20,
            "id3_mp3": b"ID3" + b"\x00" * 20,
            "mp3_frame": b"\xff\xfb" + b"\x00" * 20,
            "wav": b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 8,
            "mp4_m4a": b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 8,
            "aiff": b"FORM" + b"\x00" * 20,
            "flac": b"fLaC" + b"\x00" * 20,
        }
        for name, buf in cases.items():
            self.assertTrue(_looks_like_audio(buf), name)

    def test_rejects_non_audio(self):
        for buf in (b"GIF89a" + b"\x00" * 20, b"<html><body>" + b"\x00" * 8,
                    b'{"json":1}   ', b"\x89PNG\r\n\x1a\n" + b"\x00" * 8):
            self.assertFalse(_looks_like_audio(buf), buf[:8])

    def test_rejects_too_short(self):
        self.assertFalse(_looks_like_audio(b""))
        self.assertFalse(_looks_like_audio(b"OggS"))  # < 12 байт


if __name__ == "__main__":
    unittest.main()

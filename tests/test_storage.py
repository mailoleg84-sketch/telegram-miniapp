"""Тесты слоя хранилища кэшей (webapp/storage.py)."""
import os
import tempfile
import unittest
from pathlib import Path

from webapp.storage import LocalDiskStorage, evict_dir, _resolve_root


class LocalDiskStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_read_exists_delete_roundtrip(self):
        store = LocalDiskStorage(self.dir / "sub")  # вложенный каталог создастся
        self.assertFalse(store.exists("a.bin"))
        store.write("a.bin", b"hello")
        self.assertTrue(store.exists("a.bin"))
        self.assertEqual(store.read("a.bin"), b"hello")
        store.delete("a.bin")
        self.assertFalse(store.exists("a.bin"))
        # Повторное удаление не падает.
        store.delete("a.bin")


class EvictDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_evict_keeps_newest_and_exempts_none_markers(self):
        for i in range(5):
            p = self.dir / f"f{i}.bin"
            p.write_bytes(b"x")
            os.utime(p, (1000 + i, 1000 + i))  # f0 — самый старый, f4 — самый новый
        none_marker = self.dir / "marker.none"
        none_marker.write_bytes(b"1")
        os.utime(none_marker, (1, 1))  # формально старейший, но .none не выселяем

        evict_dir(self.dir, max_files=2)

        remaining = sorted(p.name for p in self.dir.glob("*") if not p.name.endswith(".none"))
        self.assertEqual(remaining, ["f3.bin", "f4.bin"])  # оставлены 2 самых новых
        self.assertTrue(none_marker.is_file())  # маркер не тронут

    def test_evict_noop_when_under_limit(self):
        (self.dir / "a.bin").write_bytes(b"x")
        evict_dir(self.dir, max_files=10)
        self.assertTrue((self.dir / "a.bin").is_file())

    def test_evict_disabled_when_max_zero(self):
        for i in range(3):
            (self.dir / f"f{i}.bin").write_bytes(b"x")
        evict_dir(self.dir, max_files=0)
        self.assertEqual(len(list(self.dir.glob("*.bin"))), 3)

    def test_local_storage_evict_uses_base_dir(self):
        store = LocalDiskStorage(self.dir)
        for i in range(4):
            p = self.dir / f"f{i}.bin"
            p.write_bytes(b"x")
            os.utime(p, (2000 + i, 2000 + i))
        store.evict(max_files=1)
        remaining = sorted(p.name for p in self.dir.glob("*"))
        self.assertEqual(remaining, ["f3.bin"])


class ResolveRootTests(unittest.TestCase):
    def test_env_override_and_default(self):
        old = os.environ.get("CACHE_ROOT")
        try:
            os.environ["CACHE_ROOT"] = "/tmp/custom-cache-root"
            self.assertEqual(_resolve_root(), Path("/tmp/custom-cache-root"))
            os.environ.pop("CACHE_ROOT", None)
            self.assertTrue(str(_resolve_root()).replace("\\", "/").endswith("static/generated"))
        finally:
            if old is None:
                os.environ.pop("CACHE_ROOT", None)
            else:
                os.environ["CACHE_ROOT"] = old


if __name__ == "__main__":
    unittest.main()

"""Тесты слоя хранилища кэшей (webapp/storage.py)."""
import os
import tempfile
import unittest
from pathlib import Path

from webapp.storage import (
    LocalDiskStorage, S3Storage, evict_dir, make_storage, _resolve_root,
)


class LocalDiskStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_write_read_exists_delete_roundtrip(self):
        store = LocalDiskStorage(self.dir / "sub")  # вложенный каталог создастся
        self.assertFalse(await store.exists("a.bin"))
        await store.write("a.bin", b"hello")
        self.assertTrue(await store.exists("a.bin"))
        self.assertEqual(await store.read("a.bin"), b"hello")
        await store.delete("a.bin")
        self.assertFalse(await store.exists("a.bin"))
        # Повторное удаление не падает.
        await store.delete("a.bin")


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


class MakeStorageFactoryTests(unittest.TestCase):
    R2_ENV = {
        "R2_BUCKET": "tutor-cache",
        "R2_ENDPOINT_URL": "https://acc.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
    }

    def test_local_by_default(self):
        for k in self.R2_ENV:
            os.environ.pop(k, None)
        store = make_storage("vocabulary")
        self.assertIsInstance(store, LocalDiskStorage)

    def test_s3_when_r2_configured(self):
        old = {k: os.environ.get(k) for k in self.R2_ENV}
        try:
            os.environ.update(self.R2_ENV)
            store = make_storage("vocabulary")
            self.assertIsInstance(store, S3Storage)
            self.assertEqual(store.bucket, "tutor-cache")
            self.assertEqual(store.prefix, "vocabulary")
            self.assertEqual(store.endpoint_url, "https://acc.r2.cloudflarestorage.com")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_s3_key_prefixing(self):
        s = S3Storage("b", "vocabulary", "https://e", "ak", "sk")
        self.assertEqual(s._key("abc.png"), "vocabulary/abc.png")
        s2 = S3Storage("b", "", "https://e", "ak", "sk")
        self.assertEqual(s2._key("abc.png"), "abc.png")


if __name__ == "__main__":
    unittest.main()

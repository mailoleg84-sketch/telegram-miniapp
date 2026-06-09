"""Слой хранилища файловых кэшей (картинки слов, озвучка, бесплатные фото).

Два backend'а за единым async-интерфейсом (`exists/read/write/delete`):

- ``LocalDiskStorage`` — локальный диск. Корень — переменная ``CACHE_ROOT``
  (по умолчанию ``<static>/generated``). На Render это эфемерный диск (стирается
  при деплое); можно указать на persistent disk.
- ``S3Storage`` — S3-совместимое облако (Cloudflare R2). Включается, когда заданы
  переменные ``R2_*`` (см. ``_r2_configured``). Тогда кэши переживают деплой и не
  привязаны к одному инстансу. Раздаём прокси-методом через свой сервер, поэтому
  бакет может быть приватным.

Выбор backend'а — в ``make_storage`` по env. Код вызова (server.py) работает с
любым через одинаковый async-интерфейс.
"""
import os
from pathlib import Path

_DEFAULT_ROOT = Path(__file__).parent / "static" / "generated"


def _resolve_root() -> Path:
    """Корень кэшей из CACHE_ROOT (env), иначе исторический <static>/generated."""
    raw = os.getenv("CACHE_ROOT", "").strip().strip('"').strip("'")
    return Path(raw) if raw else _DEFAULT_ROOT


CACHE_ROOT = _resolve_root()


def evict_dir(directory, max_files: int, exempt_suffix: str = ".none") -> None:
    """Удаляет самые старые файлы каталога, если их больше max_files (локально).

    Файлы с суффиксом `exempt_suffix` (крошечные маркеры «картинки нет») не
    учитываются и не удаляются. Бросает OSError наверх — логирование делает
    вызывающий слой. Для S3 ретенция настраивается lifecycle-политикой бакета.
    """
    if max_files <= 0:
        return
    directory = Path(directory)
    files = [
        p for p in directory.glob("*")
        if p.is_file() and not (exempt_suffix and p.name.endswith(exempt_suffix))
    ]
    if len(files) <= max_files:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    for path in files[: len(files) - max_files]:
        path.unlink(missing_ok=True)


class LocalDiskStorage:
    """Файловый кэш в каталоге base_dir. Ключ = имя файла (без подкаталогов)."""

    backend = "local"

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def full_path(self, name: str) -> Path:
        return self.base_dir / name

    async def exists(self, name: str) -> bool:
        return self.full_path(name).is_file()

    async def read(self, name: str) -> bytes:
        return self.full_path(name).read_bytes()

    async def write(self, name: str, data: bytes) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.full_path(name).write_bytes(data)

    async def delete(self, name: str) -> None:
        self.full_path(name).unlink(missing_ok=True)

    def evict(self, max_files: int, exempt_suffix: str = ".none") -> None:
        evict_dir(self.base_dir, max_files, exempt_suffix=exempt_suffix)


class S3Storage:
    """Хранилище в S3-совместимом облаке (Cloudflare R2) поверх aioboto3.

    Тот же async-интерфейс, что у LocalDiskStorage. aioboto3 импортируется лениво
    (только при реальной операции), чтобы локально/без R2 зависимость не требовалась.
    """

    backend = "s3"

    def __init__(self, bucket: str, prefix: str, endpoint_url: str,
                 access_key: str, secret_key: str, region: str = "auto"):
        self.bucket = bucket
        self.prefix = (prefix or "").strip("/")
        self.endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self.region = region or "auto"

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def _client(self):
        import aioboto3  # ленивый импорт: нужен только когда R2 включён
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self.region,
        )

    async def exists(self, name: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self.bucket, Key=self._key(name))
                return True
            except Exception:  # noqa: BLE001 — нет объекта / ошибка доступа -> считаем «нет»
                return False

    async def read(self, name: str) -> bytes:
        async with self._client() as s3:
            resp = await s3.get_object(Bucket=self.bucket, Key=self._key(name))
            async with resp["Body"] as body:
                return await body.read()

    async def write(self, name: str, data: bytes) -> None:
        async with self._client() as s3:
            await s3.put_object(Bucket=self.bucket, Key=self._key(name), Body=data)

    async def delete(self, name: str) -> None:
        async with self._client() as s3:
            try:
                await s3.delete_object(Bucket=self.bucket, Key=self._key(name))
            except Exception:  # noqa: BLE001
                pass

    def evict(self, max_files: int, exempt_suffix: str = ".none") -> None:
        # На S3 ретенцию делает lifecycle-политика бакета — здесь no-op.
        return None


def _r2_endpoint() -> str:
    raw = os.getenv("R2_ENDPOINT_URL", "").strip().strip('"').strip("'")
    if raw:
        return raw
    account = os.getenv("R2_ACCOUNT_ID", "").strip().strip('"').strip("'")
    return f"https://{account}.r2.cloudflarestorage.com" if account else ""


def _r2_configured() -> bool:
    return bool(
        os.getenv("R2_BUCKET")
        and _r2_endpoint()
        and os.getenv("R2_ACCESS_KEY_ID")
        and os.getenv("R2_SECRET_ACCESS_KEY")
    )


def make_storage(subdir: str):
    """Возвращает backend для подкаталога/префикса: S3 (R2) если настроен, иначе диск."""
    if _r2_configured():
        return S3Storage(
            bucket=os.getenv("R2_BUCKET", "").strip(),
            prefix=subdir,
            endpoint_url=_r2_endpoint(),
            access_key=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
            secret_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
            region=os.getenv("R2_REGION", "auto").strip() or "auto",
        )
    return LocalDiskStorage(CACHE_ROOT / subdir)


# Все три файловых кэша — через фабрику: S3/R2 если задан (переживают деплой),
# иначе локальный диск. Картинки слов — самый дорогой кэш (повторная генерация =
# деньги OpenAI); озвучка экономит latency на первом проигрывании после деплоя;
# фото Pixabay экономит квоту запросов и тоже грузится мгновенно из кэша.
vocab_image_storage = make_storage("vocabulary")
word_audio_storage = make_storage("audio")
vocab_photo_storage = make_storage("vocab_photos")

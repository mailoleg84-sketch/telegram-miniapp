"""Слой хранилища файловых кэшей (картинки слов, озвучка, бесплатные фото).

Сейчас единственный backend — локальный диск (`LocalDiskStorage`). Корень кэша
задаётся переменной окружения `CACHE_ROOT` (по умолчанию `<static>/generated`,
как было исторически).

Зачем: на Render диск эфемерный и стирается при каждом деплое — сгенерированные
платно картинки и озвучка теряются и создаются заново. Если указать `CACHE_ROOT`
на смонтированный **persistent disk** Render, кэши переживут деплой.

Расширение на облако (S3 / Cloudflare R2) — отдельным шагом: достаточно
реализовать класс с тем же интерфейсом (`exists/read/write/delete/evict`) и
вернуть его из фабрик ниже. Код вызова в `server.py` менять не придётся.
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
    """Удаляет самые старые файлы каталога, если их больше max_files.

    Файлы с суффиксом `exempt_suffix` (крошечные маркеры «картинки нет») не
    учитываются и не удаляются. Бросает OSError наверх — логирование делает
    вызывающий слой.
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

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def full_path(self, name: str) -> Path:
        return self.base_dir / name

    def exists(self, name: str) -> bool:
        return self.full_path(name).is_file()

    def read(self, name: str) -> bytes:
        return self.full_path(name).read_bytes()

    def write(self, name: str, data: bytes) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.full_path(name).write_bytes(data)

    def delete(self, name: str) -> None:
        self.full_path(name).unlink(missing_ok=True)

    def evict(self, max_files: int, exempt_suffix: str = ".none") -> None:
        evict_dir(self.base_dir, max_files, exempt_suffix=exempt_suffix)


# Готовые хранилища под три кэша (единый источник истины о расположении кэшей).
vocab_image_storage = LocalDiskStorage(CACHE_ROOT / "vocabulary")
word_audio_storage = LocalDiskStorage(CACHE_ROOT / "audio")
vocab_photo_storage = LocalDiskStorage(CACHE_ROOT / "vocab_photos")

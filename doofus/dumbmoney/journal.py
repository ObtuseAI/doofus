"""Minimal tamper-evident append-only JSONL journal."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator

from .canonical import canonical_json, content_hash


class JournalIntegrityError(RuntimeError):
    pass


class DuplicateRecordError(ValueError):
    pass


class HashChainJournal:
    """Append-only application API with a hash chain and fsync durability.

    The filesystem can still be altered by its owner.  Verification makes such
    alteration evident; no claim of hardware immutability is made.
    """

    def __init__(self, path: Path | str, *, stream_id: str) -> None:
        self.path = Path(path)
        self.stream_id = stream_id
        self._lock = threading.RLock()
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")

    @staticmethod
    def _record_material(record: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in record.items() if key != "record_hash"}

    @staticmethod
    @contextmanager
    def _lock_file(handle: BinaryIO) -> Iterator[None]:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 30.0
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("journal interprocess lock timed out") from exc
                    time.sleep(0.01)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]

    @contextmanager
    def _interprocess_lock(self) -> Iterator[None]:
        """Serialize the complete verify/check/append transaction."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            with self._lock_file(handle):
                yield

    def _read_verified_locked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw_bytes = self.path.read_bytes()
        if raw_bytes and not raw_bytes.endswith(b"\n"):
            raise JournalIntegrityError("journal has a partial trailing record")
        records: list[dict[str, Any]] = []
        previous_hash: str | None = None
        for line_number, raw_bytes_line in enumerate(raw_bytes.splitlines(), start=1):
            if not raw_bytes_line:
                raise JournalIntegrityError(f"blank record at line {line_number}")
            try:
                raw = raw_bytes_line.decode("utf-8")
                record = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalIntegrityError(f"invalid JSON at line {line_number}") from exc
            if record.get("schema_id") != "dumbmoney.append_record.v1":
                raise JournalIntegrityError(f"unknown journal schema at line {line_number}")
            if record.get("stream_id") != self.stream_id:
                raise JournalIntegrityError(f"stream mismatch at line {line_number}")
            if record.get("sequence") != line_number:
                raise JournalIntegrityError(f"sequence mismatch at line {line_number}")
            if record.get("previous_record_hash") != previous_hash:
                raise JournalIntegrityError(f"broken hash chain at line {line_number}")
            if record.get("payload_hash") != content_hash(record.get("payload")):
                raise JournalIntegrityError(f"payload hash mismatch at line {line_number}")
            expected = content_hash(self._record_material(record))
            if record.get("record_hash") != expected:
                raise JournalIntegrityError(f"record hash mismatch at line {line_number}")
            if canonical_json(record) != raw:
                raise JournalIntegrityError(f"non-canonical record at line {line_number}")
            previous_hash = record["record_hash"]
            records.append(record)
        return records

    def read_verified(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._interprocess_lock():
                return self._read_verified_locked()

    def append(
        self,
        payload: dict[str, Any],
        *,
        unique_key: str | None = None,
        unique_value: str | None = None,
        validate_existing: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            with self._interprocess_lock():
                records = self._read_verified_locked()
                if validate_existing is not None:
                    validate_existing(records)
                if unique_key is not None:
                    for existing in records:
                        if existing["payload"].get(unique_key) == unique_value:
                            raise DuplicateRecordError(
                                f"duplicate {unique_key}: {unique_value}"
                            )
                material: dict[str, Any] = {
                    "schema_id": "dumbmoney.append_record.v1",
                    "stream_id": self.stream_id,
                    "sequence": len(records) + 1,
                    "previous_record_hash": records[-1]["record_hash"] if records else None,
                    "payload_hash": content_hash(payload),
                    "payload": payload,
                }
                record = {**material, "record_hash": content_hash(material)}
                self.path.parent.mkdir(parents=True, exist_ok=True)
                serialized = f"{canonical_json(record)}\n".encode("utf-8")
                with self.path.open("ab") as handle:
                    handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                return record

    def verify(self) -> bool:
        self.read_verified()
        return True

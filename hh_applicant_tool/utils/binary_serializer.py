from __future__ import annotations

import io
import struct
from datetime import datetime
from typing import Any

# ---- compression backends (stdlib only) ----

try:
    import zlib
except Exception:  # pragma: no cover
    zlib = None

try:
    import gzip
except Exception:  # pragma: no cover
    gzip = None


class BinaryType:
    NULL = 0x00
    MAP = 0x01
    STRING = 0x02
    NUMBER = 0x03
    FLOAT = 0x04
    LIST = 0x05
    BOOLEAN = 0x06
    DATETIME = 0x07


class CompressionType:
    NONE = 0x00
    ZLIB = 0x01
    GZIP = 0x02


class BinarySerializer:
    _U_INT_32 = struct.Struct("<I")
    _S_INT_64 = struct.Struct("<q")
    _FLOAT_64 = struct.Struct("<d")
    _U_INT_8 = struct.Struct("<B")

    def __init__(self) -> None:
        self._compression_order = self._detect_compression()

    # ---------- Public API ----------

    def serialize(self, value: Any, *, compress: bool = True) -> bytes:
        payload = io.BytesIO()
        self._write_value(payload, value)
        raw = payload.getvalue()

        if not compress:
            return bytes([CompressionType.NONE]) + raw

        algo = self._compression_order[0]

        if algo == CompressionType.ZLIB:
            return bytes([algo]) + zlib.compress(raw)

        if algo == CompressionType.GZIP:
            return bytes([algo]) + self._gzip_compress(raw)

        return bytes([CompressionType.NONE]) + raw

    def deserialize(self, data: bytes) -> Any:
        if not data:
            raise ValueError("Empty payload")

        algo = data[0]
        payload = data[1:]

        if algo == CompressionType.ZLIB:
            payload = zlib.decompress(payload)

        elif algo == CompressionType.GZIP:
            payload = self._gzip_decompress(payload)

        elif algo != CompressionType.NONE:
            raise ValueError(f"Unknown compression type: {algo}")

        return self._read_value(io.BytesIO(payload))

    # ---------- Compression detection ----------

    def _detect_compression(self) -> list[int]:
        order: list[int] = []

        if zlib is not None:
            order.append(CompressionType.ZLIB)

        if gzip is not None:
            order.append(CompressionType.GZIP)

        if not order:
            order.append(CompressionType.NONE)

        return order

    def _gzip_compress(self, data: bytes) -> bytes:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as f:
            f.write(data)
        return buf.getvalue()

    def _gzip_decompress(self, data: bytes) -> bytes:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as f:
            return f.read()

    # ---------- Serialization ----------

    def _write_value(self, stream: io.BytesIO, value: Any) -> None:
        if value is None:
            stream.write(bytes([BinaryType.NULL]))

        elif isinstance(value, bool):
            stream.write(bytes([BinaryType.BOOLEAN]))
            stream.write(self._U_INT_8.pack(1 if value else 0))

        elif isinstance(value, datetime):
            stream.write(bytes([BinaryType.DATETIME]))
            stream.write(self._FLOAT_64.pack(value.timestamp()))

        elif isinstance(value, dict):
            stream.write(bytes([BinaryType.MAP]))
            stream.write(self._U_INT_32.pack(len(value)))
            for k, v in value.items():
                self._write_value(stream, k)
                self._write_value(stream, v)

        elif isinstance(value, str):
            data = value.encode("utf-8")
            stream.write(bytes([BinaryType.STRING]))
            stream.write(self._U_INT_32.pack(len(data)))
            stream.write(data)

        elif isinstance(value, int):
            stream.write(bytes([BinaryType.NUMBER]))
            stream.write(self._S_INT_64.pack(value))

        elif isinstance(value, float):
            stream.write(bytes([BinaryType.FLOAT]))
            stream.write(self._FLOAT_64.pack(value))

        elif isinstance(value, list):
            stream.write(bytes([BinaryType.LIST]))
            stream.write(self._U_INT_32.pack(len(value)))
            for item in value:
                self._write_value(stream, item)

        else:
            raise TypeError(f"Unsupported type: {type(value)!r}")

    def _read_value(self, stream: io.BytesIO) -> Any:
        type_byte = stream.read(1)
        if not type_byte:
            return None

        t = type_byte[0]

        if t == BinaryType.NULL:
            return None

        if t == BinaryType.BOOLEAN:
            (v,) = self._U_INT_8.unpack(stream.read(1))
            return v == 1

        if t == BinaryType.DATETIME:
            (ts,) = self._FLOAT_64.unpack(stream.read(8))
            return datetime.fromtimestamp(ts)

        if t == BinaryType.MAP:
            (n,) = self._U_INT_32.unpack(stream.read(4))
            return {
                self._read_value(stream): self._read_value(stream)
                for _ in range(n)
            }

        if t == BinaryType.STRING:
            (n,) = self._U_INT_32.unpack(stream.read(4))
            return stream.read(n).decode("utf-8")

        if t == BinaryType.NUMBER:
            (v,) = self._S_INT_64.unpack(stream.read(8))
            return v

        if t == BinaryType.FLOAT:
            (v,) = self._FLOAT_64.unpack(stream.read(8))
            return v

        if t == BinaryType.LIST:
            (n,) = self._U_INT_32.unpack(stream.read(4))
            return [self._read_value(stream) for _ in range(n)]

        raise TypeError(f"Unknown type code: {t:#x}")

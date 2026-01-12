# Формат для передачи данных по сети, который лучше сжимается чем JSON
# Автогенерированный текст по моей спецификации. Из преимуществ поддержка дат
# и ключи любого типа в Map
from __future__ import annotations

import gzip
import io
import struct
import zlib
from datetime import datetime
from typing import Any, Callable, Final

# ---- Constants ----

BINARY_TYPES: Final = {
    type(None): 0x00,
    dict: 0x01,
    str: 0x02,
    int: 0x03,
    float: 0x04,
    list: 0x05,
    bool: 0x06,
    datetime: 0x07,
}

# Коды типов (для десериализации)
T_NULL, T_MAP, T_STR, T_INT, T_FLOAT, T_LIST, T_BOOL, T_DT = range(8)

# Сжатие
COMP_NONE, COMP_ZLIB, COMP_GZIP = range(3)

# Схемы упаковки
U32 = struct.Struct("<I")
S64 = struct.Struct("<q")
F64 = struct.Struct("<d")
U8 = struct.Struct("<B")

# ---- Compression Logic (Pure functions) ----


def gzip_compress(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as f:
        f.write(data)
    return buf.getvalue()


def gzip_decompress(data: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as f:
        return f.read()


COMPRESSORS: dict[int, Callable[[bytes], bytes]] = {
    COMP_ZLIB: zlib.compress,
    COMP_GZIP: gzip_compress,
    COMP_NONE: lambda d: d,
}

DECOMPRESSORS: dict[int, Callable[[bytes], bytes]] = {
    COMP_ZLIB: zlib.decompress,
    COMP_GZIP: gzip_decompress,
    COMP_NONE: lambda d: d,
}


def get_best_algo() -> int:
    if zlib:
        return COMP_ZLIB
    if gzip:
        return COMP_GZIP
    return COMP_NONE


# ---- Serialization (Recursive Functions) ----


def write_value(value: Any) -> bytes:
    """Рекурсивно преобразует значение в bytes (Pure)"""
    match value:
        case None:
            return bytes([T_NULL])

        case bool():
            return bytes([T_BOOL]) + U8.pack(1 if value else 0)

        case datetime():
            return bytes([T_DT]) + F64.pack(value.timestamp())

        case int():
            return bytes([T_INT]) + S64.pack(value)

        case float():
            return bytes([T_FLOAT]) + F64.pack(value)

        case str():
            data = value.encode("utf-8")
            return bytes([T_STR]) + U32.pack(len(data)) + data

        case list():
            content = b"".join(map(write_value, value))
            return bytes([T_LIST]) + U32.pack(len(value)) + content

        case dict():
            content = b"".join(
                write_value(k) + write_value(v) for k, v in value.items()
            )
            return bytes([T_MAP]) + U32.pack(len(value)) + content

        case _:
            raise TypeError(f"Unsupported type: {type(value)}")


# ---- Deserialization (Stream-based but stateless) ----


def read_value(stream: io.BytesIO) -> Any:
    """Читает значение из потока байт"""
    type_byte = stream.read(1)
    if not type_byte:
        return None

    match type_byte[0]:
        case 0x00:  # NULL
            return None
        case 0x06:  # BOOL
            return U8.unpack(stream.read(1))[0] == 1
        case 0x07:  # DT
            return datetime.fromtimestamp(F64.unpack(stream.read(8))[0])
        case 0x03:  # INT
            return S64.unpack(stream.read(8))[0]
        case 0x04:  # FLOAT
            return F64.unpack(stream.read(8))[0]
        case 0x02:  # STR
            size = U32.unpack(stream.read(4))[0]
            return stream.read(size).decode("utf-8")
        case 0x05:  # LIST
            size = U32.unpack(stream.read(4))[0]
            return [read_value(stream) for _ in range(size)]
        case 0x01:  # MAP
            size = U32.unpack(stream.read(4))[0]
            return {read_value(stream): read_value(stream) for _ in range(size)}
        case t:
            raise TypeError(f"Unknown type code: {t:#x}")


# ---- Public API (Composition) ----


def serialize(value: Any, compress: bool = True) -> bytes:
    raw_payload = write_value(value)
    algo = get_best_algo() if compress else COMP_NONE

    compressor = COMPRESSORS.get(algo, COMPRESSORS[COMP_NONE])
    return bytes([algo]) + compressor(raw_payload)


def deserialize(data: bytes) -> Any:
    if not data:
        raise ValueError("Empty payload")

    algo, payload = data[0], data[1:]

    if algo not in DECOMPRESSORS:
        raise ValueError(f"Unknown compression type: {algo}")

    raw_data = DECOMPRESSORS[algo](payload)
    return read_value(io.BytesIO(raw_data))

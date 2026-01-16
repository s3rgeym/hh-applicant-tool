from __future__ import annotations

import base64
import ctypes
import io
import os
import platform
import sys

try:
    from PIL import Image
except ImportError:

    class Image:
        pass


ESC = "\x1b"


def setup_terminal() -> None:
    if platform.system() != "Windows":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        # -11 = STD_OUTPUT_HANDLE
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        # Если что-то пошло не так (старая Windows или нет прав),
        # просто продолжаем работу без цветов
        pass


def print_kitty_image(data: bytes) -> None:
    # Кодируем весь файл целиком (он уже сжат в PNG)
    b64data = base64.b64encode(data).decode("ascii")

    # f=100 говорит терминалу: "это PNG, разберись сам с размерами"
    # Нам больше не нужно указывать s=... и v=...
    sys.stdout.write(f"\033_Ga=T,f=100;{b64data}\033\\")
    sys.stdout.flush()
    print()


def print_sixel_mage(image_bytes: bytes) -> None:
    img = Image.open(io.BytesIO(image_bytes))

    # Рекомендуется оставить ограничение размера,
    # иначе Zellij может "лагать" на огромных картинках
    # max_size = (800, 600)
    # img.thumbnail(max_size, Image.Resampling.LANCZOS)
    img = img.convert("RGB")

    try:
        img = img.quantize(colors=256, method=Image.Quantize.MAXCOVERAGE)
    except Exception:
        img = img.quantize(colors=256)

    palette = img.getpalette()[: 256 * 3]
    width, height = img.size
    pixels = img.load()

    is_multiplexer = "ZELLIJ" in os.environ or "TMUX" in os.environ

    # Собираем всё в список строк, чтобы минимизировать количество вызовов write
    out = []

    # 1. Начало (Обертка для Zellij)
    if is_multiplexer:
        out.append(f"{ESC}P+p")

    # 2. Sixel заголовок + Растр
    out.append(f'{ESC}Pq"1;1;{width};{height}')

    # 3. Палитра
    for i in range(256):
        r, g, b = palette[i * 3 : i * 3 + 3]
        out.append(f"#{i};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")

    # 4. Отрисовка
    for y in range(0, height, 6):
        h_chunk = min(6, height - y)

        # Считаем уникальные цвета в полосе (быстрее, чем перебирать всю палитру)
        colors_in_band = set()
        for dy in range(h_chunk):
            for x in range(width):
                colors_in_band.add(pixels[x, y + dy])

        for color in colors_in_band:
            out.append(f"#{color}")
            last_char = ""
            count = 0

            for x in range(width):
                bits = 0
                for dy in range(h_chunk):
                    if pixels[x, y + dy] == color:
                        bits |= 1 << dy

                char = chr(63 + bits)
                if char == last_char:
                    count += 1
                else:
                    if count > 0:
                        out.append(
                            f"!{count}{last_char}"
                            if count > 3
                            else last_char * count
                        )
                    last_char, count = char, 1

            if count > 0:
                out.append(
                    f"!{count}{last_char}" if count > 3 else last_char * count
                )
            out.append("$")
        out.append("-")

    # 5. Конец Sixel
    out.append(f"{ESC}\\")

    # 6. Конец обертки мультиплексора
    if is_multiplexer:
        out.append(f"{ESC}\\")

    # ВЫВОД: Одной строкой БЕЗ лишних переносов в конце
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    print()

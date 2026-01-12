import base64
import ctypes
import platform
import sys


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

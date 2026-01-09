import ctypes
import platform


def enable_terminal_colors() -> None:
    if not platform.system() == "Windows":
        return
    kernel32 = ctypes.windll.kernel32  # ty:ignore[unresolved-attribute]
    # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # Берем дескриптор стандартного вывода (stdout)
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)

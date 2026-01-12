import ctypes
import platform


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

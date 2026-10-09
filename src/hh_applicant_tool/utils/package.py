from importlib.metadata import version

PACKAGE_NAME = (__package__ or __name__).split(".")[0].replace("_", "-")


def parse_version(v: str) -> tuple[int, int, int]:
    return tuple(map(int, v.split(".")))


def get_package_version() -> str | None:
    return version(PACKAGE_NAME)

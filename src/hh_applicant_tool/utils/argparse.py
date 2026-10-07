import argparse
import os


class ArgumentFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    pass


def str_or_file(v: str | None) -> str | None:
    if v is not None and os.path.exists(v):
        with open(v, "r", encoding="utf-8") as f:
            return f.read()

    return v

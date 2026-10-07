from typing import Sequence

import urllib3

from .tool import HHApplicantTool


def main(argv: Sequence[str] | None = None) -> None | int:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    return HHApplicantTool().run(argv)

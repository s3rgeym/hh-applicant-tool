import sys
from typing import Sequence

import urllib3

from .tool import APICaptchaHandler, HHApplicantTool


def main(argv: Sequence[str] | None = None) -> None | int:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    return HHApplicantTool(
        captcha_handler_class=APICaptchaHandler,
    ).run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

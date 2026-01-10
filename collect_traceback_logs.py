import pathlib
from datetime import datetime, timedelta

from hh_applicant_tool.utils.config import get_config_path
from hh_applicant_tool.utils.log import collect_traceback_logs

if __name__ == "__main__":
    p: pathlib.Path = get_config_path() / "log.txt"

    with p.open() as f:
        print(collect_traceback_logs(f, datetime.now() - timedelta(hours=24)))

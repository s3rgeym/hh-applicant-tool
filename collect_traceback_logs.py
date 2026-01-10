import re
from collections import deque
from datetime import datetime, timedelta

TS_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def collect_traceback_logs(
    fp,
    after_dt: datetime,
    maxlen=2000,
) -> str:
    error_lines = deque(maxlen=maxlen)
    prev_line = ""
    log_dt = None
    collecting_traceback = False
    for line in fp:
        if ts_match := TS_RE.match(line):
            log_dt = datetime.strptime(ts_match.group(0), "%Y-%m-%d %H:%M:%S")
            collecting_traceback = False

        if (
            line.startswith("Traceback (most recent call last):")
            and log_dt
            and log_dt >= after_dt
        ):
            error_lines.append(prev_line)
            collecting_traceback = True

        if collecting_traceback:
            error_lines.append(line)

        prev_line = line
    return "".join(error_lines)


if __name__ == "__main__":
    import pathlib

    p = pathlib.Path.home() / ".config" / "hh-applicant-tool" / "log.txt"

    with p.open() as f:
        print(collect_traceback_logs(f, datetime.now() - timedelta(hours=24)))

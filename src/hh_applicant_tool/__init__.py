from __future__ import annotations


def __getattr__(name: str):
    if name == "HHApplicantTool":
        from .main import HHApplicantTool

        return HHApplicantTool
    raise AttributeError(name)

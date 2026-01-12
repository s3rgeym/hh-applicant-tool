import random
import uuid


def generate_android_useragent() -> str:
    """Generates Android App User-Agent"""
    devices = (
        "23053RN02A, 23053RN02Y, 23053RN02I, 23053RN02L, 23077RABDC".split(", ")
    )
    device = random.choice(devices)
    minor = random.randint(100, 150)
    patch = random.randint(10000, 15000)
    android = random.randint(11, 15)
    return (
        f"ru.hh.android/7.{minor}.{patch}, Device: {device}, "
        f"Android OS: {android} (UUID: {uuid.uuid4()})"
    )

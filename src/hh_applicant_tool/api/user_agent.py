import random
import uuid

MOBILE_MODELS: list[str] = [
    # https://www.gsmarena.com/xiaomi_redmi_12-12328.php
    "23053RN02A",
    "23053RN02Y",
    "23053RN02I",
    "23053RN02L",
    "23077RABDC",
    # https://www.gsmarena.com/xiaomi_redmi_14c-13291.php
    "2411DRN47C",
    "2409BRN2CA",
    "2409BRN2CG",
    "2409BRN2CY",
    # https://www.gsmarena.com/xiaomi_redmi_15c_5g-14039.php
    "2508CRN2BE",
    "2508CRN2BC",
    "2508CRN2BG",
    # https://www.gsmarena.com/samsung_galaxy_a16-13383.php
    "SM-A165F",
    "SM-A165F/DS",
    "SM-A165M",
    "SM-A165M/DS",
    "SM-A165F/DSB",
    # Еще какие-то модели
    "24108PCE2I",
    "MZB0KE1IN"
]


def generate_android_useragent() -> str:
    """Generates Android App User-Agent"""
    model = random.choice(MOBILE_MODELS)
    minor = random.randint(100, 150)
    patch = random.randint(10000, 15000)
    android = random.randint(11, 15)
    return (
        f"ru.hh.android/7.{minor}.{patch}, Device: {model}, "
        f"Android OS: {android} (UUID: {uuid.uuid4()})"
    )

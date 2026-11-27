import random
import uuid

# https://deviceatlas.com/blog/list-of-user-agent-strings
MODELS = [
    "SM-S938B",  # Samsung Galaxy S25 Ultra
    "SM-S928B",  # Samsung Galaxy S24 Ultra
    "SM-A556B",  # Samsung Galaxy A55 5G
    "SM-A566B",  # Samsung Galaxy A56 5G
    "SM-S921B",  # Samsung Galaxy S24
    "2312DRA50G",  # Redmi Note 13 Pro 5G
    "23117RA68G",  # Redmi Note 13 Pro
    "BRP-NX1M",  # Honor Magic 7 Lite
    "MTN-NX1M",  # Honor Magic8 Lite
    "2506BPN68G",  # Xiaomi 15T Pro
    "2407FPN8EG",  # Xiaomi 14T Pro
    "Pixel 9",  # Google Pixel 9
    "Pixel 9a",  # Google Pixel 9a
    "CPH2699",  # Oppo Reno13 F
    "CPH2481",  # Oppo Reno8 T
    "VOG-L29",  # Huawei P30 Pro
    "MAR-LX1A",  # Huawei P30 lite
    "moto g06",  # Motorola moto g06
    "moto g04",  # Motorola moto g04
    "RMX3085",  # Realme 8
    "RMX3710",  # Realme C55
    "CPH2747",  # OnePlus 15
    "CPH2581",  # OnePlus 12
]


def generate_android_useragent() -> str:
    """Generates Android App User-Agent"""
    model = random.choice(MODELS)
    minor = random.randint(100, 150)
    patch = random.randint(10000, 15000)
    android = random.randint(16, 17)
    return (
        f"ru.hh.android/7.{minor}.{patch}, Device: {model}, "
        f"Android OS: {android} (UUID: {uuid.uuid4()})"
    )

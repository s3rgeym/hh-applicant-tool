import json
from pathlib import Path

from hh_applicant_tool.utils.binary_serializer import BinarySerializer

data_file: Path = Path("data.json")

with data_file.open() as f:
    data = json.load(f)

ser = BinarySerializer()
bin = ser.serialize(data)
print("original file size:", data_file.stat().st_size)
print("serialized binary data size:", len(bin))
data1 = ser.deserialize(bin)
print(data["items"][-1])
print(data1["items"][-1])
assert data == data1

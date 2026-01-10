if __name__ == "__main__":
    import json
    from pathlib import Path

    from hh_applicant_tool.utils.binpack import deserialize, serialize

    p = Path("data.json")
    with p.open() as f:
        data = json.load(f)

    packed = serialize(data)
    print("original file size:", p.stat().st_size)
    print("serialized binary data size:", len(packed))
    unpacked = deserialize(packed)
    print(data["items"][-1])
    print(unpacked["items"][-1])
    assert data == unpacked

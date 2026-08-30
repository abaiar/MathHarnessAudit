from mathaudit.hashing import canonical_json, sha256_json, sha256_text


def test_canonical_json_ignores_mapping_order():
    left = {"b": 2, "a": [1, 3]}
    right = {"a": [1, 3], "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert sha256_json(left) == sha256_json(right)


def test_text_hash_is_utf8_stable():
    assert sha256_text("数学") == "872c1fa141b5ed8d2f2b99255b4180eff7c3ec3079f98bfb261bfa83aac4ec68"

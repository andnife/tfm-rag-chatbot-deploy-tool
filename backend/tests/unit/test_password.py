from tfm_rag.infrastructure.auth.password import hash_password, verify_password


def test_hash_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong", h) is False


def test_different_passwords_produce_different_hashes() -> None:
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    assert h1 != h2  # bcrypt has random salt


def test_corrupted_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False

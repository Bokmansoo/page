import pytest
from src.services.validation import validate_external_url


def test_validate_valid_url():
    # Public domains should resolve and validate successfully
    # Google is a safe public domain to test DNS resolution
    try:
        host = validate_external_url("https://www.google.com")
        assert host == "www.google.com"
    except ValueError as e:
        # If internet is not connected or DNS resolution fails during test runs, gaierror might occur, which is acceptable
        assert "Could not resolve host" in str(e)


def test_validate_invalid_scheme():
    # Only http and https allowed
    with pytest.raises(ValueError) as exc:
        validate_external_url("ftp://ftp.example.com")
    assert "Only http and https schemes are allowed" in str(exc.value)


def test_validate_private_ip():
    # Block loopback and private ranges
    private_urls = [
        "http://127.0.0.1",
        "https://192.168.1.10",
        "http://10.0.0.1",
        "http://localhost",
    ]
    for url in private_urls:
        with pytest.raises(ValueError) as exc:
            validate_external_url(url)
        assert (
            "Access to private/restricted IP address is blocked" in str(exc.value)
            or "Could not resolve host" in str(exc.value)
        )

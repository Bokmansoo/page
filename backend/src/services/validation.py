import ipaddress
import socket
from urllib.parse import urlparse
from fastapi import HTTPException, UploadFile
from src.config import settings

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def validate_external_url(url: str) -> str:
    """
    Validates a URL to prevent Server-Side Request Forgery (SSRF).
    Ensures that the URL resolves only to public, non-private IP addresses.
    Returns the resolved IP address on success, otherwise raises ValueError.
    """
    if not url:
        raise ValueError("URL cannot be empty")

    parsed_url = urlparse(url)
    if parsed_url.scheme not in ("http", "https"):
        raise ValueError("Only http and https schemes are allowed")

    hostname = parsed_url.hostname
    if not hostname:
        raise ValueError("Invalid URL hostname")

    try:
        # Resolve all IP addresses for the hostname
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(f"Could not resolve host: {hostname}")

    # Check each resolved IP
    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError(f"Invalid IP address resolved: {ip_str}")

        # Check if the IP falls in a private/restricted range
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            raise ValueError(f"Access to private/restricted IP address is blocked: {ip_str}")

    return hostname


def validate_file_upload(file: UploadFile, file_size: int) -> None:
    """
    Validates the uploaded file for type and size constraints.
    Raises HTTPException 400 if validation fails.
    """
    # Check extension
    filename = file.filename or ""
    ext = ""
    if "." in filename:
        ext = filename.rsplit(".", 1)[-1]
    if not ext or f".{ext.lower()}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types are: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Check size
    max_size_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File is too large. Maximum allowed size is {settings.MAX_UPLOAD_SIZE_MB}MB."
        )

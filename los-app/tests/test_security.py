import pytest
from app.core.logger import mask_pii_string, mask_pii_data, PIIMaskingLogFilter
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_aes_key,
    encrypt_payload,
    decrypt_payload
)
import logging

def test_pii_masking():
    # Mobile
    assert mask_pii_string("Call me at 9876543210 please") == "Call me at [MASKED_MOBILE] please"
    assert mask_pii_string("Phone: +91 9876543210") == "Phone: [MASKED_MOBILE]"
    
    # PAN
    assert mask_pii_string("Customer PAN is ABCDE1234F.") == "Customer PAN is [MASKED_PAN]."
    
    # Aadhaar
    assert mask_pii_string("Aadhaar: 1234 5678 9012") == "Aadhaar: [MASKED_AADHAAR]"
    
    # DOB
    assert mask_pii_string("Born on 1990-05-12 or 12/05/1990") == "Born on [MASKED_DOB] or [MASKED_DOB]"
    
    # Email
    assert mask_pii_string("Contact user@example.com for info") == "Contact [MASKED_EMAIL] for info"

    # Nested data masking
    data = {
        "user": {
            "pan": "ABCDE1234F",
            "phone": "9876543210"
        },
        "tags": ["1995-01-01"]
    }
    masked = mask_pii_data(data)
    assert masked["user"]["pan"] == "[MASKED_PAN]"
    assert masked["user"]["phone"] == "[MASKED_MOBILE]"
    assert masked["tags"][0] == "[MASKED_DOB]"

def test_pii_log_filter():
    filt = PIIMaskingLogFilter()
    record = logging.LogRecord("test", logging.INFO, "path", 10, "User PAN: ABCDE1234F", (), None)
    filt.filter(record)
    assert record.msg == "User PAN: [MASKED_PAN]"

def test_password_hashing():
    pwd = "secretpassword123"
    hashed = get_password_hash(pwd)
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongpass", hashed) is False

def test_jwt_tokens():
    token = create_access_token(subject="test_user", app_name="test_app", is_admin=True)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "test_user"
    assert payload["app_name"] == "test_app"
    assert payload["is_admin"] is True

    assert decode_access_token("invalid.token.here") is None

def test_aes_gcm_encryption_roundtrip():
    key = generate_aes_key()
    original_text = json_str = '{"loan_amount": 500000, "customer_name": "John Doe"}'
    
    encrypted = encrypt_payload(original_text, key)
    assert "ciphertext" in encrypted
    assert "iv" in encrypted
    assert "tag" in encrypted
    
    decrypted = decrypt_payload(encrypted, key)
    assert decrypted == original_text

"""Unit tests for policy/pii.py's field classification, separate from
the gate-level integration tests in test_gate.py."""

from policy.pii import is_pii_field, should_mask


def test_dob_is_pii_but_not_masked():
    assert is_pii_field("dob") is True
    assert should_mask("dob") is False  # sensitive enough to gate, not unusual UX friction to mask


def test_ssn_is_pii_and_masked():
    assert is_pii_field("ssn") is True
    assert should_mask("ssn") is True


def test_account_number_is_pii_and_masked():
    assert is_pii_field("bank_account_number") is True
    assert should_mask("bank_account_number") is True


def test_ordinary_fields_are_not_pii():
    for field_id in ["full_name", "address", "income", "email", "phone_number"]:
        assert is_pii_field(field_id) is False, f"'{field_id}' should not be classified as PII"


def test_case_insensitive():
    assert is_pii_field("DateOfBirth") is True
    assert is_pii_field("SSN") is True

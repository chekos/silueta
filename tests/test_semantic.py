from silueta.semantic import classify_sample, is_credit_card, is_npi, is_plausible_ssn, luhn_valid


def test_luhn():
    assert luhn_valid("4532015112830366")
    assert not luhn_valid("4532015112830367")


def test_credit_card():
    assert is_credit_card("4532 0151 1283 0366")
    assert not is_credit_card("1234")


def test_npi_checksum():
    assert is_npi("1234567893")  # standard NPI test number
    assert not is_npi("1234567890")
    assert not is_npi("123456789")


def test_ssn_plausibility():
    assert is_plausible_ssn("521-44-1001")
    assert not is_plausible_ssn("000-12-3456")
    assert not is_plausible_ssn("666-12-3456")
    assert not is_plausible_ssn("912-12-3456")


def test_classify_emails():
    hits = classify_sample([f"user{i}@example.com" for i in range(10)])
    assert any(h.type == "email" for h in hits)


def test_high_severity_reports_on_any_hit():
    values = ["hello"] * 99 + ["521-44-1001"]
    hits = classify_sample(values)
    ssn = [h for h in hits if h.type == "us_ssn"]
    assert ssn and ssn[0].severity == "high" and ssn[0].match_rate < 0.6

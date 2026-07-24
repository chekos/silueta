from silueta.masks import mask_value


def test_ssn_mask():
    assert mask_value("123-45-6789") == "999-99-9999"


def test_name_mask():
    assert mask_value("Smith, John") == "Aaaaa, Aaaa"


def test_mixed_mask():
    assert mask_value("MRN-700123") == "AAA-999999"


def test_non_ascii_masks_to_x():
    assert mask_value("José") == "Aaax"
    # The accented character must not survive in any form.
    assert "é" not in mask_value("José")

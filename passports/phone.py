import phonenumbers


def normalize_uk_phone(raw):
    """Parses a UK phone number in any common format and returns it as E.164
    (e.g. '+447990575555'), or None if it isn't a valid UK number."""
    try:
        parsed = phonenumbers.parse(raw, 'GB')
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

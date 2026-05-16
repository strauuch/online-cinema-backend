import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from app.database.validators.accounts_validators import (
    validate_password_strength,
    validate_email,
    validate_name,
    validate_image,
    validate_birth_date,
)
from app.database.validators.movies_validators import (
    validate_movie_year,
    validate_imdb_rating,
    validate_movie_price,
    validate_movie_duration,
)

# ==============================================================================
# validate_password_strength
# ==============================================================================


def test_password_valid():
    assert validate_password_strength("StrongPass1!") == "StrongPass1!"


def test_password_too_short():
    with pytest.raises(ValueError, match="8 characters"):
        validate_password_strength("Ab1!")


def test_password_no_uppercase():
    with pytest.raises(ValueError, match="uppercase"):
        validate_password_strength("weakpass1!")


def test_password_no_lowercase():
    with pytest.raises(ValueError, match="lower"):
        validate_password_strength("WEAKPASS1!")


def test_password_no_digit():
    with pytest.raises(ValueError, match="digit"):
        validate_password_strength("WeakPass!!")


def test_password_no_special_char():
    with pytest.raises(ValueError, match="special character"):
        validate_password_strength("WeakPass11")


def test_password_all_requirements_met():
    # each requirement at its exact minimum
    result = validate_password_strength("Aa1!aaaa")
    assert result == "Aa1!aaaa"


# ==============================================================================
# validate_email
# ==============================================================================


def test_email_valid():
    result = validate_email("user@example.com")
    assert "@" in result


def test_email_invalid_no_at():
    with pytest.raises(ValueError):
        validate_email("notanemail")


def test_email_invalid_no_domain():
    with pytest.raises(ValueError):
        validate_email("user@")


def test_email_normalised_lowercase():
    result = validate_email("user@Example.COM")
    assert result == result.lower()


# ==============================================================================
# validate_name
# ==============================================================================


def test_name_valid():
    validate_name("John")  # should not raise


def test_name_valid_all_lowercase():
    validate_name("alice")


def test_name_with_digit_raises():
    with pytest.raises(ValueError):
        validate_name("John1")


def test_name_with_space_raises():
    with pytest.raises(ValueError):
        validate_name("John Doe")


def test_name_with_special_char_raises():
    with pytest.raises(ValueError):
        validate_name("John!")


def test_name_with_cyrillic_raises():
    with pytest.raises(ValueError):
        validate_name("Иван")


# ==============================================================================
# validate_image
# ==============================================================================


def _make_upload(content: bytes, content_type: str) -> MagicMock:
    mock = MagicMock()
    mock.content_type = content_type
    mock.file = MagicMock()
    mock.file.read.return_value = content
    return mock


def test_image_valid_jpeg():
    avatar = _make_upload(b"x" * 100, "image/jpeg")
    validate_image(avatar)  # should not raise


def test_image_valid_png():
    avatar = _make_upload(b"x" * 100, "image/png")
    validate_image(avatar)


def test_image_too_large():
    big_content = b"x" * (1 * 1024 * 1024 + 1)
    avatar = _make_upload(big_content, "image/jpeg")
    with pytest.raises(ValueError, match="1 MB"):
        validate_image(avatar)


def test_image_unsupported_type():
    avatar = _make_upload(b"x" * 100, "image/gif")
    with pytest.raises(ValueError, match="Unsupported"):
        validate_image(avatar)


def test_image_pdf_rejected():
    avatar = _make_upload(b"x" * 100, "application/pdf")
    with pytest.raises(ValueError):
        validate_image(avatar)


# ==============================================================================
# validate_birth_date
# ==============================================================================


def test_birth_date_valid_adult():
    birth_date = date.today() - timedelta(days=365 * 25)
    validate_birth_date(birth_date)  # should not raise


def test_birth_date_under_18():
    birth_date = date.today() - timedelta(days=365 * 17)
    with pytest.raises(ValueError, match="18"):
        validate_birth_date(birth_date)


def test_birth_date_exactly_18():
    birth_date = date.today() - timedelta(days=365 * 18 + 1)
    validate_birth_date(birth_date)  # should not raise


def test_birth_date_year_before_1900():
    with pytest.raises(ValueError, match="1900"):
        validate_birth_date(date(1899, 12, 31))


def test_birth_date_year_1900_is_valid():
    validate_birth_date(date(1900, 1, 1))


# ==============================================================================
# validate_movie_year
# ==============================================================================


def test_movie_year_valid():
    assert validate_movie_year(2000) == 2000


def test_movie_year_minimum_boundary():
    assert validate_movie_year(1895) == 1895


def test_movie_year_before_1895():
    with pytest.raises(ValueError, match="1895"):
        validate_movie_year(1894)


def test_movie_year_too_far_future():
    from datetime import datetime

    too_far = datetime.now().year + 6
    with pytest.raises(ValueError):
        validate_movie_year(too_far)


def test_movie_year_max_boundary():
    from datetime import datetime

    max_year = datetime.now().year + 5
    assert validate_movie_year(max_year) == max_year


# ==============================================================================
# validate_imdb_rating
# ==============================================================================


def test_imdb_rating_valid():
    assert validate_imdb_rating(7.5) == 7.5


def test_imdb_rating_zero():
    assert validate_imdb_rating(0) == 0


def test_imdb_rating_ten():
    assert validate_imdb_rating(10) == 10


def test_imdb_rating_below_zero():
    with pytest.raises(ValueError, match="between 0 and 10"):
        validate_imdb_rating(-0.1)


def test_imdb_rating_above_ten():
    with pytest.raises(ValueError, match="between 0 and 10"):
        validate_imdb_rating(10.1)


# ==============================================================================
# validate_movie_price
# ==============================================================================


def test_movie_price_valid():
    assert validate_movie_price(Decimal("9.99")) == Decimal("9.99")


def test_movie_price_zero():
    assert validate_movie_price(Decimal("0.00")) == Decimal("0.00")


def test_movie_price_negative():
    with pytest.raises(ValueError, match="negative"):
        validate_movie_price(Decimal("-0.01"))


def test_movie_price_large_value():
    assert validate_movie_price(Decimal("999.99")) == Decimal("999.99")


# ==============================================================================
# validate_movie_duration
# ==============================================================================


def test_movie_duration_valid():
    assert validate_movie_duration(120) == 120


def test_movie_duration_one_minute():
    assert validate_movie_duration(1) == 1


def test_movie_duration_zero():
    with pytest.raises(ValueError, match="positive"):
        validate_movie_duration(0)


def test_movie_duration_negative():
    with pytest.raises(ValueError, match="positive"):
        validate_movie_duration(-10)

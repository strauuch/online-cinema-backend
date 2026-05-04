import decimal
from datetime import datetime


def validate_movie_year(year: int) -> int:
    current_year = datetime.now().year
    if year < 1895:
        raise ValueError("Year cannot be earlier than 1895.")
    if year > current_year + 5:
        raise ValueError(f"Year cannot be greater than {current_year + 5}.")
    return year


def validate_imdb_rating(rating: float) -> float:
    if not 0 <= rating <= 10:
        raise ValueError("IMDb rating must be between 0 and 10.")
    return rating


def validate_movie_price(price: decimal.Decimal) -> decimal.Decimal:
    if price < 0:
        raise ValueError("Price cannot be negative.")
    return price


def validate_movie_duration(time: int) -> int:
    if time <= 0:
        raise ValueError("Duration must be a positive integer (minutes).")
    return time

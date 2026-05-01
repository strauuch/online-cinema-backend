import re
import logging
import email_validator

from datetime import date
from fastapi import UploadFile

from database.models.accounts import GenderEnum

logger = logging.getLogger(__name__)


def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lower letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[@$!%*?&#]", password):
        raise ValueError(
            "Password must contain at least one special character: @, $, !, %, *, ?, #, &."
        )
    return password


def validate_email(user_email: str) -> str:
    try:
        email_info = email_validator.validate_email(
            user_email, check_deliverability=False
        )
        email = email_info.normalized
    except email_validator.EmailNotValidError as error:
        raise ValueError(str(error))
    else:
        return email


def validate_name(name: str):
    if re.search(r"^[A-Za-z]*$", name) is None:
        raise ValueError(f"{name} contains non-english letters")


def validate_image(avatar: UploadFile) -> None:
    max_file_size = 1 * 1024 * 1024  # 1MB

    content = avatar.file.read()
    if len(content) > max_file_size:
        logger.warning(f"File upload rejected: size too large ({len(content)} bytes)")
        avatar.file.seek(0)
        raise ValueError("Image size exceeds 1 MB")

    allowed_types = ["image/jpeg", "image/png", "image/jpg"]
    if avatar.content_type not in allowed_types:
        logger.warning(f"File upload rejected: unsupported type {avatar.content_type}")
        avatar.file.seek(0)
        raise ValueError(
            f"Unsupported file type: {avatar.content_type}. Use JPG or PNG."
        )

    avatar.file.seek(0)


def validate_gender(gender: str) -> None:
    if gender not in GenderEnum.__members__.values():
        raise ValueError(
            f"Gender must be one of: {', '.join(g.value for g in GenderEnum)}"
        )


def validate_birth_date(birth_date: date) -> None:
    if birth_date.year < 1900:
        raise ValueError("Invalid birth date - year must be greater than 1900.")

    age = (date.today() - birth_date).days // 365
    if age < 18:
        raise ValueError("You must be at least 18 years old to register.")

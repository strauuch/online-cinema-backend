from datetime import date

from fastapi import UploadFile, Form, File
from pydantic import BaseModel, field_validator, ConfigDict, EmailStr, AliasPath, Field

from database.models.accounts import GenderEnum, UserGroupEnum
from database.validators import accounts_validators as validators


class BaseEmailPasswordSchema(BaseModel):
    email: EmailStr
    password: str

    model_config = {"from_attributes": True}

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validators.validate_password_strength(value)


class UserRegistrationRequestSchema(BaseEmailPasswordSchema):
    pass


class PasswordResetRequestSchema(BaseModel):
    email: EmailStr


class PasswordResetCompleteRequestSchema(BaseEmailPasswordSchema):
    token: str


class PasswordChangeRequestSchema(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validators.validate_password_strength(value)


class UserLoginRequestSchema(BaseEmailPasswordSchema):
    pass


class UserLoginResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRegistrationResponseSchema(BaseModel):
    id: int
    email: EmailStr

    model_config = {"from_attributes": True}


class UserActivationRequestSchema(BaseModel):
    email: EmailStr
    token: str


class UserActivationResendRequestSchema(BaseModel):
    email: EmailStr


class MessageResponseSchema(BaseModel):
    message: str


class TokenRefreshRequestSchema(BaseModel):
    refresh_token: str


class TokenRefreshResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdateRequestSchema(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    gender: GenderEnum | None = None
    date_of_birth: date | None = None
    info: str | None = None
    avatar: UploadFile | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_names(cls, v: str | None) -> str | None:
        if v is not None:
            validators.validate_name(v)
            return v.lower().strip()
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_birth_date(cls, v: date | None) -> date | None:
        if v is not None:
            validators.validate_birth_date(v)
        return v

    @field_validator("avatar")
    @classmethod
    def validate_avatar_file(cls, v: UploadFile | None) -> UploadFile | None:
        if v is not None and v.filename:
            validators.validate_image(v)
        return v

    @classmethod
    def as_form(
        cls,
        first_name: str = Form(None),
        last_name: str = Form(None),
        gender: GenderEnum = Form(None),
        date_of_birth: date = Form(None),
        info: str = Form(None),
        avatar: UploadFile = File(None),
    ) -> "ProfileUpdateRequestSchema":
        return cls(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=date_of_birth,
            info=info,
            avatar=avatar,
        )


class ProfileResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    user_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None
    info: str | None = None
    avatar: str | None = None


class UserMeResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    profile: ProfileResponseSchema | None = None


class AdminUserListResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    group_name: UserGroupEnum = Field(validation_alias=AliasPath("group", "name"))


class AdminUserDetailResponseSchema(AdminUserListResponseSchema):
    profile: ProfileResponseSchema | None = None


class AdminUserUpdateRequestSchema(BaseModel):
    group_id: int | None = None
    is_active: bool | None = None


class AdminUserUpdateResponseSchema(AdminUserUpdateRequestSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr

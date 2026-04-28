import enum


class UserGroupEnum(str, enum.Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class GenderEnum(str, enum.Enum):
    MAN = "man"
    WOMAN = "woman"


class NotificationType(enum.Enum):
    COMMENT_LIKE = "comment_like"
    COMMENT_REPLY = "comment_reply"
    SYSTEM = "system"

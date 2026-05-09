from datetime import datetime
from sqlalchemy import select
from app.database.models.accounts import UserModel, UserGroupModel, UserGroupEnum


class UserFactory:
    def __init__(self, db_session):
        self.db = db_session

    async def _ensure_groups(self):
        for group in UserGroupEnum:
            exists = await self.db.scalar(select(UserGroupModel).where(UserGroupModel.name == group))
            if not exists:
                self.db.add(UserGroupModel(name=group))
        await self.db.commit()

    async def create_user(self, email: str = None, is_active: bool = False, group: UserGroupEnum = UserGroupEnum.USER):
        await self._ensure_groups()

        if email is None:
            email = f"test_{int(datetime.now().timestamp())}@example.com"

        group_obj = await self.db.scalar(select(UserGroupModel).where(UserGroupModel.name == group))

        user = UserModel.create(
            email=email,
            raw_password="StrongTestPass123!",
            group_id=group_obj.id
        )
        user.is_active = is_active
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def create_active_user(self, email: str = None):
        return await self.create_user(email=email, is_active=True)

    async def create_admin_user(self, email: str = None):
        return await self.create_user(email=email, is_active=True, group=UserGroupEnum.ADMIN)

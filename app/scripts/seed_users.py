import logging

from sqlalchemy import select

from app.database.models import accounts, carts, movies, orders, payments
from app.database.models.accounts import UserModel, UserGroupModel
from app.database.models.enums import UserGroupEnum
from app.scripts.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    async def handle(self, session, *args, **kwargs):
        logger.info("Starting database seeding...")

        groups_to_seed = [
            UserGroupEnum.ADMIN,
            UserGroupEnum.MODERATOR,
            UserGroupEnum.USER,
        ]
        group_map = {}

        for group_name in groups_to_seed:
            stmt = select(UserGroupModel).where(UserGroupModel.name == group_name)
            res = await session.execute(stmt)
            group = res.scalar_one_or_none()

            if not group:
                group = UserGroupModel(name=group_name)
                session.add(group)
                await session.flush()
                logger.info(f"Group created: {group_name}")
            group_map[group_name] = group.id

        users_data = [
            {
                "email": "admin@cinema.com",
                "role": UserGroupEnum.ADMIN,
                "pass": "Admin_12345@",
            },
            {
                "email": "moderator@cinema.com",
                "role": UserGroupEnum.MODERATOR,
                "pass": "Mod_12345@",
            },
        ]

        for data in users_data:
            check_stmt = select(UserModel).where(UserModel.email == data["email"])
            res = await session.execute(check_stmt)
            if not res.scalar_one_or_none():
                user = UserModel.create(
                    email=data["email"],
                    raw_password=data["pass"],
                    group_id=group_map[data["role"]],
                )
                user.is_active = True
                session.add(user)
                logger.info(
                    f"Successfully created {data['role'].value}: {data['email']}"
                )

        await session.commit()
        logger.info("Seeding process finished.")

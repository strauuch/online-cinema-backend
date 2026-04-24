from abc import ABC, abstractmethod
from database.engine import AsyncPostgresqlSessionLocal


class BaseCommand(ABC):
    @abstractmethod
    async def handle(self, *args, **kwargs):
        pass

    async def run(self, *args, **kwargs):
        async with AsyncPostgresqlSessionLocal() as session:
            await self.handle(session, *args, **kwargs)

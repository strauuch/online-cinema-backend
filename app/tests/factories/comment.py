import uuid
from app.database.models.movies import MovieCommentModel


class CommentFactory:
    def __init__(self, db_session):
        self.db = db_session

    async def create_comment(
        self,
        movie=None,
        movie_id=None,
        user=None,
        user_id=None,
        text: str = None,
        parent_id=None,
    ):

        if movie_id is None and movie is not None:
            movie_id = movie.id
        if movie_id is None:
            raise ValueError("Either 'movie' or 'movie_id' must be provided")

        if user_id is None and user is not None:
            user_id = user.id
        if user_id is None:
            from app.tests.factories.user import UserFactory
            user_factory = UserFactory(self.db)
            temp_user = await user_factory.create_active_user()
            user_id = temp_user.id

        comment = MovieCommentModel(
            movie_id=movie_id,
            user_id=user_id,
            text=text or f"Test comment {uuid.uuid4().hex[:8]}",
            parent_id=parent_id,
        )

        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)
        return comment
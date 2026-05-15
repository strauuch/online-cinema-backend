import uuid

from datetime import datetime
from decimal import Decimal
from sqlalchemy import select, insert

from app.database.models.movies import (
    GenreModel,
    StarModel,
    DirectorModel,
    CertificationModel,
    MovieModel,
    movie_genres,
    movie_stars,
    movie_directors, MovieFavoriteModel, MovieVoteModel, MovieRatingModel, MovieCommentModel,
)


class MovieFactory:
    def __init__(self, db_session):
        self.db = db_session

    async def _ensure_basic_entities(self):
        if not await self.db.scalar(select(CertificationModel)):
            self.db.add(CertificationModel(name="PG-13"))
            self.db.add(CertificationModel(name="R"))
            self.db.add(CertificationModel(name="G"))
            await self.db.commit()

        existing_genres = await self.db.scalars(select(GenreModel.name))
        existing_names = {g for g in existing_genres}
        for name in ["Action", "Drama", "Comedy", "Sci-Fi", "Thriller"]:
            if name not in existing_names:
                self.db.add(GenreModel(name=name))
        await self.db.commit()

        if not await self.db.scalar(select(StarModel)):
            for name in ["Leonardo DiCaprio", "Scarlett Johansson", "Tom Hardy"]:
                self.db.add(StarModel(name=name))
            await self.db.commit()

        if not await self.db.scalar(select(DirectorModel)):
            for name in ["Christopher Nolan", "Denis Villeneuve", "Quentin Tarantino"]:
                self.db.add(DirectorModel(name=name))
            await self.db.commit()

    async def create_genre(self, name: str = None) -> GenreModel:
        await self._ensure_basic_entities()
        if name is None:
            name = f"Genre_{uuid.uuid4().hex[:8]}"

        genre = GenreModel(name=name)
        self.db.add(genre)
        await self.db.commit()
        await self.db.refresh(genre)
        return genre

    async def create_movie(self, **kwargs) -> MovieModel:
        await self._ensure_basic_entities()

        name = kwargs.pop("name", f"Test Movie {uuid.uuid4().hex[:8]}")
        cert = await self.db.scalar(select(CertificationModel))

        movie = MovieModel(
            name=name,
            year=kwargs.pop("year", 2025),
            time=kwargs.pop("time", 130),
            imdb=kwargs.pop("imdb", 7.5),
            votes=kwargs.pop("votes", 120000),
            description=kwargs.pop("description", "A test movie description."),
            price=kwargs.pop("price", Decimal("12.99")),
            certification_id=cert.id,
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ["genres", "stars", "directors"]
            },
        )

        self.db.add(movie)
        await self.db.flush()

        if genres := kwargs.get("genres"):
            for g in genres:
                g_obj = (
                    g
                    if isinstance(g, GenreModel)
                    else await self.db.scalar(
                        select(GenreModel).where(GenreModel.name == g)
                    )
                )
                if g_obj:
                    await self.db.execute(
                        insert(movie_genres).values(
                            movie_id=movie.id, genre_id=g_obj.id
                        )
                    )

        if stars := kwargs.get("stars"):
            for s in stars:
                if isinstance(s, str):
                    star_obj = await self.db.scalar(
                        select(StarModel).where(StarModel.name == s)
                    )
                    if not star_obj:
                        star_obj = StarModel(name=s)
                        self.db.add(star_obj)
                        await self.db.flush()
                else:
                    star_obj = s

                await self.db.execute(
                    insert(movie_stars).values(movie_id=movie.id, star_id=star_obj.id)
                )

        if directors := kwargs.get("directors"):
            for d in directors:
                if isinstance(d, str):
                    dir_obj = await self.db.scalar(
                        select(DirectorModel).where(DirectorModel.name == d)
                    )
                    if not dir_obj:
                        dir_obj = DirectorModel(name=d)
                        self.db.add(dir_obj)
                        await self.db.flush()
                else:
                    dir_obj = d

                await self.db.execute(
                    insert(movie_directors).values(
                        movie_id=movie.id, director_id=dir_obj.id
                    )
                )

        await self.db.commit()
        await self.db.refresh(movie, ["genres", "stars", "directors", "certification"])
        return movie

    async def create_comment(self, movie, user, text: str = None, parent_id=None):
        comment = MovieCommentModel(
            movie_id=movie.id,
            user_id=user.id,
            text=text or f"Test comment {uuid.uuid4().hex[:8]}",
            parent_id=parent_id
        )
        self.db.add(comment)
        await self.db.commit()
        await self.db.refresh(comment)
        return comment

    async def create_rating(self, movie, user, score: int = 8):
        rating = MovieRatingModel(
            movie_id=movie.id,
            user_id=user.id,
            score=score
        )
        self.db.add(rating)
        await self.db.commit()
        return rating

    async def create_vote(self, movie, user, is_like: bool = True):
        vote = MovieVoteModel(
            movie_id=movie.id,
            user_id=user.id,
            is_like=is_like
        )
        self.db.add(vote)
        await self.db.commit()
        return vote

    async def create_favorite(self, movie, user):
        fav = MovieFavoriteModel(user_id=user.id, movie_id=movie.id)
        self.db.add(fav)
        await self.db.commit()
        return fav

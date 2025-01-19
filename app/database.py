from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.future import select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, status
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "postgresql://postgres:95920822@localhost/apis"

engine = create_engine(DATABASE_URL, echo=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
class Base(AsyncAttrs, DeclarativeBase):
    async def save(self, db: Session):
        """
        :param db:
        :return:
        """
        try:
            db.add(self)
            return  db.commit()
        except SQLAlchemyError as ex:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=repr(ex)
            ) from ex

    @classmethod
    async def find_by_id(cls, db: Session, id: str):
        query = select(cls).where(cls.id == id)
        result =  db.execute(query)
        return result.scalars().first()


inspector = inspect(engine)
tables = inspector.get_table_names() 
print(tables)
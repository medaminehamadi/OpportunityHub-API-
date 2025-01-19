from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine
from app.database import Base, SessionLocal 
from app.routers import router

app = FastAPI(
    title="Opportunity Hub API",
    description="API for managing programs, reviews, and opportunities for students.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    conn = psycopg2.connect(
        host='localhost',
        database='apisc',  
        user='postgres',
        password='toor',
        cursor_factory=RealDictCursor
    )
    cursor = conn.cursor()
    print("Database connection was successful!")
except Exception as error:
    print("Connecting to the database failed.")
    print("Error:", error)

DATABASE_URL = "postgresql://postgres:95920822@localhost/apis"
engine = create_engine(DATABASE_URL, echo=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app.include_router(router)


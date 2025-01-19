import datetime
import enum
from sqlalchemy import UUID, Boolean, Column, DateTime, Integer, String, ForeignKey, Text, Float, select
from passlib.context import CryptContext
from sqlalchemy.orm import relationship, Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from app.auth.hash import verify_password
from app.utils import utcnow
from app.database import Base
import uuid
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
class UserType(str, enum.Enum):
        STUDENT = "student"
        PARTNER = "partner"

class User(Base):
        __tablename__ = "users"
        id: Mapped[uuid.UUID] = mapped_column(
            primary_key=True, index=True, default=uuid.uuid4
        )
        email: Mapped[str] = mapped_column(unique=True, index=True)
        full_name: Mapped[str]
        password: Mapped[str]
        is_active: Mapped[bool] = mapped_column(default=True)
        created_at: Mapped[datetime.datetime] = mapped_column(server_default=utcnow())
        updated_at: Mapped[datetime.datetime] = mapped_column(
            server_default=utcnow(), server_onupdate=utcnow(), onupdate=utcnow()
        )
        user_type: Mapped[UserType] = mapped_column(default=UserType.STUDENT)

        @classmethod
        async def find_by_email(cls, db: Session, email: str):
            query = select(cls).where(cls.email == email)
            result = db.execute(query)
            return result.scalar_one_or_none()

        @classmethod
        async def authenticate(cls, db: AsyncSession, email: str, password: str):
            user = await cls.find_by_email(db=db, email=email)
            if not user or not verify_password(password, user.password):
                return False
            return user
        student_details = relationship("Student", back_populates="user", uselist=False)
        partner_details = relationship("Partner", back_populates="user", uselist=False)

class BlackListToken(Base):
    __tablename__ = "blacklisttokens"
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    expire: Mapped[datetime.datetime]
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=utcnow())

class Student(Base):
    __tablename__ = "students"
    id: Mapped[uuid.UUID] = mapped_column(
            primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # Changed to UUID
    university = Column(String)
    username = Column(String)
    user = relationship("User", back_populates="student_details")
    interested = Column(String, nullable=True, unique=True, default="")

class Scholarship(Base):
    __tablename__ = "scholarships"
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, index=True, default=uuid.uuid4
    )
    title = Column(String)
    description = Column(Text)
    location = Column(String)
    application_link = Column(String)
    field_of_study = Column(String)
    funding_type = Column(String)
    funding_amount = Column(Float)
    duration = Column(Integer)
    status = Column(String, default="open")

    partner_id = Column(UUID(as_uuid=True), ForeignKey("partners.id"))
    partner = relationship("Partner", back_populates="scholarship_details")

    feedbacks = relationship(
        "Feedback", 
        cascade="all, delete-orphan", 
        backref="scholarship"
    )
    


    

class Partner(Base):
    __tablename__ = "partners"
    id: Mapped[uuid.UUID] = mapped_column(
            primary_key=True, index=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # Changed to UUID
    phone_number = Column(String)
    website = Column(String)
    address = Column(String)
    country = Column(String)
    user = relationship("User", back_populates="partner_details")

    scholarship_details = relationship("Scholarship", back_populates="partner", lazy="subquery")


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scholarship_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("scholarships.id", ondelete="CASCADE"), 
        nullable=False
    )
    student_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("students.id", ondelete="CASCADE"), 
        nullable=False
    )
    rating = Column(Integer, nullable=False)  # Rating out of 5
    review = Column(String, nullable=True)  # Review text
    tips_on_applying = Column(String, nullable=True)  # Tips on applying for the scholarship
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    likes_count = Column(Integer, default=0)

    likes = relationship("Likes", back_populates="feedback")



class Likes(Base):
    __tablename__ = "likes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback.id"), nullable=False)

    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    feedback = relationship("Feedback", back_populates="likes")


    
class Discussion(Base):
    __tablename__ = "discussions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, unique=True) 
    scholarship_id = Column(String, nullable=False, unique=True)  # One discussion per scholarship
    channel_id = Column(String, nullable=False)  # Discord channel ID



class Tip(Base):
    __tablename__ = "tips"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String)
    content = Column(Text)
    scholarship_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("scholarships.id", ondelete="CASCADE"), 
        nullable=False
    )
    user_id = Column(String, nullable=False)
    date_shared = Column(DateTime)


class CountryRequirement(Base):
    __tablename__ = "country_requirements"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, index=True, default=uuid.uuid4)
    country = Column(String, nullable=False)
    document_type = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    mandatory = Column(Boolean, default=True)



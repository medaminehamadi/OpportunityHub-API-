from asyncio.log import logger
from typing import Annotated, List
from datetime import datetime
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    BackgroundTasks,
    Request,
    Response,
    Cookie,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
import requests
from sqlalchemy import UUID, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from pydantic import UUID4, BaseModel, ValidationError
from app import schemas, models
from app.auth import jwt
from app.auth.hash import get_password_hash, verify_password
from app.auth.jwt import (
    create_token_pair,
    refresh_token_state,
    decode_access_token,
    SUB,
    JTI,
    EXP,
)
from app.database import get_db
from app.exceptions import BadRequestException, NotFoundException
router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
from fastapi.security import OAuth2PasswordRequestForm
class TokenData(BaseModel):
    user_id: str
    user_type: str  # 'PARTNER', 'STUDENT', etc.

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    try:
        logger.info(f"Received token: {token}")

        payload = await jwt.decode_access_token(token, db)
        logger.info(f"Decoded token payload: {payload}")
        
        user = TokenData(**payload)  # Parse user data from the token
        logger.info(f"User data parsed from token: {user}")
        
        return user
    except JWTError:
        logger.error("Invalid token error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

#users
@router.post("/register", response_model=schemas.User,tags=["users"])
async def register(
    data: schemas.UserRegister,
    bg_task: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Hash password and prepare user data
    user_data = data.dict(exclude={"confirm_password", "university", "username", "phone_number", "website", "address", "country"})
    user_data["password"] = get_password_hash(user_data["password"])
    user_data["user_type"] = data.user_type if data.user_type else "student"

    # Create the user
    user = models.User(**user_data)
    user.is_active = False
    await user.save(db=db)

    # Create student or partner based on the user_type
    if user.user_type == models.UserType.STUDENT:
        student_data = schemas.StudentCreate(user_id=user.id, university=data.university, username=data.username)
        student = models.Student(**student_data.dict())
        db.add(student)
        db.commit()

    elif user.user_type == models.UserType.PARTNER:
        partner_data = schemas.PartnerCreate(user_id=user.id, phone_number=data.phone_number, website=data.website, address=data.address, country=data.country)
        partner = models.Partner(**partner_data.dict())
        db.add(partner)
        db.commit()

    return schemas.User.from_orm(user)


@router.post("/login", tags=["users"])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),  # Handles username/password and grant_type
    db: AsyncSession = Depends(get_db),
):
    # Authenticate user
    user = await models.User.authenticate(
        db=db, email=form_data.username, password=form_data.password
    )

    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    # Generate token pair
    token_pair = create_token_pair(user=schemas.User.from_orm(user))

    return {
        "access_token": token_pair.access.token,
        "refresh_token": token_pair.refresh.token,  # Include refresh token in the response
        "token_type": "bearer",
    }


@router.post("/refresh",tags=["users"])
async def refresh(refresh: Annotated[str | None, Cookie()] = None):
    print(refresh)
    if not refresh:
        raise BadRequestException(detail="refresh token required")
    return refresh_token_state(token=refresh)

@router.post("/logout", response_model=schemas.SuccessResponseScheme,tags=["users"])
async def logout(
    token: Annotated[str, Depends(oauth2_scheme)],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    payload = await decode_access_token(token=token, db=db)
    black_listed = models.BlackListToken(
        id=payload[JTI], expire=datetime.utcfromtimestamp(payload[EXP])
    )
    await black_listed.save(db=db)
    return {"msg": "Successfully logged out"}

@router.post("/password-reset", response_model=schemas.SuccessResponseScheme,tags=["users"])
async def password_reset_token(
    token: str,
    data: schemas.PasswordResetSchema,
    db: AsyncSession = Depends(get_db),
):
    payload = await decode_access_token(token=token, db=db)
    user = await models.User.find_by_id(db=db, id=payload[SUB])
    if not user:
        raise NotFoundException(detail="User not found")

    user.password = get_password_hash(data.password)
    await user.save(db=db)

    return {"msg": "Password succesfully updated"}

@router.post("/password-update", response_model=schemas.SuccessResponseScheme,tags=["users"])
async def password_update(
    token: Annotated[str, Depends(oauth2_scheme)],
    data: schemas.PasswordUpdateSchema,
    db: AsyncSession = Depends(get_db),
):
    payload = await decode_access_token(token=token, db=db)
    user = await models.User.find_by_id(db=db, id=payload[SUB])
    if not user:
        raise NotFoundException(detail="User not found")

    # raise Validation error
    if not verify_password(data.old_password, user.password):
        try:
            schemas.OldPasswordErrorSchema(old_password=False)
        except ValidationError as e:
            raise RequestValidationError(e.raw_errors)
    user.password = get_password_hash(data.password)
    await user.save(db=db)

    return {"msg": "Successfully updated"}

#Programs
@router.post("/Programs/",tags=["Programs"])
async def create_scholarship(
    scholarship_data: schemas.ScholarshipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.user_type != 'partner':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to add scholarships"
        )
    
    partner = db.execute(
        select(models.Partner).filter(models.Partner.user_id == current_user.user_id)
    )
    partner = partner.scalars().first()
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found"
        )
    
    scholarship = models.Scholarship(
        title=scholarship_data.title,
        description=scholarship_data.description,
        location=scholarship_data.location,
        application_link=scholarship_data.application_link,
        field_of_study=scholarship_data.field_of_study,
        funding_type=scholarship_data.funding_type,
        funding_amount=scholarship_data.funding_amount,
        duration=scholarship_data.duration,
        status=scholarship_data.status,
        partner_id=partner.id  # Associate the scholarship with the partner
    )
    
    db.add(scholarship)
    db.commit()
    db.refresh(scholarship)
    return scholarship

@router.get("/api/Programs",tags=["Programs"])
async def get_scholarships(db: AsyncSession = Depends(get_db)):
    try:
        result = db.execute(select(models.Scholarship))
        scholarships = result.scalars().all()
        return scholarships
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/Programs/filters",tags=["Programs"])
async def get_scholarships_by_filters(
    location: str = None,
    field_of_study: str = None,
    funding_type: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(models.Scholarship)
    if location:
        query = query.filter(models.Scholarship.location == location)
    if field_of_study:
        query = query.filter(models.Scholarship.field_of_study == field_of_study)
    if funding_type:
        query = query.filter(models.Scholarship.funding_type == funding_type)
    
    scholarships =  db.execute(query)
    return scholarships.scalars().all()

@router.get("/api/Programs/{id}",tags=["Programs"])
async def get_scholarship(id: UUID4, db: AsyncSession = Depends(get_db)):
    scholarship =  db.execute(select(models.Scholarship).filter(models.Scholarship.id == id))
    scholarship = scholarship.scalars().first()
    if not scholarship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scholarship not found")
    return scholarship
@router.put("/api/Program/{id}", response_model=schemas.ScholarshipCreate,tags=["Programs"])
async def update_scholarship(
    id: UUID4,
    scholarship_data: schemas.ScholarshipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    scholarship =  db.execute(select(models.Scholarship).filter(models.Scholarship.id == id))
    scholarship = scholarship.scalars().first()
    if not scholarship:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scholarship not found")

    if current_user.user_type != 'partner' :
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to update this scholarship")

    for key, value in scholarship_data.dict(exclude_unset=True).items():
        setattr(scholarship, key, value)

    db.commit()
    db.refresh(scholarship)
    return scholarship

@router.delete("/api/Programs/{id}", tags=["Programs"])
def delete_scholarship(
    id: UUID4,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user)
):
    scholarship_query = db.execute(
        select(models.Scholarship).filter(models.Scholarship.id == id)
    )
    scholarship = scholarship_query.scalars().first()

    if not scholarship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scholarship not found"
        )

    # Authorization check 
    if current_user.user_type != "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this scholarship"
        )

    
    db.delete(scholarship)
    db.commit()

    return {"message": "Scholarship deleted successfully"}

#Reviews 
import random

@router.post("/Reviews/", tags=["Reviews"])
def create_feedback(
    feedback_data: schemas.FeedbackCreate,
    db: Session = Depends(get_db),  # Use a synchronous `Session`
    current_user: TokenData = Depends(get_current_user),
):
    # Retrieve the student record
    student_query = db.execute(
        select(models.Student).filter(models.Student.user_id == current_user.user_id)
    )
    student = student_query.scalars().first()
    
    # Assign a random student ID if no student is found
    if not student:
        random_student_query = db.execute(select(models.Student.id))
        random_student_ids = random_student_query.scalars().all()
        if not random_student_ids:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No students found in the database"
            )
        student_id = random.choice(random_student_ids)
    else:
        student_id = student.id
    
    # Retrieve the scholarship record
    scholarship_query = db.execute(
        select(models.Scholarship).filter(models.Scholarship.id == feedback_data.scholarship_id)
    )
    scholarship = scholarship_query.scalars().first()
    if not scholarship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scholarship not found"
        )
    
    # Create the feedback record
    feedback = models.Feedback(
        scholarship_id=feedback_data.scholarship_id,
        student_id=student_id,  # Use the assigned or retrieved student ID
        rating=feedback_data.rating,
        review=feedback_data.review,
        tips_on_applying=feedback_data.tips_on_applying,
        likes_count=0,
        created_at=datetime.utcnow(),
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback

@router.get("/api/Reviews/{scholarship_id}",tags=["Reviews"])
async def get_feedback(id: UUID4, db: AsyncSession = Depends(get_db)):
    feedback =  db.execute(select(models.Feedback).filter(models.Feedback.scholarship_id == id))
    feedback = feedback.scalars().first()
    if not feedback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scholarship not found")
    return feedback

@router.delete("/api/Reviews/{id}",tags=["Reviews"])
async def delete_feedback(id: UUID4, db: AsyncSession = Depends(get_db),current_user: TokenData = Depends(get_current_user),):
    
    feedback = db.execute(select(models.Feedback).filter(models.Feedback.id == id))
    feedback = feedback.scalars().first()
    
    if not feedback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
   
    if current_user.user_type != "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this scholarship"
        )

   
    db.execute(delete(models.Likes).filter(models.Likes.feedback_id == id))
    
   
    db.delete(feedback)
    db.commit()  # Commit the transaction
    
    return {"message": "Feedback deleted successfully"}
@router.post("/Reviews/{feedback_id}/like",tags=["Reviews"])
async def add_like(
    feedback_id: UUID4,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
   
    feedback_query = db.execute(
        select(models.Feedback).filter(models.Feedback.id == feedback_id)
    )
    feedback = feedback_query.scalars().first()
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found"
        )

    
    student_query = db.execute(
        select(models.Student).filter(models.Student.user_id == current_user.user_id)
    )
    student = student_query.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found for the current user"
        )

    
    like_query = db.execute(
        select(models.Likes).filter(
            models.Likes.feedback_id == feedback_id,
            models.Likes.student_id == student.id,
        )
    )
    existing_like = like_query.scalars().first()
    if existing_like:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already liked this feedback"
        )

    
    like = models.Likes(
        feedback_id=feedback_id,
        student_id=student.id
    )
    db.add(like)

    
    feedback.likes_count += 1
    db.commit()
    db.refresh(feedback)

    return {"message": "Like added successfully", "likes_count": models.Feedback.likes_count}



#Discussions


class Scholarship(BaseModel):
    id: str
    title: str

@router.post("/create-channel/", tags=["Discussions"])
async def create_channel(
    scholarship: Scholarship, 
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),  # Authorization handled here
):
    """
    Create a Discord channel for a scholarship or retrieve the existing one.
    """
    # Check if a discussion already exists for the scholarship
    existing_discussion = db.query(models.Discussion).filter(
        models.Discussion.scholarship_id == scholarship.id
    ).first()
    
    if existing_discussion:
        # If the channel already exists, return the link
        channel_id = existing_discussion.channel_id
        channel_link = f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_id}"
        return {"status": "Channel already exists", "channel_link": channel_link}
    
    # Create a new Discord channel
    url = f"https://discord.com/api/v10/guilds/{DISCORD_GUILD_ID}/channels"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": scholarship.title.replace(" ", "-").lower(),  # Channel name
        "type": 0,  # Text channel
        "topic": f"Discussion channel for {scholarship.title}"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 201:
        # Save the new discussion to the database
        channel_data = response.json()
        new_discussion = models.Discussion(
            user_id=current_user.user_id,  # Link the discussion to the user
            scholarship_id=scholarship.id,  # Link the discussion to the scholarship
            channel_id=channel_data["id"],  # Discord channel ID
        )
        db.add(new_discussion)
        db.commit()
        
        # Return the newly created channel's link
        channel_link = f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_data['id']}"
        return {"status": "Channel created", "channel_link": channel_link}
    else:
        # Handle Discord API errors
        raise HTTPException(status_code=response.status_code, detail=response.json())

@router.get("/discussions/{scholarship_id}", tags=["Discussions"])
async def get_discussion_by_scholarship_id(
    scholarship_id: str,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),  # Authorization handled here
):
    
    
    scholarship = db.query(models.Scholarship).filter(
        models.Scholarship.id == scholarship_id
    ).first()
    
    if not scholarship:
        raise HTTPException(
            status_code=404,
            detail="Scholarship not found"
        )
    
    existing_discussion = db.query(models.Discussion).filter(
        models.Discussion.scholarship_id == scholarship_id
    ).first()
    
    if not existing_discussion:
        raise HTTPException(
            status_code=404,
            detail="No discussion found for the specified scholarship"
        )
    
    # Return the discussion link
    channel_id = existing_discussion.channel_id
    channel_link = f"https://discord.com/channels/{DISCORD_GUILD_ID}/{channel_id}"
    return {"status": "Discussion found", "channel_link": channel_link}

@router.post("/Programs/mark-interest/{scholarship_id}",tags=["Programs"])
async def add_interest(
    scholarship_id: str,  
    db: AsyncSession = Depends(get_db),  
    current_user: TokenData = Depends(get_current_user),  
):

    student = db.execute(select(models.Student).filter(models.Student.user_id == current_user.user_id))
    student = student.scalars().first()

    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

   

    student.interested = scholarship_id
  
    db.commit()

    return {"message": "Interest successfully marked"}





#requirements
@router.post("/requirements", tags=["Requirements"])
def add_country_requirement(
    requirement: schemas.CountryRequirementsCreate,  # Accept a list of requirements
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.user_type != "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this scholarship"
        )
    try:
        
        for req in requirement.requirements:
            new_requirement = models.CountryRequirement(
                country=requirement.country,  
                document_type=req.document_type,
                description=req.description,
                mandatory=req.mandatory,
            )
            db.add(new_requirement)
        
        
        db.commit()
        
        # If successful, return the list of created requirements
        db.refresh(new_requirement)
        return {"status": "Requirements added successfully.", "country": requirement.country}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@router.get("/requirements/{country}", tags=["Requirements"])
def get_requirements_by_country(
    country: str,
    db: Session = Depends(get_db),
):
    result = db.execute(
        select(models.CountryRequirement).filter(models.CountryRequirement.country.ilike(country))
    )
    requirements = result.scalars().all()
    if not requirements:
        raise HTTPException(
            status_code=404, detail=f"No requirements found for the country: {country}"
        )
    return requirements
@router.put("/requirements/{requirement_id}", tags=["Requirements"], response_model=schemas.CountryRequirementResponse)
def update_country_requirement(
    requirement_id: UUID4,  
    updated_data: schemas.CountryRequirementUpdate,  
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    requirement = db.query(models.CountryRequirement).filter(models.CountryRequirement.id == requirement_id).first()
    if not requirement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement with ID {requirement_id} not found",
        )
    if current_user.user_type != "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this scholarship"
        )

    
    for key, value in updated_data.dict(exclude_unset=True).items():
        setattr(requirement, key, value)
    
    try:
        db.commit()
        db.refresh(requirement)
        return requirement  
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )

@router.delete("/requirements/{requirement_id}", tags=["Requirements"], response_model=schemas.CountryRequirementResponse)
def delete_country_requirement(
    requirement_id: UUID4,  
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    requirement = db.query(models.CountryRequirement).filter(models.CountryRequirement.id == requirement_id).first()
    if current_user.user_type != "partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this scholarship"
        )
    if not requirement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement with ID {requirement_id} not found",
        )
    
    try:
        db.delete(requirement)
        db.commit()

        return schemas.CountryRequirementResponse(**requirement.__dict__)  
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}",
        )


#tips
@router.post("/tips", tags=["Tips"])
async def create_tip(
    tip_data: schemas.TipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    
    if current_user.user_type not in ["student", "partner"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to share tips"
        )
    
    
    scholarship = db.execute(
        select(models.Scholarship).filter(models.Scholarship.id == tip_data.scholarship_id)
    )
    scholarship = scholarship.scalars().first()
    if not scholarship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scholarship not found"
        )

    
    tip = models.Tip(
        title=tip_data.title,
        content=tip_data.content,
        scholarship_id=tip_data.scholarship_id,
        user_id=current_user.user_id,  
        date_shared=datetime.utcnow()
    )

    db.add(tip)
    db.commit()
    db.refresh(tip)

    return {"message": "Tip successfully shared", "tip_id": tip.id}
@router.get("/tips/{scholarship_id}", tags=["Tips"], response_model=List[schemas.TipResponse])
async def get_tips_by_scholarship(
    scholarship_id: UUID4,
    db: AsyncSession = Depends(get_db),
):
    
    result =  db.execute(
        select(models.Tip).filter(models.Tip.scholarship_id == scholarship_id)
    )
    tips = result.scalars().all()

    if not tips:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tips found for the scholarship ID: {scholarship_id}"
        )

    return tips


@router.put("/tips/{tip_id}", tags=["Tips"])
async def update_tip(
    tip_id: UUID4,
    update_data: schemas.TipUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Update an existing tip. Only the user who created the tip can update it.
    """
   
    result = db.execute(
        select(models.Tip).filter(models.Tip.id == tip_id)
    )
    tip = result.scalars().first()
    

    if not tip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tip with ID {tip_id} not found"
        )

    
    if tip.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to update this tip"
        )

    
    if update_data.title is not None:
        tip.title = update_data.title
    if update_data.content is not None:
        tip.content = update_data.content

    
    db.commit()
    db.refresh(tip)

    return {"message": "Tip successfully updated", "tip_id": tip.id}

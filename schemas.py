from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    class Config:
        from_attributes = True

class MediaItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    release_year: Optional[int] = None
    media_type: str
    poster_url: Optional[str] = None
    background_url: Optional[str] = None
    trailer_url: Optional[str] = None
    imdb_rating: Optional[float] = None

class MediaItemResponse(MediaItemCreate):
    id: int
    class Config:
        from_attributes = True

class UserCollectionCreate(BaseModel):
    media_id: int
    status: str
    rating: Optional[float] = None
    review: Optional[str] = None

class UserCollectionUpdate(BaseModel):
    status: str
    rating: Optional[float] = None
    review: Optional[str] = None

class UserCollectionResponse(UserCollectionCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True

# СХЕМИ ДЛЯ КОМЕНТАРІВ
class CommentCreate(BaseModel):
    media_id: int
    text: str

class CommentResponse(BaseModel):
    id: int
    text: str
    created_at: datetime
    username: str
    class Config:
        from_attributes = True
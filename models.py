from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    
    collections = relationship("UserCollection", back_populates="user")
    comments = relationship("Comment", back_populates="user")
    created_media = relationship("MediaItem", back_populates="owner")

class MediaItem(Base):
    __tablename__ = "media_items"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String, nullable=True)
    release_year = Column(Integer, nullable=True)
    media_type = Column(String)
    
    # --- НОВІ МЕТАДАНІ ДЛЯ РІВНЯ IMDb ---
    genre = Column(String, nullable=True)     # Жанр (наприклад: Sci-Fi, Комедія)
    country = Column(String, nullable=True)   # Країна
    actors = Column(String, nullable=True)    # Режисер / Актори
    
    poster_url = Column(String, nullable=True)
    background_url = Column(String, nullable=True)
    trailer_url = Column(String, nullable=True)
    imdb_rating = Column(Float, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    owner = relationship("User", back_populates="created_media")
    collections = relationship("UserCollection", back_populates="media_item", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="media_item", cascade="all, delete-orphan")

class UserCollection(Base):
    __tablename__ = "user_collections"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    media_id = Column(Integer, ForeignKey("media_items.id"))
    status = Column(String, default="В планах")
    rating = Column(Float, nullable=True)
    review = Column(String, nullable=True)

    user = relationship("User", back_populates="collections")
    media_item = relationship("MediaItem", back_populates="collections")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String)
    karma = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, ForeignKey("users.id"))
    media_id = Column(Integer, ForeignKey("media_items.id"))

    user = relationship("User", back_populates="comments")
    media_item = relationship("MediaItem", back_populates="comments")
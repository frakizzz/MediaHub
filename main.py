from fastapi import Request, UploadFile, File
from fastapi.responses import HTMLResponse 
from fastapi.templating import Jinja2Templates 
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt
from jwt.exceptions import InvalidTokenError
from datetime import datetime, timedelta, timezone
import bcrypt
import os
import uuid
import shutil

from database import engine, Base, get_db
import models, schemas

app = FastAPI(title="Інформаційна система управління мультимедійним контентом", version="1.0")

# --- СТАТИКА ТА ТЕМПЛЕЙТИ ---
templates = Jinja2Templates(directory="templates")
# Дозволяємо серверу показувати картинки з папки static
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- БЕЗПЕКА ТА ТОКЕНИ ---
SECRET_KEY = "super_secret_diploma_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_password_hash(password: str):
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_bytes.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не вдалося перевірити облікові дані",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception
    
    result = await db.execute(select(models.User).where(models.User.username == username))
    user = result.scalars().first()
    if user is None: raise credentials_exception
    return user

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- МАРШРУТИ ---
@app.get("/", response_class=HTMLResponse, tags=["Фронтенд"])
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# --- ЗАВАНТАЖЕННЯ ФАЙЛІВ ---
@app.post("/upload-image/", tags=["Файли"])
async def upload_image(file: UploadFile = File(...)):
    # Генеруємо унікальне ім'я для картинки
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = f"static/uploads/{filename}"
    
    # Зберігаємо файл
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Повертаємо URL для бази даних
    return {"url": f"/{file_path}"}

@app.post("/login", response_model=schemas.Token, tags=["Авторизація"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.User).where(models.User.username == form_data.username))
    user = result.scalars().first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неправильний логін або пароль")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/", response_model=schemas.UserResponse, tags=["Авторизація"])
async def create_user(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    result_email = await db.execute(select(models.User).where(models.User.email == user.email))
    if result_email.scalars().first(): raise HTTPException(status_code=400, detail="Цей email вже існує")
    result_username = await db.execute(select(models.User).where(models.User.username == user.username))
    if result_username.scalars().first(): raise HTTPException(status_code=400, detail="Цей нікнейм зайнятий")

    hashed_password = get_password_hash(user.password)
    new_user = models.User(username=user.username, email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@app.post("/media/", response_model=schemas.MediaItemResponse, tags=["Контент бази"])
async def create_media(media: schemas.MediaItemCreate, db: AsyncSession = Depends(get_db)):
    new_media = models.MediaItem(**media.model_dump())
    db.add(new_media)
    await db.commit()
    await db.refresh(new_media)
    return new_media

@app.get("/media/", response_model=list[schemas.MediaItemResponse], tags=["Контент бази"])
async def get_all_media(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.MediaItem))
    return result.scalars().all()

@app.post("/collection/", response_model=schemas.UserCollectionResponse, tags=["Моя колекція"])
async def add_to_collection(item: schemas.UserCollectionCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result_media = await db.execute(select(models.MediaItem).where(models.MediaItem.id == item.media_id))
    if not result_media.scalars().first(): raise HTTPException(status_code=404, detail="Контент не знайдено")
    
    result_col = await db.execute(select(models.UserCollection).where(models.UserCollection.user_id == current_user.id, models.UserCollection.media_id == item.media_id))
    if result_col.scalars().first(): raise HTTPException(status_code=400, detail="Вже є у колекції")

    new_col_item = models.UserCollection(user_id=current_user.id, media_id=item.media_id, status=item.status, rating=item.rating, review=item.review)
    db.add(new_col_item)
    await db.commit()
    await db.refresh(new_col_item)
    return new_col_item

@app.get("/collection/", response_model=list[schemas.UserCollectionResponse], tags=["Моя колекція"])
async def get_my_collection(current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.UserCollection).where(models.UserCollection.user_id == current_user.id))
    return result.scalars().all()

@app.put("/collection/{item_id}", response_model=schemas.UserCollectionResponse, tags=["Моя колекція"])
async def update_collection_item(item_id: int, item_data: schemas.UserCollectionUpdate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.UserCollection).where(models.UserCollection.id == item_id, models.UserCollection.user_id == current_user.id))
    item = result.scalars().first()
    if not item: raise HTTPException(status_code=404, detail="Запис не знайдено у вашій колекції")
    
    item.status = item_data.status
    item.rating = item_data.rating
    item.review = item_data.review
    await db.commit()
    await db.refresh(item)
    return item

@app.delete("/collection/{item_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Моя колекція"])
async def delete_collection_item(item_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.UserCollection).where(models.UserCollection.id == item_id, models.UserCollection.user_id == current_user.id))
    item = result.scalars().first()
    if not item: raise HTTPException(status_code=404, detail="Запис не знайдено у вашій колекції")
    
    await db.delete(item)
    await db.commit()

@app.get("/media/{media_id}/details", tags=["Деталі контенту"])
async def get_media_details(media_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Шукаємо фільм
    result_media = await db.execute(select(models.MediaItem).where(models.MediaItem.id == media_id))
    media = result_media.scalars().first()
    if not media: raise HTTPException(status_code=404, detail="Контент не знайдено")

    # 2. Вираховуємо рейтинг MediaHub (середнє арифметичне всіх оцінок користувачів)
    result_ratings = await db.execute(select(models.UserCollection.rating).where(models.UserCollection.media_id == media_id, models.UserCollection.rating.isnot(None)))
    ratings = result_ratings.scalars().all()
    site_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    # 3. Підтягуємо всі коментарі кімнати
    result_comments = await db.execute(
        select(models.Comment, models.User.username)
        .join(models.User)
        .where(models.Comment.media_id == media_id)
        .order_by(models.Comment.created_at.desc())
    )
    comments = [{"id": c[0].id, "text": c[0].text, "created_at": c[0].created_at, "username": c[1]} for c in result_comments.all()]

    return {
        "media": media,
        "site_rating": site_rating,
        "comments": comments
    }

@app.post("/comments/", tags=["Деталі контенту"])
async def post_comment(comment: schemas.CommentCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_comment = models.Comment(text=comment.text, media_id=comment.media_id, user_id=current_user.id)
    db.add(new_comment)
    await db.commit()
    return {"message": "Коментар додано"}
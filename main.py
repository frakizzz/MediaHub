from fastapi import Request, UploadFile, File, FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse 
from fastapi.templating import Jinja2Templates 
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import jwt
from jwt.exceptions import InvalidTokenError
from datetime import datetime, timedelta, timezone
import bcrypt
import os
import uuid
import shutil
from sqlalchemy import or_

from database import engine, Base, get_db
import models, schemas

app = FastAPI(title="Інформаційна система управління мультимедійним контентом", version="1.0")

# --- СТАТИКА ТА ТЕМПЛЕЙТИ ---
templates = Jinja2Templates(directory="templates")
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

# --- МАРШРУТИ ФРОНТЕНДУ ---
@app.get("/", response_class=HTMLResponse, tags=["Фронтенд"])
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# --- ЗАВАНТАЖЕННЯ ФАЙЛІВ ---
@app.post("/upload-image/", tags=["Файли"])
async def upload_image(file: UploadFile = File(...)):
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = f"static/uploads/{filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/{file_path}"}

# --- АВТОРИЗАЦІЯ ---
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

# --- ГЛОБАЛЬНИЙ КАТАЛОГ (З ПОШУКОМ, ФІЛЬТРАМИ ТА СОРТУВАННЯМ) ---
@app.post("/media/", response_model=schemas.MediaItemResponse, tags=["Контент бази"])
async def create_media(media: schemas.MediaItemCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_media = models.MediaItem(**media.model_dump(), owner_id=current_user.id)
    db.add(new_media)
    await db.commit()
    await db.refresh(new_media)
    return new_media

@app.get("/media/", response_model=list[schemas.MediaItemResponse], tags=["Контент бази"])
async def get_all_media(q: str = None, type: str = None, sort: str = None, db: AsyncSession = Depends(get_db)):
    query = select(models.MediaItem)
    if q:
        # ТЕПЕР ШУКАЄ ТАКОЖ ЗА АКТОРСЬКИМ СКЛАДОМ ТА ЖАНРОМ!
        query = query.where(
            or_(
                models.MediaItem.title.ilike(f"%{q}%"),
                models.MediaItem.actors.ilike(f"%{q}%"),
                models.MediaItem.genre.ilike(f"%{q}%")
            )
        )
    if type and type != "Всі":
        query = query.where(models.MediaItem.media_type == type)
    
    if sort == "imdb":
        query = query.order_by(models.MediaItem.imdb_rating.desc())
    elif sort == "year":
        query = query.order_by(models.MediaItem.release_year.desc())
    else:
        query = query.order_by(models.MediaItem.id.desc())
        
    result = await db.execute(query)
    return result.scalars().all()

@app.put("/media/{media_id}", response_model=schemas.MediaItemResponse, tags=["Контент бази"])
async def update_media_item(media_id: int, media_data: schemas.MediaItemCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.MediaItem).where(models.MediaItem.id == media_id))
    item = result.scalars().first()
    if not item: raise HTTPException(status_code=404, detail="Контент не знайдено")
    if item.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Ви не є власником цього релізу!")
    
    for key, value in media_data.model_dump().items():
        setattr(item, key, value)
        
    await db.commit()
    await db.refresh(item)
    return item

@app.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Контент бази"])
async def delete_media_item(media_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.MediaItem).where(models.MediaItem.id == media_id))
    item = result.scalars().first()
    if not item: raise HTTPException(status_code=404, detail="Контент не знайдено")
    if item.owner_id != current_user.id: raise HTTPException(status_code=403, detail="Доступ заборонено")
    await db.delete(item)
    await db.commit()

# --- СТОРІНКА ФІЛЬМУ ТА REDDIT-КІМНАТИ ---
@app.get("/media/{media_id}/details", tags=["Деталі контенту"])
async def get_media_details(media_id: int, db: AsyncSession = Depends(get_db)):
    result_media = await db.execute(select(models.MediaItem).where(models.MediaItem.id == media_id))
    media = result_media.scalars().first()
    if not media: raise HTTPException(status_code=404, detail="Контент не знайдено")

    result_ratings = await db.execute(select(models.UserCollection.rating).where(models.UserCollection.media_id == media_id, models.UserCollection.rating.isnot(None)))
    ratings = result_ratings.scalars().all()
    site_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    # АЛГОРИТМ "СХОЖИЙ КОНТЕНТ": Шукаємо 4 релізи того ж жанру (але не цей самий фільм)
    similar_media = []
    if media.genre:
        first_genre = media.genre.split(',')[0].strip() # Беремо перший жанр, якщо їх кілька
        res_similar = await db.execute(
            select(models.MediaItem)
            .where(models.MediaItem.genre.ilike(f"%{first_genre}%"), models.MediaItem.id != media_id)
            .limit(4)
        )
        # Перетворюємо об'єкти на словники для зручної відправки
        similar_media = [{"id": s.id, "title": s.title, "poster_url": s.poster_url, "release_year": s.release_year} for s in res_similar.scalars().all()]

    result_comments = await db.execute(
        select(models.Comment, models.User.username)
        .join(models.User)
        .where(models.Comment.media_id == media_id)
        .order_by(models.Comment.karma.desc(), models.Comment.created_at.desc())
    )
    comments = [{"id": c[0].id, "text": c[0].text, "created_at": c[0].created_at, "karma": c[0].karma or 0, "username": c[1]} for c in result_comments.all()]

    return {
        "media": media, 
        "site_rating": site_rating, 
        "comments": comments,
        "similar": similar_media # ВІДДАЄМО СХОЖИЙ КОНТЕНТ НА ФРОНТЕНД
    }

@app.post("/comments/", tags=["Деталі контенту"])
async def post_comment(comment: schemas.CommentCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    new_comment = models.Comment(text=comment.text, media_id=comment.media_id, user_id=current_user.id, karma=0)
    db.add(new_comment)
    await db.commit()
    return {"message": "Коментар додано"}

@app.post("/comments/{comment_id}/vote", tags=["Деталі контенту"])
async def vote_comment(comment_id: int, direction: str, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Comment).where(models.Comment.id == comment_id))
    comment = result.scalars().first()
    if not comment: raise HTTPException(status_code=404, detail="Коментар не знайдено")
    
    comment.karma = (comment.karma or 0) + (1 if direction == "up" else -1)
    await db.commit()
    return {"karma": comment.karma}

# --- ОСОБИСТА МЕДІАТЕКА ---
@app.post("/collection/", response_model=schemas.UserCollectionResponse, tags=["Моя колекція"])
async def add_to_collection(item: schemas.UserCollectionCreate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result_col = await db.execute(select(models.UserCollection).where(models.UserCollection.user_id == current_user.id, models.UserCollection.media_id == item.media_id))
    if result_col.scalars().first(): raise HTTPException(status_code=400, detail="Вже є у вашій медіатеці")

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
    if not item: raise HTTPException(status_code=404, detail="Запис не знайдено")
    
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
    if not item: raise HTTPException(status_code=404, detail="Запис не знайдено")
    await db.delete(item)
    await db.commit()

# --- ОСОБИСТА СТАТИСТИКА КАБІНЕТУ ---
@app.get("/profile/", tags=["Особистий кабінет"])
async def get_my_profile(current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    res_added = await db.execute(select(func.count(models.MediaItem.id)).where(models.MediaItem.owner_id == current_user.id))
    res_col = await db.execute(select(func.count(models.UserCollection.id)).where(models.UserCollection.user_id == current_user.id))
    res_com = await db.execute(select(func.count(models.Comment.id)).where(models.Comment.user_id == current_user.id))
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "added_media_count": res_added.scalar(),
        "collection_count": res_col.scalar(),
        "comments_count": res_com.scalar()
    }
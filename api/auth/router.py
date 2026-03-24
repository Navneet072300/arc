from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import schemas, service
from api.db.models.user import User
from api.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: schemas.RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await service.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email,
        hashed_password=service.hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    access_token = service.create_access_token(user.id)
    refresh_token = await service.create_refresh_token(db, user.id)
    return schemas.TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=schemas.TokenResponse)
async def login(body: schemas.LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await service.get_user_by_email(db, body.email)
    if not user or not service.verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    access_token = service.create_access_token(user.id)
    refresh_token = await service.create_refresh_token(db, user.id)
    return schemas.TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=schemas.AccessTokenResponse)
async def refresh(body: schemas.RefreshRequest, db: AsyncSession = Depends(get_db)):
    rt = await service.verify_refresh_token(db, body.refresh_token)
    if not rt:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    rt.revoked = True
    await db.commit()
    new_access = service.create_access_token(rt.user_id)
    return schemas.AccessTokenResponse(access_token=new_access)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: schemas.RefreshRequest, db: AsyncSession = Depends(get_db)):
    rt = await service.verify_refresh_token(db, body.refresh_token)
    if rt:
        rt.revoked = True
        await db.commit()

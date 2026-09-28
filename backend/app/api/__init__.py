from fastapi import APIRouter

from app.api import admin, auth, training, users

router = APIRouter()
for module in (auth, users, admin, training):
    router.include_router(module.router)

from fastapi import APIRouter

from app.api import admin, auth, body, nutrition, training, users

router = APIRouter()
for module in (auth, users, admin, training, nutrition, body):
    router.include_router(module.router)

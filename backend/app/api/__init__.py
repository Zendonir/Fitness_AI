from fastapi import APIRouter

from app.api import admin, auth, body, nutrition, stats, training, users

router = APIRouter()
for module in (auth, users, admin, training, nutrition, body, stats):
    router.include_router(module.router)

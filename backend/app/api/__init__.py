from fastapi import APIRouter

from app.api import admin, auth, body, coach, integrations, media, nutrition, stats, training, users

router = APIRouter()
for module in (auth, users, admin, training, nutrition, body, stats, integrations, media):
    router.include_router(module.router)
router.include_router(coach.router)
router.include_router(coach.push_router)

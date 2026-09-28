from fastapi import APIRouter

from app.api import admin, auth, body, coach, integrations, nutrition, stats, training, users

router = APIRouter()
for module in (auth, users, admin, training, nutrition, body, stats, integrations):
    router.include_router(module.router)
router.include_router(coach.router)
router.include_router(coach.push_router)

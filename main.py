from fastapi import FastAPI

from app.routes import authentication_router

app = FastAPI()

app.include_router(authentication_router.router)
from fastapi import APIRouter
from typing import Optional
from datetime import datetime, timedelta
import string
from bson.objectid import ObjectId
from passlib.hash import bcrypt
from jose import jwt
from app.database.connect_database import get_database
from app.model.authentication_model import User, VerifyEmail, VerifyOTP
from app.Utils.utils import SECRET_KEY, ALGORITHM, smtp_server, port, sender_email, sender_password
from fastapi import HTTPException
from fastapi.param_functions import Depends
import smtplib
import random

router = APIRouter()


# Function to generate 6-Digit OPT
async def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


# Function to generate Access Token with expiry limit
async def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = await jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# API to register a user in database
@router.post('/register')
async def register(user: User, db=Depends(get_database)):
    try:
        # Query to check if email already exists in database
        existing_user = await db.users.find_one({'email': user.email})
        if existing_user:
            return HTTPException(status_code=400, detail="Email already registered")
        # Code to encrypt password
        user.password = bcrypt.hash(user.password)
        # Query to insert data into the database
        await db.users.insert_one(user.dict())
        return {"message": "Registration Successful"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# API for User Login
@router.post('/login')
async def login(email: str, password: str, db=Depends(get_database)):
    try:
        # Query to find the user from database
        user = await db.users.find_one({'email': email})
        # Code to decrypt password and check credentials as they exist in database
        if not user or not bcrypt.verify(password, user['password']):
            return HTTPException(status_code=400, detail="Invalid email or password")
        if not user['is_verified']:
            return HTTPException(status_code=400, detail="Email not verified")
        # Function called here to generate and return access token
        access_token = create_access_token(data={"sub": email})
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# API to verify user Email.
@router.post('/verify_email')
async def verify_email(data: VerifyEmail, db=Depends(get_database)):
    try:
        # Query to find Email from the database
        user = await db.users.find_one({'email': data.email})
        # Code to check that email is valid or not
        if not user:
            return HTTPException(status_code=400, detail="Invalid email")
        # Code to check whether email is verified or not
        if user['is_verified']:
            return HTTPException(status_code=400, detail="Email already verified")
        # Function called here to generate OPT and to send it in the database if user email is correct
        otp = await generate_otp()
        user['otp'] = otp
        user['otp_created_at'] = datetime.now()
        # Query to update otp in database
        await db.users.update_one({'_id': ObjectId(user['_id'])},
                                  {'$set': {'otp': otp, 'otp_created_at': user['otp_created_at']}})
        # Send email with OTP to the user
        return {"message": "OTP sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_email")
async def send_mail(email: str, db=Depends(get_database)):
    try:
        # Retrieve the user's email address
        user = await db.users.find_one({"email": email})
        if not user:
            return HTTPException(status_code=404, detail="User not found")
        receiver_email = user["email"]

        # The email content
        subject = 'Your OTP'
        otp = random.randint(100000, 999999)
        body = f'Your OTP is: {otp}'

        # Create the email message
        message = f'Subject: {subject}\n\n{body}'

        # Connect to the SMTP server and send the email
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, message)
        await db.users.update_one({'_id': ObjectId(user['_id'])},
                                  {'$set': {'otp': otp, 'otp_created_at': datetime.now()}})

        return {'message': f'OTP sent successfully to {receiver_email}'}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# API to verify OTP from database and generate token
@router.post('/verify_otp')
async def verify_otp(data: VerifyOTP, db=Depends(get_database)):
    try:
        # Query to find email from the database
        user = await db.users.find_one({'email': data.email})
        if not user:
            return HTTPException(status_code=400, detail="Invalid email")
        # Code to check whether OTP created or not
        if not user['otp'] or not user['otp_created_at']:
            return HTTPException(status_code=400, detail="OTP not generated")
        # Code to set OTP expiration time
        otp_expiry_time = user['otp_created_at'] + timedelta(minutes=5)
        if datetime.now() > otp_expiry_time:
            return HTTPException(status_code=400, detail="OTP expired")
        # Code to check whether otp is correct or not
        if data.otp != user["otp"]:
            return HTTPException(status_code=400, detail="Invalid OTP")
        # Function called here to check if otp is correct then generate the access token
        access_token = await create_access_token(data={"sub": data.email})
        # Code to update the status of verified from false to true
        await db.users.update_one({'_id': ObjectId(user['_id'])}, {'$set': {'is_verified': True}})
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

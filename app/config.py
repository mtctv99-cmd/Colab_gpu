import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.DATABASE_URL = os.getenv('DATABASE_URL')
        self.SECRET_KEY = os.getenv('SECRET_KEY')

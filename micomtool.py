import logging
import requests
import json
import hashlib
import urllib.parse
import time
import sys
import random
from datetime import datetime, timedelta, timezone
import ntplib

# Constants
VERSION = "1.0"
MAX_RETRIES = 5  # Maximum number of retries for network operations
RETRY_DELAY = 60  # Delay in seconds between retries
API_BASE_URL = "https://sgp-api.buy.mi.com/bbs/api/global/"
AUTH_URL = "https://account.xiaomi.com/pass/serviceLoginAuth2"
REGION_URL = "https://account.xiaomi.com/pass/user/login/region"
USER_AGENT = "XiaoMi/MiuiBrowser/14.28.0-gn"
SERVICE_SID = "18n_bbs_global"
INVALID_CREDENTIALS_CODE = 70016
NTP_SERVERS = ["pool.ntp.org", "time.google.com", "time.windows.com"]

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

print(f"\n[V{VERSION}] For feedback:\n- GitHub: https://github.com/bluebeard9998\n- Intagram: @ranjbar.ed1998\n")

class AuthSession:
    """Handles authentication with Xiaomi's login service."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cookies = {}
        self.region = None

    def login(self, user, password):
        """Attempt to log in to Xiaomi account with retry logic."""
        login_data = {
            "callback": "https://sgp-api.buy.mi.com/bbs/api/global/user/login-back?followup=https%3A%2F%2Fnew.c.mi.com%2Fglobal%2F&sign=NTRhYmNhZWI1ZWM2YTFmY2U3YzU1NzZhOTBhYjJmZWI1ZjY3MWNiNQ%2C%2C",
            "sid": SERVICE_SID,
            "_sign": "Phs2y/c0Xf7vJZG9Z6n9c+Nbn7g=",
            "user": user,
            "hash": hashlib.md5(password.encode('utf-8')).hexdigest().upper(),
            "_json": "true",
            "serviceParam": '{"checkSafePhone":false,"checkSafeAddress":false,"lsrp_score":0.0}'
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.post(AUTH_URL, data=login_data)
                json_data = self._parse_response(response)

                if json_data.get("code") == INVALID_CREDENTIALS_CODE:
                    logger.warning(f"Invalid credentials on attempt {attempt + 1}/{MAX_RETRIES}, retrying...")
                    time.sleep(RETRY_DELAY)
                    continue

                if "notificationUrl" in json_data:
                    self._handle_verification(json_data["notificationUrl"])

                region_response = self.session.get(REGION_URL, cookies=response.cookies)
                self.region = json.loads(region_response.text[11:])["data"]["region"]
                logger.info(f"Account Region: {self.region}")

                location_response = self.session.get(json_data['location'], allow_redirects=False)
                self.cookies = location_response.cookies.get_dict()
                logger.info("Login successful")
                return True

            except requests.RequestException as e:
                logger.error(f"Login error on attempt {attempt + 1}/{MAX_RETRIES}: {e}, retrying in {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Response parsing error: {e}, retrying in {RETRY_DELAY}s")
                time.sleep(RETRY_DELAY)

        logger.error("Max retries exceeded for login")
        return False

    def _parse_response(self, response):
        """Parse JSON response, stripping prefix and handling malformed data."""
        try:
            return json.loads(response.text[11:])
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response: {e}")
            raise

    def _handle_verification(self, url):
        """Handle verification prompts with user-friendly messages."""
        if "SetEmail" in url:
            logger.error(f"Verification required: Add email to account - {url}")
            sys.exit(1)
        elif "BindAppealOrSafePhone" in url:
            logger.error(f"Verification required: Add phone number - {url}")
            sys.exit(1)
        else:
            logger.error(f"Unknown verification required: {url}")
            sys.exit(1)

class ComTool:
    """Manages Xiaomi community API interactions and scheduling."""
    def __init__(self, auth_session):
        self.api = API_BASE_URL
        self.session = auth_session
        self.ntp_servers = NTP_SERVERS
        self.beijing_tz = timezone(timedelta(hours=8))

    def check_state(self):
        """Check the current authorization state."""
        url = self.api + "user/bl-switch/state"
        try:
            response = self.session.session.get(url, cookies=self.session.cookies)
            return response.json()
        except requests.RequestException as e:
            logger.error(f"State check error: {e}")
            return None

    def apply_request(self):
        """Submit an application request."""
        url = self.api + "apply/bl-auth"
        data = '{"is_retry":true}'
        try:
            response = self.session.session.post(url, data=data, cookies=self.session.cookies)
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Application error: {e}")
            return None

    def get_ntp_time(self):
        """Fetch time from NTP servers, falling back to system time with warning."""
        client = ntplib.NTPClient()
        for server in self.ntp_servers:
            try:
                response = client.request(server, version=3, timeout=5)
                return datetime.fromtimestamp(response.tx_time, timezone.utc)
            except ntplib.NTPException:
                continue
        logger.warning("All NTP servers failed, using system time")
        return datetime.now(timezone.utc)

    def precise_sleep(self, target_time, precision=0.01):
        """Sleep until the target time with high precision."""
        while True:
            diff = (target_time - datetime.now(target_time.tzinfo)).total_seconds()
            if diff <= 0:
                return
            sleep_time = max(min(diff - precision / 2, 1), precision)
            time.sleep(sleep_time)

    def schedule_minute_task(self):
        """Schedule application attempts every minute with random jitter."""
        while True:
            try:
                now = self.get_ntp_time().astimezone(self.beijing_tz)
                next_minute = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))
                logger.info(f"Next execution at: {next_minute.strftime('%Y-%m-%d %H:%M:%S.%f')} CST")
                self.precise_sleep(next_minute)

                jitter = random.uniform(0, 10)
                logger.info(f"Applying random jitter of {jitter:.2f} seconds before application")
                time.sleep(jitter)

                if (result := self._process_application()) is not None:
                    logger.info("Application process completed with a result; continuing scheduling")

            except Exception as e:
                logger.error(f"Scheduling error: {e}, retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)

    def _process_application(self):
        """Process an application attempt with retries."""
        for attempt in range(MAX_RETRIES):
            if (state := self.check_state()) and state.get('data'):
                state_data = state['data']
                if state_data.get("is_pass") == 1:
                    logger.info(f"Access granted until {state_data.get('deadline_format', '')}")
                    return True

                if state_data.get("button_state") == 1:
                    if (apply_resp := self.apply_request()) and apply_resp.get('data'):
                        return self._handle_application_response(apply_resp['data'])

            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES} failed, retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
        logger.error("Max retries exceeded for application process")
        return None

    def _handle_application_response(self, data):
        """Handle the response from an application attempt."""
        result = data.get("apply_result")
        deadline = data.get("deadline_format", "N/A")

        if result == 1:
            logger.info("Application Successful")
            return True
        elif result in (3, 4):
            logger.info(f"Retry after: {deadline}")
            self._schedule_retry(deadline)
            return False
        elif result in (5, 6, 7):
            logger.warning("Temporary error, retrying...")
            time.sleep(RETRY_DELAY)
            return False
        else:
            logger.warning("Unknown response, retrying...")
            time.sleep(RETRY_DELAY)
            return False

    def _schedule_retry(self, deadline):
        """Schedule a retry based on the provided deadline."""
        try:
            retry_time = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S.%f").replace(
                year=datetime.now().year,
                tzinfo=self.beijing_tz
            )
            delay = (retry_time - datetime.now(self.beijing_tz)).total_seconds()
            if delay > 0:
                logger.info(f"Waiting until {deadline} for retry...")
                time.sleep(delay)
        except ValueError as e:
            logger.error(f"Failed to parse deadline '{deadline}': {e}, using default retry delay")
            time.sleep(RETRY_DELAY)

def main():
    """Main script entry point for authentication and scheduling."""
    auth = AuthSession()
    login_attempts = 0
    max_login_attempts = 3

    while login_attempts < max_login_attempts:
        user = input("\nEnter username: ")
        password = input("\nEnter password: ")
        if auth.login(user, password):
            break
        login_attempts += 1
        logger.warning(f"Authentication failed ({login_attempts}/{max_login_attempts})")
    else:
        logger.error("Max login attempts exceeded, exiting...")
        sys.exit(1)

    tool = ComTool(auth)
    while True:
        try:
            tool.schedule_minute_task()
        except KeyboardInterrupt:
            logger.info("Exiting on user interrupt...")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Critical error: {e}, restarting in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()

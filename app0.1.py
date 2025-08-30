import streamlit as st
import pandas as pd
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import google.auth
import os
import json
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
import re
import tempfile 
import time

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, InvalidArgumentException
from selenium.webdriver.common.keys import Keys 

# --- Selenium Driver Management for Streamlit Cloud ---
if 'driver' not in st.session_state:
    st.session_state.driver = None

def get_selenium_driver():
    """
    Initializes and returns a headless Selenium WebDriver.
    This function is tailored for Streamlit Cloud deployment.
    """
    if st.session_state.driver is None:
        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--log-level=3")
            
            # This is the path for Chromium installed via packages.txt
            service = Service(executable_path='/usr/bin/chromium-driver')

            driver = webdriver.Chrome(service=service, options=options)
            st.session_state.driver = driver
            st.success("✅ Successfully initialized headless Chrome driver!")
        except WebDriverException as e:
            st.error(f"❌ Failed to initialize Chrome driver: {e}")
            st.warning("This application is configured to run on Streamlit Cloud. It will not launch a visible browser on your local machine.")
            st.session_state.driver = None
            st.stop()
    return st.session_state.driver

def close_selenium_driver():
    """
    Quits the Selenium WebDriver session.
    """
    if st.session_state.driver:
        st.session_state.driver.quit()
        st.session_state.driver = None
        st.info("Automated browser session closed.")

def apply_cookies(driver, cookies_json):
    """
    Deletes existing cookies and applies new ones from a JSON string.
    """
    try:
        cookies = json.loads(cookies_json)
        driver.delete_all_cookies()
        for cookie in cookies:
            if 'domain' in cookie:
                del cookie['domain']
            if 'sameSite' in cookie:
                del cookie['sameSite']
            driver.add_cookie(cookie)
        return True
    except Exception as e:
        st.error(f"❌ Failed to apply cookies: {e}")
        return False

# --- Streamlit UI Configuration ---
st.set_page_config(
    page_title="Instagram Affiliate Messenger",
    page_icon="💬",
    layout="centered"
)

# Load environment variables from .env file (for Google Auth)
load_dotenv()
try:
    GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
except KeyError:
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "project_id": "instagram-affiliate-messenger",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uris": ["http://localhost:8501"],
        "javascript_origins": ["http://localhost:8501"]
    }
}
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    st.error("Google Client ID or Secret not found. Please set them in your secrets.toml or .env file.")
    st.stop()

# --- Helper Functions for Google Sheets ---
def get_google_credentials():
    creds = None
    if 'credentials' in st.session_state:
        creds = st.session_state['credentials']

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                st.error(f"Error refreshing token: {e}")
                creds = None
        else:
            flow = Flow.from_client_config(
                CLIENT_SECRETS_FILE, SCOPES, redirect_uri='http://localhost:8501'
            )
            auth_url, _ = flow.authorization_url(prompt='consent')
            st.session_state['auth_url'] = auth_url
            st.warning("Click the button below to authenticate with Google.")
            st.link_button("Authenticate with Google", url=auth_url)

            auth_code = st.query_params.get("code")
            if auth_code:
                try:
                    flow.fetch_token(code=auth_code)
                    creds = flow.credentials
                    st.session_state['credentials'] = creds
                    st.success("Authentication successful!")
                    st.query_params.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Authentication failed: {e}")
                    del st.session_state['auth_url']
                    st.query_params.clear()
                    return None
            else:
                return None
    return creds

@st.cache_data(ttl=3600)
def fetch_sheet_names(sheet_id, _creds):
    try:
        service = google.auth.transport.requests.AuthorizedSession(_creds)
        response = service.get(f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?fields=sheets.properties.title')
        response.raise_for_status()
        data = response.json()
        sheet_titles = [s['properties']['title'] for s in data.get('sheets', [])]
        return sheet_titles
    except Exception as e:
        st.error(f"Error fetching sheet names: {e}")
        return []

@st.cache_data(ttl=60)
def read_sheet_data(sheet_id, sheet_name, _creds):
    try:
        service = google.auth.transport.requests.AuthorizedSession(_creds)
        response = service.get(f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{sheet_name}')
        response.raise_for_status()
        data = response.json()
        values = data.get('values', [])
        return values
    except Exception as e:
        st.error(f"Error reading sheet data: {e}")
        return []

def update_sheet_data(sheet_id, sheet_name, row_number, data_to_write, creds):
    try:
        service = google.auth.transport.requests.AuthorizedSession(creds)
        range_to_update = f"{sheet_name}!H{row_number}:K{row_number}" 
        body = {"values": [data_to_write]}
        response = service.put(
            f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{range_to_update}?valueInputOption=RAW',
            json=body
        )
        response.raise_for_status()
        st.success(f"Sheet updated successfully for row {row_number}.")
        return True
    except Exception as e:
        st.error(f"Error updating sheet: {e}")
        return False

# --- App UI Layout ---
st.title("💬 Instagram Affiliate Messenger")
st.markdown("Automate Instagram messaging.")

st.info("Since this app is running in a headless browser, you must provide your login session cookies to authenticate.")

# --- Cookie Management Section ---
cookie_data = st.text_area(
    "Paste your Instagram cookies (JSON format)",
    height=250,
    help="1. Log in to Instagram in your browser.\n2. Use a browser extension (like 'EditThisCookie') to export your session cookies as JSON.\n3. Paste the full JSON string here."
)

if st.button("Close Automated Browser Session", help="Closes the Selenium connection."):
    close_selenium_driver()
    
st.markdown("---")

# --- Multiple Influencer ID Input ---
st.subheader("Influencers to Message")
influencer_ids_input = st.text_area(
    "Enter Influencer IDs (one per line)",
    height=200,
    placeholder="e.g.,\n1234567890\n9876543210\n..."
)

# --- Multiple Custom Messages Input ---
st.subheader("Messages to Send")
if 'custom_messages' not in st.session_state:
    st.session_state.custom_messages = [""]

for i, msg in enumerate(st.session_state.custom_messages):
    st.session_state.custom_messages[i] = st.text_area(f"Message {i+1}", value=msg, key=f"message_input_{i}", height=100)

col_msg_buttons = st.columns(2)
with col_msg_buttons[0]:
    if st.button("Add Another Message", key="add_msg_btn"):
        st.session_state.custom_messages.append("")
        st.rerun()
with col_msg_buttons[1]:
    if len(st.session_state.custom_messages) > 1 and st.button("Remove Last Message", key="remove_msg_btn"):
        st.session_state.custom_messages.pop()
        st.rerun()

# --- Image Upload Input (Modified for multiple files) ---
st.subheader("Images to Attach (Optional)")
uploaded_files = st.file_uploader("Upload images", type=["png", "jpg", "jpeg", "gif"], accept_multiple_files=True, key="images_upload")

if 'uploaded_image_paths' not in st.session_state:
    st.session_state['uploaded_image_paths'] = []

if uploaded_files:
    st.session_state['uploaded_image_paths'] = []
    for i, uploaded_file in enumerate(uploaded_files):
        st.image(uploaded_file, caption=f"Uploaded Image {i+1}", width=150)
        try:
            temp_dir = tempfile.gettempdir()
            sanitized_filename = re.sub(r'[^\w\s.-]', '', uploaded_file.name).strip()
            if not sanitized_filename:
                sanitized_filename = f"uploaded_image_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}.tmp"
            
            temp_file_path = os.path.join(temp_dir, sanitized_filename)

            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.session_state['uploaded_image_paths'].append(temp_file_path)
            st.info(f"Image '{uploaded_file.name}' saved temporarily.")
        except Exception as e:
            st.error(f"Error saving uploaded image '{uploaded_file.name}': {e}")
            st.session_state['uploaded_image_paths'] = []
            break
else:
    st.session_state['uploaded_image_paths'] = []

# --- Automation State Management ---
if 'influencer_list' not in st.session_state:
    st.session_state['influencer_list'] = []
if 'current_influencer_index' not in st.session_state:
    st.session_state['current_influencer_index'] = 0
if 'automation_running' not in st.session_state:
    st.session_state['automation_running'] = False
if 'last_status' not in st.session_state:
    st.session_state['last_status'] = "Ready to start automation. Please configure the inputs and click 'Start Messaging Session'."

st.markdown("---")

# --- Automation Control Buttons ---
col1, col2 = st.columns(2)
status_message_placeholder = st.empty()

with col1:
    start_button_disabled = st.session_state.automation_running
    start_button = st.button("Start Messaging Session", type="primary", key="start_btn", use_container_width=True, disabled=start_button_disabled)

with col2:
    stop_button_disabled = not st.session_state.automation_running
    stop_button = st.button("Stop Automation", type="secondary", key="stop_btn", use_container_width=True, disabled=stop_button_disabled)

if stop_button: 
    st.session_state.automation_running = False
    st.session_state.last_status = "Automation stopped by user. Click 'Start Messaging Session' to resume."
    status_message_placeholder.info(st.session_state.last_status)

if start_button:
    influencer_ids = [i.strip() for i in influencer_ids_input.split('\n') if i.strip()]
    messages_to_send = [msg.strip() for msg in st.session_state.custom_messages if msg.strip()]
    images_to_send = st.session_state.get('uploaded_image_paths', [])

    if not influencer_ids:
        st.session_state.last_status = "Please enter at least one Influencer ID."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    elif not messages_to_send and not images_to_send:
        st.session_state.last_status = "Please enter at least one message OR upload at least one image to send."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    elif not cookie_data.strip():
        st.session_state.last_status = "Please provide your Instagram login cookies."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    else:
        st.session_state.automation_running = True
        st.session_state['influencer_list'] = influencer_ids
        st.session_state['current_influencer_index'] = 0
        st.rerun()

# --- Automation Loop Logic ---
if st.session_state.automation_running and st.session_state.get('influencer_list') and \
   st.session_state['current_influencer_index'] < len(st.session_state['influencer_list']):

    influencer_id = st.session_state['influencer_list'][st.session_state['current_influencer_index']]
    messages_to_send = [msg.strip() for msg in st.session_state.custom_messages if msg.strip()]
    image_paths_to_send = st.session_state.get('uploaded_image_paths', [])
    
    st.markdown(f"---")
    st.subheader(f"Automating for Influencer: `{influencer_id}`")
    
    driver = get_selenium_driver()
    if not driver:
        st.session_state.automation_running = False
        st.stop()
    
    # Base URL to apply cookies to before navigation
    base_url = "https://www.instagram.com/"
    driver.get(base_url)
    
    if not apply_cookies(driver, cookie_data):
        st.warning("Failed to apply cookies. Please ensure they are valid and try again.")
        st.session_state.automation_running = False
        st.stop()
    
    chat_url = f"https://www.instagram.com/direct/t/{influencer_id}/"
    st.session_state.last_status = f"Navigating to chat for influencer `{influencer_id}`..."
    status_message_placeholder.info(st.session_state.last_status)

    try:
        driver.get(chat_url)
        
        # --- Using a robust selector for the message input box ---
        # AVOID DYNAMIC CLASS NAMES LIKE 'x1n2onr6'
        # A more stable approach is to find the <textarea> element with a specific placeholder or role.
        message_input_selector = 'textarea[placeholder*="Message..."]'
        
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, message_input_selector))
        )
        message_textarea = driver.find_element(By.CSS_SELECTOR, message_input_selector)

        # Send all text messages first
        for i, msg_content in enumerate(messages_to_send):
            message_textarea.clear()
            message_textarea.send_keys(msg_content)
            
            st.session_state.last_status = f"Pasting message {i+1} for `{influencer_id}`. Sending..."
            status_message_placeholder.success(st.session_state.last_status)
            
            time.sleep(1)
            message_textarea.send_keys(Keys.ENTER)
            
            st.session_state.last_status = f"Message {i+1} sent successfully."
            status_message_placeholder.success(st.session_state.last_status)
            
            time.sleep(2) # Delay between messages

        # Image upload logic (Instagram-specific)
        if image_paths_to_send:
            st.warning("Warning: Image upload on Instagram is highly prone to failure. Use with caution.")
            st.session_state.last_status = f"Attempting to upload {len(image_paths_to_send)} image(s)..."
            status_message_placeholder.info(st.session_state.last_status)
            try:
                # Instagram's file input can be tricky. This selector may change.
                file_input_selector = 'input[accept*="image/jpeg,image/png,image/heic,image/heif,video/mp4,video/quicktime"]'
                file_input_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, file_input_selector))
                )
                
                # Join paths for multiple file upload
                all_image_paths_string = "\n".join(image_paths_to_send)
                file_input_element.send_keys(all_image_paths_string)
                
                st.session_state.last_status = "Image(s) sent to upload input. Waiting for Instagram to process..."
                status_message_placeholder.success(st.session_state.last_status)
                time.sleep(10) # Longer delay for upload and processing
            except Exception as e:
                st.session_state.last_status = f"Error during image upload: {e}. Proceeding without image for this influencer."
                status_message_placeholder.error(st.session_state.last_status)
            finally:
                for temp_path in image_paths_to_send:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                st.session_state['uploaded_image_paths'] = []

        # --- Move to Next Influencer ---
        st.session_state['current_influencer_index'] += 1
        time.sleep(5) # Delay before moving to the next chat to avoid rate limits
        
        if st.session_state.automation_running and st.session_state['current_influencer_index'] < len(st.session_state['influencer_list']):
            st.session_state.last_status = f"Messages sent to `{influencer_id}`. Moving to next influencer..."
            status_message_placeholder.info(st.session_state.last_status)
            st.rerun()
        else:
            st.session_state.last_status = "All influencers processed. Automation finished."
            status_message_placeholder.success(st.session_state.last_status)
            st.session_state.automation_running = False
            st.session_state['influencer_list'] = []
            st.session_state['current_influencer_index'] = 0

    except TimeoutException:
        st.session_state.last_status = f"Timeout for `{influencer_id}`. Could not find a required element. Moving to next influencer."
        status_message_placeholder.warning(st.session_state.last_status)
        st.session_state['current_influencer_index'] += 1
        st.rerun()
    except NoSuchElementException as e:
        st.session_state.last_status = f"Element not found for `{influencer_id}`: {e}. Instagram's UI might have changed. Moving to next influencer."
        status_message_placeholder.warning(st.session_state.last_status)
        st.session_state['current_influencer_index'] += 1
        st.rerun()
    except WebDriverException as e:
        st.session_state.last_status = f"Browser error during automation for `{influencer_id}`: {e}. The connection might have been lost. Automation stopped."
        status_message_placeholder.error(st.session_state.last_status)
        close_selenium_driver()
        st.session_state.automation_running = False
    except Exception as e:
        st.session_state.last_status = f"An unexpected error occurred for `{influencer_id}`: {e}. Automation stopped."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    
    if not st.session_state.automation_running:
        st.stop()

else:
    status_message_placeholder.info(st.session_state.last_status)

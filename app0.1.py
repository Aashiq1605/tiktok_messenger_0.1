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

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys # Import Keys for simulating keyboard presses
import time # For delays


# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "project_id": "tiktok-affiliate-messenger", # You can put a dummy value here
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uris": ["http://localhost:8501"], # Streamlit's default local URL
        "javascript_origins": ["http://localhost:8501"]
    }
}

# Ensure client ID and secret are loaded
if not CLIENT_SECRETS_FILE["web"]["client_id"] or not CLIENT_SECRETS_FILE["web"]["client_secret"]:
    st.error("Google Client ID or Secret not found. Please set them in the .env file.")
    st.stop()

# --- Global Selenium Driver (Managed in session state) ---
if 'driver' not in st.session_state:
    st.session_state.driver = None

def get_selenium_driver():
    # Only create a new driver if one doesn't exist in session state
    if st.session_state.driver is None:
        try:
            options = webdriver.ChromeOptions()
            # No debuggerAddress needed for launching a new instance
            
            # Optional: Add arguments for better stability or specific behavior
            options.add_argument("--start-maximized") # Maximize the browser window
            options.add_argument("--disable-infobars") # Disable info bars
            options.add_argument("--disable-extensions") # Disable extensions
            options.add_argument("--no-sandbox") # Bypass OS security model (needed in some environments)
            options.add_argument("--disable-dev-shm-usage") # Overcome limited resource problems

            # You still need a Service object to specify chromedriver path if not in PATH
            # Assuming chromedriver is in PATH or current directory
            service = Service() 

            driver = webdriver.Chrome(service=service, options=options)
            st.session_state.driver = driver
            st.success("Launched a new Chrome instance!") # Simplified message
        except WebDriverException as e:
            st.error(f"Failed to launch browser: {e}. "
                     f"Please ensure ChromeDriver is correctly installed and its version matches your Chrome browser. "
                     f"Also, check system resources and permissions.")
            st.session_state.driver = None
    return st.session_state.driver

def close_selenium_driver():
    if st.session_state.driver:
        st.session_state.driver.quit()
        st.session_state.driver = None
        st.info("Automated browser session closed.")


# --- Helper Functions ---

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

@st.cache_data(ttl=60) # This cache will now be cleared by st.cache_data.clear()
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

# Function to launch TikTok login in the browser
def launch_tiktok_login():
    driver = get_selenium_driver() # This will now launch a new instance if one isn't active
    if driver:
        tiktok_login_url = "https://seller.tiktok.com/login/choose-region?redirect_url=https%3A%2F%2Faffiliate.tiktok.com%2Fseller%2Fim&needLogin=1"
        try:
            driver.get(tiktok_login_url)
            st.success("Launched TikTok login in new Chrome instance.") # Simplified message
        except WebDriverException as e:
            st.error(f"Failed to open TikTok login page: {e}. Ensure the new browser instance launched correctly.")
    else:
        st.warning("Could not launch TikTok login. Failed to get a browser driver.")


# --- Streamlit UI ---
st.set_page_config(
    page_title="TikTok Affiliate Messenger",
    page_icon="💬",
    layout="centered"
)

st.title("💬 TikTok Affiliate Messenger") # Corrected icon in title
st.markdown("Automate TikTok Affiliate messaging with Google Sheets.")

# Move "Close Automated Browser Session" to the top
if st.button("Close Automated Browser Session", help="Closes the Selenium-controlled browser window (if open)."):
    close_selenium_driver()

# Google Authentication
creds = get_google_credentials()
if not creds:
    st.info("Please authenticate with your Google account to proceed.")
    st.stop()

# Store ID Input
store_id = st.text_input("TikTok Store ID", key="store_id", help="Enter your TikTok Shop ID. This is typically found in your TikTok Seller Center URL.")
if not store_id:
    st.warning("Please enter your TikTok Store ID to generate chat links.")

# New button for launching TikTok login
if st.button("Launch TikTok Login", help="Opens TikTok's login page in a NEW automated browser instance. You'll need to log in manually in that window."):
    launch_tiktok_login()

# Sheet Link Input
sheet_link = st.text_input("Google Sheet Link", placeholder="Paste your Google Sheet URL here", key="sheet_link")
sheet_id = None
if sheet_link:
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if match:
        sheet_id = match.group(1)
        st.success(f"Google Sheet ID detected: {sheet_id}")
    else:
        st.error("Invalid Google Sheet link. Please ensure it's a valid URL.")
        sheet_id = None

# --- Logic for Always Visible Sheet Selection ---
sheet_names = []
selected_sheet_name = None
selectbox_disabled = True # Start disabled by default

if sheet_id and creds:
    sheet_names = fetch_sheet_names(sheet_id, creds)
    if sheet_names:
        selectbox_disabled = False # Enable if sheets are found
        # If a sheet was previously selected for this sheet_id, try to maintain it
        if 'selected_sheet_name_cache' not in st.session_state or st.session_state.selected_sheet_name_cache not in sheet_names:
            st.session_state.selected_sheet_name_cache = sheet_names[0] # Default to the first sheet

        # Find the index of the cached selected sheet name
        try:
            default_index = sheet_names.index(st.session_state.selected_sheet_name_cache)
        except ValueError:
            default_index = 0 # If cached name not found, default to first sheet
    else:
        # If sheet_id is valid but no sheets are returned, disable and show warning
        st.warning("No sheets found or unable to fetch sheet names. Check link and permissions.")
        st.session_state['selected_sheet_name'] = None
        if 'selected_sheet_name_cache' in st.session_state:
            del st.session_state['selected_sheet_name_cache'] # Clear cache if no sheets found
        sheet_names = ["No sheets available"] # Placeholder for the selectbox
        default_index = 0 # Point to the placeholder
else:
    # If no sheet_id or creds, clear cache and set placeholder
    st.session_state['selected_sheet_name'] = None
    if 'selected_sheet_name_cache' in st.session_state:
        del st.session_state['selected_sheet_name_cache'] # Clear cache if sheet_id is not valid
    sheet_names = ["Enter Google Sheet Link above"] # Placeholder when no link
    default_index = 0 # Point to the placeholder

# The st.selectbox is now always present
selected_sheet_name = st.selectbox(
    "Select Sheet", 
    options=sheet_names, # Use the dynamically populated or placeholder list
    key="selected_sheet_name_ui", 
    index=default_index,
    disabled=selectbox_disabled # Control its interactiveness
)

# Only update the actual selected_sheet_name in session state if it's a real sheet name
if sheet_names and selected_sheet_name != "Enter Google Sheet Link above" and selected_sheet_name != "No sheets available":
    st.session_state.selected_sheet_name_cache = selected_sheet_name
    st.session_state.selected_sheet_name = selected_sheet_name
else:
    # If placeholder is selected or no valid sheets, ensure session state reflects no valid selection
    st.session_state.selected_sheet_name = None
    if 'selected_sheet_name_cache' in st.session_state:
        del st.session_state['selected_sheet_name_cache']


if st.session_state.selected_sheet_name is None and sheet_id: # Only warn if sheet_id exists but no real selection
    st.warning("Please select a sheet from the dropdown, or ensure your sheet has valid data.")

custom_message = st.text_area("Custom Message", placeholder="Enter the message you want to send", height=150, key="custom_message")

if 'creators' not in st.session_state:
    st.session_state['creators'] = []
if 'current_creator_index' not in st.session_state:
    st.session_state['current_creator_index'] = 0
if 'automation_running' not in st.session_state:
    st.session_state['automation_running'] = False # New state variable
if 'last_status' not in st.session_state:
    st.session_state['last_status'] = "Ready to start automation. Please configure the inputs and click 'Start Messaging Session'."


st.markdown("---")

col1, col2 = st.columns(2)

status_message_placeholder = st.empty()

with col1:
    # Disable start button if automation is already running
    start_button_disabled = st.session_state.automation_running
    start_button = st.button("Start Messaging Session", type="primary", key="start_btn", use_container_width=True, disabled=start_button_disabled)

with col2:
    # Enable stop button only when automation is running
    stop_button_disabled = not st.session_state.automation_running
    stop_button = st.button("Stop Automation", type="secondary", key="stop_btn", use_container_width=True, disabled=stop_button_disabled)

# Handle Stop Automation button click first
if stop_button: 
    st.session_state.automation_running = False
    st.session_state.last_status = "Automation stopped by user. Click 'Start Messaging Session' to resume."
    status_message_placeholder.info(st.session_state.last_status)
    # No rerun here, let Streamlit re-render naturally.

# Handle Start Messaging Session button click
if start_button:
    # Clear all st.cache_data caches to force re-reading of the sheet data
    st.cache_data.clear() 

    if not sheet_id or not st.session_state.get('selected_sheet_name'):
        st.session_state.last_status = "Please provide a valid Google Sheet link and select a sheet."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Ensure automation doesn't start if prerequisites are missing
    elif not custom_message.strip():
        st.session_state.last_status = "Please enter a custom message."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    elif not store_id.strip():
        st.session_state.last_status = "Please enter your TikTok Store ID."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    else:
        # Check if driver is active before proceeding with automation
        if not st.session_state.driver:
            st.session_state.last_status = "Please launch a browser instance first using 'Launch TikTok Login'."
            status_message_placeholder.error(st.session_state.last_status)
            st.session_state.automation_running = False
            st.stop() # Prevent further execution if no driver

        st.session_state.automation_running = True # Set to True to begin automation
        
        # Only fetch data if starting fresh or if creators list is empty (e.g., after an error or initial load)
        # Also reset index if starting a new list
        if not st.session_state.get('creators') or st.session_state['current_creator_index'] >= len(st.session_state['creators']):
            st.session_state['current_creator_index'] = 0 # Reset to start from the beginning if list needs re-fetching
            st.session_state.last_status = f"Reading Sheet: \"{st.session_state.selected_sheet_name}\"..."
            status_message_placeholder.info(st.session_state.last_status)
            
            sheet_data = read_sheet_data(sheet_id, st.session_state.selected_sheet_name, creds)

            if not sheet_data or len(sheet_data) < 2:
                st.session_state.last_status = "No data found in the specified sheet or range."
                status_message_placeholder.warning(st.session_state.last_status)
                st.session_state['creators'] = []
                st.session_state.automation_running = False
            else:
                creators_list = []
                link_col_idx = 4 # Column 5 (0-indexed)
                approached_col_idx = 7 # Column 8 (0-indexed)

                if len(sheet_data[0]) <= link_col_idx or len(sheet_data[0]) <= approached_col_idx:
                    st.session_state.last_status = (
                        f"Sheet does not have enough columns for the expected data. "
                        f"Please ensure column {link_col_idx + 1} (for Link) and "
                        f"column {approached_col_idx + 1} (for Approached) exist."
                    )
                    status_message_placeholder.error(st.session_state.last_status)
                    st.session_state['creators'] = []
                    st.session_state.automation_running = False
                else:
                    for i, row in enumerate(sheet_data[1:]): # Iterate from the second row (index 1) for data
                        if len(row) <= approached_col_idx: # Check if 'approached' column exists for the row
                            # If row is too short to even contain 'approached' column, treat as not approached
                            raw_approached_value = ''
                        else:
                            raw_approached_value = row[approached_col_idx]
                        
                        if len(row) <= link_col_idx: # Check if 'link' column exists for the row
                             link = '' # Treat as empty link if not present
                        else:
                             link = row[link_col_idx]


                        # Determine if the row has been approached based on various possibilities
                        is_approached = False
                        if isinstance(raw_approached_value, bool):
                            is_approached = raw_approached_value # Directly use boolean True/False
                        elif isinstance(raw_approached_value, str):
                            is_approached = raw_approached_value.strip().upper() == "TRUE" # Handle "TRUE" string

                        # Add to creators_list ONLY if 'cid=' is in link and 'is_approached' is False
                        if "cid=" in link and not is_approached:
                            try:
                                cid = link.split("cid=")[1].split("&")[0]
                                creators_list.append({"row": i + 2, "cid": cid})
                            except IndexError:
                                st.warning(f"Could not parse CID from link in row {i + 2}: {link}")

                    st.session_state['creators'] = creators_list

                    if not st.session_state['creators']:
                        st.session_state.last_status = "No new creators found to message based on fixed column positions (Link in column 5, Approached in column 8)."
                        status_message_placeholder.info(st.session_state.last_status)
                        st.session_state.automation_running = False
                    else:
                        st.session_state.last_status = f"Found {len(st.session_state['creators'])} new creators to message. Preparing browser for automation..."
                        status_message_placeholder.success(st.session_state.last_status)
        
        # If automation is set to run and we have creators, trigger the first step immediately
        if st.session_state.automation_running and st.session_state.get('creators'):
            st.rerun() # Trigger a rerun to enter the automation loop below

# --- Automation Loop Logic (executes on every rerun if automation_running is True) ---
if st.session_state.automation_running and st.session_state.get('creators') and \
   st.session_state['current_creator_index'] < len(st.session_state['creators']):
    
    current_creator = st.session_state['creators'][st.session_state['current_creator_index']]
    creator_row = current_creator['row']
    creator_cid = current_creator['cid']
    message_to_send = custom_message.strip()

    st.markdown(f"---")
    st.subheader(f"Automating for Current Creator: Row {creator_row}")
    st.markdown(f"**Creator ID:** {creator_cid}")
    
    driver = get_selenium_driver() # Ensure driver is active (it will retrieve the existing one if launched)
    if not driver:
        st.session_state.last_status = "Browser driver is not active. Automation stopped."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation if driver fails
        st.stop() # Stop the current script execution

    chat_url = f"https://affiliate.tiktok.com/seller/im?shop_id={store_id}&creator_id={creator_cid}&enter_from=affiliate_creator_details&shop_region=TH"
    st.session_state.last_status = f"Navigating to chat for creator (Row {creator_row})..."
    status_message_placeholder.info(st.session_state.last_status)

    try:
        driver.get(chat_url)
        
        # Selector for the message input area
        message_input_selector = 'textarea[placeholder*="Send a message"]' 
        
        WebDriverWait(driver, 30).until( # Max 30 seconds to find the message input
            EC.presence_of_element_located((By.CSS_SELECTOR, message_input_selector))
        )
        
        message_textarea = driver.find_element(By.CSS_SELECTOR, message_input_selector)
        
        message_textarea.clear()
        message_textarea.send_keys(message_to_send)
        
        st.session_state.last_status = f"Message successfully pasted for creator (Row {creator_row}). Attempting to send using Enter key..."
        status_message_placeholder.success(st.session_state.last_status)
        
        time.sleep(1) # Short delay after pasting the message

        # --- NEW SENDING LOGIC: Press Enter key after pasting the message ---
        message_textarea.send_keys(Keys.ENTER)
        
        st.session_state.last_status = f"Message sent successfully (via Enter key) for creator (Row {creator_row}). Updating sheet..."
        status_message_placeholder.success(st.session_state.last_status)
        # --- END OF NEW SENDING LOGIC ---
        
        time.sleep(2) # Short delay to allow the message to be sent and UI to update on TikTok's side

        # Update sheet data
        today_str = datetime.now().strftime("%m/%d/%Y")
        week_start = datetime.now() - timedelta(days=datetime.now().weekday()) # Use timedelta for date arithmetic
        week_str = week_start.strftime("%m/%d/%Y")
        month_str = datetime.now().strftime("%B")

        update_success = update_sheet_data(
            sheet_id, 
            st.session_state.selected_sheet_name, 
            creator_row, 
            [True, today_str, week_str, month_str], 
            creds
        )
        
        if update_success:
            st.session_state['current_creator_index'] += 1
            if st.session_state.automation_running and st.session_state['current_creator_index'] < len(st.session_state['creators']):
                st.session_state.last_status = f"Sheet updated for creator {creator_row}. Moving to next influencer..."
                status_message_placeholder.info(st.session_state.last_status)
                st.rerun() # Trigger next step of automation
            else:
                st.session_state.last_status = "All eligible creators processed for this session!"
                status_message_placeholder.success(st.session_state.last_status)
                st.session_state['creators'] = [] # Clear list to allow fresh start
                st.session_state['current_creator_index'] = 0
                st.session_state.automation_running = False # Stop automation
        else:
            st.session_state.last_status = f"Failed to update sheet for row {creator_row}. Automation stopped."
            status_message_placeholder.error(st.session_state.last_status)
            st.session_state.automation_running = False # Stop automation on update failure

    except TimeoutException:
        st.session_state.last_status = (f"Timeout during automation for creator (Row {creator_row}). "
                                         "Chat input was not found within the time limit. Please ensure you are logged into TikTok. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation on timeout
    except NoSuchElementException as e:
        st.session_state.last_status = (f"Element not found during automation for creator (Row {creator_row}): {e}. "
                                         "TikTok UI might have changed or page failed to load correctly. Please ensure you are logged into TikTok. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation on element not found
    except WebDriverException as e:
        st.session_state.last_status = (f"Browser error during automation: {e}. "
                                         "The connection to the automated browser might have been lost. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        close_selenium_driver() # Attempt to clean up
        st.session_state.automation_running = False # Stop automation on general WebDriver error
    except Exception as e:
        st.session_state.last_status = (f"An unexpected error occurred during automation: {e}. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    
    # If automation was stopped (by error or completion) within this block, ensure Streamlit stops the rerun chain
    if not st.session_state.automation_running:
        st.stop() 

# Display last status message when automation is not running or completed
else:
    status_message_placeholder.info(st.session_state.last_status)
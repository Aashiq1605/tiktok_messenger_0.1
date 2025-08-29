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
import tempfile # For creating temporary files

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys # Import Keys for simulating keyboard presses
import time # For delays
import subprocess

# --- Chrome Debug Mode Config ---
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"  # MacOS path
USER_DATA_DIR = os.path.expanduser("~/chrome_debug_profile")
REMOTE_DEBUG_PORT = "9222"

def launch_chrome_instance(store_id: str):
    """Launch Chrome in remote debugging mode automatically and open TikTok Seller for given store."""
    # Kill any previous debug Chrome instance
    subprocess.Popen(
        ["pkill", "-f", "chrome_debug_profile"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)

    # TikTok Seller login URL for store
    tiktok_url = f"https://seller.tiktokglobalshop.com/account/login?shop_id={store_id}"

    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={REMOTE_DEBUG_PORT}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        tiktok_url
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    st.success(f"✅ Chrome launched in debug mode and opened TikTok Seller for store ID {store_id}")



# --- Streamlit UI Configuration ---
st.set_page_config(
    page_title="TikTok Affiliate Messenger",
    page_icon="💬",
    layout="centered"
)

# Load environment variables from .env file
load_dotenv()

try:
    GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
except KeyError:
    # This fallback is useful for local development if you prefer not to use secrets.toml
    # and instead rely on the .env file.
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# --- Google API Configuration ---
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


# Ensure client ID and secret are loaded from environment variables
if not CLIENT_SECRETS_FILE["web"]["client_id"] or not CLIENT_SECRETS_FILE["web"]["client_secret"]:
    st.error("Google Client ID or Secret not found. Please set them in the .env file.")
    st.stop()

# --- Global Selenium Driver Management ---
if 'driver' not in st.session_state:
    st.session_state.driver = None

def get_selenium_driver():
    """Attach to the Chrome instance launched by this app."""
    if st.session_state.driver is None:
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{REMOTE_DEBUG_PORT}")
            service = Service()  # assumes chromedriver is in PATH
            driver = webdriver.Chrome(service=service, options=options)
            st.session_state.driver = driver
            st.success("✅ Successfully attached to Chrome instance!")
        except WebDriverException as e:
            st.error(f"❌ Failed to connect to Chrome: {e}")
            st.session_state.driver = None
    return st.session_state.driver


def close_selenium_driver():
    """
    Quits the Selenium WebDriver session.
    """
    if st.session_state.driver:
        st.session_state.driver.quit()
        st.session_state.driver = None
        st.info("Automated browser session closed.")

# Button to manually close the browser connection
if st.button("Close Automated Browser Session", help="Closes the Selenium connection to the browser. The browser window itself will remain open if it was launched manually."):
    close_selenium_driver()

# --- Helper Functions for Google Sheets ---

def get_google_credentials():
    """
    Handles Google authentication flow for accessing Google Sheets.
    Caches credentials in session state.
    """
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
                    st.query_params.clear() # Clear auth code from URL
                    st.rerun() # Rerun to remove auth elements
                except Exception as e:
                    st.error(f"Authentication failed: {e}")
                    del st.session_state['auth_url']
                    st.query_params.clear()
                    return None
            else:
                return None # Still waiting for auth code
    return creds

@st.cache_data(ttl=3600)
def fetch_sheet_names(sheet_id, _creds):
    """
    Fetches the names of all sheets within a given Google Spreadsheet.
    """
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
    """
    Reads all data from a specified sheet in a Google Spreadsheet.
    """
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
    """
    Updates a specific row in a Google Sheet with provided data (columns H to K).
    """
    try:
        service = google.auth.transport.requests.AuthorizedSession(creds)
        # Update columns H, I, J, K (0-indexed: 7, 8, 9, 10)
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

# --- Streamlit App UI Layout ---

st.title("💬 TikTok Affiliate Messenger")
st.markdown("Automate TikTok Affiliate messaging with Google Sheets.")

# Google Authentication Check
creds = get_google_credentials()
if not creds:
    st.info("Please authenticate with your Google account to proceed.")
    st.stop()

# TikTok Store ID Input
store_id = st.text_input("TikTok Store ID", key="store_id", help="Enter your TikTok Shop ID. This is typically found in your TikTok Seller Center URL.")
if not store_id:
    st.warning("Please enter your TikTok Store ID to generate chat links.")

### button to launch chrome with tiktok
if st.button("Launch chrome instance", help="Start Chrome in debug mode automatically and open TikTok Seller."):
    if store_id.strip():
        launch_chrome_instance(store_id)
    else:
        st.error("⚠️ Please enter your TikTok Store ID first.")


# Google Sheet Link Input and ID Extraction
sheet_link = st.text_input("Google Sheet Link", placeholder="Paste your Google Sheet URL here", key="sheet_link")
sheet_id = None
if sheet_link:
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if match:
        sheet_id = match.group(1)
        st.success(f"Google Sheet ID detected: `{sheet_id}`")
    else:
        st.error("Invalid Google Sheet link. Please ensure it's a valid Google Sheet URL.")
        sheet_id = None

# --- Dynamic Sheet Selection ---
sheet_names = []
selected_sheet_name = None
selectbox_disabled = True # Start disabled by default

if sheet_id and creds:
    sheet_names = fetch_sheet_names(sheet_id, creds)
    if sheet_names:
        selectbox_disabled = False # Enable if sheets are found
        # Try to maintain the previously selected sheet, or default to the first
        if 'selected_sheet_name_cache' not in st.session_state or st.session_state.selected_sheet_name_cache not in sheet_names:
            st.session_state.selected_sheet_name_cache = sheet_names[0]

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
        default_index = 0
else:
    # If no sheet_id or creds, clear cache and set placeholder
    st.session_state['selected_sheet_name'] = None
    if 'selected_sheet_name_cache' in st.session_state:
        del st.session_state['selected_sheet_name_cache'] # Clear cache if sheet_id is not valid
    sheet_names = ["Enter Google Sheet Link above"] # Placeholder when no link
    default_index = 0

# The st.selectbox is now always present
selected_sheet_name = st.selectbox(
    "Select Sheet", 
    options=sheet_names, 
    key="selected_sheet_name_ui", 
    index=default_index,
    disabled=selectbox_disabled 
)

# Only update the actual selected_sheet_name in session state if it's a real sheet name
if sheet_names and selected_sheet_name not in ["Enter Google Sheet Link above", "No sheets available"]:
    st.session_state.selected_sheet_name_cache = selected_sheet_name
    st.session_state.selected_sheet_name = selected_sheet_name
else:
    # If placeholder is selected or no valid sheets, ensure session state reflects no valid selection
    st.session_state.selected_sheet_name = None
    if 'selected_sheet_name_cache' in st.session_state:
        del st.session_state['selected_sheet_name_cache']

if st.session_state.selected_sheet_name is None and sheet_id:
    st.warning("Please select a sheet from the dropdown, or ensure your sheet has valid data and permissions.")

# --- Multiple Custom Messages Input ---
st.subheader("Messages to Send")
# Initialize custom_messages in session state if not present
if 'custom_messages' not in st.session_state:
    st.session_state.custom_messages = [""] # Start with one empty message input

# Display existing message inputs and allow editing
# Using a unique key for each text area prevents issues when adding/removing
for i, msg in enumerate(st.session_state.custom_messages):
    st.session_state.custom_messages[i] = st.text_area(f"Message {i+1}", value=msg, key=f"message_input_{i}", height=100)

# Buttons to add/remove messages dynamically
col_msg_buttons = st.columns(2)
with col_msg_buttons[0]:
    if st.button("Add Another Message", key="add_msg_btn"):
        st.session_state.custom_messages.append("")
        st.rerun() # Rerun to display the new text area
with col_msg_buttons[1]:
    if len(st.session_state.custom_messages) > 1 and st.button("Remove Last Message", key="remove_msg_btn"):
        st.session_state.custom_messages.pop()
        st.rerun() # Rerun to remove the text area

# --- Image Upload Input (Modified for multiple files) ---
st.subheader("Images to Attach (Optional)")
uploaded_files = st.file_uploader("Upload images", type=["png", "jpg", "jpeg", "gif"], accept_multiple_files=True, key="images_upload")

# Handle uploaded files: save temporarily and store paths in session state
if 'uploaded_image_paths' not in st.session_state:
    st.session_state['uploaded_image_paths'] = []

if uploaded_files:
    st.session_state['uploaded_image_paths'] = [] # Clear previous list
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
            st.session_state['uploaded_image_paths'] = [] # Clear all if one fails
            break # Stop processing other files
else:
    st.session_state['uploaded_image_paths'] = [] # Clear paths if no files are uploaded or cleared by user

# --- Automation State Management ---
# Initialize automation state variables in session state
if 'creators' not in st.session_state:
    st.session_state['creators'] = []
if 'current_creator_index' not in st.session_state:
    st.session_state['current_creator_index'] = 0
if 'automation_running' not in st.session_state:
    st.session_state['automation_running'] = False
if 'last_status' not in st.session_state:
    st.session_state['last_status'] = "Ready to start automation. Please configure the inputs and click 'Start Messaging Session'."

st.markdown("---") # Visual separator

# --- Automation Control Buttons ---
col1, col2 = st.columns(2)

# Placeholder for dynamic status messages during automation
status_message_placeholder = st.empty()

with col1:
    start_button_disabled = st.session_state.automation_running
    start_button = st.button("Start Messaging Session", type="primary", key="start_btn", use_container_width=True, disabled=start_button_disabled)

with col2:
    stop_button_disabled = not st.session_state.automation_running
    stop_button = st.button("Stop Automation", type="secondary", key="stop_btn", use_container_width=True, disabled=stop_button_disabled)

# Handle Stop Automation button click first
if stop_button: 
    st.session_state.automation_running = False
    st.session_state.last_status = "Automation stopped by user. Click 'Start Messaging Session' to resume."
    status_message_placeholder.info(st.session_state.last_status)

# Handle Start Messaging Session button click
if start_button:
    # Clear all st.cache_data caches to force re-reading of the sheet data
    st.cache_data.clear() 

    # Validate inputs before starting automation
    # Get messages from the session state's list, filtering out empty ones
    messages_to_send_from_ui = [msg.strip() for msg in st.session_state.custom_messages if msg.strip()]

    # Validate if at least one message or image is provided
    if not messages_to_send_from_ui and not st.session_state['uploaded_image_paths']:
        st.session_state.last_status = "Please enter at least one message OR upload at least one image to send."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    elif not sheet_id or not st.session_state.get('selected_sheet_name'):
        st.session_state.last_status = "Please provide a valid Google Sheet link and select a sheet."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    elif not store_id.strip():
        st.session_state.last_status = "Please enter your TikTok Store ID."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    else:
        st.session_state.automation_running = True # Set to True to begin automation
        
        # Only fetch data if starting fresh or if creators list is empty (e.g., after an error or initial load)
        # Also reset index if starting a new list
        if not st.session_state.get('creators') or st.session_state['current_creator_index'] >= len(st.session_state['creators']):
            st.session_state['current_creator_index'] = 0 # Reset to start from the beginning
            st.session_state.last_status = f"Reading Sheet: \"{st.session_state.selected_sheet_name}\"..."
            status_message_placeholder.info(st.session_state.last_status)
            
            sheet_data = read_sheet_data(sheet_id, st.session_state.selected_sheet_name, creds)

            if not sheet_data or len(sheet_data) < 2: # Check for headers + at least one data row
                st.session_state.last_status = "No data found in the specified sheet or range."
                status_message_placeholder.warning(st.session_state.last_status)
                st.session_state['creators'] = []
                st.session_state.automation_running = False
            else:
                creators_list = []
                link_col_idx = 4 # Column E (5th column, 0-indexed)
                approached_col_idx = 7 # Column H (8th column, 0-indexed)

                # Validate if necessary columns exist in the header row
                if len(sheet_data[0]) <= link_col_idx or len(sheet_data[0]) <= approached_col_idx:
                    st.session_state.last_status = (
                        f"Sheet does not have enough columns for the expected data. "
                        f"Please ensure column {link_col_idx + 1} (for Link) and "
                        f"column {approached_col_idx + 1} (for Approached) exist in your sheet headers."
                    )
                    status_message_placeholder.error(st.session_state.last_status)
                    st.session_state['creators'] = []
                    st.session_state.automation_running = False
                else:
                    for i, row in enumerate(sheet_data[1:]): # Iterate from the second row (index 1) for data
                        # Safely get 'approached' value, handling short rows
                        raw_approached_value = ''
                        if len(row) > approached_col_idx:
                            raw_approached_value = row[approached_col_idx]
                        
                        # Safely get 'link' value, handling short rows
                        link = ''
                        if len(row) > link_col_idx:
                            link = row[link_col_idx]

                        # Determine if the row has been approached (case-insensitive "TRUE")
                        is_approached = False
                        if isinstance(raw_approached_value, bool):
                            is_approached = raw_approached_value
                        elif isinstance(raw_approached_value, str):
                            is_approached = raw_approached_value.strip().upper() == "TRUE"

                        # Add to creators_list ONLY if 'cid=' is in link and 'is_approached' is False
                        if "cid=" in link and not is_approached:
                            try:
                                cid = link.split("cid=")[1].split("&")[0]
                                creators_list.append({"row": i + 2, "cid": cid}) # Store actual row number in sheet (1-indexed)
                            except IndexError:
                                st.warning(f"Could not parse CID from link in row {i + 2}: {link}")

                    st.session_state['creators'] = creators_list

                    if not st.session_state['creators']:
                        st.session_state.last_status = "No new creators found to message based on fixed column positions (Link in column E, Approached in column H)."
                        status_message_placeholder.info(st.session_state.last_status)
                        st.session_state.automation_running = False
                    else:
                        st.session_state.last_status = f"Found {len(st.session_state['creators'])} new creators to message. Preparing browser for automation..."
                        status_message_placeholder.success(st.session_state.last_status)
        
        # If automation is set to run and we have creators, trigger the first step immediately
        if st.session_state.automation_running and st.session_state.get('creators'):
            st.rerun() # Trigger a rerun to enter the automation loop below

# --- Automation Loop Logic (executes on every rerun if automation_running is True) ---
# This block will be executed repeatedly as st.rerun() is called
if st.session_state.automation_running and st.session_state.get('creators') and \
   st.session_state['current_creator_index'] < len(st.session_state['creators']):
    
    current_creator = st.session_state['creators'][st.session_state['current_creator_index']]
    creator_row = current_creator['row']
    creator_cid = current_creator['cid']
    # Get messages from the session state's list, filtering out empty ones
    messages_to_send = [msg.strip() for msg in st.session_state.custom_messages if msg.strip()] 
    image_paths_to_send = st.session_state.get('uploaded_image_paths', []) # Get list of paths

    st.markdown(f"---")
    st.subheader(f"Automating for Current Creator: Row {creator_row}")
    st.markdown(f"**Creator ID:** `{creator_cid}`")
    
    driver = get_selenium_driver() # Ensure driver is active
    if not driver:
        st.session_state.last_status = "Browser driver is not active. Automation stopped."
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation if driver fails
        st.stop() # Stop the current script execution immediately

    chat_url = f"https://affiliate.tiktok.com/seller/im?shop_id={store_id}&creator_id={creator_cid}&enter_from=affiliate_creator_details&shop_region=TH"
    st.session_state.last_status = f"Navigating to chat for creator (Row {creator_row})...."
    status_message_placeholder.info(st.session_state.last_status)

    try:
        driver.get(chat_url)
        
        # Selector for the message input area (this should be consistent across TikTok updates)
        message_input_selector = 'textarea[placeholder*="Send a message"]' 
        
        WebDriverWait(driver, 30).until( # Max 30 seconds to find the message input
            EC.presence_of_element_located((By.CSS_SELECTOR, message_input_selector))
        )
        message_textarea = driver.find_element(By.CSS_SELECTOR, message_input_selector)
        
        # --- Multiple Messages Sending Logic (send all messages first) ---
        for i, msg_content in enumerate(messages_to_send):
            if not msg_content.strip(): # Skip if a message input was left empty
                continue

            message_textarea.clear() # Clear any previous text in the input box
            message_textarea.send_keys(msg_content) # Type the current message
            
            st.session_state.last_status = f"Message {i+1} successfully pasted for creator (Row {creator_row}). Sending..."
            status_message_placeholder.success(st.session_state.last_status)
            
            time.sleep(1) # Short delay after pasting the message

            # Simulate pressing Enter key to send the message
            message_textarea.send_keys(Keys.ENTER)
            
            st.session_state.last_status = f"Message {i+1} sent successfully for creator (Row {creator_row})."
            status_message_placeholder.success(st.session_state.last_status)
            
            time.sleep(2) # Short delay to allow the message to be sent and UI to update

        # --- Image Upload Logic (send image(s) last) ---
        if image_paths_to_send: # Check if there are any images to send
            st.session_state.last_status = f"Attempting to upload {len(image_paths_to_send)} image(s) for creator (Row {creator_row})..."
            status_message_placeholder.info(st.session_state.last_status)
            try:
                # --- CRITICAL: CUSTOMIZE THESE SELECTORS FOR TIKTOK'S UI ---
                # You MUST inspect the TikTok page (in the manually launched Chrome) to get the correct selectors.
                
                # Step 1 (Optional but often needed): Click the attachment/image icon/button
                # This button might reveal or activate the actual file input.
                # Example (replace with actual selector from TikTok if needed):
                # attach_button_selector = 'button[aria-label="Add photo/video"]' 
                # WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, attach_button_selector))).click()
                # time.sleep(1) # Small delay after clicking
                
                # Step 2: Find the HIDDEN <input type="file"> element
                # This is the element you send the file path(s) to. It's often hidden by CSS.
                
                # Generic attempt to find the file input directly
                file_input_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]')) 
                )
                
                # Join all image paths with newline characters for multiple file upload
                # This is the most common and robust way to send multiple files to a single input[type="file"]
                all_image_paths_string = "\n".join(image_paths_to_send)
                
                file_input_element.send_keys(all_image_paths_string)
                
                st.session_state.last_status = f"Image(s) sent to upload input for creator (Row {creator_row}). Waiting for TikTok to process..."
                status_message_placeholder.success(st.session_state.last_status)
                
                # IMPORTANT: Add a delay here to allow TikTok to upload and process the images.
                # This delay might need to be significant (e.g., 5-15 seconds) depending on image sizes and network.
                time.sleep(5) # Increased delay for multiple images

                # --- Click "OK" button in popup if it appears ---
                dialog_selector = 'div.arco-modal[role="dialog"]' # Selector for the modal dialog
                ok_button_selector = 'button.arco-btn.arco-btn-primary.arco-btn-size-large.arco-btn-shape-square'
                
                try:
                    # Wait for the dialog to be visible
                    WebDriverWait(driver, 5).until( # Short wait for popup
                        EC.visibility_of_element_located((By.CSS_SELECTOR, dialog_selector))
                    )
                    st.session_state.last_status = f"Image confirmation dialog detected for creator (Row {creator_row}). Clicking OK..."
                    status_message_placeholder.info(st.session_state.last_status)

                    # Wait for the OK button to be clickable within the dialog
                    ok_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ok_button_selector))
                    )
                    ok_button.click()
                    st.session_state.last_status = f"Clicked OK on image confirmation dialog for creator (Row {creator_row})."
                    status_message_placeholder.success(st.session_state.last_status)
                    time.sleep(2) # Give time for dialog to close and image(s) to send
                except TimeoutException:
                    st.session_state.last_status = "No image confirmation dialog appeared or took too long. Proceeding."
                    status_message_placeholder.info(st.session_state.last_status)
                except Exception as e:
                    st.session_state.last_status = f"Error interacting with image confirmation dialog: {e}. Proceeding."
                    status_message_placeholder.error(st.session_state.last_status)
                # --- END OK BUTTON LOGIC ---

                time.sleep(2) # Additional delay after potential dialog interaction

            except TimeoutException:
                st.session_state.last_status = (f"Timeout: Image upload element not found or image not processed for creator (Row {creator_row}). "
                                                 "Automation proceeding without image upload for this creator.")
                status_message_placeholder.warning(st.session_state.last_status)
            except NoSuchElementException:
                st.session_state.last_status = (f"Image upload element not found for creator (Row {creator_row}). "
                                                 "Automation proceeding without image upload for this creator.")
                status_message_placeholder.warning(st.session_state.last_status)
            except Exception as e:
                st.session_state.last_status = (f"Error during image upload for creator (Row {creator_row}): {e}. "
                                                 "Automation proceeding without image upload for this creator.")
                status_message_placeholder.error(st.session_state.last_status)
            finally:
                # Clean up the temporary image files after attempting to send them
                for temp_path in image_paths_to_send:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            st.info(f"Cleaned up temporary image file: {temp_path}")
                        except Exception as e:
                            st.warning(f"Could not remove temporary image file {temp_path}: {e}")
                st.session_state['uploaded_image_paths'] = [] # Clear paths for the next automation cycle

        # --- Update Google Sheet ---
        today_str = datetime.now().strftime("%m/%d/%Y")
        week_start = datetime.now() - timedelta(days=datetime.now().weekday()) # Start of current week (Monday)
        week_str = week_start.strftime("%m/%d/%Y")
        month_str = datetime.now().strftime("%B")

        update_success = update_sheet_data(
            sheet_id, 
            st.session_state.selected_sheet_name, 
            creator_row, 
            [True, today_str, week_str, month_str], # Data to write: Approached=True, Today's Date, Week Start, Month
            creds
        )
        
        # --- Move to Next Creator or Complete Automation ---
        if update_success:
            st.session_state['current_creator_index'] += 1
            if st.session_state.automation_running and st.session_state['current_creator_index'] < len(st.session_state['creators']):
                st.session_state.last_status = f"Sheet updated for creator {creator_row}. Moving to next influencer..."
                status_message_placeholder.info(st.session_state.last_status)
                st.rerun() # Trigger next step of automation
            else:
                st.session_state.last_status = "All eligible creators processed for this session! Automation finished."
                status_message_placeholder.success(st.session_state.last_status)
                # Reset state for a fresh start
                st.session_state['creators'] = []
                st.session_state['current_creator_index'] = 0
                st.session_state.automation_running = False # Stop automation
        else:
            st.session_state.last_status = f"Failed to update sheet for row {creator_row}. Automation stopped."
            status_message_placeholder.error(st.session_state.last_status)
            st.session_state.automation_running = False # Stop automation on update failure

    except TimeoutException:
        st.session_state.last_status = (f"Timeout during automation for creator (Row {creator_row}). "
                                         "A required element (e.g., chat input) was not found within the time limit. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation on timeout
    except NoSuchElementException as e:
        st.session_state.last_status = (f"Element not found during automation for creator (Row {creator_row}): {e}. "
                                         "TikTok UI might have changed or page failed to load correctly. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False # Stop automation on element not found
    except WebDriverException as e:
        st.session_state.last_status = (f"Browser error during automation: {e}. "
                                         "The connection to the automated browser might have been lost. Please ensure Chrome is still open. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        close_selenium_driver() # Attempt to clean up
        st.session_state.automation_running = False # Stop automation on general WebDriver error
    except Exception as e:
        st.session_state.last_status = (f"An unexpected error occurred during automation: {e}. Automation stopped.")
        status_message_placeholder.error(st.session_state.last_status)
        st.session_state.automation_running = False
    
    # If automation was stopped (by error or completion) within this block, ensure Streamlit stops the rerun chain
    if not st.session_state.automation_running:
        st.stop() # Stop the current script execution to prevent infinite reruns if automation is intentionally halted

# Display last status message when automation is not running or completed
else:
    status_message_placeholder.info(st.session_state.last_status)

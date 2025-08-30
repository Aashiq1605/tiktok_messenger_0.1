import streamlit as st
import pandas as pd
import os
import re
import tempfile
from datetime import datetime, timedelta

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys
import time
import subprocess

# --- Chrome Debug Mode Config ---
# On a Mac, the path to Chrome is /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
# On Linux, it's typically /usr/bin/google-chrome-stable
# On Windows, it can be C:\Program Files\Google\Chrome\Application\chrome.exe
# IMPORTANT: This path must be correct for the OS where you run the app.
# The `launch_chrome_instance` function will not work on Streamlit Cloud.
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR = os.path.expanduser("~/chrome_debug_profile")
REMOTE_DEBUG_PORT = "9222"

def launch_chrome_instance(store_id: str):
    """Launch Chrome in remote debugging mode automatically and open TikTok Seller for given store."""
    # This function is intended for local development only.
    # It will not work on Streamlit Cloud as there is no user-facing browser.
    
    # We'll remove the `pkill` command to prevent errors on systems where it's not installed.
    # You can manually kill any existing instances before running if needed.
    # The `subprocess.Popen` call might fail silently or raise an error on some systems.
    
    tiktok_url = f"https://seller.tiktokglobalshop.com/account/login?shop_id={store_id}"

    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={REMOTE_DEBUG_PORT}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        tiktok_url
    ]
    
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        st.success(f"✅ Chrome launched in debug mode and opened TikTok Seller for store ID {store_id}. Please ensure you are logged in.")
        st.warning("Note: This feature only works on your local machine and will not launch a visible browser on Streamlit Cloud.")
    except FileNotFoundError:
        st.error(f"❌ Could not find Chrome executable at '{CHROME_PATH}'. Please check the path and try again.")
    except Exception as e:
        st.error(f"❌ An error occurred while trying to launch Chrome: {e}")


# --- Streamlit UI Configuration ---
st.set_page_config(
    page_title="TikTok Affiliate Messenger",
    page_icon="💬",
    layout="centered"
)


# --- Global Selenium Driver Management ---
if 'driver' not in st.session_state:
    st.session_state.driver = None

def get_selenium_driver():
    """Attach to the Chrome instance launched by this app."""
    if st.session_state.driver is None:
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"127.0.0.1:{REMOTE_DEBUG_PORT}")
            service = Service()
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

# --- Streamlit App UI Layout ---

st.title("💬 TikTok Affiliate Messenger")
st.markdown("Automate TikTok Affiliate messaging.")

# TikTok Store ID Input
store_id = st.text_input("TikTok Store ID", key="store_id", help="Enter your TikTok Shop ID. This is typically found in your TikTok Seller Center URL.")
if not store_id:
    st.warning("Please enter your TikTok Store ID.")

### button to launch chrome with tiktok
if st.button("Launch Chrome Instance (Local Only)", help="Start Chrome in debug mode automatically and open TikTok Seller. This function is only for local use."):
    if store_id.strip():
        launch_chrome_instance(store_id)
    else:
        st.error("⚠️ Please enter your TikTok Store ID first.")

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

# --- Image Upload Input ---
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

st.markdown("---")

# --- Manual Chat Automation ---
st.subheader("Send Message to Creator")
creator_id = st.text_input("Creator ID (CID)", help="Paste the 'cid' from the TikTok Affiliate link here.")

col1, col2 = st.columns(2)

with col1:
    send_button_disabled = not creator_id.strip() or (not st.session_state.custom_messages and not st.session_state.uploaded_image_paths)
    send_button = st.button("Send Message", type="primary", key="send_btn", use_container_width=True, disabled=send_button_disabled)

# Placeholder for dynamic status messages
status_message_placeholder = st.empty()


if send_button:
    # Get messages and image paths from session state
    messages_to_send = [msg.strip() for msg in st.session_state.custom_messages if msg.strip()]
    image_paths_to_send = st.session_state.get('uploaded_image_paths', [])

    if not messages_to_send and not image_paths_to_send:
        status_message_placeholder.error("Please enter at least one message or upload at least one image to send.")
        st.stop()
    
    if not creator_id.strip():
        status_message_placeholder.error("Please enter a Creator ID.")
        st.stop()
    
    if not store_id.strip():
        status_message_placeholder.error("Please enter your TikTok Store ID.")
        st.stop()

    status_message_placeholder.info(f"Connecting to browser and preparing to send message to creator '{creator_id}'...")

    driver = get_selenium_driver()
    if not driver:
        status_message_placeholder.error("Browser driver is not active. Please ensure Chrome is launched in debug mode.")
        st.stop()

    chat_url = f"https://affiliate.tiktok.com/seller/im?shop_id={store_id}&creator_id={creator_id}&enter_from=affiliate_creator_details&shop_region=TH"
    status_message_placeholder.info(f"Navigating to chat for creator '{creator_id}'...")

    try:
        driver.get(chat_url)

        message_input_selector = 'textarea[placeholder*="Send a message"]'
        
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, message_input_selector))
        )
        message_textarea = driver.find_element(By.CSS_SELECTOR, message_input_selector)

        # Send all messages first
        for i, msg_content in enumerate(messages_to_send):
            if not msg_content.strip():
                continue

            message_textarea.clear()
            message_textarea.send_keys(msg_content)
            
            status_message_placeholder.success(f"Message {i+1} pasted. Sending...")
            
            time.sleep(1)
            message_textarea.send_keys(Keys.ENTER)
            
            status_message_placeholder.success(f"Message {i+1} sent successfully.")
            
            time.sleep(2)

        # Send images last
        if image_paths_to_send:
            status_message_placeholder.info(f"Attempting to upload {len(image_paths_to_send)} image(s)...")
            try:
                # Find the hidden file input element
                file_input_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="file"]'))
                )
                
                all_image_paths_string = "\n".join(image_paths_to_send)
                
                file_input_element.send_keys(all_image_paths_string)
                
                status_message_placeholder.success("Image(s) sent to upload input. Waiting for TikTok to process...")
                time.sleep(5) # Delay to allow image upload

                # Optional: Handle pop-up dialog after image upload
                dialog_selector = 'div.arco-modal[role="dialog"]'
                ok_button_selector = 'button.arco-btn.arco-btn-primary.arco-btn-size-large.arco-btn-shape-square'
                try:
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, dialog_selector))
                    )
                    status_message_placeholder.info("Image confirmation dialog detected. Clicking OK...")
                    ok_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ok_button_selector))
                    )
                    ok_button.click()
                    status_message_placeholder.success("Clicked OK on image dialog.")
                    time.sleep(2)
                except TimeoutException:
                    status_message_placeholder.info("No image confirmation dialog appeared. Proceeding.")
                except Exception as e:
                    status_message_placeholder.error(f"Error interacting with image confirmation dialog: {e}. Proceeding.")
            
            except TimeoutException:
                status_message_placeholder.warning("Timeout: Image upload element not found. Automation proceeding without image upload.")
            except NoSuchElementException:
                status_message_placeholder.warning("Image upload element not found. Automation proceeding without image upload.")
            except Exception as e:
                status_message_placeholder.error(f"Error during image upload: {e}. Automation proceeding without image upload.")
            finally:
                for temp_path in image_paths_to_send:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                            st.info(f"Cleaned up temporary image file: {temp_path}")
                        except Exception as e:
                            st.warning(f"Could not remove temporary image file {temp_path}: {e}")
                st.session_state['uploaded_image_paths'] = []

        status_message_placeholder.success("All messages and images sent successfully!")
        st.balloons()
    
    except TimeoutException:
        status_message_placeholder.error(f"Timeout: A required element was not found within the time limit.")
    except NoSuchElementException as e:
        status_message_placeholder.error(f"Element not found: {e}. TikTok UI might have changed.")
    except WebDriverException as e:
        status_message_placeholder.error(f"Browser error: {e}. The connection to the automated browser might have been lost. Please ensure Chrome is still open.")
        close_selenium_driver()
    except Exception as e:
        status_message_placeholder.error(f"An unexpected error occurred: {e}.")

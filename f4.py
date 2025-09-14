import streamlit as st
import pandas as pd
import time
import random
from datetime import datetime, timedelta
import threading
import queue
import os
import pyttsx3
import requests
from typing import Dict, List, Optional

# ----------- File Configuration ------------
REFERENCE_FILE_PATH = "/Users/dhaval/Desktop/RA/ref22.csv"
ACTIVE_FILE_PATH = "/Users/dhaval/Desktop/RA/Testing.csv"

# ----------- Server Configuration ------------
SERVER_URL = "http://your-server.com/api/heartbeat"  # Replace with your actual server URL
SERVER_TIMEOUT = 5  # seconds
CONNECTION_WARNING_THRESHOLD = 60  # seconds

# ----------- Global Queues ------------
rfid_event_queue = queue.Queue()
server_status_queue = queue.Queue()

# ----------- TTS Function ------------
def speak(text):
    def _speak():
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"TTS Error: {e}")
    threading.Thread(target=_speak, daemon=True).start()

# ----------- Server Connection Functions ------------
def check_server_connection():
    """Check if server is reachable"""
    try:
        response = requests.get(SERVER_URL, timeout=SERVER_TIMEOUT)
        return response.status_code == 200
    except Exception:
        return False

def server_monitor_thread(running_flag):
    """Background thread to monitor server connectivity"""
    last_successful_connection = datetime.now()
    
    while running_flag['running']:
        if check_server_connection():
            last_successful_connection = datetime.now()
            server_status_queue.put({
                'status': 'connected',
                'timestamp': last_successful_connection,
                'message': 'Server connected'
            })
        else:
            time_since_last_connection = datetime.now() - last_successful_connection
            if time_since_last_connection.total_seconds() > CONNECTION_WARNING_THRESHOLD:
                server_status_queue.put({
                    'status': 'disconnected',
                    'timestamp': datetime.now(),
                    'message': f'Server disconnected for {int(time_since_last_connection.total_seconds())} seconds',
                    'last_connected': last_successful_connection
                })
        
        time.sleep(10)  # Check every 10 seconds

# ----------- Lab Occupancy Tracking ------------
class LabOccupancyTracker:
    def __init__(self):
        self.current_occupants = {}  # {name: entry_timestamp}
        self.entry_exit_log = []
    
    def person_entered(self, name: str, epc: str, timestamp: str):
        """Record person entering the lab"""
        self.current_occupants[name] = {
            'epc': epc,
            'entry_time': timestamp,
            'status': 'IN'
        }
        self.entry_exit_log.append({
            'name': name,
            'epc': epc,
            'action': 'ENTRY',
            'timestamp': timestamp
        })
    
    def person_exited(self, name: str, timestamp: str):
        """Record person exiting the lab"""
        if name in self.current_occupants:
            entry_time = self.current_occupants[name]['entry_time']
            duration = self.calculate_duration(entry_time, timestamp)
            
            self.entry_exit_log.append({
                'name': name,
                'epc': self.current_occupants[name]['epc'],
                'action': 'EXIT',
                'timestamp': timestamp,
                'duration': duration
            })
            
            del self.current_occupants[name]
    
    def calculate_duration(self, entry_time: str, exit_time: str) -> str:
        """Calculate duration between entry and exit"""
        try:
            entry_dt = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
            exit_dt = datetime.strptime(exit_time, '%Y-%m-%d %H:%M:%S')
            duration = exit_dt - entry_dt
            
            hours = duration.seconds // 3600
            minutes = (duration.seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        except:
            return "Unknown"
    
    def get_current_occupants(self) -> Dict:
        """Get list of people currently in the lab"""
        return self.current_occupants.copy()
    
    def get_occupancy_count(self) -> int:
        """Get current occupancy count"""
        return len(self.current_occupants)
    
    def force_exit_all(self, timestamp: str):
        """Force exit all occupants (for emergency or system reset)"""
        for name in list(self.current_occupants.keys()):
            self.person_exited(name, timestamp)

# ----------- Enhanced Functions ------------
def announce_all_matches(matched_names):
    """Announce all matched names from the comparison"""
    if not matched_names:
        speak("No matches found")
        return
    
    if len(matched_names) == 1:
        speak(f"Access granted to {matched_names[0]}. Welcome to the Lab")
    else:
        names_text = ", ".join(matched_names[:-1]) + f", and {matched_names[-1]}"
        speak(f"Access granted to {names_text}. Welcome to the Lab")

def log_all_matches(matched_names, matched_epcs):
    """Log all matched users to access logs"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    for i, name in enumerate(matched_names):
        epc = matched_epcs[i] if i < len(matched_epcs) else "Unknown"
        log_entry = {
            'status': 'GRANTED',
            'reason': 'Bulk access granted',
            'name': name,
            'card_id': epc,
            'timestamp': timestamp
        }
        st.session_state.access_logs.append(log_entry)
        
        # Track occupancy
        st.session_state.occupancy_tracker.person_entered(name, epc, timestamp)
    
    # Keep only last 50 logs
    if len(st.session_state.access_logs) > 50:
        st.session_state.access_logs = st.session_state.access_logs[-50:]

def announce_lab_occupancy():
    """Announce current lab occupancy with names"""
    occupants = st.session_state.occupancy_tracker.get_current_occupants()
    count = len(occupants)
    
    if count == 0:
        speak("Lab is currently empty")
        return
    
    names = list(occupants.keys())
    if count == 1:
        speak(f"One person currently in the lab: {names[0]}")
    else:
        names_text = ", ".join(names[:-1]) + f", and {names[-1]}"
        speak(f"{count} people currently in the lab: {names_text}")

# ----------- Page Configuration ------------
st.set_page_config(
    page_title="RFID Entrance System",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------- Initialize Session State ------------
if 'system_running' not in st.session_state:
    st.session_state.system_running = False

if 'access_logs' not in st.session_state:
    st.session_state.access_logs = []

if 'last_scan' not in st.session_state:
    st.session_state.last_scan = None

if 'last_comparison_time' not in st.session_state:
    st.session_state.last_comparison_time = None

if 'occupancy_tracker' not in st.session_state:
    st.session_state.occupancy_tracker = LabOccupancyTracker()

if 'server_status' not in st.session_state:
    st.session_state.server_status = {
        'connected': True,
        'last_check': datetime.now(),
        'message': 'Checking connection...'
    }

# ----------- Data Loading Functions ------------
def get_reference_data():
    if os.path.exists(REFERENCE_FILE_PATH):
        return pd.read_csv(REFERENCE_FILE_PATH)
    else:
        return pd.DataFrame(columns=['EPC', 'Name'])

def get_active_data():
    if os.path.exists(ACTIVE_FILE_PATH):
        return pd.read_csv(ACTIVE_FILE_PATH)
    else:
        return pd.DataFrame(columns=['EPC'])

# ----------- Enhanced EPC Comparison ------------
def compare_active_with_reference(active_df, reference_df):
    reference_epcs = set(reference_df['EPC'])
    active_df['status'] = active_df['EPC'].apply(lambda epc: 'MATCHED ✅' if epc in reference_epcs else 'NOT FOUND ❌')
    
    # Get matched names and EPCs
    matched_epcs = active_df[active_df['status'] == 'MATCHED ✅']['EPC'].tolist()
    matched_names = []
    
    for epc in matched_epcs:
        name_row = reference_df[reference_df['EPC'] == epc]
        if not name_row.empty:
            matched_names.append(name_row.iloc[0]['Name'])
    
    return active_df, matched_names, matched_epcs

# ----------- RFID Simulation ------------
def simulate_rfid_scan():
    return random.choice([
        "A02A061028A201547A021102",
        "A02A061028A201548A021802",
        "A02A061028A201550A021902",
        "UNKNOWN123456789"
    ])

def process_rfid_scan(card_id, reference_df):
    user_info = reference_df[reference_df['EPC'] == card_id]
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if user_info.empty:
        return {
            'status': 'DENIED',
            'reason': 'User not found',
            'name': 'Unknown',
            'card_id': card_id,
            'timestamp': timestamp
        }
    
    user = user_info.iloc[0]
    name = user['Name']
    
    # Check if person is already in lab (for exit tracking)
    current_occupants = st.session_state.occupancy_tracker.get_current_occupants()
    
    if name in current_occupants:
        # Person is exiting
        st.session_state.occupancy_tracker.person_exited(name, timestamp)
        action = 'EXIT'
        message = f"Goodbye {name}. Thank you for visiting the lab."
    else:
        # Person is entering
        st.session_state.occupancy_tracker.person_entered(name, card_id, timestamp)
        action = 'ENTRY'
        message = f"Access granted to {name}. Welcome to the Lab"
    
    return {
        'status': 'GRANTED',
        'reason': f'Access granted - {action}',
        'name': name,
        'card_id': card_id,
        'timestamp': timestamp,
        'action': action,
        'message': message
    }

# ----------- Scanner Thread ------------
def rfid_scanner_thread(running_flag):
    while running_flag['running']:
        if random.random() < 0.3:
            card_id = simulate_rfid_scan()
            rfid_event_queue.put(card_id)
        time.sleep(1)

# ----------- Main Application ------------
def main():
    st.title("🔐 RFID Entrance System with Server Monitoring")
    st.markdown("---")

    # Check server status
    if not server_status_queue.empty():
        status_update = server_status_queue.get()
        st.session_state.server_status = status_update
        
        if status_update['status'] == 'disconnected':
            st.error(f"⚠️ {status_update['message']}")
            speak("Warning: Server connection lost")

    with st.sidebar:
        st.header("System Controls")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("🟢 Start System", use_container_width=True):
                st.session_state.system_running = True
                st.success("System Started!")
                speak("RFID system initialized")
                
                # Start RFID scanner
                if 'scanner_thread' not in st.session_state or not st.session_state.scanner_thread.is_alive():
                    st.session_state.system_running_flag = {"running": True}
                    st.session_state.scanner_thread = threading.Thread(
                        target=rfid_scanner_thread,
                        args=(st.session_state.system_running_flag,),
                        daemon=True
                    )
                    st.session_state.scanner_thread.start()
                
                # Start server monitor
                if 'server_monitor_thread' not in st.session_state or not st.session_state.server_monitor_thread.is_alive():
                    st.session_state.server_monitor_flag = {"running": True}
                    st.session_state.server_monitor_thread = threading.Thread(
                        target=server_monitor_thread,
                        args=(st.session_state.server_monitor_flag,),
                        daemon=True
                    )
                    st.session_state.server_monitor_thread.start()

        with col2:
            if st.button("🔴 Stop System", use_container_width=True):
                st.session_state.system_running = False
                if 'system_running_flag' in st.session_state:
                    st.session_state.system_running_flag['running'] = False
                if 'server_monitor_flag' in st.session_state:
                    st.session_state.server_monitor_flag['running'] = False
                st.warning("System Stopped!")

        if st.button("🔄 Restart System", use_container_width=True):
            # Stop everything
            st.session_state.system_running = False
            if 'system_running_flag' in st.session_state:
                st.session_state.system_running_flag['running'] = False
            if 'server_monitor_flag' in st.session_state:
                st.session_state.server_monitor_flag['running'] = False
            
            time.sleep(0.5)
            
            # Reset and restart
            st.session_state.system_running = True
            st.session_state.access_logs = []
            st.session_state.last_scan = None
            st.session_state.occupancy_tracker = LabOccupancyTracker()
            st.info("System Restarted!")
            
            # Restart threads
            st.session_state.system_running_flag = {"running": True}
            st.session_state.scanner_thread = threading.Thread(
                target=rfid_scanner_thread,
                args=(st.session_state.system_running_flag,),
                daemon=True
            )
            st.session_state.scanner_thread.start()
            
            st.session_state.server_monitor_flag = {"running": True}
            st.session_state.server_monitor_thread = threading.Thread(
                target=server_monitor_thread,
                args=(st.session_state.server_monitor_flag,),
                daemon=True
            )
            st.session_state.server_monitor_thread.start()

        st.markdown("---")
        st.header("System Status")
        status_color = "🟢" if st.session_state.system_running else "🔴"
        status_text = "RUNNING" if st.session_state.system_running else "STOPPED"
        st.markdown(f"**Status:** {status_color} {status_text}")
        
        # Server status
        server_color = "🟢" if st.session_state.server_status.get('connected', True) else "🔴"
        server_text = "CONNECTED" if st.session_state.server_status.get('connected', True) else "DISCONNECTED"
        st.markdown(f"**Server:** {server_color} {server_text}")

        # Lab occupancy
        occupancy_count = st.session_state.occupancy_tracker.get_occupancy_count()
        st.markdown(f"**Lab Occupancy:** {occupancy_count} people")

        st.markdown("---")
        st.header("Manual Testing")
        test_card = st.text_input("Enter EPC:", placeholder="A02A061028A201547A021102")
        if st.button("🔍 Test Scan"):
            if test_card and st.session_state.system_running:
                rfid_event_queue.put(test_card)

        st.markdown("---")
        st.header("Lab Management")
        
        if st.button("📢 Announce All Present", use_container_width=True):
            active_df = get_active_data()
            reference_df = get_reference_data()
            if not active_df.empty and not reference_df.empty:
                _, matched_names, matched_epcs = compare_active_with_reference(active_df, reference_df)
                if matched_names:
                    announce_all_matches(matched_names)
                    log_all_matches(matched_names, matched_epcs)
                    st.success(f"Announced and logged {len(matched_names)} matches!")
                else:
                    speak("No one detected in the lab")
                    st.info("No matches found to announce")
            else:
                st.warning("No data available for comparison")
        
        if st.button("👥 Announce Lab Occupancy", use_container_width=True):
            announce_lab_occupancy()
        
        if st.button("🚪 Force Exit All", use_container_width=True):
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            st.session_state.occupancy_tracker.force_exit_all(timestamp)
            st.success("All occupants marked as exited")
            speak("All lab occupants have been logged as exited")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("📊 Access Monitor")

        # Process RFID events
        if st.session_state.system_running and not rfid_event_queue.empty():
            card_id = rfid_event_queue.get()
            reference_df = get_reference_data()
            result = process_rfid_scan(card_id, reference_df)

            st.session_state.access_logs.append(result)
            st.session_state.last_scan = result

            if len(st.session_state.access_logs) > 50:
                st.session_state.access_logs = st.session_state.access_logs[-50:]

            if result['status'] == 'GRANTED':
                st.write(f"✅ Speaking: {result['message']}")
                speak(result['message'])
            else:
                st.write("❌ Speaking: Access denied")
                speak("Access denied. Unknown user")

        # Display last scan result
        if st.session_state.last_scan:
            result = st.session_state.last_scan
            if result['status'] == 'GRANTED':
                st.success("✅ ACCESS GRANTED")
                action_emoji = "🚪➡️" if result.get('action') == 'ENTRY' else "🚪⬅️"
                st.markdown(f"""
                **Action:** {action_emoji} {result.get('action', 'ACCESS')}  
                **Name:** {result['name']}  
                **EPC:** {result['card_id']}  
                **Time:** {result['timestamp']}
                """)
            else:
                st.error("❌ ACCESS DENIED")
                st.markdown(f"""
                **Reason:** {result['reason']}  
                **EPC:** {result['card_id']}  
                **Time:** {result['timestamp']}
                """)

        st.markdown("---")
        st.subheader("📋 Recent Access Logs")

        if st.session_state.access_logs:
            logs_df = pd.DataFrame(st.session_state.access_logs)
            if 'timestamp' in logs_df.columns:
                logs_df = logs_df.sort_values('timestamp', ascending=False)
            logs_df = logs_df.fillna("N/A")

            def color_status(val):
                return 'background-color: #d4edda' if val == 'GRANTED' else 'background-color: #f8d7da'

            styled_df = logs_df.style.map(color_status, subset=['status'])
            st.dataframe(styled_df, use_container_width=True, height=300)
        else:
            st.info("No access attempts yet.")

    with col2:
        st.header("📈 Statistics")
        if st.session_state.access_logs:
            logs_df = pd.DataFrame(st.session_state.access_logs)
            total = len(logs_df)
            granted = len(logs_df[logs_df['status'] == 'GRANTED'])
            denied = len(logs_df[logs_df['status'] == 'DENIED'])
            st.metric("Total Attempts", total)
            st.metric("Access Granted", granted, delta=f"{(granted/total*100):.1f}%")
            st.metric("Access Denied", denied, delta=f"{(denied/total*100):.1f}%")

            top_users = logs_df[logs_df['status'] == 'GRANTED']['name'].value_counts().head(5)
            st.markdown("---")
            st.subheader("👥 Top Users")
            for user, count in top_users.items():
                st.write(f"**{user}:** {count} entries")
        else:
            st.info("No statistics available.")

        st.markdown("---")
        st.subheader("🏢 Current Lab Occupancy")
        current_occupants = st.session_state.occupancy_tracker.get_current_occupants()
        
        if current_occupants:
            st.success(f"**{len(current_occupants)} people in lab:**")
            for name, info in current_occupants.items():
                entry_time = datetime.strptime(info['entry_time'], '%Y-%m-%d %H:%M:%S')
                duration = datetime.now() - entry_time
                hours = duration.seconds // 3600
                minutes = (duration.seconds % 3600) // 60
                st.write(f"**{name}** - {hours}h {minutes}m")
        else:
            st.info("Lab is currently empty")

        st.markdown("---")
        st.subheader("💾 Database View")
        reference_df = get_reference_data()
        st.write(f"**Reference Records:** {len(reference_df)}")
        st.dataframe(reference_df, use_container_width=True)

    # Server status warning
    if not st.session_state.server_status.get('connected', True):
        st.error("🚨 **SERVER CONNECTION WARNING**")
        st.error(st.session_state.server_status.get('message', 'Server disconnected'))
        
        # Show people still in lab during server outage
        current_occupants = st.session_state.occupancy_tracker.get_current_occupants()
        if current_occupants:
            st.warning("⚠️ **People still in lab during server outage:**")
            for name in current_occupants.keys():
                st.write(f"• {name}")

    st.markdown("---")
    st.header("🔍 EPC Match Status Check")

    active_df = get_active_data()
    reference_df = get_reference_data()

    if not active_df.empty and not reference_df.empty:
        result_df, matched_names, matched_epcs = compare_active_with_reference(active_df, reference_df)
        
        st.dataframe(result_df, use_container_width=True)
        
        if matched_names:
            st.success(f"✅ **{len(matched_names)} people detected:**")
            for i, name in enumerate(matched_names, 1):
                st.write(f"{i}. {name}")
        else:
            st.warning("❌ No matches found between active and reference files")
    else:
        st.warning("One or both files are empty or missing.")

    if st.session_state.system_running:
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()
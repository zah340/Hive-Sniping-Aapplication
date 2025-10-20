import sys
import json
import time
import threading
import winsound
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, 
                           QSpinBox, QLabel, QDialog, QLineEdit, QDialogButtonBox,
                           QMessageBox, QMenu, QFrame, QTextEdit, QStyledItemDelegate)
from PyQt5.QtCore import QTimer, pyqtSignal, QObject, Qt, QRect
from PyQt5.QtGui import QFont, QPalette, QColor, QPainter


class PlayerListDelegate(QStyledItemDelegate):
    """Custom delegate to paint item backgrounds"""
    
    def paint(self, painter, option, index):
        """Custom paint method to draw background colors"""
        # Get the item
        item = index.data(Qt.UserRole)
        
        if isinstance(item, PlayerListItem):
            # Fill background with custom color
            painter.fillRect(option.rect, QColor(item.current_background_color))
            
            # Draw border
            painter.setPen(QColor("#333333"))
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
            
            # Draw text
            painter.setPen(QColor("white"))
            painter.drawText(option.rect.adjusted(15, 0, -15, 0), 
                           Qt.AlignLeft | Qt.AlignVCenter, 
                           item.text())
        else:
            # Fall back to default painting
            super().paint(painter, option, index)


class GameData:
    """Represents game data for a specific gamemode"""
    def __init__(self, games_played: int = 0, victories: int = 0):
        self.games_played = games_played
        self.victories = victories
    
    def __eq__(self, other):
        if not isinstance(other, GameData):
            return False
        return self.games_played == other.games_played and self.victories == other.victories


class PlayerActivity:
    """Represents a player's latest activity"""
    def __init__(self, gamemode: str, result: str, timestamp: datetime):
        self.gamemode = gamemode
        self.result = result  # "Win" or "Loss"
        self.timestamp = timestamp


class TrackerSignals(QObject):
    """Signals for communicating between threads"""
    activity_detected = pyqtSignal(str, str, str, datetime)  # username, gamemode, result, timestamp
    error_occurred = pyqtSignal(str, str)  # username, error_message


class HiveAPI:
    """Handles Hive API interactions"""
    
    BASE_URL = "https://api.playhive.com/v0/game/all/all/{}"
    
    GAMEMODE_MAPPING = {
        'sky': 'SkyWars',
        'murder': 'Murder Mystery',
        'dr': 'DeathRun',
        'hide': 'Hide and Seek',
        'party': 'Block Party',
        'sg': 'Survival Games',
        'ctf': 'Capture the Flag',
        'ground': 'Ground Wars',
        'grav': 'Gravity',
        'bridge': 'The Bridge',
        'drop': 'Block Drop',
        'build': 'Just Build',
        'bed': 'Bedwars'
    }
    
    @classmethod
    def fetch_player_data(cls, username: str) -> Optional[Dict]:
        """Fetch player data from Hive API"""
        try:
            url = cls.BASE_URL.format(username)
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return None
    
    @classmethod
    def parse_game_data(cls, api_data: Dict) -> Dict[str, GameData]:
        """Parse API response into gamemode data"""
        game_data = {}
        
        for gamemode_key, gamemode_name in cls.GAMEMODE_MAPPING.items():
            if gamemode_key in api_data:
                mode_data = api_data[gamemode_key]
                
                try:
                    # Handle different API response formats
                    if isinstance(mode_data, list):
                        if mode_data:
                            best_stats = None
                            for item in mode_data:
                                if isinstance(item, dict):
                                    possible_played = item.get('played', item.get('games_played', item.get('games', 0)))
                                    possible_victories = item.get('victories', item.get('wins', item.get('victories_count', 0)))
                                    
                                    if possible_played > 0:
                                        best_stats = {'played': possible_played, 'victories': possible_victories}
                                        break
                            
                            mode_stats = best_stats if best_stats else {'played': 0, 'victories': 0}
                        else:
                            mode_stats = {'played': 0, 'victories': 0}
                            
                    elif isinstance(mode_data, dict):
                        mode_stats = mode_data
                    
                    elif isinstance(mode_data, (int, float)):
                        mode_stats = {'played': int(mode_data), 'victories': 0}
                    
                    else:
                        continue
                    
                    # Extract stats with multiple fallback field names
                    games_played = 0
                    victories = 0
                    
                    for field in ['played', 'games_played', 'games', 'total_games', 'matches']:
                        if field in mode_stats:
                            games_played = int(mode_stats[field] or 0)
                            break
                    
                    for field in ['victories', 'wins', 'victories_count', 'win_count', 'total_wins']:
                        if field in mode_stats:
                            victories = int(mode_stats[field] or 0)
                            break
                    
                    game_data[gamemode_key] = GameData(games_played, victories)
                    
                except Exception as e:
                    game_data[gamemode_key] = GameData(0, 0)
        
        return game_data


class PlayerTracker:
    """Tracks a single player's game activity"""
    
    def __init__(self, username: str, signals: TrackerSignals):
        self.username = username
        self.signals = signals
        self.previous_data: Dict[str, GameData] = {}
        self.last_activity: Optional[PlayerActivity] = None
        self.error_message: str = ""
        
    def update(self):
        """Update player data and detect new activity"""
        api_data = HiveAPI.fetch_player_data(self.username)
        
        if api_data is None:
            self.error_message = "API Error"
            self.signals.error_occurred.emit(self.username, self.error_message)
            return
            
        self.error_message = ""
        current_data = HiveAPI.parse_game_data(api_data)
        
        # Check for new activity
        for gamemode_key, current_game_data in current_data.items():
            if gamemode_key in self.previous_data:
                previous_game_data = self.previous_data[gamemode_key]
                
                # Check if games_played increased
                if current_game_data.games_played > previous_game_data.games_played:
                    victories_diff = current_game_data.victories - previous_game_data.victories
                    
                    if victories_diff > 0:
                        result = "Win"
                    else:
                        result = "Loss"
                    
                    gamemode_name = HiveAPI.GAMEMODE_MAPPING[gamemode_key]
                    timestamp = datetime.now()
                    
                    self.last_activity = PlayerActivity(gamemode_name, result, timestamp)
                    self.signals.activity_detected.emit(self.username, gamemode_name, result, timestamp)
        
        self.previous_data = current_data


class AddUserDialog(QDialog):
    """Dialog for adding new users"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Username")
        self.setModal(True)
        self.resize(400, 150)
        
        layout = QVBoxLayout()
        
        label = QLabel("Username:")
        label.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username...")
        self.username_input.setStyleSheet("""
            QLineEdit {
                background-color: #404040;
                color: white;
                border: 1px solid #606060;
                padding: 8px;
                font-size: 14px;
                border-radius: 4px;
            }
        """)
        
        layout.addWidget(label)
        layout.addWidget(self.username_input)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setStyleSheet("""
            QDialogButtonBox {
                font-size: 12px;
            }
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        self.setStyleSheet("QDialog { background-color: #2a2a2a; }")
        
        self.username_input.setFocus()
    
    def get_username(self) -> str:
        return self.username_input.text().strip()


class BlacklistDialog(QDialog):
    """Dialog for managing blacklist"""
    
    def __init__(self, blacklist: List[str], protected_blacklist: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Blacklist")
        self.setModal(True)
        self.resize(500, 500)
        self.protected_blacklist = protected_blacklist
        
        layout = QVBoxLayout()
        
        # Protected blacklist section
        if protected_blacklist:
            protected_label = QLabel("Protected Blacklist (Cannot be removed):")
            protected_label.setStyleSheet("color: #ff6b6b; font-size: 14px; font-weight: bold;")
            
            protected_text = QTextEdit()
            protected_text.setPlainText("\n".join(protected_blacklist))
            protected_text.setReadOnly(True)
            protected_text.setMaximumHeight(100)
            protected_text.setStyleSheet("""
                QTextEdit {
                    background-color: #3a3a3a;
                    color: #ff6b6b;
                    border: 1px solid #606060;
                    padding: 8px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            
            layout.addWidget(protected_label)
            layout.addWidget(protected_text)
        
        # User editable blacklist section
        label = QLabel("Your Blacklist (one per line):")
        label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-top: 10px;")
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter usernames to blacklist, one per line...")
        self.text_edit.setPlainText("\n".join(blacklist))
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #404040;
                color: white;
                border: 1px solid #606060;
                padding: 8px;
                font-size: 14px;
                border-radius: 4px;
            }
        """)
        
        layout.addWidget(label)
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.setStyleSheet("""
            QDialogButtonBox {
                font-size: 12px;
            }
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
        self.setStyleSheet("QDialog { background-color: #2a2a2a; }")
    
    def get_blacklist(self) -> List[str]:
        text = self.text_edit.toPlainText()
        return [line.strip() for line in text.split('\n') if line.strip()]


class PlayerListItem(QListWidgetItem):
    """Custom list item for players with color-changing background"""
    
    def __init__(self, username: str, parent_widget):
        super().__init__()
        self.username = username
        self.parent_widget = parent_widget
        self.error_message = ""
        self.last_activity_time: Optional[datetime] = None
        self.last_gamemode: str = ""
        self.last_result: str = ""
        self.current_background_color = "#2a2a2a"  # Default grey
        self.color_change_time: Optional[datetime] = None
        
        # Store reference to self in item data for delegate
        self.setData(Qt.UserRole, self)
        
        # Set initial background color
        self.setBackground(QColor(self.current_background_color))
        self.setForeground(QColor("white"))
        
        self.update_display()
    
    def update_activity(self, gamemode: str, result: str, timestamp: datetime):
        """Update activity information and set background color"""
        self.last_activity_time = timestamp
        self.last_gamemode = gamemode
        self.last_result = result
        self.error_message = ""
        
        # Set background color based on result
        if result == "Win":
            self.current_background_color = "#00ff00"  # Bright green
        else:  # Loss
            self.current_background_color = "#ff0000"  # Bright red
        
        self.color_change_time = timestamp
        
        # Update display and colors
        self.update_display()
        
        # Debug print
        print(f"Updated {self.username}: {gamemode} {result} - Color: {self.current_background_color}")
    
    def set_error(self, error_msg: str):
        """Set error message"""
        self.error_message = error_msg
        self.current_background_color = "#2a2a2a"
        self.update_display()
    
    def check_color_timeout(self):
        """Check if should show no activity after 1000 seconds"""
        if self.last_activity_time:
            time_elapsed = (datetime.now() - self.last_activity_time).total_seconds()
            if time_elapsed >= 1000:
                # Reset to no activity
                self.last_activity_time = None
                self.last_gamemode = ""
                self.last_result = ""
                self.current_background_color = "#2a2a2a"
                return True
        
        # Check if color should revert to grey after 30 seconds
        if self.color_change_time and self.current_background_color not in ["#2a2a2a"]:
            time_elapsed = (datetime.now() - self.color_change_time).total_seconds()
            if time_elapsed >= 30:
                self.current_background_color = "#2a2a2a"
                print(f"Color timeout for {self.username} - reverting to grey")
                return True
        return False
    
    def update_display(self):
        """Update the display text with improved layout"""
        if self.error_message:
            activity_text = f"{self.username:<20} {self.error_message}"
        elif self.last_activity_time:
            time_ago = self.format_time_ago(self.last_activity_time)
            # Format: Username (left) | Gamemode (center) | Time (right)
            activity_text = f"{self.username:<20} │ {self.last_gamemode:^30} │ {time_ago:>10}"
        else:
            activity_text = f"{self.username:<20} │ {'No activity':^30} │ {'-':>10}"
        
        self.setText(activity_text)
        
        # Set background color
        self.setBackground(QColor(self.current_background_color))
        self.setForeground(QColor("white"))
    
    def format_time_ago(self, timestamp: datetime) -> str:
        """Format time difference - always in seconds"""
        now = datetime.now()
        diff = now - timestamp
        seconds = int(diff.total_seconds())
        return f"{seconds}s ago"
    
    def get_sort_key(self) -> Tuple[int, datetime]:
        """Get sort key for ordering items (most recent activity first)"""
        if self.last_activity_time:
            # Has activity - sort by timestamp (most recent first = larger timestamp)
            return (0, self.last_activity_time)
        else:
            # No activity - sort to bottom
            return (1, datetime.min)


class HiveTrackerApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hive MCPE Player Tracker")
        self.setGeometry(100, 100, 900, 600)
        
        # Protected blacklist - users that cannot be removed or tracked
        self.protected_blacklist = ["zah German", "Zayypoo", "TopazAnt6349", "NurRamon", "sxdaq", "dqrk 1ce", "H0nri", "Rcvcx", "GG Kronix", "xqleqn" , "zRqbia", "Isixtra", "cb6h"]  # Add your usernames here
        
        # User-editable blacklist
        self.blacklist = []
        
        # Data structures
        self.trackers: Dict[str, PlayerTracker] = {}
        self.signals = TrackerSignals()
        self.is_running = False
        self.polling_thread: Optional[threading.Thread] = None
        
        # Setup UI
        self.setup_ui()
        self.apply_theme()
        
        # Connect signals
        self.signals.activity_detected.connect(self.on_activity_detected)
        self.signals.error_occurred.connect(self.on_error_occurred)
        
        # Setup timers
        self.display_timer = QTimer()
        self.display_timer.timeout.connect(self.update_display)
        self.display_timer.start(1000)  # Update every second
        
        self.color_timer = QTimer()
        self.color_timer.timeout.connect(self.check_color_timeouts)
        self.color_timer.start(1000)  # Check color timeouts every second
        
        # Start polling
        self.start_polling()
    
    def setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with API rate info
        header = QLabel("API-Rate: 30.0 Requests/User/Min (Intervall: 2.00s)")
        header.setStyleSheet("""
            QLabel {
                background-color: #404040;
                color: white;
                padding: 10px;
                font-size: 12px;
                border-bottom: 1px solid #606060;
                text-align: center;
            }
        """)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Main player list
        self.player_list = QListWidget()
        self.player_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.player_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Set custom delegate for painting backgrounds
        self.player_list.setItemDelegate(PlayerListDelegate())
        
        # Style the list to match the design
        self.player_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                color: white;
                border: none;
                outline: none;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 14px;
                font-weight: bold;
            }
            QListWidget::item {
                border-bottom: 1px solid #333333;
                padding: 15px;
                min-height: 20px;
            }
            QListWidget::item:selected {
                border: 2px solid #0078D4;
            }
            QListWidget::item:hover {
                border: 1px solid #606060;
            }
        """)
        
        layout.addWidget(self.player_list)
        
        # Bottom controls
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet("""
            QFrame {
                background-color: #404040;
                border-top: 1px solid #606060;
                padding: 10px;
            }
        """)
        bottom_layout = QHBoxLayout(bottom_frame)
        
        # Manual update button
        manual_button = QPushButton("manual update")
        manual_button.clicked.connect(self.manual_update)
        manual_button.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        
        # Blacklist button
        blacklist_button = QPushButton("Blacklist")
        blacklist_button.clicked.connect(self.open_blacklist_dialog)
        blacklist_button.setStyleSheet("""
            QPushButton {
                background-color: #D43900;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b83000;
            }
        """)
        
        # RPM control
        rpm_label = QLabel("Requests/Min:")
        rpm_label.setStyleSheet("color: white; font-size: 12px;")
        
        self.rpm_spinbox = QSpinBox()
        self.rpm_spinbox.setMinimum(1)
        self.rpm_spinbox.setMaximum(300)
        self.rpm_spinbox.setValue(120)
        self.rpm_spinbox.valueChanged.connect(self.update_header)
        self.rpm_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #606060;
                color: white;
                border: 1px solid #808080;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 60px;
            }
        """)
        
        # Add button
        add_button = QPushButton("Add User")
        add_button.clicked.connect(self.add_user)
        add_button.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        
        bottom_layout.addWidget(manual_button)
        bottom_layout.addWidget(blacklist_button)
        bottom_layout.addStretch()
        bottom_layout.addWidget(rpm_label)
        bottom_layout.addWidget(self.rpm_spinbox)
        bottom_layout.addWidget(add_button)
        
        layout.addWidget(bottom_frame)
        
        # Store header reference for updates
        self.header_label = header
        self.update_header()
    
    def apply_theme(self):
        """Apply the dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2a2a2a;
            }
        """)
    
    def update_header(self):
        """Update the header with current API rate info"""
        rpm = self.rpm_spinbox.value()
        interval = 60.0 / rpm
        self.header_label.setText(f"API-Rate: {rpm/2:.1f} Requests/User/Min (Intervall: {interval:.2f}s)")
    
    def check_color_timeouts(self):
        """Check all items for color timeout and update display"""
        needs_update = False
        for i in range(self.player_list.count()):
            item = self.player_list.item(i)
            if isinstance(item, PlayerListItem):
                if item.check_color_timeout():
                    item.update_display()
                    needs_update = True
        
        # Force visual refresh if needed
        if needs_update:
            self.player_list.viewport().update()
    
    def show_context_menu(self, position):
        """Show context menu for player list"""
        item = self.player_list.itemAt(position)
        if item and isinstance(item, PlayerListItem):
            menu = QMenu()
            menu.setStyleSheet("""
                QMenu {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #606060;
                }
                QMenu::item:selected {
                    background-color: #0078D4;
                }
            """)
            remove_action = menu.addAction("Remove")
            
            action = menu.exec_(self.player_list.mapToGlobal(position))
            if action == remove_action:
                self.remove_user(item.username)
    
    def open_blacklist_dialog(self):
        """Open blacklist management dialog"""
        dialog = BlacklistDialog(self.blacklist, self.protected_blacklist, self)
        if dialog.exec_() == QDialog.Accepted:
            self.blacklist = dialog.get_blacklist()
    
    def is_blacklisted(self, username: str) -> bool:
        """Check if username is in either blacklist (case insensitive)"""
        username_lower = username.lower().strip()
        
        # Check protected blacklist
        for protected in self.protected_blacklist:
            if protected.lower().strip() == username_lower:
                return True
        
        # Check user blacklist
        for blocked in self.blacklist:
            if blocked.lower().strip() == username_lower:
                return True
        
        return False
    
    def add_user(self):
        """Add a new user to track"""
        dialog = AddUserDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            username = dialog.get_username()
            
            if not username:
                return
            
            # Check if username is blacklisted (case insensitive)
            if self.is_blacklisted(username):
                QMessageBox.warning(self, "Blacklisted", 
                                  f"User '{username}' is blacklisted and cannot be added.")
                return
            
            # Check if already tracking
            if username in self.trackers:
                QMessageBox.information(self, "Already Tracking", 
                                      f"User '{username}' is already being tracked.")
                return
            
            if username and username not in self.trackers:
                # Create tracker
                tracker = PlayerTracker(username, self.signals)
                self.trackers[username] = tracker
                
                # Create list item
                item = PlayerListItem(username, self.player_list)
                item.tracker = tracker
                self.player_list.addItem(item)
                
                # Initial update
                threading.Thread(target=tracker.update, daemon=True).start()
    
    def remove_user(self, username: str):
        """Remove a user from tracking"""
        if username in self.trackers:
            del self.trackers[username]
            
            # Remove from list
            for i in range(self.player_list.count()):
                item = self.player_list.item(i)
                if isinstance(item, PlayerListItem) and item.username == username:
                    self.player_list.takeItem(i)
                    break
    
    def manual_update(self):
        """Manually trigger update for all users"""
        for tracker in self.trackers.values():
            threading.Thread(target=tracker.update, daemon=True).start()
    
    def play_notification_sound(self):
        """Play notification sound using Windows system beep in a separate thread"""
        def beep():
            try:
                winsound.Beep(800, 200)
            except:
                pass
        threading.Thread(target=beep, daemon=True).start()
    
    def sort_player_list(self):
        """Sort player list - most recent activity at top"""
        print("\n=== Sorting Player List ===")
        
        # Collect all items with their data
        items_data = []
        for i in range(self.player_list.count()):
            item = self.player_list.item(i)
            if isinstance(item, PlayerListItem):
                sort_key = item.get_sort_key()
                print(f"Item {i}: {item.username} - Sort key: {sort_key}")
                # Store the data we need
                items_data.append({
                    'username': item.username,
                    'tracker': item.tracker,
                    'last_activity_time': item.last_activity_time,
                    'last_gamemode': item.last_gamemode,
                    'last_result': item.last_result,
                    'error_message': item.error_message,
                    'current_background_color': item.current_background_color,
                    'color_change_time': item.color_change_time,
                    'sort_key': sort_key
                })
        
        # Sort by activity (most recent first)
        # Lower priority number = higher in list, so we DON'T reverse
        # For same priority, sort by timestamp descending (most recent first)
        items_data.sort(key=lambda x: (x['sort_key'][0], -x['sort_key'][1].timestamp() if x['sort_key'][1] != datetime.min else 0))
        
        print("After sorting:")
        for idx, data in enumerate(items_data):
            print(f"  {idx}: {data['username']} - {data['sort_key']}")
        
        # Clear list
        self.player_list.clear()
        
        # Recreate items in sorted order
        for data in items_data:
            new_item = PlayerListItem(data['username'], self.player_list)
            new_item.tracker = data['tracker']
            new_item.last_activity_time = data['last_activity_time']
            new_item.last_gamemode = data['last_gamemode']
            new_item.last_result = data['last_result']
            new_item.error_message = data['error_message']
            new_item.current_background_color = data['current_background_color']
            new_item.color_change_time = data['color_change_time']
            new_item.setData(Qt.UserRole, new_item)  # Store reference for delegate
            self.player_list.addItem(new_item)
            new_item.update_display()
            print(f"  Added {new_item.username} with color {new_item.current_background_color}, text: {new_item.text()}")
        
        # Force repaint
        self.player_list.viewport().repaint()
        print("=== Sort Complete ===\n")
    
    def on_activity_detected(self, username: str, gamemode: str, result: str, timestamp: datetime):
        """Handle detected activity"""
        print(f"\n=== Activity Detected ===")
        print(f"Username: {username}")
        print(f"Gamemode: {gamemode}")
        print(f"Result: {result}")
        print(f"Timestamp: {timestamp}")
        
        # Update item first
        found = False
        for i in range(self.player_list.count()):
            item = self.player_list.item(i)
            if isinstance(item, PlayerListItem) and item.username == username:
                print(f"Found item at index {i}")
                item.update_activity(gamemode, result, timestamp)
                found = True
                break
        
        if found:
            # Play notification sound
            self.play_notification_sound()
            
            # Sort list to move this user to top (use QTimer to avoid threading issues)
            print("Scheduling sort...")
            QTimer.singleShot(100, self.sort_player_list)
        else:
            print(f"WARNING: Item not found for {username}")
    
    def on_error_occurred(self, username: str, error_message: str):
        """Handle API errors"""
        for i in range(self.player_list.count()):
            item = self.player_list.item(i)
            if isinstance(item, PlayerListItem) and item.username == username:
                item.set_error(error_message)
                break
    
    def update_display(self):
        """Update display text for all items"""
        for i in range(self.player_list.count()):
            item = self.player_list.item(i)
            if isinstance(item, PlayerListItem):
                item.update_display()
        
        # Force visual refresh
        self.player_list.viewport().update()
    
    def start_polling(self):
        """Start the polling thread"""
        self.is_running = True
        self.polling_thread = threading.Thread(target=self.polling_loop, daemon=True)
        self.polling_thread.start()
    
    def stop_polling(self):
        """Stop the polling thread"""
        self.is_running = False
        if self.polling_thread:
            self.polling_thread.join(timeout=1.0)
    
    def polling_loop(self):
        """Main polling loop"""
        while self.is_running:
            if not self.trackers:
                time.sleep(1)
                continue
            
            rpm = self.rpm_spinbox.value()
            interval = 60.0 / rpm
            
            for tracker in list(self.trackers.values()):
                if not self.is_running:
                    break
                
                try:
                    tracker.update()
                except Exception as e:
                    print(f"Error updating {tracker.username}: {e}")
                
                if self.is_running and interval > 0:
                    time.sleep(interval)
    
    def closeEvent(self, event):
        """Handle application close"""
        self.stop_polling()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = HiveTrackerApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
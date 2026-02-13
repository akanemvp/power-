"""
Power+ Calculator - Backend API Server
Automatically fetches and updates Baseball Savant data
Deploy to free hosting services like Render, Railway, or Fly.io
"""

from flask import Flask, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import os

app = Flask(__name__, static_folder='static')
CORS(app)

# Cache configuration
CACHE_FILE = 'data_cache.json'
CACHE_DURATION = timedelta(hours=6)  # Refresh every 6 hours

# Constants
LEAGUE_AVG_BAT_SPEED = 72.0
LEAGUE_AVG_SWING_LENGTH = 7.3
LEAGUE_AVG_EFFICIENCY = LEAGUE_AVG_BAT_SPEED / LEAGUE_AVG_SWING_LENGTH


def calculate_power_plus(bat_speed, swing_length):
    """Calculate Power+ metric"""
    if swing_length == 0 or pd.isna(swing_length) or pd.isna(bat_speed):
        return None
    player_efficiency = bat_speed / swing_length
    power_plus = (player_efficiency / LEAGUE_AVG_EFFICIENCY) * 100
    return round(power_plus, 1)


def get_grade(power_plus):
    """Get descriptive grade"""
    if pd.isna(power_plus):
        return "N/A"
    if power_plus >= 110:
        return "Elite"
    elif power_plus >= 105:
        return "Above Average"
    elif power_plus >= 95:
        return "Average"
    elif power_plus >= 90:
        return "Below Average"
    else:
        return "Poor"


def fetch_baseball_savant_data(year=2025):
    """
    Fetch data from Baseball Savant
    Note: This is a template - actual implementation may need adjustment
    based on Baseball Savant's current structure
    """
    url = f"https://baseballsavant.mlb.com/leaderboard/bat-tracking"
    params = {
        'year': year,
        'type': 'batter',
        'minSwings': 1,
        'csv': 'true'
    }
    
    try:
        # Attempt to get CSV directly
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            # Try to parse as CSV
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            return df
        else:
            print(f"Failed to fetch data: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None


def process_data(df):
    """Process and enrich data with Power+ (Smarter Column Finding)"""
    df = df.copy()
    
    # 1. Find the Bat Speed column
    # It looks for anything containing 'bat_speed' and takes the first one found
    speed_cols = [c for c in df.columns if 'bat_speed' in c.lower()]
    speed_col = speed_cols[0] if speed_cols else None

    # 2. Find the Swing Length column
    length_cols = [c for c in df.columns if 'swing_length' in c.lower()]
    length_col = length_cols[0] if length_cols else None

    # 3. Handle missing columns gracefully instead of crashing
    if not speed_col or not length_col:
        print(f"ERROR: Could not find columns. Available: {df.columns.tolist()}")
        return pd.DataFrame() # Return empty if data is broken

    # 4. Clean and Calculate
    df = df.dropna(subset=[speed_col, length_col])
    df['bat_speed'] = pd.to_numeric(df[speed_col], errors='coerce')
    df['swing_length'] = pd.to_numeric(df[length_col], errors='coerce')
    
    df['power_plus'] = df.apply(
        lambda row: calculate_power_plus(row['bat_speed'], row['swing_length']),
        axis=1
    )
    return df


def load_cached_data():
    """Load data from cache if fresh enough"""
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
        
        cache_time = datetime.fromisoformat(cache['timestamp'])
        if datetime.now() - cache_time < CACHE_DURATION:
            print("Using cached data")
            return cache['data']
        else:
            print("Cache expired")
            return None
    except Exception as e:
        print(f"Error loading cache: {e}")
        return None


def save_to_cache(data):
    """Save data to cache"""
    try:
        cache = {
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
        print("Data cached successfully")
    except Exception as e:
        print(f"Error saving cache: {e}")


def get_data(force_refresh=False):
    """Get data from cache or fetch fresh"""
    if not force_refresh:
        cached = load_cached_data()
        if cached:
            return cached
    
    print("Fetching fresh data from Baseball Savant...")
    df = fetch_baseball_savant_data()
    
    if df is None or df.empty:
        print("Failed to fetch data, using cached data if available")
        cached = load_cached_data()
        return cached if cached else {"error": "No data available"}
    
    df = process_data(df)
    df = df.replace({pd.NA: None, float('nan'): None})
    data = df.to_dict('records')
    
    save_to_cache(data)
    return data


# API Routes

@app.route('/')
def index():
    """Serve the main web app from the root folder"""
    return send_file('index.html')
    
@app.route('/api/players')
def get_all_players():
    """Get all players with Power+ data"""
    data = get_data()
    return jsonify(data)


@app.route('/api/players/qualified')
def get_qualified_players():
    """Get players with 300+ swings"""
    data = get_data()
    qualified = [p for p in data if p.get('swings', 0) >= 300]
    return jsonify(qualified)


@app.route('/api/players/elite')
def get_elite_players():
    """Get players with elite Power+ (110+)"""
    data = get_data()
    elite = [p for p in data if p.get('power_plus', 0) >= 110]
    return jsonify(elite)


@app.route('/api/player/<player_name>')
def get_player(player_name):
    """Get specific player data"""
    data = get_data()
    player = next((p for p in data if player_name.lower() in p.get('player_name', '').lower()), None)
    
    if player:
        return jsonify(player)
    else:
        return jsonify({"error": "Player not found"}), 404


@app.route('/api/stats/summary')
def get_summary():
    """Get summary statistics"""
    data = get_data()
    
    if not data or isinstance(data, dict) and 'error' in data:
        return jsonify({"error": "No data available"}), 500
    
    df = pd.DataFrame(data)
    
    summary = {
        'total_players': len(df),
        'avg_bat_speed': round(df['bat_speed'].mean(), 2),
        'avg_swing_length': round(df['swing_length'].mean(), 2),
        'avg_power_plus': round(df['power_plus'].mean(), 1),
        'elite_count': len(df[df['power_plus'] >= 110]),
        'above_avg_count': len(df[(df['power_plus'] >= 105) & (df['power_plus'] < 110)]),
        'qualified_count': len(df[df['swings'] >= 300]),
        'last_updated': datetime.now().isoformat()
    }
    
    return jsonify(summary)


@app.route('/api/refresh')
def refresh_data():
    """Force refresh data from Baseball Savant"""
    data = get_data(force_refresh=True)
    return jsonify({
        "status": "success",
        "players_count": len(data),
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/teams/<team_abbrev>')
def get_team_players(team_abbrev):
    """Get all players from a specific team"""
    data = get_data()
    team_players = [p for p in data if p.get('team', '').upper() == team_abbrev.upper()]
    return jsonify(team_players)


# Health check for deployment platforms
@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    # Use the port assigned by Render, or default to 5000 for local testing
    port = int(os.environ.get("PORT", 5000))
    # host='0.0.0.0' makes the server accessible to the internet
    app.run(host='0.0.0.0', port=port)

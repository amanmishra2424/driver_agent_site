from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime, timedelta
import json
import random
import string
import requests
from urllib.parse import quote
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import os
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
import secrets
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # More secure secret key

# MongoDB configuration
app.config['MONGO_URI'] = 'mongodb+srv://print_queue_db:jai_ho@aman.dlsk6.mongodb.net/driver_db?retryWrites=true&w=majority'

try:
    mongo = PyMongo(app)
    print("MongoDB connected successfully!")
except Exception as e:
    print(f"MongoDB connection error: {e}")
    mongo = None

# Mail configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False     # Must be False when USE_TLS=True
app.config['MAIL_USERNAME'] = 'printech030225@gmail.com'
app.config['MAIL_PASSWORD'] = 'sbxvawkjjwlaoryi'  # ← Your 16-char App Password
app.config['MAIL_DEFAULT_SENDER'] = 'printech030225@gmail.com'

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

# Telegram Bot configuration
TELEGRAM_BOT_TOKEN = "8124516129:AAH7xG560dYJOxT5WKLRryFfH6PIAiFysVo"  # Replace with your actual bot token
TELEGRAM_ADMIN_CHAT_ID = "1372796454cc"  # Replace with your admin chat ID

# New pricing structure
PRICING = {
    "hourly": {
        "base_rate_short": 600,  # 600₹ for less than 5 hours
        "base_rate": 800,  # 800₹ for 8 hours
        "overtime_rate": 100,  # 100₹ per hour (7am-10pm)
        "night_food_charge": 200,  # Additional 200₹ after 10pm for food
        "night_travel_charge": 100  # Additional 100₹ after 12am for travel
    },
    "outstation": {
        "overnight": 1500,  # 1200₹ + 300₹ food expense per day
        "same_day": 1800  # Fixed rate for same-day return
    },
    "pickup_drop": {
        "above_100km": 1300,  # Base rate for >100km + travel charges
        "60_to_100km": 1000,  # Fixed rate for 60-100km
        "below_60km": 800  # Fixed rate for <60km
    }
}

# Initialize database with sample data if empty
def init_db():
    try:
        if not mongo or not mongo.db:
            print("MongoDB connection not available")
            return
            
        if mongo.db.drivers.count_documents({}) == 0:
            sample_drivers = [
                {"name": "John Smith", "rating": 4.8, "car_types": ["Manual", "Automatic"]},
                {"name": "Sarah Johnson", "rating": 4.9, "car_types": ["Automatic", "Semi-Automatic"]},
                {"name": "Mike Wilson", "rating": 4.7, "car_types": ["Electric"]},
                {"name": "Emily Davis", "rating": 4.6, "car_types": ["Automatic", "Semi-Automatic"]},
                {"name": "David Brown", "rating": 4.8, "car_types": ["Electric", "Automatic"]}
            ]
            
            mongo.db.drivers.insert_many(sample_drivers)
            print("Sample drivers added to database")
    except Exception as e:
        print(f"Error initializing database: {e}")

# Call init_db function
init_db()

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_telegram_message(chat_id, message):
    """Send message using Telegram Bot API"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data)
        return response.json()
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return None

def get_user_by_id(user_id):
    """Get user by ID"""
    return mongo.db.users.find_one({"_id": ObjectId(user_id)})

def is_authenticated():
    """Check if user is authenticated"""
    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        return user is not None
    return False

def get_current_user():
    """Get current user"""
    if 'user_id' in session:
        return get_user_by_id(session['user_id'])
    return None

# Function to get route information from OpenStreetMap (via OSRM)
def get_route_info(start_lat, start_lon, end_lat, end_lon):
    """Get route information using OSRM (OpenStreetMap Routing Machine)"""
    try:
        # Using the OSRM demo server - for production use your own OSRM instance
        url = f"https://router.project-osrm.org/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=false"
        response = requests.get(url)
        data = response.json()
        
        if data["code"] == "Ok" and len(data["routes"]) > 0:
            route = data["routes"][0]
            # Distance in meters, convert to kilometers
            distance_km = route["distance"] / 1000
            # Duration in seconds, convert to minutes
            duration_min = route["duration"] / 60
            
            return {
                "distance": distance_km,
                "duration": duration_min,
                "distance_text": f"{distance_km:.1f} km",
                "duration_text": f"{duration_min:.0f} min"
            }
    except Exception as e:
        print(f"Error getting route: {e}")
    
    # Default values if route calculation fails
    return {
        "distance": 10,  # Default 10 km
        "duration": 30,  # Default 30 minutes
        "distance_text": "10.0 km",
        "duration_text": "30 min"
    }

# Function to geocode an address using Nominatim (OpenStreetMap)
def geocode_address(address):
    """Convert address to coordinates using Nominatim"""
    try:
        # Add a custom user agent as required by Nominatim usage policy
        headers = {
            'User-Agent': 'RideBookerApp/1.0'
        }
        
        params = {
            'q': address,
            'format': 'json',
            'limit': 1
        }
        
        response = requests.get('https://nominatim.openstreetmap.org/search', params=params, headers=headers)
        data = response.json()
        
        if data and len(data) > 0:
            return {
                'lat': float(data[0]['lat']),
                'lon': float(data[0]['lon']),
                'display_name': data[0]['display_name']
            }
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    # Default to Mumbai coordinates if geocoding fails
    return {
        'lat': 19.0760,
        'lon': 72.8777,
        'display_name': 'Mumbai, Maharashtra, India'
    }

# Calculate fare based on booking type and parameters
def calculate_fare(booking_type, distance, duration, start_time, end_time, num_days=1):
    """Calculate fare based on booking type and parameters"""
    try:
        if booking_type == "hourly":
            # Calculate total hours
            start_hour = int(start_time.split(":")[0])
            end_hour = int(end_time.split(":")[0])
            
            # Handle overnight bookings
            if end_hour < start_hour:
                end_hour += 24
                
            total_hours = end_hour - start_hour
            
            # Check if less than 5 hours (use fixed rate)
            if total_hours < 5:
                base_rate = PRICING["hourly"]["base_rate_short"]
                total_fare = base_rate
                
                return {
                    "base_fare": base_rate,
                    "overtime_charges": 0,
                    "total_fare": total_fare,
                    "breakdown": [
                        {"label": "Fixed rate (less than 5 hours)", "amount": base_rate}
                    ]
                }
            else:
                # Base rate for 8 hours
                base_rate = PRICING["hourly"]["base_rate"]
                
                # Calculate overtime charges
                overtime_charges = 0
                if total_hours > 8:
                    overtime_hours = total_hours - 8
                    
                    # Regular overtime (7am-10pm)
                    overtime_charges = overtime_hours * PRICING["hourly"]["overtime_rate"]
                    
                    # Check for night charges (after 10pm)
                    if end_hour >= 22:  # 10pm or later
                        # Add food charge
                        overtime_charges += PRICING["hourly"]["night_food_charge"]
                        
                        # Check for late night charges (after 12am)
                        if end_hour >= 24:  # 12am or later
                            overtime_charges += PRICING["hourly"]["night_travel_charge"]
                
                total_fare = base_rate + overtime_charges
                    
                return {
                    "base_fare": base_rate,
                    "overtime_charges": overtime_charges,
                    "total_fare": total_fare,
                    "breakdown": [
                        {"label": "Base rate (8 hours)", "amount": base_rate},
                        {"label": "Overtime charges", "amount": overtime_charges}
                    ]
                }
            
        elif booking_type == "outstation_overnight":
            # Daily rate for overnight stay
            daily_rate = PRICING["outstation"]["overnight"]
            total_fare = daily_rate * num_days
            
            return {
                "base_fare": daily_rate,
                "total_fare": total_fare,
                "num_days": num_days,
                "breakdown": [
                    {"label": f"Daily rate (₹1200 + ₹300 food) × {num_days} days", "amount": total_fare}
                ]
            }
            
        elif booking_type == "outstation_same_day":
            # Fixed rate for same-day return
            total_fare = PRICING["outstation"]["same_day"]
            
            return {
                "base_fare": total_fare,
                "total_fare": total_fare,
                "breakdown": [
                    {"label": "Same-day return rate", "amount": total_fare}
                ]
            }
                
        elif booking_type == "pickup_drop":
            travel_charges = 0
            base_fare = 0
            
            if distance > 100:
                base_fare = PRICING["pickup_drop"]["above_100km"]
                travel_charges = (distance - 100) * 10  # Assuming 10₹ per km for additional distance
                total_fare = base_fare + travel_charges
                
                return {
                    "base_fare": base_fare,
                    "travel_charges": travel_charges,
                    "total_fare": total_fare,
                    "breakdown": [
                        {"label": "Base rate (>100km)", "amount": base_fare},
                        {"label": f"Travel charges ({distance-100:.1f} km × ₹10)", "amount": travel_charges}
                    ]
                }
                
            elif distance > 60:
                base_fare = PRICING["pickup_drop"]["60_to_100km"]
                total_fare = base_fare
                
                return {
                    "base_fare": base_fare,
                    "total_fare": total_fare,
                    "breakdown": [
                        {"label": "Fixed rate (60-100km)", "amount": base_fare}
                    ]
                }
                
            else:
                base_fare = PRICING["pickup_drop"]["below_60km"]
                total_fare = base_fare
                
                return {
                    "base_fare": base_fare,
                    "total_fare": total_fare,
                    "breakdown": [
                        {"label": "Fixed rate (<60km)", "amount": base_fare}
                    ]
                }
    except Exception as e:
        print(f"Error calculating fare: {e}")
        return {"total_fare": 1000, "breakdown": [{"label": "Default rate", "amount": 1000}]}

# Generate PDF invoice
def generate_invoice_pdf(booking_data, fare_details):
    buffer = io.BytesIO()
    
    # Create the PDF object
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Add logo/header
    p.setFont("Helvetica-Bold", 24)
    p.drawString(50, height - 50, "RideBooker")
    
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 70, "Premium Driver Services")
    
    # Add a line
    p.line(50, height - 80, width - 50, height - 80)
    
    # Add invoice title
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 120, "BOOKING INVOICE")
    
    # Add booking details
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 150, "Booking Details:")
    
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 170, f"Booking ID: {booking_data.get('_id', 'N/A')}")
    p.drawString(50, height - 185, f"Date: {booking_data.get('date', 'N/A')}")
    p.drawString(50, height - 200, f"Time: {booking_data.get('time', 'N/A')}")
    p.drawString(50, height - 215, f"Car Type: {booking_data.get('carType', 'N/A')}")
    
    booking_type = booking_data.get('bookingType', 'N/A')
    if booking_type == 'hourly':
        booking_type_display = 'Hourly Basis'
    elif booking_type == 'outstation_overnight':
        booking_type_display = 'Outstation (Overnight)'
    elif booking_type == 'outstation_same_day':
        booking_type_display = 'Outstation (Same Day)'
    elif booking_type == 'pickup_drop':
        booking_type_display = 'Pickup & Drop'
    else:
        booking_type_display = booking_type
        
    p.drawString(50, height - 230, f"Booking Type: {booking_type_display}")
    
    if booking_type == 'outstation_overnight':
        p.drawString(50, height - 245, f"Number of Days: {booking_data.get('num_days', 1)}")
    
    # Add customer details
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 275, "Customer Details:")
    
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 295, f"Name: {booking_data.get('customerName', 'N/A')}")
    p.drawString(50, height - 310, f"Phone: {booking_data.get('customerPhone', 'N/A')}")
    
    # Add journey details
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 340, "Journey Details:")
    
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 360, f"From: {booking_data.get('pickup', 'N/A')}")
    p.drawString(50, height - 375, f"To: {booking_data.get('destination', 'N/A')}")
    p.drawString(50, height - 390, f"Distance: {booking_data.get('distance', 0):.1f} km")
    
    # Add fare breakdown
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 420, "Fare Breakdown:")
    
    # Create table data
    table_data = [["Description", "Amount (₹)"]]
    
    # Add breakdown items
    for item in fare_details.get('breakdown', []):
        table_data.append([item.get('label', 'Item'), f"₹{item.get('amount', 0):.2f}"])
    
    # Add total
    table_data.append(["Total", f"₹{fare_details.get('total_fare', 0):.2f}"])
    
    # Create the table
    table = Table(table_data, colWidths=[300, 100])
    
    # Add style to the table
    style = TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (1, 0), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (1, 0), 12),
        ('BACKGROUND', (0, -1), (1, -1), colors.lightgrey),
        ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])
    
    table.setStyle(style)
    
    # Draw the table
    table.wrapOn(p, width - 100, height)
    table.drawOn(p, 50, height - 420 - len(table_data) * 20)
    
    # Add footer
    p.setFont("Helvetica-Oblique", 8)
    p.drawString(50, 50, "This is a computer-generated invoice and does not require a signature.")
    p.drawString(50, 35, "For any queries, please contact us at support@ridebooker.com")
    
    # Save the PDF
    p.showPage()
    p.save()
    
    # Move to the beginning of the buffer
    buffer.seek(0)
    return buffer

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RideBooker - Premium Driver Services</title>
    <!-- Leaflet CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" 
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" 
          crossorigin=""/>
    <!-- Leaflet Routing Machine CSS -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css" />
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
            color: white;
        }

        .header h1 {
            font-size: 3em;
            font-weight: 700;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            margin-bottom: 10px;
        }

        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }

        .auth-section, .booking-section, .bookings-section, .invoice-section {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
        }

        .form-group label {
            margin-bottom: 8px;
            font-weight: 600;
            color: #555;
        }

        .form-group input, .form-group select {
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: white;
        }

        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 40px;
            border-radius: 50px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 30px rgba(102, 126, 234, 0.4);
        }

        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .btn-secondary {
            background: #6c757d;
            box-shadow: 0 10px 20px rgba(108, 117, 125, 0.3);
        }

        .btn-secondary:hover {
            box-shadow: 0 15px 30px rgba(108, 117, 125, 0.4);
        }

        .btn-success {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            box-shadow: 0 10px 20px rgba(40, 167, 69, 0.3);
        }

        .btn-success:hover {
            box-shadow: 0 15px 30px rgba(40, 167, 69, 0.4);
        }

        .booking-item {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            border-left: 4px solid #667eea;
        }

        .rate-chart {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }

        .rate-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #dee2e6;
        }

        .total-fare {
            font-size: 1.2em;
            font-weight: bold;
            color: #667eea;
            padding-top: 10px;
            border-top: 2px solid #667eea;
        }

        #map {
            height: 300px;
            border-radius: 10px;
            margin: 20px 0;
        }

        .hidden {
            display: none !important;
        }

        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .otp-input {
            text-align: center;
            font-size: 24px;
            letter-spacing: 10px;
            font-weight: bold;
        }

        .logout-btn {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255,255,255,0.2);
            color: white;
            border: 1px solid rgba(255,255,255,0.3);
            padding: 10px 20px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 14px;
        }

        .auth-options {
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-top: 20px;
        }

        .auth-option {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #ddd;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .auth-option:hover {
            background: #f5f5f5;
        }

        .auth-tabs {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 1px solid #ddd;
        }

        .auth-tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.3s ease;
        }

        .auth-tab.active {
            border-bottom: 2px solid #667eea;
            color: #667eea;
            font-weight: 600;
        }

        .user-profile {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
        }

        .user-info {
            display: flex;
            flex-direction: column;
        }

        .user-name {
            font-weight: 600;
            color: #333;
        }

        .user-email {
            font-size: 14px;
            color: #666;
        }

        .time-picker {
            display: flex;
            gap: 10px;
            align-items: center;
        }

        .time-picker select {
            flex: 1;
        }

        .time-label {
            font-weight: normal;
            color: #666;
            font-size: 14px;
        }

        .address-suggestions {
            position: absolute;
            background: white;
            border: 1px solid #ddd;
            border-radius: 8px;
            max-height: 200px;
            overflow-y: auto;
            width: 100%;
            z-index: 1000;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }

        .address-suggestion {
            padding: 10px 15px;
            cursor: pointer;
            border-bottom: 1px solid #eee;
        }

        .address-suggestion:hover {
            background: #f5f5f5;
        }

        .address-input-container {
            position: relative;
        }

        .booking-type-tabs {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 1px solid #ddd;
            overflow-x: auto;
            padding-bottom: 5px;
        }

        .booking-type-tab {
            padding: 10px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.3s ease;
            white-space: nowrap;
        }

        .booking-type-tab.active {
            border-bottom: 2px solid #667eea;
            color: #667eea;
            font-weight: 600;
        }

        .pricing-info {
            background: #f0f4ff;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            border-left: 4px solid #667eea;
        }

        .pricing-info h3 {
            margin-bottom: 10px;
            color: #333;
        }

        .pricing-info ul {
            padding-left: 20px;
        }

        .pricing-info li {
            margin-bottom: 5px;
        }

        .invoice-container {
            background: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }

        .invoice-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }

        .invoice-logo {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }

        .invoice-details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .invoice-section-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
            color: #555;
        }

        .invoice-item {
            margin-bottom: 5px;
            display: flex;
        }

        .invoice-item-label {
            font-weight: 500;
            width: 120px;
            color: #666;
        }

        .invoice-item-value {
            font-weight: 400;
        }

        .invoice-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 30px;
        }

        .invoice-table th {
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #555;
        }

        .invoice-table td {
            padding: 12px;
            border-bottom: 1px solid #eee;
        }

        .invoice-table tr:last-child td {
            border-bottom: none;
            border-top: 2px solid #667eea;
            font-weight: 600;
        }

        .invoice-table .amount {
            text-align: right;
        }

        .invoice-actions {
            display: flex;
            justify-content: flex-end;
            gap: 15px;
            margin-top: 20px;
        }

        .success-message, .error-message {
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            display: none;
        }

        .success-message {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }

        .error-message {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }

        .action-buttons {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 30px;
        }

        @media (max-width: 768px) {
            .header h1 { font-size: 2em; }
            .form-grid { grid-template-columns: 1fr; }
            .auth-section, .booking-section, .bookings-section, .invoice-section { padding: 20px; }
            .booking-type-tabs { flex-wrap: nowrap; }
            .invoice-header { flex-direction: column; align-items: flex-start; }
            .invoice-actions { flex-direction: column; }
            .action-buttons { flex-direction: column; gap: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚗 RideBooker</h1>
            <p>Book Premium Drivers with Ease</p>
            <button class="logout-btn hidden" id="logoutBtn" onclick="logout()">Logout</button>
        </div>

        <!-- Authentication Section -->
        <div class="auth-section" id="authSection">
            <h2 style="margin-bottom: 30px; color: #333; text-align: center;">Login to Continue</h2>
            
            <div class="success-message" id="authSuccessMessage"></div>
            <div class="error-message" id="authErrorMessage"></div>

            <div class="auth-tabs">
                <div class="auth-tab active" id="emailTab" onclick="switchTab('email')">Email</div>
                <div class="auth-tab" id="phoneTab" onclick="switchTab('phone')">Phone</div>
            </div>

            <div id="emailSection">
                <div class="form-group">
                    <label for="userEmail">Enter Your Email</label>
                    <input type="email" id="userEmail" placeholder="example@gmail.com" required>
                </div>
                <div style="text-align: center;">
                    <button class="btn" onclick="sendEmailOTP()">Send OTP</button>
                </div>
            </div>

            <div id="phoneSection" class="hidden">
                <div class="form-group">
                    <label for="phoneNumber">Enter Your Phone Number</label>
                    <input type="tel" id="phoneNumber" placeholder="+1234567890" required>
                </div>
                <div style="text-align: center;">
                    <button class="btn" onclick="sendOTP()">Send OTP</button>
                </div>
            </div>

            <div id="otpSection" class="hidden">
                <div class="form-group">
                    <label for="otpInput">Enter 6-Digit OTP</label>
                    <input type="text" id="otpInput" class="otp-input" maxlength="6" placeholder="000000" required>
                </div>
                <div style="text-align: center;">
                    <button class="btn" onclick="verifyOTP()">Verify OTP</button>
                    <button class="btn" onclick="resendOTP()" style="margin-left: 10px; background: #6c757d;">Resend OTP</button>
                </div>
            </div>
        </div>

        <!-- Main Booking Section -->
        <div class="booking-section hidden" id="bookingSection">
            <div class="user-profile" id="userProfile">
                <!-- User profile will be populated here -->
            </div>
            
            <h2 style="margin-bottom: 30px; color: #333; text-align: center;">Book Your Driver</h2>
            
            <div class="success-message" id="successMessage"></div>
            <div class="error-message" id="errorMessage"></div>

            <div class="booking-type-tabs">
                <div class="booking-type-tab active" id="hourlyTab" onclick="switchBookingType('hourly')">Hourly Basis</div>
                <div class="booking-type-tab" id="outstation_overnightTab" onclick="switchBookingType('outstation_overnight')">Outstation (Overnight)</div>
                <div class="booking-type-tab" id="outstation_same_dayTab" onclick="switchBookingType('outstation_same_day')">Outstation (Same Day)</div>
                <div class="booking-type-tab" id="pickup_dropTab" onclick="switchBookingType('pickup_drop')">Pickup & Drop</div>
            </div>

            <form id="bookingForm">
                <input type="hidden" id="bookingType" name="bookingType" value="hourly">
                
                <div class="form-grid">
                    <div class="form-group">
                        <label for="pickup">Pickup Location</label>
                        <div class="address-input-container">
                            <input type="text" id="pickup" name="pickup" placeholder="Enter pickup address" required>
                            <div id="pickupSuggestions" class="address-suggestions hidden"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="destination">Destination</label>
                        <div class="address-input-container">
                            <input type="text" id="destination" name="destination" placeholder="Enter destination" required>
                            <div id="destinationSuggestions" class="address-suggestions hidden"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="date">Date</label>
                        <input type="date" id="date" name="date" required>
                    </div>
                    <div class="form-group">
                        <label for="carType">Car Type</label>
                        <select id="carType" name="carType" required>
                            <option value="Manual">Manual</option>
                            <option value="Automatic">Automatic</option>
                            <option value="Semi-Automatic">Semi-Automatic</option>
                            <option value="Electric">Electric Vehicle</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Timing</label>
                        <div class="time-picker">
                            <select id="startTime" name="startTime" required>
                                <option value="">From</option>
                                <option value="00:00">12:00 AM</option>
                                <option value="01:00">1:00 AM</option>
                                <option value="02:00">2:00 AM</option>
                                <option value="03:00">3:00 AM</option>
                                <option value="04:00">4:00 AM</option>
                                <option value="05:00">5:00 AM</option>
                                <option value="06:00">6:00 AM</option>
                                <option value="07:00">7:00 AM</option>
                                <option value="08:00">8:00 AM</option>
                                <option value="09:00">9:00 AM</option>
                                <option value="10:00">10:00 AM</option>
                                <option value="11:00">11:00 AM</option>
                                <option value="12:00">12:00 PM</option>
                                <option value="13:00">1:00 PM</option>
                                <option value="14:00">2:00 PM</option>
                                <option value="15:00">3:00 PM</option>
                                <option value="16:00">4:00 PM</option>
                                <option value="17:00">5:00 PM</option>
                                <option value="18:00">6:00 PM</option>
                                <option value="19:00">7:00 PM</option>
                                <option value="20:00">8:00 PM</option>
                                <option value="21:00">9:00 PM</option>
                                <option value="22:00">10:00 PM</option>
                                <option value="23:00">11:00 PM</option>
                            </select>
                            <span class="time-label">to</span>
                            <select id="endTime" name="endTime" required>
                                <option value="">To</option>
                                <option value="00:00">12:00 AM</option>
                                <option value="01:00">1:00 AM</option>
                                <option value="02:00">2:00 AM</option>
                                <option value="03:00">3:00 AM</option>
                                <option value="04:00">4:00 AM</option>
                                <option value="05:00">5:00 AM</option>
                                <option value="06:00">6:00 AM</option>
                                <option value="07:00">7:00 AM</option>
                                <option value="08:00">8:00 AM</option>
                                <option value="09:00">9:00 AM</option>
                                <option value="10:00">10:00 AM</option>
                                <option value="11:00">11:00 AM</option>
                                <option value="12:00">12:00 PM</option>
                                <option value="13:00">1:00 PM</option>
                                <option value="14:00">2:00 PM</option>
                                <option value="15:00">3:00 PM</option>
                                <option value="16:00">4:00 PM</option>
                                <option value="17:00">5:00 PM</option>
                                <option value="18:00">6:00 PM</option>
                                <option value="19:00">7:00 PM</option>
                                <option value="20:00">8:00 PM</option>
                                <option value="21:00">9:00 PM</option>
                                <option value="22:00">10:00 PM</option>
                                <option value="23:00">11:00 PM</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group" id="numDaysGroup">
                        <label for="numDays">Number of Days</label>
                        <input type="number" id="numDays" name="numDays" min="1" value="1" placeholder="Enter number of days">
                    </div>
                    <div class="form-group">
                        <label for="customerName">Your Name</label>
                        <input type="text" id="customerName" name="customerName" placeholder="Enter your name" required>
                    </div>
                    <div class="form-group">
                        <label for="customerPhone">Your Phone Number</label>
                        <input type="tel" id="customerPhone" name="customerPhone" placeholder="Enter your phone number" required>
                    </div>
                </div>

                <div id="map"></div>
                
                <div class="rate-chart hidden" id="rateChart">
                    <h3 style="margin-bottom: 15px;">Estimated Fare Breakdown</h3>
                    <div class="rate-item">
                        <span>Distance:</span>
                        <span id="distanceDisplay">-</span>
                    </div>
                    <div class="rate-item">
                        <span>Estimated Duration:</span>
                        <span id="durationDisplay">-</span>
                    </div>
                    <div class="rate-item">
                        <span>Base Rate:</span>
                        <span id="baseRateDisplay">-</span>
                    </div>
                    <div class="rate-item" id="additionalChargesRow">
                        <span id="additionalChargesLabel">Additional Charges:</span>
                        <span id="additionalChargesDisplay">-</span>
                    </div>
                    <div class="rate-item total-fare">
                        <span>Estimated Total:</span>
                        <span id="totalFareDisplay">-</span>
                    </div>
                </div>
                
                <div class="action-buttons">
                    <button type="button" class="btn btn-secondary" id="knowRateBtn" onclick="calculateAndShowRate()">Know Rate</button>
                    <button type="submit" class="btn">
                        <span id="searchText">Submit Booking Request</span>
                        <span id="searchLoading" class="loading hidden"></span>
                    </button>
                </div>
            </form>
        </div>

        <!-- Invoice Section -->
        <div class="invoice-section hidden" id="invoiceSection">
            <h2 style="margin-bottom: 30px; color: #333; text-align: center;">Booking Summary</h2>
            
            <div class="invoice-container" id="invoiceContainer">
                <!-- Invoice content will be populated here -->
            </div>
            
            <div class="invoice-actions">
                <button class="btn btn-secondary" onclick="backToBooking()">Back to Booking</button>
                <button class="btn" onclick="downloadInvoice()">Download Invoice</button>
                <button class="btn btn-success" onclick="confirmBooking()">Confirm Booking</button>
            </div>
        </div>

        <div class="bookings-section hidden" id="bookingsSection">
            <h2 style="margin-bottom: 30px; color: #333;">Your Bookings</h2>
            <div id="bookingsList">
                <p style="text-align: center; color: #666;">No bookings yet. Book a driver to see your reservations here.</p>
            </div>
        </div>
    </div>

    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" 
            integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" 
            crossorigin=""></script>
    <!-- Leaflet Routing Machine JS -->
    <script src="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.js"></script>
    
    <script>
        let map, routingControl;
        let currentBookingData = {};
        let estimatedDistance = 0;
        let estimatedDuration = 0;
        let currentAuthMethod = 'email';
        let pickupCoords = null;
        let destinationCoords = null;
        let currentBookingType = 'hourly';
        let fareDetails = {};

        // Check if user is already logged in
        window.onload = function() {
            checkAuthStatus();
            
            // Hide number of days field initially (only show for outstation overnight)
            document.getElementById('numDaysGroup').classList.add('hidden');
        };

        function switchTab(tab) {
            currentAuthMethod = tab;
            
            if (tab === 'email') {
                document.getElementById('emailTab').classList.add('active');
                document.getElementById('phoneTab').classList.remove('active');
                document.getElementById('emailSection').classList.remove('hidden');
                document.getElementById('phoneSection').classList.add('hidden');
            } else {
                document.getElementById('emailTab').classList.remove('active');
                document.getElementById('phoneTab').classList.add('active');
                document.getElementById('emailSection').classList.add('hidden');
                document.getElementById('phoneSection').classList.remove('hidden');
            }
            
            document.getElementById('otpSection').classList.add('hidden');
        }

        function switchBookingType(type) {
            currentBookingType = type;
            document.getElementById('bookingType').value = type;
            
            // Update active tab
            document.querySelectorAll('.booking-type-tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            document.getElementById(`${type}Tab`).classList.add('active');
            
            // Show/hide number of days field for outstation overnight
            if (type === 'outstation_overnight') {
                document.getElementById('numDaysGroup').classList.remove('hidden');
            } else {
                document.getElementById('numDaysGroup').classList.add('hidden');
            }
            
            // Hide rate chart when switching booking type
            document.getElementById('rateChart').classList.add('hidden');
        }

        function checkAuthStatus() {
            fetch('/check_auth')
                .then(response => response.json())
                .then(data => {
                    if (data.authenticated) {
                        showMainApp();
                        if (data.user) {
                            displayUserProfile(data.user);
                        }
                    } else {
                        showAuthSection();
                    }
                });
        }

        function displayUserProfile(user) {
            const profileDiv = document.getElementById('userProfile');
            profileDiv.innerHTML = `
                <div class="user-info">
                    <div class="user-name">${user.name || 'User'}</div>
                    <div class="user-email">${user.email || user.phone || ''}</div>
                </div>
            `;
            
            // Pre-fill customer name if available
            if (user.name) {
                document.getElementById('customerName').value = user.name;
            }
            
            // Pre-fill phone number if available
            if (user.phone) {
                document.getElementById('customerPhone').value = user.phone;
            }
        }

        function showAuthSection() {
            document.getElementById('authSection').classList.remove('hidden');
            document.getElementById('bookingSection').classList.add('hidden');
            document.getElementById('bookingsSection').classList.add('hidden');
            document.getElementById('invoiceSection').classList.add('hidden');
            document.getElementById('logoutBtn').classList.add('hidden');
        }

        function showMainApp() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('bookingSection').classList.remove('hidden');
            document.getElementById('bookingsSection').classList.remove('hidden');
            document.getElementById('invoiceSection').classList.add('hidden');
            document.getElementById('logoutBtn').classList.remove('hidden');
            loadBookings();
            initMap();
            setupAddressSearch();
        }

        function showInvoiceSection() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('bookingSection').classList.add('hidden');
            document.getElementById('bookingsSection').classList.add('hidden');
            document.getElementById('invoiceSection').classList.remove('hidden');
        }

        function backToBooking() {
            document.getElementById('invoiceSection').classList.add('hidden');
            document.getElementById('bookingSection').classList.remove('hidden');
        }

        async function sendEmailOTP() {
            const email = document.getElementById('userEmail').value;
            if (!email) {
                showAuthError('Please enter your email');
                return;
            }

            try {
                const response = await fetch('/send_email_otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: email })
                });

                const result = await response.json();
                if (result.success) {
                    document.getElementById('emailSection').classList.add('hidden');
                    document.getElementById('phoneSection').classList.add('hidden');
                    document.getElementById('otpSection').classList.remove('hidden');
                    showAuthSuccess('OTP sent successfully! Check your email.');
                } else {
                    showAuthError(result.message);
                }
            } catch (error) {
                showAuthError('Failed to send OTP. Please try again.');
            }
        }

        async function sendOTP() {
            const phoneNumber = document.getElementById('phoneNumber').value;
            if (!phoneNumber) {
                showAuthError('Please enter your phone number');
                return;
            }

            try {
                const response = await fetch('/send_otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: phoneNumber })
                });

                const result = await response.json();
                if (result.success) {
                    document.getElementById('emailSection').classList.add('hidden');
                    document.getElementById('phoneSection').classList.add('hidden');
                    document.getElementById('otpSection').classList.remove('hidden');
                    showAuthSuccess('OTP sent successfully! Check your phone.');
                } else {
                    showAuthError(result.message);
                }
            } catch (error) {
                showAuthError('Failed to send OTP. Please try again.');
            }
        }

        async function verifyOTP() {
            const otp = document.getElementById('otpInput').value;
            if (!otp || otp.length !== 6) {
                showAuthError('Please enter a valid 6-digit OTP');
                return;
            }

            let data = {};
            if (currentAuthMethod === 'email') {
                data = {
                    email: document.getElementById('userEmail').value,
                    otp: otp
                };
            } else {
                data = {
                    phone: document.getElementById('phoneNumber').value,
                    otp: otp
                };
            }

            try {
                const response = await fetch('/verify_otp', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                if (result.success) {
                    showAuthSuccess('Login successful!');
                    setTimeout(() => {
                        checkAuthStatus();
                    }, 1000);
                } else {
                    showAuthError(result.message);
                }
            } catch (error) {
                showAuthError('Verification failed. Please try again.');
            }
        }

        function resendOTP() {
            if (currentAuthMethod === 'email') {
                document.getElementById('emailSection').classList.remove('hidden');
            } else {
                document.getElementById('phoneSection').classList.remove('hidden');
            }
            document.getElementById('otpSection').classList.add('hidden');
            document.getElementById('otpInput').value = '';
        }

        function logout() {
            fetch('/logout', { method: 'POST' })
                .then(() => {
                    showAuthSection();
                    document.getElementById('phoneNumber').value = '';
                    document.getElementById('userEmail').value = '';
                    document.getElementById('otpInput').value = '';
                    switchTab('email');
                });
        }

        function initMap() {
            // Initialize the map centered on Mumbai
            map = L.map('map').setView([19.0760, 72.8777], 12);
            
            // Add OpenStreetMap tile layer
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }).addTo(map);
            
            // Initialize routing control (but don't add to map yet)
            routingControl = L.Routing.control({
                waypoints: [],
                routeWhileDragging: false,
                showAlternatives: false,
                fitSelectedRoutes: true,
                lineOptions: {
                    styles: [{ color: '#6366F1', weight: 6 }]
                },
                createMarker: function(i, waypoint, n) {
                    const marker = L.marker(waypoint.latLng, {
                        draggable: true,
                        icon: L.icon({
                            iconUrl: i === 0 
                                ? 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png' 
                                : 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
                            iconSize: [25, 41],
                            iconAnchor: [12, 41],
                            popupAnchor: [1, -34],
                            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
                            shadowSize: [41, 41]
                        })
                    });
                    return marker;
                }
            });
            
            // Listen for route calculation events
            routingControl.on('routesfound', function(e) {
                const routes = e.routes;
                const summary = routes[0].summary;
                
                // Update distance and duration
                estimatedDistance = summary.totalDistance / 1000; // Convert to km
                estimatedDuration = summary.totalTime / 60; // Convert to minutes
                
                document.getElementById('distanceDisplay').textContent = `${estimatedDistance.toFixed(1)} km`;
                document.getElementById('durationDisplay').textContent = `${Math.round(estimatedDuration)} min`;
            });
        }

        function setupAddressSearch() {
            const pickupInput = document.getElementById('pickup');
            const destinationInput = document.getElementById('destination');
            const pickupSuggestions = document.getElementById('pickupSuggestions');
            const destinationSuggestions = document.getElementById('destinationSuggestions');
            
            // Setup debounce function for address search
            let pickupTimeout = null;
            let destinationTimeout = null;
            
            // Pickup input event listener
            pickupInput.addEventListener('input', function() {
                clearTimeout(pickupTimeout);
                const query = this.value.trim();
                
                if (query.length < 3) {
                    pickupSuggestions.classList.add('hidden');
                    return;
                }
                
                pickupTimeout = setTimeout(() => {
                    searchAddress(query, pickupSuggestions, (address) => {
                        pickupInput.value = address.display_name;
                        pickupCoords = [address.lat, address.lon];
                        pickupSuggestions.classList.add('hidden');
                        updateRoute();
                    });
                }, 500);
            });
            
            // Destination input event listener
            destinationInput.addEventListener('input', function() {
                clearTimeout(destinationTimeout);
                const query = this.value.trim();
                
                if (query.length < 3) {
                    destinationSuggestions.classList.add('hidden');
                    return;
                }
                
                destinationTimeout = setTimeout(() => {
                    searchAddress(query, destinationSuggestions, (address) => {
                        destinationInput.value = address.display_name;
                        destinationCoords = [address.lat, address.lon];
                        destinationSuggestions.classList.add('hidden');
                        updateRoute();
                    });
                }, 500);
            });
            
            // Hide suggestions when clicking outside
            document.addEventListener('click', function(e) {
                if (!pickupInput.contains(e.target) && !pickupSuggestions.contains(e.target)) {
                    pickupSuggestions.classList.add('hidden');
                }
                
                if (!destinationInput.contains(e.target) && !destinationSuggestions.contains(e.target)) {
                    destinationSuggestions.classList.add('hidden');
                }
            });
            
            // Add focus event listeners to show suggestions again if input has value
            pickupInput.addEventListener('focus', function() {
                if (this.value.trim().length >= 3) {
                    searchAddress(this.value.trim(), pickupSuggestions, (address) => {
                        pickupInput.value = address.display_name;
                        pickupCoords = [address.lat, address.lon];
                        pickupSuggestions.classList.add('hidden');
                        updateRoute();
                    });
                }
            });
            
            destinationInput.addEventListener('focus', function() {
                if (this.value.trim().length >= 3) {
                    searchAddress(this.value.trim(), destinationSuggestions, (address) => {
                        destinationInput.value = address.display_name;
                        destinationCoords = [address.lat, address.lon];
                        destinationSuggestions.classList.add('hidden');
                        updateRoute();
                    });
                }
            });
        }
        
        async function searchAddress(query, suggestionsElement, onSelect) {
            try {
                // Add a custom user agent as required by Nominatim usage policy
                const headers = {
                    'User-Agent': 'RideBookerApp/1.0'
                };
                
                const params = new URLSearchParams({
                    q: query,
                    format: 'json',
                    limit: 5
                });
                
                const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, { headers });
                const data = await response.json();
                
                if (data && data.length > 0) {
                    suggestionsElement.innerHTML = '';
                    
                    data.forEach(address => {
                        const div = document.createElement('div');
                        div.className = 'address-suggestion';
                        div.textContent = address.display_name;
                        div.addEventListener('click', () => {
                            onSelect(address);
                        });
                        suggestionsElement.appendChild(div);
                    });
                    
                    suggestionsElement.classList.remove('hidden');
                } else {
                    suggestionsElement.classList.add('hidden');
                }
            } catch (error) {
                console.error('Error searching address:', error);
                suggestionsElement.classList.add('hidden');
            }
        }
        
        function updateRoute() {
            if (pickupCoords && destinationCoords) {
                // Remove previous routing control if it exists
                if (routingControl._map) {
                    map.removeControl(routingControl);
                }
                
                // Create new routing control with the coordinates
                routingControl = L.Routing.control({
                    waypoints: [
                        L.latLng(pickupCoords[0], pickupCoords[1]),
                        L.latLng(destinationCoords[0], destinationCoords[1])
                    ],
                    routeWhileDragging: false,
                    showAlternatives: false,
                    fitSelectedRoutes: true,
                    lineOptions: {
                        styles: [{ color: '#6366F1', weight: 6 }]
                    },
                    createMarker: function(i, waypoint, n) {
                        const marker = L.marker(waypoint.latLng, {
                            draggable: true,
                            icon: L.icon({
                                iconUrl: i === 0 
                                    ? 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png' 
                                    : 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41],
                                popupAnchor: [1, -34],
                                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
                                shadowSize: [41, 41]
                            })
                        });
                        return marker;
                    }
                }).addTo(map);
                
                // Listen for route calculation events
                routingControl.on('routesfound', function(e) {
                    const routes = e.routes;
                    const summary = routes[0].summary;
                    
                    // Update distance and duration
                    estimatedDistance = summary.totalDistance / 1000; // Convert to km
                    estimatedDuration = summary.totalTime / 60; // Convert to minutes
                    
                    document.getElementById('distanceDisplay').textContent = `${estimatedDistance.toFixed(1)} km`;
                    document.getElementById('durationDisplay').textContent = `${Math.round(estimatedDuration)} min`;
                });
                
                // If routing fails, use our backend route calculation
                routingControl.on('routingerror', function(e) {
                    calculateRouteFromBackend();
                });
            }
        }
        
        async function calculateRouteFromBackend() {
            if (!pickupCoords || !destinationCoords) return;
            
            try {
                const response = await fetch('/calculate_route', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        pickup_lat: pickupCoords[0],
                        pickup_lon: pickupCoords[1],
                        destination_lat: destinationCoords[0],
                        destination_lon: destinationCoords[1]
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    estimatedDistance = data.distance;
                    estimatedDuration = data.duration;
                    
                    document.getElementById('distanceDisplay').textContent = data.distance_text;
                    document.getElementById('durationDisplay').textContent = data.duration_text;
                }
            } catch (error) {
                console.error('Error calculating route from backend:', error);
                // Use default values if backend fails
                estimatedDistance = 10;
                estimatedDuration = 30;
                
                document.getElementById('distanceDisplay').textContent = '10.0 km';
                document.getElementById('durationDisplay').textContent = '30 min';
            }
        }

        function calculateAndShowRate() {
            const bookingType = document.getElementById('bookingType').value;
            const startTime = document.getElementById('startTime').value;
            const endTime = document.getElementById('endTime').value;
            const numDays = parseInt(document.getElementById('numDays').value) || 1;
            
            if (!bookingType) {
                showError('Please select a booking type');
                return;
            }
            
            if (!startTime || !endTime) {
                showError('Please select both start and end times');
                return;
            }
            
            if (!pickupCoords || !destinationCoords) {
                showError('Please select valid pickup and destination addresses');
                return;
            }

            // Call backend to calculate fare
            fetch('/calculate_fare', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    booking_type: bookingType,
                    distance: estimatedDistance,
                    duration: estimatedDuration,
                    start_time: startTime,
                    end_time: endTime,
                    num_days: numDays
                })
            })
            .then(response => response.json())
            .then(data => {
                fareDetails = data;
                
                document.getElementById('baseRateDisplay').textContent = `₹${data.base_fare}`;
                
                if (data.overtime_charges > 0) {
                    document.getElementById('additionalChargesLabel').textContent = "Overtime Charges:";
                    document.getElementById('additionalChargesDisplay').textContent = `₹${data.overtime_charges}`;
                    document.getElementById('additionalChargesRow').classList.remove('hidden');
                } else if (data.travel_charges > 0) {
                    document.getElementById('additionalChargesLabel').textContent = "Travel Charges:";
                    document.getElementById('additionalChargesDisplay').textContent = `₹${data.travel_charges}`;
                    document.getElementById('additionalChargesRow').classList.remove('hidden');
                } else {
                    document.getElementById('additionalChargesRow').classList.add('hidden');
                }
                
                document.getElementById('totalFareDisplay').textContent = `₹${data.total_fare}`;
                document.getElementById('rateChart').classList.remove('hidden');
            })
            .catch(error => {
                console.error('Error calculating fare:', error);
                showError('Failed to calculate fare. Please try again.');
            });
        }

        // Validate time selection
        document.getElementById('endTime').addEventListener('change', function() {
            const startTime = document.getElementById('startTime').value;
            const endTime = this.value;
            
            if (startTime && endTime) {
                if (startTime >= endTime && currentBookingType === 'hourly') {
                    showError('End time must be after start time');
                    this.value = '';
                }
            }
        });

        // Update fare when number of days changes
        document.getElementById('numDays').addEventListener('change', function() {
            // Hide rate chart when number of days changes
            document.getElementById('rateChart').classList.add('hidden');
        });

        document.getElementById('bookingForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const submitBtn = document.querySelector('.btn');
            const searchText = document.getElementById('searchText');
            const searchLoading = document.getElementById('searchLoading');
            
            // Validate time selection
            const startTime = document.getElementById('startTime').value;
            const endTime = document.getElementById('endTime').value;
            
            if (!startTime || !endTime) {
                showError('Please select both start and end times');
                return;
            }
            
            if (startTime >= endTime && currentBookingType === 'hourly') {
                showError('End time must be after start time');
                return;
            }
            
            // Validate addresses
            if (!pickupCoords || !destinationCoords) {
                showError('Please select valid pickup and destination addresses');
                return;
            }
            
            // Validate phone number
            const phoneNumber = document.getElementById('customerPhone').value;
            if (!phoneNumber) {
                showError('Please enter your phone number for driver contact');
                return;
            }
            
            // Check if fare has been calculated
            if (Object.keys(fareDetails).length === 0) {
                showError('Please click "Know Rate" to calculate fare before submitting');
                return;
            }
            
            searchText.classList.add('hidden');
            searchLoading.classList.remove('hidden');
            submitBtn.disabled = true;

            const formData = new FormData(this);
            currentBookingData = Object.fromEntries(formData);
            currentBookingData.distance = estimatedDistance;
            currentBookingData.duration = estimatedDuration;
            currentBookingData.time = `${startTime} - ${endTime}`;
            currentBookingData.pickup_coords = pickupCoords;
            currentBookingData.destination_coords = destinationCoords;
            currentBookingData.estimated_fare = fareDetails.total_fare;

            try {
                // Generate invoice preview
                generateInvoicePreview(currentBookingData, fareDetails);
                
                // Show invoice section
                showInvoiceSection();
            } catch (error) {
                showError('Failed to generate booking preview. Please try again.');
            } finally {
                searchText.classList.remove('hidden');
                searchLoading.classList.remove('hidden');
                submitBtn.disabled = false;
            }
        });

        function generateInvoicePreview(bookingData, fareDetails) {
            const invoiceContainer = document.getElementById('invoiceContainer');
            
            // Format booking type for display
            let bookingTypeDisplay = bookingData.bookingType;
            if (bookingTypeDisplay === 'hourly') {
                bookingTypeDisplay = 'Hourly Basis';
            } else if (bookingTypeDisplay === 'outstation_overnight') {
                bookingTypeDisplay = 'Outstation (Overnight)';
            } else if (bookingTypeDisplay === 'outstation_same_day') {
                bookingTypeDisplay = 'Outstation (Same Day)';
            } else if (bookingTypeDisplay === 'pickup_drop') {
                bookingTypeDisplay = 'Pickup & Drop';
            }
            
            // Generate invoice HTML
            let invoiceHTML = `
                <div class="invoice-header">
                    <div class="invoice-logo">🚗 RideBooker</div>
                    <div>
                        <div style="font-weight: bold; font-size: 20px;">BOOKING SUMMARY</div>
                        <div style="color: #666;">Date: ${new Date().toLocaleDateString()}</div>
                    </div>
                </div>
                
                <div class="invoice-details">
                    <div>
                        <div class="invoice-section-title">Customer Details</div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Name:</div>
                            <div class="invoice-item-value">${bookingData.customerName}</div>
                        </div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Phone:</div>
                            <div class="invoice-item-value">${bookingData.customerPhone}</div>
                        </div>
                    </div>
                    
                    <div>
                        <div class="invoice-section-title">Booking Details</div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Date:</div>
                            <div class="invoice-item-value">${bookingData.date}</div>
                        </div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Time:</div>
                            <div class="invoice-item-value">${bookingData.time}</div>
                        </div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Car Type:</div>
                            <div class="invoice-item-value">${bookingData.carType}</div>
                        </div>
                        <div class="invoice-item">
                            <div class="invoice-item-label">Booking Type:</div>
                            <div class="invoice-item-value">${bookingTypeDisplay}</div>
                        </div>`;
                        
            if (bookingData.bookingType === 'outstation_overnight') {
                invoiceHTML += `
                        <div class="invoice-item">
                            <div class="invoice-item-label">Number of Days:</div>
                            <div class="invoice-item-value">${bookingData.numDays}</div>
                        </div>`;
            }
                        
            invoiceHTML += `
                    </div>
                </div>
                
                <div class="invoice-section-title">Journey Details</div>
                <div class="invoice-item">
                    <div class="invoice-item-label">From:</div>
                    <div class="invoice-item-value">${bookingData.pickup}</div>
                </div>
                <div class="invoice-item">
                    <div class="invoice-item-label">To:</div>
                    <div class="invoice-item-value">${bookingData.destination}</div>
                </div>
                <div class="invoice-item">
                    <div class="invoice-item-label">Distance:</div>
                    <div class="invoice-item-value">${estimatedDistance.toFixed(1)} km</div>
                </div>
                
                <div class="invoice-section-title" style="margin-top: 20px;">Fare Breakdown</div>
                <table class="invoice-table">
                    <thead>
                        <tr>
                            <th>Description</th>
                            <th class="amount">Amount (₹)</th>
                        </tr>
                    </thead>
                    <tbody>`;
                    
            // Add fare breakdown items
            fareDetails.breakdown.forEach(item => {
                invoiceHTML += `
                        <tr>
                            <td>${item.label}</td>
                            <td class="amount">₹${item.amount.toFixed(2)}</td>
                        </tr>`;
            });
                    
            invoiceHTML += `
                        <tr>
                            <td><strong>Total</strong></td>
                            <td class="amount"><strong>₹${fareDetails.total_fare.toFixed(2)}</strong></td>
                        </tr>
                    </tbody>
                </table>
                
                <div style="font-size: 12px; color: #666; margin-top: 30px;">
                    <p>This is a booking summary. Upon confirmation, your request will be sent to our admin who will assign a driver based on availability.</p>
                    <p>For any queries, please contact us at support@ridebooker.com</p>
                </div>
            `;
            
            invoiceContainer.innerHTML = invoiceHTML;
        }

        function downloadInvoice() {
            // Create a form to submit for PDF download
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/download_invoice';
            form.target = '_blank';
            
            // Add booking data as hidden fields
            for (const key in currentBookingData) {
                if (typeof currentBookingData[key] !== 'object') { // Skip objects like coordinates
                    const input = document.createElement('input');
                    input.type = 'hidden';
                    input.name = key;
                    input.value = currentBookingData[key];
                    form.appendChild(input);
                }
            }
            
            // Add fare details
            const fareInput = document.createElement('input');
            fareInput.type = 'hidden';
            fareInput.name = 'fare_details';
            fareInput.value = JSON.stringify(fareDetails);
            form.appendChild(fareInput);
            
            // Submit the form
            document.body.appendChild(form);
            form.submit();
            document.body.removeChild(form);
        }

        async function confirmBooking() {
            try {
                const response = await fetch('/submit_booking', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        booking_data: currentBookingData,
                        fare_details: fareDetails
                    })
                });

                const result = await response.json();

                if (result.success) {
                    // Show success message
                    showSuccess(`Booking request submitted successfully! Your booking ID is ${result.bookingId}. Notification sent to admin.`);
                    
                    // Reset form and go back to booking section
                    document.getElementById('bookingForm').reset();
                    document.getElementById('rateChart').classList.add('hidden');
                    
                    // Reset map
                    if (routingControl._map) {
                        map.removeControl(routingControl);
                    }
                    pickupCoords = null;
                    destinationCoords = null;
                    
                    // Reset fare details
                    fareDetails = {};
                    
                    // Reload bookings
                    loadBookings();
                    
                    // Go back to booking section
                    showMainApp();
                } else {
                    showError(result.message || 'Booking failed. Please try again.');
                }
            } catch (error) {
                showError('Booking failed. Please try again.');
            }
        }

        async function loadBookings() {
            try {
                const response = await fetch('/get_bookings');
                const bookings = await response.json();
                displayBookings(bookings);
            } catch (error) {
                console.error('Failed to load bookings:', error);
            }
        }

        function displayBookings(bookings) {
            const bookingsList = document.getElementById('bookingsList');
            
            if (bookings.length === 0) {
                bookingsList.innerHTML = '<p style="text-align: center; color: #666;">No bookings yet. Book a driver to see your reservations here.</p>';
                return;
            }

            bookingsList.innerHTML = bookings.map(booking => {
                // Format booking type for display
                let bookingTypeDisplay = booking.bookingType || 'N/A';
                if (bookingTypeDisplay === 'hourly') {
                    bookingTypeDisplay = 'Hourly Basis';
                } else if (bookingTypeDisplay === 'outstation_overnight') {
                    bookingTypeDisplay = 'Outstation (Overnight)';
                } else if (bookingTypeDisplay === 'outstation_same_day') {
                    bookingTypeDisplay = 'Outstation (Same Day)';
                } else if (bookingTypeDisplay === 'pickup_drop') {
                    bookingTypeDisplay = 'Pickup & Drop';
                }
                
                return `
                <div class="booking-item">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <strong>Booking #${booking._id.substring(0, 8)}</strong>
                        <span style="background: #d4edda; color: #155724; padding: 5px 15px; border-radius: 20px; font-size: 12px; font-weight: 600;">${booking.status.toUpperCase()}</span>
                    </div>
                    <div><strong>From:</strong> ${booking.pickup}</div>
                    <div><strong>To:</strong> ${booking.destination}</div>
                    <div><strong>Date:</strong> ${booking.date}</div>
                    <div><strong>Time:</strong> ${booking.time}</div>
                    <div><strong>Booking Type:</strong> ${bookingTypeDisplay}</div>
                    <div><strong>Car Type:</strong> ${booking.carType}</div>
                    <div><strong>Distance:</strong> ${booking.distance ? booking.distance.toFixed(1) + ' km' : 'N/A'}</div>
                    <div><strong>Estimated Fare:</strong> ₹${booking.estimated_fare || 'N/A'}</div>
                    <div style="margin-top: 10px;">
                        <button class="btn" style="padding: 8px 15px; font-size: 14px;" onclick="downloadBookingInvoice('${booking._id}')">Download Invoice</button>
                    </div>
                </div>
            `}).join('');
        }

        function downloadBookingInvoice(bookingId) {
            window.open(`/download_booking_invoice/${bookingId}`, '_blank');
        }

        function showSuccess(message) {
            const successMsg = document.getElementById('successMessage');
            successMsg.textContent = message;
            successMsg.style.display = 'block';
            document.getElementById('errorMessage').style.display = 'none';
            setTimeout(() => successMsg.style.display = 'none', 5000);
        }

        function showError(message) {
            const errorMsg = document.getElementById('errorMessage');
            errorMsg.textContent = message;
            errorMsg.style.display = 'block';
            document.getElementById('successMessage').style.display = 'none';
            setTimeout(() => errorMsg.style.display = 'none', 5000);
        }

        function showAuthSuccess(message) {
            const successMsg = document.getElementById('authSuccessMessage');
            successMsg.textContent = message;
            successMsg.style.display = 'block';
            document.getElementById('authErrorMessage').style.display = 'none';
            setTimeout(() => successMsg.style.display = 'none', 5000);
        }

        function showAuthError(message) {
            const errorMsg = document.getElementById('authErrorMessage');
            errorMsg.textContent = message;
            errorMsg.style.display = 'block';
            document.getElementById('authSuccessMessage').style.display = 'none';
            setTimeout(() => errorMsg.style.display = 'none', 5000);
        }

        // Set minimum date to today
        document.getElementById('date').min = new Date().toISOString().split('T')[0];
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/check_auth')
def check_auth():
    user = get_current_user()
    if user:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': str(user['_id']),
                'name': user.get('name'),
                'email': user.get('email'),
                'phone': user.get('phone')
            }
        })
    return jsonify({'authenticated': False})

@app.route('/send_email_otp', methods=['POST'])
def send_email_otp():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'})
        
        # Generate OTP
        otp_code = generate_otp()
        
        # Check if OTP already exists for this email
        existing_otp = mongo.db.otps.find_one({'email': email})
        if existing_otp:
            mongo.db.otps.update_one(
                {'email': email},
                {'$set': {
                    'otp': otp_code,
                    'timestamp': datetime.utcnow(),
                    'attempts': 0
                }}
            )
        else:
            mongo.db.otps.insert_one({
                'email': email,
                'otp': otp_code,
                'timestamp': datetime.utcnow(),
                'attempts': 0
            })
        
        # Send email with OTP
        msg = Message('Your RideBooker OTP Code',
                     recipients=[email],
                     body=f'Your OTP code for RideBooker is: {otp_code}\n\nThis code will expire in 5 minutes.')
        
        mail.send(msg)
        
        return jsonify({
            'success': True, 
            'message': f'OTP sent to {email}',
            'debug_otp': otp_code  # Remove this in production
        })
        
    except Exception as e:
        print(f"Error sending email OTP: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to send OTP'})

@app.route('/send_otp', methods=['POST'])
def send_otp():
    try:
        data = request.get_json()
        phone = data.get('phone')
        
        if not phone:
            return jsonify({'success': False, 'message': 'Phone number is required'})
        
        # Generate OTP
        otp_code = generate_otp()
        
        # Check if OTP already exists for this phone
        existing_otp = mongo.db.otps.find_one({'phone': phone})
        if existing_otp:
            mongo.db.otps.update_one(
                {'phone': phone},
                {'$set': {
                    'otp': otp_code,
                    'timestamp': datetime.utcnow(),
                    'attempts': 0
                }}
            )
        else:
            mongo.db.otps.insert_one({
                'phone': phone,
                'otp': otp_code,
                'timestamp': datetime.utcnow(),
                'attempts': 0
            })
        
        # In production, integrate with SMS service like Twilio
        # For demo purposes, we'll just log the OTP
        print(f"OTP for {phone}: {otp_code}")
        
        return jsonify({
            'success': True, 
            'message': f'OTP sent to {phone}',
            'debug_otp': otp_code  # Remove this in production
        })
        
    except Exception as e:
        print(f"Error sending OTP: {str(e)}")
        return jsonify({'success': False, 'message': 'Failed to send OTP'})

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    try:
        data = request.get_json()
        email = data.get('email')
        phone = data.get('phone')
        entered_otp = data.get('otp')
        
        if not entered_otp:
            return jsonify({'success': False, 'message': 'OTP is required'})
        
        # Find OTP in database
        otp_record = None
        if email:
            otp_record = mongo.db.otps.find_one({'email': email})
        elif phone:
            otp_record = mongo.db.otps.find_one({'phone': phone})
        
        if not otp_record:
            return jsonify({'success': False, 'message': 'OTP not found or expired'})
        
        # Check if OTP is expired (5 minutes)
        if datetime.utcnow() - otp_record['timestamp'] > timedelta(minutes=5):
            mongo.db.otps.delete_one({'_id': otp_record['_id']})
            return jsonify({'success': False, 'message': 'OTP expired'})
        
        # Check attempts
        if otp_record['attempts'] >= 3:
            mongo.db.otps.delete_one({'_id': otp_record['_id']})
            return jsonify({'success': False, 'message': 'Too many failed attempts'})
        
        # Verify OTP
        if otp_record['otp'] == entered_otp:
            # Check if user exists
            user = None
            if email:
                user = mongo.db.users.find_one({'email': email})
                if not user:
                    user_id = mongo.db.users.insert_one({
                        'email': email,
                        'created_at': datetime.utcnow()
                    }).inserted_id
                    user = mongo.db.users.find_one({'_id': user_id})
            elif phone:
                user = mongo.db.users.find_one({'phone': phone})
                if not user:
                    user_id = mongo.db.users.insert_one({
                        'phone': phone,
                        'created_at': datetime.utcnow()
                    }).inserted_id
                    user = mongo.db.users.find_one({'_id': user_id})
            
            # Set user in session
            session['user_id'] = str(user['_id'])
            
            # Delete the OTP record
            mongo.db.otps.delete_one({'_id': otp_record['_id']})
            
            return jsonify({'success': True, 'message': 'Login successful'})
        else:
            mongo.db.otps.update_one(
                {'_id': otp_record['_id']},
                {'$inc': {'attempts': 1}}
            )
            return jsonify({'success': False, 'message': 'Invalid OTP'})
            
    except Exception as e:
        print(f"Error verifying OTP: {str(e)}")
        return jsonify({'success': False, 'message': 'Verification failed'})

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/calculate_route', methods=['POST'])
def calculate_route():
    """Calculate route using OpenStreetMap Routing Machine (OSRM)"""
    try:
        data = request.get_json()
        pickup_lat = data.get('pickup_lat')
        pickup_lon = data.get('pickup_lon')
        destination_lat = data.get('destination_lat')
        destination_lon = data.get('destination_lon')
        
        if not all([pickup_lat, pickup_lon, destination_lat, destination_lon]):
            return jsonify({'success': False, 'message': 'Missing coordinates'})
        
        route_info = get_route_info(pickup_lat, pickup_lon, destination_lat, destination_lon)
        
        return jsonify({
            'success': True,
            'distance': route_info['distance'],
            'duration': route_info['duration'],
            'distance_text': route_info['distance_text'],
            'duration_text': route_info['duration_text']
        })
    except Exception as e:
        print(f"Error calculating route: {e}")
        return jsonify({'success': False, 'message': 'Failed to calculate route'})

@app.route('/calculate_fare', methods=['POST'])
def calculate_fare_route():
    """Calculate fare based on booking type and parameters"""
    try:
        data = request.get_json()
        booking_type = data.get('booking_type')
        distance = data.get('distance', 0)
        duration = data.get('duration', 0)
        start_time = data.get('start_time', '')
        end_time = data.get('end_time', '')
        num_days = data.get('num_days', 1)
        
        fare_details = calculate_fare(booking_type, distance, duration, start_time, end_time, num_days)
        
        return jsonify(fare_details)
    except Exception as e:
        print(f"Error calculating fare: {e}")
        return jsonify({'success': False, 'message': 'Failed to calculate fare'})

@app.route('/submit_booking', methods=['POST'])
def submit_booking():
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
        
    try:
        data = request.get_json()
        booking_data = data.get('booking_data', {})
        fare_details = data.get('fare_details', {})
        
        # Get current user
        user = get_current_user()
        
        # Create booking
        booking = {
            'user_id': user['_id'],
            'pickup': booking_data.get('pickup', ''),
            'destination': booking_data.get('destination', ''),
            'date': booking_data.get('date', ''),
            'time': booking_data.get('time', ''),
            'carType': booking_data.get('carType', ''),
            'bookingType': booking_data.get('bookingType', ''),
            'numDays': int(booking_data.get('numDays', 1)),
            'distance': booking_data.get('distance', 0),
            'duration': booking_data.get('duration', 0),
            'estimated_fare': fare_details.get('total_fare', 0),
            'customerName': booking_data.get('customerName', ''),
            'customerPhone': booking_data.get('customerPhone', ''),
            'status': 'pending',
            'created_at': datetime.utcnow()
        }
        
        booking_id = mongo.db.bookings.insert_one(booking).inserted_id
        
        # Format booking type for display
        booking_type = booking_data.get('bookingType', '')
        if booking_type == 'hourly':
            booking_type_display = 'Hourly Basis'
        elif booking_type == 'outstation_overnight':
            booking_type_display = 'Outstation (Overnight)'
        elif booking_type == 'outstation_same_day':
            booking_type_display = 'Outstation (Same Day)'
        elif booking_type == 'pickup_drop':
            booking_type_display = 'Pickup & Drop'
        else:
            booking_type_display = booking_type
        
        # Send Telegram notification to admin
        telegram_message = f"""🚗 <b>NEW DRIVER BOOKING REQUEST</b>

📋 <b>Booking ID:</b> {booking_id}
👤 <b>Customer:</b> {booking_data.get('customerName', 'N/A')}
📱 <b>Phone:</b> {booking_data.get('customerPhone', 'N/A')}
📧 <b>Email:</b> {user.get('email', 'N/A')}
🏠 <b>Pickup:</b> {booking_data.get('pickup', 'N/A')}
🎯 <b>Destination:</b> {booking_data.get('destination', 'N/A')}
📅 <b>Date:</b> {booking_data.get('date', 'N/A')}
⏰ <b>Time:</b> {booking_data.get('time', 'N/A')}
🚙 <b>Car Type:</b> {booking_data.get('carType', 'N/A')}
📊 <b>Booking Type:</b> {booking_type_display}
📏 <b>Distance:</b> {booking_data.get('distance', 0):.1f} km
💰 <b>Estimated Fare:</b> ₹{fare_details.get('total_fare', 0)}

Please assign a driver for this booking and confirm with the customer."""
        
        # Send Telegram message
        send_telegram_message(TELEGRAM_ADMIN_CHAT_ID, telegram_message)
        
        # Send confirmation email if user has email
        if user.get('email'):
            try:
                msg = Message('Your RideBooker Booking Request',
                            recipients=[user['email']],
                            body=f"""Hello {booking_data.get('customerName', '')},

Your booking request has been submitted!

Booking ID: {booking_id}
Pickup: {booking_data.get('pickup', '')}
Destination: {booking_data.get('destination', '')}
Date: {booking_data.get('date', '')}
Time: {booking_data.get('time', '')}
Car Type: {booking_data.get('carType', '')}
Booking Type: {booking_type_display}
Estimated Fare: ₹{fare_details.get('total_fare', 0)}

Our admin will review your request and assign a driver. You will receive a confirmation once a driver is assigned.

Thank you for using RideBooker!
""")
                mail.send(msg)
            except Exception as e:
                print(f"Error sending confirmation email: {str(e)}")
        
        return jsonify({
            'success': True,
            'bookingId': str(booking_id),
            'message': 'Booking request submitted successfully!'
        })
        
    except Exception as e:
        print(f"Booking error: {e}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while processing your booking request.'
        })

@app.route('/download_invoice', methods=['POST'])
def download_invoice():
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Get booking data from form
        booking_data = {
            '_id': 'PREVIEW',
            'pickup': request.form.get('pickup', ''),
            'destination': request.form.get('destination', ''),
            'date': request.form.get('date', ''),
            'time': request.form.get('time', ''),
            'carType': request.form.get('carType', ''),
            'bookingType': request.form.get('bookingType', ''),
            'numDays': int(request.form.get('numDays', 1)),
            'distance': float(request.form.get('distance', 0)),
            'duration': float(request.form.get('duration', 0)),
            'customerName': request.form.get('customerName', ''),
            'customerPhone': request.form.get('customerPhone', '')
        }
        
        # Get fare details from form
        fare_details = json.loads(request.form.get('fare_details', '{}'))
        
        # Generate PDF
        pdf_buffer = generate_invoice_pdf(booking_data, fare_details)
        
        # Send PDF as response
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name='RideBooker_Invoice.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating invoice: {e}")
        return jsonify({'success': False, 'message': 'Failed to generate invoice'})

@app.route('/download_booking_invoice/<booking_id>', methods=['GET'])
def download_booking_invoice(booking_id):
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Get booking from database
        booking = mongo.db.bookings.find_one({'_id': ObjectId(booking_id)})
        if not booking:
            return jsonify({'success': False, 'message': 'Booking not found'})
        
        # Convert ObjectId to string
        booking['_id'] = str(booking['_id'])
        
        # Calculate fare details
        booking_type = booking.get('bookingType', '')
        distance = booking.get('distance', 0)
        duration = booking.get('duration', 0)
        
        # Extract time from time string (format: "HH:MM - HH:MM")
        time_parts = booking.get('time', '').split(' - ')
        start_time = time_parts[0] if len(time_parts) > 0 else ''
        end_time = time_parts[1] if len(time_parts) > 1 else ''
        
        num_days = booking.get('numDays', 1)
        
        fare_details = calculate_fare(booking_type, distance, duration, start_time, end_time, num_days)
        
        # Generate PDF
        pdf_buffer = generate_invoice_pdf(booking, fare_details)
        
        # Send PDF as response
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f'RideBooker_Invoice_{booking_id}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating booking invoice: {e}")
        return jsonify({'success': False, 'message': 'Failed to generate invoice'})

@app.route('/get_bookings', methods=['GET'])
def get_bookings():
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Get current user
    user = get_current_user()
    
    # Get bookings for current user
    bookings = list(mongo.db.bookings.find({'user_id': user['_id']}).sort('created_at', -1))
    
    # Convert ObjectId to string for JSON serialization
    for booking in bookings:
        booking['_id'] = str(booking['_id'])
        booking['user_id'] = str(booking['user_id'])
        # Convert datetime to string
        booking['created_at'] = booking['created_at'].isoformat()
    
    return jsonify(bookings)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
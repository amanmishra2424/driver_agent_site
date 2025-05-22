from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
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
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

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

# Your WhatsApp number (replace with your actual number)
ADMIN_WHATSAPP = "+1234567890"  # Replace with your WhatsApp number

# Rate multipliers for different car types
CAR_TYPE_MULTIPLIERS = {
    "Manual": 1.0,
    "Automatic": 1.2,
    "Semi-Automatic": 1.3,
    "Electric": 1.5
}

# Trip types and their base rates
TRIP_TYPES = {
    "Mumbai": 1.0,  # Base rate multiplier for Mumbai trips
    "Outstation": 1.5  # Higher rate for outstation trips
}

# Initialize database with sample data if empty
def init_db():
    try:
        if not mongo or not mongo.db:
            print("MongoDB connection not available")
            return
            
        if mongo.db.drivers.count_documents({}) == 0:
            sample_drivers = [
                {"name": "John Smith", "rating": 4.8, "car": "Toyota Camry", "base_rate": 15, "car_types": ["Manual", "Automatic"]},
                {"name": "Sarah Johnson", "rating": 4.9, "car": "Honda Accord", "base_rate": 18, "car_types": ["Automatic", "Semi-Automatic"]},
                {"name": "Mike Wilson", "rating": 4.7, "car": "Tesla Model 3", "base_rate": 35, "car_types": ["Electric"]},
                {"name": "Emily Davis", "rating": 4.6, "car": "Mercedes C-Class", "base_rate": 40, "car_types": ["Automatic", "Semi-Automatic"]},
                {"name": "David Brown", "rating": 4.8, "car": "BMW i3", "base_rate": 32, "car_types": ["Electric", "Automatic"]}
            ]
            
            mongo.db.drivers.insert_many(sample_drivers)
            print("Sample drivers added to database")
    except Exception as e:
        print(f"Error initializing database: {e}")

# Call init_db function
init_db()

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_whatsapp_message(phone, message):
    """Send WhatsApp message using WhatsApp Business API or web URL"""
    # For demo purposes, we'll create a WhatsApp web URL
    # In production, integrate with WhatsApp Business API
    encoded_message = quote(message)
    whatsapp_url = f"https://wa.me/{phone.replace('+', '')}?text={encoded_message}"
    return whatsapp_url

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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RideBooker - Premium Driver Services</title>
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

        .auth-section, .booking-section, .bookings-section {
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

        .drivers-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-top: 30px;
        }

        .driver-card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            border: 2px solid transparent;
        }

        .driver-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 20px 40px rgba(0,0,0,0.15);
            border-color: #667eea;
        }

        .driver-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .driver-name {
            font-size: 1.3em;
            font-weight: 700;
            color: #333;
        }

        .rating {
            display: flex;
            align-items: center;
            gap: 5px;
            color: #ffa500;
            font-weight: 600;
        }

        .price {
            font-size: 1.5em;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 15px;
        }

        .book-btn {
            width: 100%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
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

        @media (max-width: 768px) {
            .header h1 { font-size: 2em; }
            .form-grid { grid-template-columns: 1fr; }
            .drivers-grid { grid-template-columns: 1fr; }
            .auth-section, .booking-section, .bookings-section { padding: 20px; }
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
            
            <h2 style="margin-bottom: 30px; color: #333; text-align: center;">Find Your Perfect Driver</h2>
            
            <div class="success-message" id="successMessage"></div>
            <div class="error-message" id="errorMessage"></div>

            <form id="bookingForm">
                <div class="form-grid">
                    <div class="form-group">
                        <label for="pickup">Pickup Location</label>
                        <input type="text" id="pickup" name="pickup" placeholder="Enter pickup address" required>
                    </div>
                    <div class="form-group">
                        <label for="destination">Destination</label>
                        <input type="text" id="destination" name="destination" placeholder="Enter destination" required>
                    </div>
                    <div class="form-group">
                        <label for="date">Date</label>
                        <input type="date" id="date" name="date" required>
                    </div>
                    <div class="form-group">
                        <label for="tripType">Trip Type</label>
                        <select id="tripType" name="tripType" required>
                            <option value="Mumbai">Mumbai (Local)</option>
                            <option value="Outstation">Outstation</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="carType">Car Type</label>
                        <select id="carType" name="carType" required>
                            <option value="Manual">Manual</option>
                            <option value="Automatic">Automatic (+20% base rate)</option>
                            <option value="Semi-Automatic">Semi-Automatic (+30% base rate)</option>
                            <option value="Electric">Electric Vehicle (+50% base rate)</option>
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
                    <div class="form-group">
                        <label for="customerName">Your Name</label>
                        <input type="text" id="customerName" name="customerName" placeholder="Enter your name" required>
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
                    <div class="rate-item">
                        <span>Car Type Multiplier:</span>
                        <span id="multiplierDisplay">-</span>
                    </div>
                    <div class="rate-item">
                        <span>Trip Type Multiplier:</span>
                        <span id="tripMultiplierDisplay">-</span>
                    </div>
                    <div class="rate-item total-fare">
                        <span>Estimated Total:</span>
                        <span id="totalFareDisplay">-</span>
                    </div>
                </div>
                
                <div style="text-align: center;">
                    <button type="submit" class="btn">
                        <span id="searchText">Search Available Drivers</span>
                        <span id="searchLoading" class="loading hidden"></span>
                    </button>
                </div>
            </form>

            <div class="drivers-grid" id="driversGrid"></div>
        </div>

        <div class="bookings-section hidden" id="bookingsSection">
            <h2 style="margin-bottom: 30px; color: #333;">Your Bookings</h2>
            <div id="bookingsList">
                <p style="text-align: center; color: #666;">No bookings yet. Book a driver to see your reservations here.</p>
            </div>
        </div>
    </div>

    <script src="https://maps.googleapis.com/maps/api/js?key=YOUR_GOOGLE_MAPS_API_KEY&libraries=places&callback=initMap" async defer></script>
    
    <script>
        let map, directionsService, directionsRenderer;
        let currentBookingData = {};
        let estimatedDistance = 0;
        let estimatedDuration = 0;
        let currentAuthMethod = 'email';

        // Check if user is already logged in
        window.onload = function() {
            checkAuthStatus();
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
        }

        function showAuthSection() {
            document.getElementById('authSection').classList.remove('hidden');
            document.getElementById('bookingSection').classList.add('hidden');
            document.getElementById('bookingsSection').classList.add('hidden');
            document.getElementById('logoutBtn').classList.add('hidden');
        }

        function showMainApp() {
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('bookingSection').classList.remove('hidden');
            document.getElementById('bookingsSection').classList.remove('hidden');
            document.getElementById('logoutBtn').classList.remove('hidden');
            loadBookings();
            initMap();
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
            if (!google || !google.maps) return;
            
            map = new google.maps.Map(document.getElementById('map'), {
                zoom: 13,
                center: { lat: 19.0760, lng: 72.8777 } // Mumbai
            });

            directionsService = new google.maps.DirectionsService();
            directionsRenderer = new google.maps.DirectionsRenderer();
            directionsRenderer.setMap(map);

            // Initialize autocomplete for pickup and destination
            const pickupAutocomplete = new google.maps.places.Autocomplete(document.getElementById('pickup'));
            const destinationAutocomplete = new google.maps.places.Autocomplete(document.getElementById('destination'));

            // Calculate route when both addresses are entered
            document.getElementById('pickup').addEventListener('change', calculateRoute);
            document.getElementById('destination').addEventListener('change', calculateRoute);
            document.getElementById('carType').addEventListener('change', calculateFare);
            document.getElementById('tripType').addEventListener('change', calculateFare);
        }

        function calculateRoute() {
            if (!google || !google.maps || !directionsService) return;
            
            const pickup = document.getElementById('pickup').value;
            const destination = document.getElementById('destination').value;

            if (pickup && destination) {
                const request = {
                    origin: pickup,
                    destination: destination,
                    travelMode: google.maps.TravelMode.DRIVING,
                };

                directionsService.route(request, (result, status) => {
                    if (status === 'OK') {
                        directionsRenderer.setDirections(result);
                        
                        const route = result.routes[0];
                        estimatedDistance = route.legs[0].distance.value / 1000; // Convert to km
                        estimatedDuration = route.legs[0].duration.value / 60; // Convert to minutes

                        document.getElementById('distanceDisplay').textContent = route.legs[0].distance.text;
                        document.getElementById('durationDisplay').textContent = route.legs[0].duration.text;
                        
                        calculateFare();
                        document.getElementById('rateChart').classList.remove('hidden');
                    }
                });
            }
        }

        function calculateFare() {
            const carType = document.getElementById('carType').value;
            const tripType = document.getElementById('tripType').value;
            
            if (!carType || !tripType || estimatedDistance === 0) return;

            const baseRate = 15; // Base rate per km
            const carMultiplier = getCarTypeMultiplier(carType);
            const tripMultiplier = getTripTypeMultiplier(tripType);
            const totalFare = Math.round(estimatedDistance * baseRate * carMultiplier * tripMultiplier);

            document.getElementById('baseRateDisplay').textContent = `$${baseRate}/km`;
            document.getElementById('multiplierDisplay').textContent = `${carMultiplier}x`;
            document.getElementById('tripMultiplierDisplay').textContent = `${tripMultiplier}x`;
            document.getElementById('totalFareDisplay').textContent = `$${totalFare}`;
        }

        function getCarTypeMultiplier(carType) {
            const multipliers = {
                "Manual": 1.0,
                "Automatic": 1.2,
                "Semi-Automatic": 1.3,
                "Electric": 1.5
            };
            return multipliers[carType] || 1.0;
        }
        
        function getTripTypeMultiplier(tripType) {
            const multipliers = {
                "Mumbai": 1.0,
                "Outstation": 1.5
            };
            return multipliers[tripType] || 1.0;
        }

        // Validate time selection
        document.getElementById('endTime').addEventListener('change', function() {
            const startTime = document.getElementById('startTime').value;
            const endTime = this.value;
            
            if (startTime && endTime) {
                if (startTime >= endTime) {
                    showError('End time must be after start time');
                    this.value = '';
                }
            }
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
            
            if (startTime >= endTime) {
                showError('End time must be after start time');
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

            try {
                const response = await fetch('/search_drivers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(currentBookingData)
                });

                const drivers = await response.json();
                displayDrivers(drivers);
            } catch (error) {
                showError('Failed to search drivers. Please try again.');
            } finally {
                searchText.classList.remove('hidden');
                searchLoading.classList.add('hidden');
                submitBtn.disabled = false;
            }
        });

        function displayDrivers(drivers) {
            const grid = document.getElementById('driversGrid');
            grid.innerHTML = '';

            if (drivers.length === 0) {
                grid.innerHTML = '<p style="text-align: center; grid-column: 1/-1; color: #666;">No drivers available for the selected car type. Please try a different car type.</p>';
                return;
            }

            drivers.forEach(driver => {
                const carType = currentBookingData.carType;
                const tripType = currentBookingData.tripType;
                const carMultiplier = getCarTypeMultiplier(carType);
                const tripMultiplier = getTripTypeMultiplier(tripType);
                const hourlyRate = Math.round(driver.base_rate * carMultiplier * tripMultiplier);
                
                if (driver.car_types.includes(carType)) {
                    const driverCard = document.createElement('div');
                    driverCard.className = 'driver-card';
                    driverCard.innerHTML = `
                        <div class="driver-header">
                            <div class="driver-name">${driver.name}</div>
                            <div class="rating">
                                <span style="color: #ffa500;">★</span>
                                <span>${driver.rating}</span>
                            </div>
                        </div>
                        <div style="margin-bottom: 15px;">
                            <div style="color: #666; font-style: italic; margin-bottom: 10px;">${driver.car}</div>
                            <div class="price">$${hourlyRate}/hour</div>
                            <div style="font-size: 14px; color: #888;">Supports: ${driver.car_types.join(', ')}</div>
                        </div>
                        <button class="book-btn" onclick="bookDriver('${driver._id}')">
                            Book This Driver
                        </button>
                    `;
                    grid.appendChild(driverCard);
                }
            });
        }

        async function bookDriver(driverId) {
            try {
                const bookingData = {
                    ...currentBookingData,
                    driverId: driverId
                };

                const response = await fetch('/book_driver', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(bookingData)
                });

                const result = await response.json();

                if (result.success) {
                    showSuccess(`Booking confirmed! Your booking ID is ${result.bookingId}. WhatsApp notification sent to admin.`);
                    loadBookings();
                    document.getElementById('bookingForm').reset();
                    document.getElementById('driversGrid').innerHTML = '';
                    document.getElementById('rateChart').classList.add('hidden');
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

            bookingsList.innerHTML = bookings.map(booking => `
                <div class="booking-item">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <strong>Booking #${booking._id.substring(0, 8)}</strong>
                        <span style="background: #d4edda; color: #155724; padding: 5px 15px; border-radius: 20px; font-size: 12px; font-weight: 600;">${booking.status.toUpperCase()}</span>
                    </div>
                    <div><strong>Driver:</strong> ${booking.driver_name}</div>
                    <div><strong>From:</strong> ${booking.pickup}</div>
                    <div><strong>To:</strong> ${booking.destination}</div>
                    <div><strong>Date:</strong> ${booking.date}</div>
                    <div><strong>Time:</strong> ${booking.time}</div>
                    <div><strong>Trip Type:</strong> ${booking.tripType || 'N/A'}</div>
                    <div><strong>Car Type:</strong> ${booking.car_type}</div>
                    <div><strong>Distance:</strong> ${booking.distance ? booking.distance.toFixed(1) + ' km' : 'N/A'}</div>
                    <div><strong>Estimated Fare:</strong> $${booking.estimated_fare || 'N/A'}</div>
                </div>
            `).join('');
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

@app.route('/search_drivers', methods=['POST'])
def search_drivers():
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    car_type = data.get('carType')
    
    # Filter drivers based on car type availability
    drivers = list(mongo.db.drivers.find({'car_types': car_type}))
    
    # Convert ObjectId to string for JSON serialization
    for driver in drivers:
        driver['_id'] = str(driver['_id'])
    
    return jsonify(drivers)

@app.route('/book_driver', methods=['POST'])
def book_driver():
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
        
    try:
        data = request.get_json()
        driver_id = data.get('driverId')
        
        # Find the driver
        driver = mongo.db.drivers.find_one({'_id': ObjectId(driver_id)})
        if not driver:
            return jsonify({'success': False, 'message': 'Driver not found'})
        
        # Get current user
        user = get_current_user()
        
        # Calculate fare
        car_type = data.get('carType')
        trip_type = data.get('tripType')
        distance = data.get('distance', 0)
        car_multiplier = CAR_TYPE_MULTIPLIERS.get(car_type, 1.0)
        trip_multiplier = TRIP_TYPES.get(trip_type, 1.0)
        estimated_fare = round(distance * driver['base_rate'] * car_multiplier * trip_multiplier) if distance else 0
        
        # Create booking
        booking = {
            'user_id': user['_id'],
            'driver_id': ObjectId(driver_id),
            'driver_name': driver['name'],
            'pickup': data['pickup'],
            'destination': data['destination'],
            'date': data['date'],
            'time': data['time'],
            'car_type': data['carType'],
            'tripType': data['tripType'],
            'distance': distance,
            'duration': data.get('duration', 0),
            'estimated_fare': estimated_fare,
            'status': 'confirmed',
            'created_at': datetime.utcnow()
        }
        
        booking_id = mongo.db.bookings.insert_one(booking).inserted_id
        
        # Send WhatsApp notification to admin
        whatsapp_message = f"""🚗 NEW DRIVER BOOKING REQUEST

📋 Booking ID: {booking_id}
👤 Customer: {data['customerName']}
📱 Phone: {user.get('phone', 'N/A')}
📧 Email: {user.get('email', 'N/A')}
🚗 Driver: {driver['name']}
🏠 Pickup: {data['pickup']}
🎯 Destination: {data['destination']}
📅 Date: {data['date']}
⏰ Time: {data['time']}
🚙 Car Type: {data['carType']}
🌍 Trip Type: {data['tripType']}
📏 Distance: {distance:.1f} km
💰 Estimated Fare: ${estimated_fare}

Please confirm this booking with the customer and driver."""
        
        # In production, send actual WhatsApp message
        whatsapp_url = send_whatsapp_message(ADMIN_WHATSAPP, whatsapp_message)
        print(f"WhatsApp notification URL: {whatsapp_url}")
        print(f"Message: {whatsapp_message}")
        
        # Send confirmation email if user has email
        if user.get('email'):
            try:
                msg = Message('Your RideBooker Booking Confirmation',
                            recipients=[user['email']],
                            body=f"""Hello {data['customerName']},

Your booking has been confirmed!

Booking ID: {booking_id}
Driver: {driver['name']}
Pickup: {data['pickup']}
Destination: {data['destination']}
Date: {data['date']}
Time: {data['time']}
Car Type: {data['carType']}
Trip Type: {data['tripType']}
Estimated Fare: ${estimated_fare}

Thank you for using RideBooker!
""")
                mail.send(msg)
            except Exception as e:
                print(f"Error sending confirmation email: {str(e)}")
        
        return jsonify({
            'success': True,
            'bookingId': str(booking_id),
            'message': 'Booking confirmed successfully!',
            'whatsapp_url': whatsapp_url  # You can use this to open WhatsApp
        })
        
    except Exception as e:
        print(f"Booking error: {e}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while processing your booking.'
        })

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
        booking['driver_id'] = str(booking['driver_id'])
        # Convert datetime to string
        booking['created_at'] = booking['created_at'].isoformat()
    
    return jsonify(bookings)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
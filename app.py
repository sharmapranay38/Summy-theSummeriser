from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, send_file
from werkzeug.utils import secure_filename
# from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
import whisper
import soundfile as sf
import numpy as np
import matplotlib.pyplot as plt
# from pymongo import MongoClient
import mysql.connector
from mysql.connector import Error
from moviepy.video.io.VideoFileClip import VideoFileClip
from fpdf import FPDF
import requests

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SECRET_KEY'] = 'your_secret_key'

# MySQL Configuration
mysql_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'admin',  # Change this to your MySQL password
    'database': 'anushree'
}

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Initialize MySQL
def get_db_connection():
    try:
        conn = mysql.connector.connect(**mysql_config)
        return conn
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

# Create tables if they don't exist
def create_tables():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(150) UNIQUE NOT NULL,
                password VARCHAR(150) NOT NULL
            )
        ''')
        
        # Create transcripts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transcripts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(150) NOT NULL,
                filename VARCHAR(255) NOT NULL,
                transcript TEXT,
                summary TEXT,
                FOREIGN KEY (username) REFERENCES users(username)
            )
        ''')
        
        conn.commit()
        cursor.close()
        conn.close()
    except Error as e:
        print(f"Error creating tables: {e}")

# db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Connect to MongoDB
# client = MongoClient("mongodb://localhost:27017/")
# mongo_db = client["speech_db"]
# collection = mongo_db["transcripts"]

# Load Whisper Model
whisper_model = whisper.load_model("base")

# User class without SQLAlchemy
class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user_data:
        return User(user_data['id'], user_data['username'], user_data['password'])
    return None

def generate_waveform(audio_path):
    try:
        y, sr = sf.read(audio_path)  # Use soundfile instead of librosa
        plt.figure(figsize=(10, 4))
        plt.plot(np.linspace(0, len(y)/sr, num=len(y)), y, alpha=0.7)
        plt.xlabel("Time (s)")
        plt.ylabel("Amplitude")
        plt.title("Waveform")
        plt.savefig(f"{audio_path}.png")
        plt.close()
        return f"{audio_path}.png"
    except Exception as e:
        print("Waveform generation error:", e)
        return None

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")

        # Check if username exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            cursor.close()
            conn.close()
            flash("Username already exists", "danger")
            return redirect(url_for("register"))

        # Create new user
        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", 
                      (username, password))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if user_data and bcrypt.check_password_hash(user_data['password'], password):
            user = User(user_data['id'], user_data['username'], user_data['password'])
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials", "danger")

    return render_template("login.html")

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM transcripts WHERE username = %s", (current_user.username,))
    summaries = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template("dashboard.html", username=current_user.username, summaries=summaries)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully", "success")
    return redirect(url_for("login"))

# Set your Groq API key
GROQ_API_KEY = "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"

def generate_summary(text):
    """Summarize the transcribed text using Groq API."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mixtral-8x7b-32768",
        "messages": [
            {"role": "system", "content": "You are an expert AI summarizer. Summarize the given text concisely."},
            {"role": "user", "content": text}
        ]
    }
    response = requests.post(url, json=payload, headers=headers)
    try:
        response_json = response.json()
        print("Groq API Response:", response_json)  # Debugging: Print full response

        if "choices" in response_json:
            return response_json["choices"][0]["message"]["content"]
        elif "error" in response_json:
            return f"Error: {response_json['error']['message']}"
        else:
            return "Unexpected response format from Groq API."

    except Exception as e:
        return f"API request failed: {str(e)}"

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Convert video to audio if necessary
    if filename.endswith(('.mp4', '.mkv', '.mov')):
        audio_path = file_path.rsplit('.', 1)[0] + ".wav"
        clip = VideoFileClip(file_path)
        clip.audio.write_audiofile(audio_path)
    else:
        audio_path = file_path

    # Generate transcript using Whisper
    result = whisper_model.transcribe(audio_path)
    transcript = result['text']

    # Generate summary using Groq
    summary = generate_summary(transcript)

    # Save to MySQL
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transcripts (username, filename, transcript, summary) VALUES (%s, %s, %s, %s)",
        (current_user.username, filename, transcript, summary)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("dashboard"))

@app.route("/download/<filename>")
@login_required
def download_summary(filename):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM transcripts WHERE filename = %s AND username = %s", 
        (filename, current_user.username)
    )
    summary_data = cursor.fetchone()
    cursor.close()
    conn.close()

    if not summary_data:
        flash("File not found", "danger")
        return redirect(url_for("dashboard"))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt=f"Summary for {filename}", ln=True, align="C")
    
    pdf.ln(10)  # Line break

    # Add Transcript
    pdf.set_font("Arial", style="B", size=12)
    pdf.cell(0, 10, "Transcript:", ln=True)
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, summary_data["transcript"])

    pdf.ln(5)  # Line break

    # Add Summary
    pdf.set_font("Arial", style="B", size=12)
    pdf.cell(0, 10, "Summary:", ln=True)
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, summary_data["summary"])

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}.pdf")
    pdf.output(pdf_path)

    return send_file(pdf_path, as_attachment=True)

@app.route("/delete_file/<filename>", methods=["POST"])
@login_required
def delete_file(filename):
    """Deletes a specific file's transcript and summary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM transcripts WHERE filename = %s AND username = %s",
        (filename, current_user.username)
    )
    deleted_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    
    if deleted_count > 0:
        flash(f"Deleted data for {filename}.", "success")
    else:
        flash("File not found or already deleted.", "danger")

    return redirect(url_for("dashboard"))

if __name__ == '__main__':
    create_tables()  # Create tables on startup
    app.run(debug=True)


# ============= COMMENTED ORIGINAL CODE FOR REFERENCE =============

# MongoDB & SQLAlchemy version:
# from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, send_file
# from werkzeug.utils import secure_filename
# from flask_sqlalchemy import SQLAlchemy
# from flask_bcrypt import Bcrypt
# from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
# import os
# import whisper
# import soundfile as sf
# import numpy as np
# import matplotlib.pyplot as plt
# from pymongo import MongoClient
# from moviepy.video.io.VideoFileClip import VideoFileClip
# from fpdf import FPDF
# import requests  # Use requests instead of OpenAI library

# app = Flask(__name__)
# app.config['UPLOAD_FOLDER'] = 'uploads'
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
# app.config['SECRET_KEY'] = 'your_secret_key'

# # Ensure upload folder exists
# if not os.path.exists(app.config['UPLOAD_FOLDER']):
#     os.makedirs(app.config['UPLOAD_FOLDER'])

# db = SQLAlchemy(app)
# bcrypt = Bcrypt(app)
# login_manager = LoginManager(app)
# login_manager.login_view = "login"

# # Connect to MongoDB
# client = MongoClient("mongodb://localhost:27017/")
# mongo_db = client["speech_db"]
# collection = mongo_db["transcripts"]

# # Load Whisper Model
# whisper_model = whisper.load_model("base")

# # User Authentication Model
# class User(db.Model, UserMixin):
#     id = db.Column(db.Integer, primary_key=True)
#     username = db.Column(db.String(150), unique=True, nullable=False)
#     password = db.Column(db.String(150), nullable=False)

# @login_manager.user_loader
# def load_user(user_id):
#     return User.query.get(int(user_id))

# def generate_waveform(audio_path):
#     try:
#         y, sr = sf.read(audio_path)  # Use soundfile instead of librosa
#         plt.figure(figsize=(10, 4))
#         plt.plot(np.linspace(0, len(y)/sr, num=len(y)), y, alpha=0.7)
#         plt.xlabel("Time (s)")
#         plt.ylabel("Amplitude")
#         plt.title("Waveform")
#         plt.savefig(f"{audio_path}.png")
#         plt.close()
#         return f"{audio_path}.png"
#     except Exception as e:
#         print("Waveform generation error:", e)
#         return None

# @app.route("/")
# def home():
#     return render_template("index.html")

# @app.route("/register", methods=["GET", "POST"])
# def register():
#     if request.method == "POST":
#         username = request.form["username"]
#         password = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")

#         if User.query.filter_by(username=username).first():
#             flash("Username already exists", "danger")
#             return redirect(url_for("register"))

#         new_user = User(username=username, password=password)
#         db.session.add(new_user)
#         db.session.commit()
#         flash("Registration successful! Please log in.", "success")
#         return redirect(url_for("login"))

#     return render_template("register.html")

# @app.route("/login", methods=["GET", "POST"])
# def login():
#     if request.method == "POST":
#         username = request.form["username"]
#         password = request.form["password"]
#         user = User.query.filter_by(username=username).first()

#         if user and bcrypt.check_password_hash(user.password, password):
#             login_user(user)
#             return redirect(url_for("dashboard"))
#         else:
#             flash("Invalid credentials", "danger")

#     return render_template("login.html")

# @app.route("/dashboard")
# @login_required
# def dashboard():
#     summaries = collection.find({"username": current_user.username})
#     return render_template("dashboard.html", username=current_user.username, summaries=summaries)

# @app.route("/logout")
# @login_required
# def logout():
#     logout_user()
#     flash("Logged out successfully", "success")
#     return redirect(url_for("login"))

# # Set your Groq API key
# GROQ_API_KEY = "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"

# def generate_summary(text):
#     """Summarize the transcribed text using Groq API."""
#     url = "https://api.groq.com/openai/v1/chat/completions"
#     headers = {
#         "Authorization": f"Bearer {GROQ_API_KEY}",
#         "Content-Type": "application/json"
#     }
#     payload = {
#         "model": "mixtral-8x7b-32768",
#         "messages": [
#             {"role": "system", "content": "You are an expert AI summarizer. Summarize the given text concisely."},
#             {"role": "user", "content": text}
#         ]
#     }
#     response = requests.post(url, json=payload, headers=headers)
#     try:
#         response_json = response.json()
#         print("Groq API Response:", response_json)  # Debugging: Print full response

#         if "choices" in response_json:
#             return response_json["choices"][0]["message"]["content"]
#         elif "error" in response_json:
#             return f"Error: {response_json['error']['message']}"
#         else:
#             return "Unexpected response format from Groq API."

#     except Exception as e:
#         return f"API request failed: {str(e)}"

# @app.route('/upload', methods=['POST'])
# @login_required
# def upload_file():
#     if 'file' not in request.files:
#         return jsonify({"error": "No file uploaded"}), 400

#     file = request.files['file']
#     filename = secure_filename(file.filename)
#     file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     file.save(file_path)

#     # Convert video to audio if necessary
#     if filename.endswith(('.mp4', '.mkv', '.mov')):
#         audio_path = file_path.rsplit('.', 1)[0] + ".wav"
#         clip = VideoFileClip(file_path)
#         clip.audio.write_audiofile(audio_path)
#     else:
#         audio_path = file_path

#     # Generate transcript using Whisper
#     result = whisper_model.transcribe(audio_path)
#     transcript = result['text']

#     # Generate summary using Groq
#     summary = generate_summary(transcript)

#     # Save to MongoDB
#     collection.insert_one({
#         "username": current_user.username,
#         "filename": filename,
#         "transcript": transcript,
#         "summary": summary
#     })

#     return redirect(url_for("dashboard"))

# @app.route("/download/<filename>")
# @login_required
# def download_summary(filename):
#     summary_data = collection.find_one({"filename": filename, "username": current_user.username})

#     if not summary_data:
#         flash("File not found", "danger")
#         return redirect(url_for("dashboard"))

#     pdf = FPDF()
#     pdf.add_page()
#     pdf.set_font("Arial", size=12)

#     pdf.cell(200, 10, txt=f"Summary for {filename}", ln=True, align="C")
    
#     pdf.ln(10)  # Line break

#     # Add Transcript
#     pdf.set_font("Arial", style="B", size=12)
#     pdf.cell(0, 10, "Transcript:", ln=True)
#     pdf.set_font("Arial", size=12)
#     pdf.multi_cell(0, 10, summary_data["transcript"])

#     pdf.ln(5)  # Line break

#     # Add Summary
#     pdf.set_font("Arial", style="B", size=12)
#     pdf.cell(0, 10, "Summary:", ln=True)
#     pdf.set_font("Arial", size=12)
#     pdf.multi_cell(0, 10, summary_data["summary"])

#     pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}.pdf")
#     pdf.output(pdf_path)

#     return send_file(pdf_path, as_attachment=True)


# @app.route("/delete_file/<filename>", methods=["POST"])
# @login_required
# def delete_file(filename):
#     """Deletes a specific file's transcript and summary."""
#     result = collection.delete_one({"filename": filename, "username": current_user.username})
    
#     if result.deleted_count > 0:
#         flash(f"Deleted data for {filename}.", "success")
#     else:
#         flash("File not found or already deleted.", "danger")

#     return redirect(url_for("dashboard"))


# if __name__ == '__main__':
#     with app.app_context():  # Set up the application context
#         db.create_all()  # Now it works correctly
#     app.run(debug=True)
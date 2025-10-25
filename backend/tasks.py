# Celery Tasks
from celery import Celery
from celery.schedules import crontab
from datetime import datetime, timedelta
from config import Config
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import csv
import io

# Initialize Celery
celery = Celery('tasks')
celery.config_from_object(Config)

# Periodic task schedule
celery.conf.beat_schedule = {
    'send-daily-reminders': {
        'task': 'tasks.send_daily_reminders',
        'schedule': crontab(hour=18, minute=0),  # 6 PM daily
    },
    'send-monthly-reports': {
        'task': 'tasks.send_monthly_reports',
        'schedule': crontab(day_of_month=1, hour=9, minute=0),  # 1st day of month at 9 AM
    },
}


def get_db():
    """Get database session"""
    from app import create_app
    from models import db
    app = create_app()
    app.app_context().push()
    return db


def send_email(to_email, subject, html_content):
    """Send email using SMTP"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = Config.SMTP_USERNAME
        msg['To'] = to_email
        
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            server.send_message(msg)
        
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


def send_google_chat_message(message):
    """Send message to Google Chat using webhook"""
    if not Config.GOOGLE_CHAT_WEBHOOK:
        print("Google Chat webhook not configured")
        return False
    
    try:
        payload = {'text': message}
        response = requests.post(Config.GOOGLE_CHAT_WEBHOOK, json=payload)
        return response.status_code == 200
    except Exception as e:
        print(f"Google Chat error: {e}")
        return False


@celery.task
def send_daily_reminders():
    """Send daily reminders to inactive users"""
    db = get_db()
    from models import User, UserActivity, ParkingLot
    
    # Get users who haven't logged in or booked in last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    users = User.query.filter_by(role='user').all()
    reminded_count = 0
    
    for user in users:
        # Check last activity
        last_activity = UserActivity.query.filter_by(user_id=user.id).order_by(
            UserActivity.activity_timestamp.desc()
        ).first()
        
        if not last_activity or last_activity.activity_timestamp < week_ago:
            # Send reminder
            available_lots = ParkingLot.query.count()
            
            message = f"""
            <html>
            <body>
                <h2>🚗 Parking Reminder</h2>
                <p>Hi {user.username},</p>
                <p>We noticed you haven't used our parking service recently.</p>
                <p>We currently have <strong>{available_lots} parking lots</strong> available for you!</p>
                <p>Book your spot today and enjoy hassle-free parking.</p>
                <p><a href="http://localhost:8080">Visit Parking App</a></p>
                <br>
                <p>Best regards,<br>Vehicle Parking Team</p>
            </body>
            </html>
            """
            
            # Try email first
            if Config.SMTP_USERNAME:
                if send_email(user.email, "Time to park! 🚗", message):
                    reminded_count += 1
            
            # Fallback to Google Chat
            if Config.GOOGLE_CHAT_WEBHOOK:
                send_google_chat_message(
                    f"Reminder for {user.username}: {available_lots} parking lots available!"
                )
    
    print(f"Daily reminders sent to {reminded_count} users")
    return f"Sent to {reminded_count} users"


@celery.task
def send_monthly_reports():
    """Send monthly activity reports to all users"""
    db = get_db()
    from models import User, Reservation, ParkingLot, ParkingSpot
    from sqlalchemy import func
    
    users = User.query.filter_by(role='user').all()
    sent_count = 0
    
    # Get last month's date range
    today = datetime.utcnow()
    first_day_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    last_day_last_month = today.replace(day=1) - timedelta(days=1)
    
    for user in users:
        # Get monthly stats
        reservations = Reservation.query.filter(
            Reservation.user_id == user.id,
            Reservation.parking_timestamp >= first_day_last_month,
            Reservation.parking_timestamp <= last_day_last_month
        ).all()
        
        if not reservations:
            continue
        
        total_bookings = len(reservations)
        total_spent = sum(r.parking_cost for r in reservations if r.parking_cost)
        total_hours = sum(r.duration_hours for r in reservations if r.duration_hours)
        
        # Most used lot
        most_used = db.session.query(
            ParkingLot.prime_location_name,
            func.count(Reservation.id).label('count')
        ).join(ParkingSpot).join(Reservation).filter(
            Reservation.user_id == user.id,
            Reservation.parking_timestamp >= first_day_last_month,
            Reservation.parking_timestamp <= last_day_last_month
        ).group_by(ParkingLot.id).order_by(func.count(Reservation.id).desc()).first()
        
        most_used_lot = most_used[0] if most_used else "N/A"
        
        # Generate HTML report
        html_report = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #21808d; color: white; padding: 20px; text-align: center; }}
                .stats {{ background: #f4f4f4; padding: 20px; margin: 20px 0; }}
                .stat-item {{ margin: 10px 0; }}
                .stat-label {{ font-weight: bold; }}
                .footer {{ text-align: center; margin-top: 30px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚗 Monthly Parking Report</h1>
                    <p>{first_day_last_month.strftime('%B %Y')}</p>
                </div>
                
                <p>Hi {user.username},</p>
                <p>Here's your parking activity summary for last month:</p>
                
                <div class="stats">
                    <div class="stat-item">
                        <span class="stat-label">Total Bookings:</span> {total_bookings}
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Hours Parked:</span> {round(total_hours, 2)} hrs
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Amount Spent:</span> ₹{round(total_spent, 2)}
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Most Used Location:</span> {most_used_lot}
                    </div>
                </div>
                
                <p>Thank you for using our parking service!</p>
                
                <div class="footer">
                    <p>Vehicle Parking App<br>
                    <a href="http://localhost:8080">Visit Dashboard</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Send email
        if Config.SMTP_USERNAME:
            if send_email(
                user.email,
                f"Your Parking Report - {first_day_last_month.strftime('%B %Y')}",
                html_report
            ):
                sent_count += 1
    
    print(f"Monthly reports sent to {sent_count} users")
    return f"Sent to {sent_count} users"


@celery.task
def export_user_data_csv(user_id):
    """Export user parking data as CSV (async)"""
    db = get_db()
    from models import Reservation
    
    reservations = Reservation.query.filter_by(user_id=user_id).order_by(
        Reservation.parking_timestamp.desc()
    ).all()
    
    # Generate CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        'Reservation ID', 'Spot Number', 'Lot Name', 'Parking Time',
        'Leaving Time', 'Duration (hrs)', 'Cost', 'Status'
    ])
    
    for r in reservations:
        writer.writerow([
            r.id,
            r.parking_spot.spot_number,
            r.parking_spot.parking_lot.prime_location_name,
            r.parking_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            r.leaving_timestamp.strftime('%Y-%m-%d %H:%M:%S') if r.leaving_timestamp else 'Active',
            r.duration_hours or 'N/A',
            r.parking_cost or 'N/A',
            'Completed' if r.leaving_timestamp else 'Active'
        ])
    
    csv_content = output.getvalue()
    
    # In production, save to file storage or send via email
    print(f"CSV export completed for user {user_id}, {len(reservations)} records")
    
    return {
        'user_id': user_id,
        'records': len(reservations),
        'status': 'completed',
        'download_url': f'/api/user/export-csv/download/{user_id}'
    }

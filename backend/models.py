# Database Models
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    """User Model - Stores both Admin and Regular Users"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # 'admin' or 'user'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    reservations = db.relationship('Reservation', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class ParkingLot(db.Model):
    """Parking Lot Model - Represents a physical parking location"""
    __tablename__ = 'parking_lots'
    
    id = db.Column(db.Integer, primary_key=True)
    prime_location_name = db.Column(db.String(200), nullable=False)
    price_per_hour = db.Column(db.Float, nullable=False)
    address = db.Column(db.Text, nullable=False)
    pin_code = db.Column(db.String(10), nullable=False)
    number_of_spots = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    spots = db.relationship('ParkingSpot', backref='parking_lot', lazy='dynamic', cascade='all, delete-orphan')
    
    def to_dict(self):
        """Convert parking lot to dictionary"""
        available_spots = self.spots.filter_by(status='A').count()
        occupied_spots = self.spots.filter_by(status='O').count()
        
        return {
            'id': self.id,
            'prime_location_name': self.prime_location_name,
            'price_per_hour': self.price_per_hour,
            'address': self.address,
            'pin_code': self.pin_code,
            'number_of_spots': self.number_of_spots,
            'available_spots': available_spots,
            'occupied_spots': occupied_spots,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ParkingSpot(db.Model):
    """Parking Spot Model - Individual parking space within a lot"""
    __tablename__ = 'parking_spots'
    
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey('parking_lots.id'), nullable=False, index=True)
    spot_number = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(1), nullable=False, default='A')  # 'A' = Available, 'O' = Occupied
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reservations = db.relationship('Reservation', backref='parking_spot', lazy='dynamic')
    
    def to_dict(self):
        """Convert parking spot to dictionary"""
        current_reservation = None
        if self.status == 'O':
            reservation = self.reservations.filter_by(leaving_timestamp=None).first()
            if reservation:
                current_reservation = {
                    'user_id': reservation.user_id,
                    'username': reservation.user.username,
                    'parking_timestamp': reservation.parking_timestamp.isoformat()
                }
        
        return {
            'id': self.id,
            'lot_id': self.lot_id,
            'spot_number': self.spot_number,
            'status': self.status,
            'status_label': 'Available' if self.status == 'A' else 'Occupied',
            'current_reservation': current_reservation
        }


class Reservation(db.Model):
    """Reservation Model - Tracks parking spot bookings"""
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    spot_id = db.Column(db.Integer, db.ForeignKey('parking_spots.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    parking_timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    leaving_timestamp = db.Column(db.DateTime)
    parking_cost = db.Column(db.Float)
    duration_hours = db.Column(db.Float)
    remarks = db.Column(db.Text)
    
    def to_dict(self):
        """Convert reservation to dictionary"""
        return {
            'id': self.id,
            'spot_id': self.spot_id,
            'spot_number': self.parking_spot.spot_number,
            'lot_name': self.parking_spot.parking_lot.prime_location_name,
            'lot_address': self.parking_spot.parking_lot.address,
            'user_id': self.user_id,
            'username': self.user.username,
            'parking_timestamp': self.parking_timestamp.isoformat() if self.parking_timestamp else None,
            'leaving_timestamp': self.leaving_timestamp.isoformat() if self.leaving_timestamp else None,
            'parking_cost': self.parking_cost,
            'duration_hours': self.duration_hours,
            'remarks': self.remarks,
            'status': 'Active' if not self.leaving_timestamp else 'Completed'
        }
    
    def calculate_cost(self):
        """Calculate parking cost based on duration"""
        if self.leaving_timestamp and self.parking_timestamp:
            duration = (self.leaving_timestamp - self.parking_timestamp).total_seconds() / 3600  # Hours
            self.duration_hours = round(duration, 2)
            price_per_hour = self.parking_spot.parking_lot.price_per_hour
            self.parking_cost = round(duration * price_per_hour, 2)
        return self.parking_cost


class UserActivity(db.Model):
    """User Activity Model - Tracks user login and activity for reminders"""
    __tablename__ = 'user_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    activity_type = db.Column(db.String(50), nullable=False)  # 'login', 'booking', 'release'
    activity_timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.Text)
    
    def to_dict(self):
        """Convert activity to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'activity_type': self.activity_type,
            'activity_timestamp': self.activity_timestamp.isoformat(),
            'description': self.description
        }

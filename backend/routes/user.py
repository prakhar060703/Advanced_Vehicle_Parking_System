# User Routes
from flask import Blueprint, request, jsonify, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, ParkingLot, ParkingSpot, Reservation, UserActivity
from datetime import datetime, timedelta
from sqlalchemy import func
import json
import csv
import io

user_bp = Blueprint('user', __name__)

def get_current_user():
    """Get current logged-in user"""
    user_id = get_jwt_identity()
    return User.query.get(user_id)


@user_bp.route('/parking-lots/available', methods=['GET'])
@jwt_required()
def get_available_lots():
    """Get parking lots with available spots"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Try cache
    cache_key = 'user:available_lots'
    if current_app.redis_client:
        try:
            cached = current_app.redis_client.get(cache_key)
            if cached:
                return jsonify(json.loads(cached)), 200
        except:
            pass
    
    lots = ParkingLot.query.all()
    available_lots = []
    
    for lot in lots:
        available_count = lot.spots.filter_by(status='A').count()
        if available_count > 0:
            lot_dict = lot.to_dict()
            available_lots.append(lot_dict)
    
    # Cache for 2 minutes
    if current_app.redis_client:
        try:
            current_app.redis_client.setex(cache_key, 120, json.dumps(available_lots))
        except:
            pass
    
    return jsonify(available_lots), 200


@user_bp.route('/book-spot', methods=['POST'])
@jwt_required()
def book_spot():
    """Book a parking spot"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    
    if 'lot_id' not in data:
        return jsonify({'error': 'Lot ID required'}), 400
    
    lot_id = data['lot_id']
    
    # Check for active reservation
    active_reservation = Reservation.query.filter_by(
        user_id=user.id,
        leaving_timestamp=None
    ).first()
    
    if active_reservation:
        return jsonify({'error': 'You already have an active booking'}), 400
    
    # Find first available spot
    spot = ParkingSpot.query.filter_by(
        lot_id=lot_id,
        status='A'
    ).first()
    
    if not spot:
        return jsonify({'error': 'No available spots in this parking lot'}), 404
    
    # Create reservation
    reservation = Reservation(
        spot_id=spot.id,
        user_id=user.id,
        parking_timestamp=datetime.utcnow()
    )
    
    # Update spot status
    spot.status = 'O'
    
    # Log activity
    activity = UserActivity(
        user_id=user.id,
        activity_type='booking',
        description=f'Booked spot {spot.spot_number}'
    )
    
    try:
        db.session.add(reservation)
        db.session.add(activity)
        db.session.commit()
        
        # Clear cache
        if current_app.redis_client:
            try:
                current_app.redis_client.delete('user:available_lots')
                current_app.redis_client.delete('admin:parking_lots')
                current_app.redis_client.delete('admin:dashboard_stats')
            except:
                pass
        
        return jsonify({
            'message': 'Spot booked successfully',
            'reservation': reservation.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@user_bp.route('/release-spot/<int:reservation_id>', methods=['POST'])
@jwt_required()
def release_spot(reservation_id):
    """Release/vacate a parking spot"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    reservation = Reservation.query.get(reservation_id)
    
    if not reservation:
        return jsonify({'error': 'Reservation not found'}), 404
    
    if reservation.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if reservation.leaving_timestamp:
        return jsonify({'error': 'Spot already released'}), 400
    
    # Update reservation
    reservation.leaving_timestamp = datetime.utcnow()
    reservation.calculate_cost()
    
    # Update spot status
    spot = reservation.parking_spot
    spot.status = 'A'
    
    # Log activity
    activity = UserActivity(
        user_id=user.id,
        activity_type='release',
        description=f'Released spot {spot.spot_number}'
    )
    
    try:
        db.session.add(activity)
        db.session.commit()
        
        # Clear cache
        if current_app.redis_client:
            try:
                current_app.redis_client.delete('user:available_lots')
                current_app.redis_client.delete('admin:parking_lots')
                current_app.redis_client.delete('admin:dashboard_stats')
            except:
                pass
        
        return jsonify({
            'message': 'Spot released successfully',
            'reservation': reservation.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@user_bp.route('/my-reservations', methods=['GET'])
@jwt_required()
def get_my_reservations():
    """Get user's reservations"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    reservations = Reservation.query.filter_by(user_id=user.id).order_by(
        Reservation.parking_timestamp.desc()
    ).all()
    
    return jsonify([r.to_dict() for r in reservations]), 200


@user_bp.route('/active-reservation', methods=['GET'])
@jwt_required()
def get_active_reservation():
    """Get user's active reservation"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    reservation = Reservation.query.filter_by(
        user_id=user.id,
        leaving_timestamp=None
    ).first()
    
    if not reservation:
        return jsonify({'message': 'No active reservation'}), 200
    
    return jsonify(reservation.to_dict()), 200


@user_bp.route('/dashboard/stats', methods=['GET'])
@jwt_required()
def get_user_stats():
    """Get user dashboard statistics"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Total bookings
    total_bookings = Reservation.query.filter_by(user_id=user.id).count()
    
    # Active booking
    active_booking = Reservation.query.filter_by(
        user_id=user.id,
        leaving_timestamp=None
    ).first()
    
    # Total spent
    total_spent = db.session.query(func.sum(Reservation.parking_cost)).filter(
        Reservation.user_id == user.id
    ).scalar() or 0
    
    # Most used lot
    most_used_lot = db.session.query(
        ParkingLot.prime_location_name,
        func.count(Reservation.id).label('count')
    ).join(ParkingSpot).join(Reservation).filter(
        Reservation.user_id == user.id
    ).group_by(ParkingLot.id).order_by(func.count(Reservation.id).desc()).first()
    
    # This month stats
    first_day_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    month_bookings = Reservation.query.filter(
        Reservation.user_id == user.id,
        Reservation.parking_timestamp >= first_day_month
    ).count()
    
    month_spent = db.session.query(func.sum(Reservation.parking_cost)).filter(
        Reservation.user_id == user.id,
        Reservation.parking_timestamp >= first_day_month
    ).scalar() or 0
    
    stats = {
        'total_bookings': total_bookings,
        'has_active_booking': active_booking is not None,
        'active_booking': active_booking.to_dict() if active_booking else None,
        'total_spent': round(total_spent, 2),
        'most_used_lot': most_used_lot[0] if most_used_lot else 'N/A',
        'month_bookings': month_bookings,
        'month_spent': round(month_spent, 2)
    }
    
    return jsonify(stats), 200


@user_bp.route('/export-csv/download/<int:user_id>', methods=['GET'])
@jwt_required()
def download_csv(user_id):
    """Download generated CSV"""
    current_user = get_current_user()
    if not current_user or current_user.id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    reservations = Reservation.query.filter_by(user_id=user_id).order_by(
        Reservation.parking_timestamp.desc()
    ).all()
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'Reservation ID', 'Spot Number', 'Lot Name', 'Lot Address',
        'Parking Time', 'Leaving Time', 'Duration (hrs)', 'Cost', 'Status', 'Remarks'
    ])
    
    # Data
    for r in reservations:
        writer.writerow([
            r.id,
            r.parking_spot.spot_number,
            r.parking_spot.parking_lot.prime_location_name,
            r.parking_spot.parking_lot.address,
            r.parking_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            r.leaving_timestamp.strftime('%Y-%m-%d %H:%M:%S') if r.leaving_timestamp else 'Active',
            r.duration_hours or 'N/A',
            r.parking_cost or 'N/A',
            'Completed' if r.leaving_timestamp else 'Active',
            r.remarks or ''
        ])
    
    # Prepare file
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'parking_history_{user_id}_{datetime.now().strftime("%Y%m%d")}.csv'
    )

# Admin Routes
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, ParkingLot, ParkingSpot, Reservation
from datetime import datetime, timedelta
from sqlalchemy import func
import json

admin_bp = Blueprint('admin', __name__)

def admin_required():
    """Check if current user is admin"""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        return None
    return user

@admin_bp.route('/parking-lots', methods=['GET'])
@jwt_required()
def get_parking_lots():
    """Get all parking lots"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Try to get from cache
    cache_key = 'admin:parking_lots'
    if current_app.redis_client:
        try:
            cached = current_app.redis_client.get(cache_key)
            if cached:
                return jsonify(json.loads(cached)), 200
        except:
            pass
    
    lots = ParkingLot.query.all()
    result = [lot.to_dict() for lot in lots]
    
    # Cache for 5 minutes
    if current_app.redis_client:
        try:
            current_app.redis_client.setex(cache_key, 300, json.dumps(result))
        except:
            pass
    
    return jsonify(result), 200


@admin_bp.route('/parking-lots', methods=['POST'])
@jwt_required()
def create_parking_lot():
    """Create a new parking lot"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    
    # Validation
    required_fields = ['prime_location_name', 'price_per_hour', 'address', 'pin_code', 'number_of_spots']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400
    
    # Create parking lot
    lot = ParkingLot(
        prime_location_name=data['prime_location_name'],
        price_per_hour=float(data['price_per_hour']),
        address=data['address'],
        pin_code=data['pin_code'],
        number_of_spots=int(data['number_of_spots'])
    )
    
    try:
        db.session.add(lot)
        db.session.flush()
        
        # Create parking spots
        for i in range(1, lot.number_of_spots + 1):
            spot = ParkingSpot(
                lot_id=lot.id,
                spot_number=f"SPOT-{lot.id}-{i:03d}",
                status='A'
            )
            db.session.add(spot)
        
        db.session.commit()
        
        # Clear cache
        if current_app.redis_client:
            try:
                current_app.redis_client.delete('admin:parking_lots')
                current_app.redis_client.delete('user:available_lots')
            except:
                pass
        
        return jsonify({
            'message': 'Parking lot created successfully',
            'lot': lot.to_dict()
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/parking-lots/<int:lot_id>', methods=['PUT'])
@jwt_required()
def update_parking_lot(lot_id):
    """Update parking lot"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    lot = ParkingLot.query.get(lot_id)
    if not lot:
        return jsonify({'error': 'Parking lot not found'}), 404
    
    data = request.get_json()
    
    # Update fields
    if 'prime_location_name' in data:
        lot.prime_location_name = data['prime_location_name']
    if 'price_per_hour' in data:
        lot.price_per_hour = float(data['price_per_hour'])
    if 'address' in data:
        lot.address = data['address']
    if 'pin_code' in data:
        lot.pin_code = data['pin_code']
    
    # Handle spot count changes
    if 'number_of_spots' in data:
        new_count = int(data['number_of_spots'])
        current_count = lot.number_of_spots
        
        if new_count > current_count:
            # Add new spots
            for i in range(current_count + 1, new_count + 1):
                spot = ParkingSpot(
                    lot_id=lot.id,
                    spot_number=f"SPOT-{lot.id}-{i:03d}",
                    status='A'
                )
                db.session.add(spot)
            lot.number_of_spots = new_count
        elif new_count < current_count:
            # Remove spots (only if available)
            spots_to_remove = lot.spots.filter_by(status='A').limit(current_count - new_count).all()
            if len(spots_to_remove) < (current_count - new_count):
                return jsonify({'error': 'Cannot reduce spots: some are occupied'}), 400
            for spot in spots_to_remove:
                db.session.delete(spot)
            lot.number_of_spots = new_count
    
    lot.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        
        # Clear cache
        if current_app.redis_client:
            try:
                current_app.redis_client.delete('admin:parking_lots')
                current_app.redis_client.delete('user:available_lots')
            except:
                pass
        
        return jsonify({
            'message': 'Parking lot updated successfully',
            'lot': lot.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/parking-lots/<int:lot_id>', methods=['DELETE'])
@jwt_required()
def delete_parking_lot(lot_id):
    """Delete parking lot (only if all spots are available)"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    lot = ParkingLot.query.get(lot_id)
    if not lot:
        return jsonify({'error': 'Parking lot not found'}), 404
    
    # Check if any spots are occupied
    occupied = lot.spots.filter_by(status='O').count()
    if occupied > 0:
        return jsonify({'error': f'Cannot delete: {occupied} spots are occupied'}), 400
    
    try:
        db.session.delete(lot)
        db.session.commit()
        
        # Clear cache
        if current_app.redis_client:
            try:
                current_app.redis_client.delete('admin:parking_lots')
                current_app.redis_client.delete('user:available_lots')
            except:
                pass
        
        return jsonify({'message': 'Parking lot deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/parking-spots/<int:lot_id>', methods=['GET'])
@jwt_required()
def get_parking_spots(lot_id):
    """Get all spots for a parking lot"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    lot = ParkingLot.query.get(lot_id)
    if not lot:
        return jsonify({'error': 'Parking lot not found'}), 404
    
    spots = lot.spots.all()
    return jsonify([spot.to_dict() for spot in spots]), 200


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    """Get all registered users"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    users = User.query.filter_by(role='user').all()
    return jsonify([u.to_dict() for u in users]), 200


@admin_bp.route('/reservations', methods=['GET'])
@jwt_required()
def get_all_reservations():
    """Get all reservations"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    reservations = Reservation.query.order_by(Reservation.parking_timestamp.desc()).all()
    return jsonify([r.to_dict() for r in reservations]), 200


@admin_bp.route('/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Cache key
    cache_key = 'admin:dashboard_stats'
    if current_app.redis_client:
        try:
            cached = current_app.redis_client.get(cache_key)
            if cached:
                return jsonify(json.loads(cached)), 200
        except:
            pass
    
    # Calculate stats
    total_lots = ParkingLot.query.count()
    total_spots = ParkingSpot.query.count()
    available_spots = ParkingSpot.query.filter_by(status='A').count()
    occupied_spots = ParkingSpot.query.filter_by(status='O').count()
    total_users = User.query.filter_by(role='user').count()
    active_reservations = Reservation.query.filter_by(leaving_timestamp=None).count()
    completed_reservations = Reservation.query.filter(Reservation.leaving_timestamp.isnot(None)).count()
    
    # Revenue calculation
    total_revenue = db.session.query(func.sum(Reservation.parking_cost)).scalar() or 0
    
    # Today's stats
    today = datetime.utcnow().date()
    today_bookings = Reservation.query.filter(
        func.date(Reservation.parking_timestamp) == today
    ).count()
    
    stats = {
        'total_parking_lots': total_lots,
        'total_parking_spots': total_spots,
        'available_spots': available_spots,
        'occupied_spots': occupied_spots,
        'occupancy_rate': round((occupied_spots / total_spots * 100) if total_spots > 0 else 0, 2),
        'total_users': total_users,
        'active_reservations': active_reservations,
        'completed_reservations': completed_reservations,
        'total_revenue': round(total_revenue, 2),
        'today_bookings': today_bookings
    }
    
    # Cache for 2 minutes
    if current_app.redis_client:
        try:
            current_app.redis_client.setex(cache_key, 120, json.dumps(stats))
        except:
            pass
    
    return jsonify(stats), 200


@admin_bp.route('/dashboard/charts', methods=['GET'])
@jwt_required()
def get_dashboard_charts():
    """Get data for dashboard charts"""
    user = admin_required()
    if not user:
        return jsonify({'error': 'Admin access required'}), 403
    
    # Lot-wise occupancy
    lots = ParkingLot.query.all()
    lot_data = []
    for lot in lots:
        total = lot.spots.count()
        occupied = lot.spots.filter_by(status='O').count()
        lot_data.append({
            'name': lot.prime_location_name,
            'total': total,
            'occupied': occupied,
            'available': total - occupied,
            'occupancy_rate': round((occupied / total * 100) if total > 0 else 0, 2)
        })
    
    # Last 7 days bookings
    bookings_data = []
    for i in range(6, -1, -1):
        date = datetime.utcnow().date() - timedelta(days=i)
        count = Reservation.query.filter(
            func.date(Reservation.parking_timestamp) == date
        ).count()
        bookings_data.append({
            'date': date.isoformat(),
            'bookings': count
        })
    
    # Revenue by lot
    revenue_data = []
    for lot in lots:
        revenue = db.session.query(func.sum(Reservation.parking_cost)).join(
            ParkingSpot
        ).filter(ParkingSpot.lot_id == lot.id).scalar() or 0
        revenue_data.append({
            'name': lot.prime_location_name,
            'revenue': round(revenue, 2)
        })
    
    return jsonify({
        'lot_occupancy': lot_data,
        'daily_bookings': bookings_data,
        'revenue_by_lot': revenue_data
    }), 200

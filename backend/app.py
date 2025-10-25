# Main Flask Application
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from models import db, User
from datetime import datetime
import redis

# Import routes
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.user import user_bp

def create_app(config_class=Config):
    """Application factory function"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    CORS(app)
    jwt = JWTManager(app)
    
    # Initialize Redis for caching
    try:
        redis_client = redis.from_url(app.config['REDIS_URL'])
        redis_client.ping()
        app.redis_client = redis_client
        print("✓ Redis connected successfully")
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")
        app.redis_client = None
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(user_bp, url_prefix='/api/user')
    
    # Create database tables and admin user
    with app.app_context():
        db.create_all()
        create_admin_user(app)
        print("✓ Database initialized successfully")
    
    # Root endpoint
    @app.route('/')
    def index():
        return jsonify({
            'message': 'Vehicle Parking App API',
            'version': '2.0',
            'endpoints': {
                'auth': '/api/auth',
                'admin': '/api/admin',
                'user': '/api/user'
            }
        })
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Resource not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500
    
    return app


def create_admin_user(app):
    """Create default admin user if not exists"""
    admin = User.query.filter_by(username=app.config['ADMIN_USERNAME']).first()
    if not admin:
        admin = User(
            username=app.config['ADMIN_USERNAME'],
            email='admin@parkingapp.com',
            role='admin'
        )
        admin.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(admin)
        db.session.commit()
        print(f"✓ Admin user created: {app.config['ADMIN_USERNAME']}")
    else:
        print(f"✓ Admin user exists: {app.config['ADMIN_USERNAME']}")


if __name__ == '__main__':
    app = create_app()
    print("\n" + "="*50)
    print("🚗 Vehicle Parking App - Backend Server")
    print("="*50)
    print(f"Server running at: http://localhost:5000")
    print(f"Admin username: {app.config['ADMIN_USERNAME']}")
    print(f"Admin password: {app.config['ADMIN_PASSWORD']}")
    print("="*50 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)

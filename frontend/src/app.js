const { createApp } = Vue;

const API_URL = 'http://localhost:5000/api';

createApp({
    data() {
        return {
            isLoggedIn: false,
            currentUser: null,
            accessToken: null,
            
            // Forms
            showLogin: true,
            showRegister: false,
            loginForm: { username: '', password: '' },
            registerForm: { username: '', email: '', password: '' },
            
            // Admin data
            activeTab: 'lots',
            parkingLots: [],
            users: [],
            reservations: [],
            adminStats: [],
            
            // User data
            availableLots: [],
            myReservations: [],
            userStats: {},
            
            // Modals
            showCreateLotModal: false,
            showBookingModal: false,
            showSpotsModal: false,
            editingLot: null,
            lotForm: {
                prime_location_name: '',
                price_per_hour: '',
                address: '',
                pin_code: '',
                number_of_spots: ''
            },
            
            // Spots viewing
            currentViewingLot: null,
            currentSpots: []
        };
    },
    
    created() {
        this.checkAuth();
    },
    
    methods: {
        async apiCall(method, endpoint, data = null) {
            try {
                const config = {
                    method,
                    url: `${API_URL}${endpoint}`,
                    headers: {}
                };
                
                if (this.accessToken) {
                    config.headers['Authorization'] = `Bearer ${this.accessToken}`;
                }
                
                if (data) {
                    config.data = data;
                }
                
                const response = await axios(config);
                return response.data;
            } catch (error) {
                console.error('API Error:', error);
                if (error.response) {
                    alert(error.response.data.error || 'An error occurred');
                }
                throw error;
            }
        },
        
        checkAuth() {
            const token = localStorage.getItem('token');
            const user = localStorage.getItem('user');
            
            if (token && user) {
                this.accessToken = token;
                this.currentUser = JSON.parse(user);
                this.isLoggedIn = true;
                this.loadDashboard();
            }
        },
        
        async login() {
            try {
                const response = await this.apiCall('POST', '/auth/login', this.loginForm);
                this.accessToken = response.access_token;
                this.currentUser = response.user;
                this.isLoggedIn = true;
                
                localStorage.setItem('token', this.accessToken);
                localStorage.setItem('user', JSON.stringify(this.currentUser));
                
                this.loginForm = { username: '', password: '' };
                this.loadDashboard();
            } catch (error) {
                console.error('Login failed:', error);
            }
        },
        
        async register() {
            try {
                await this.apiCall('POST', '/auth/register', this.registerForm);
                alert('Registration successful! Please login.');
                this.showLogin = true;
                this.showRegister = false;
                this.registerForm = { username: '', email: '', password: '' };
            } catch (error) {
                console.error('Registration failed:', error);
            }
        },
        
        logout() {
            this.isLoggedIn = false;
            this.currentUser = null;
            this.accessToken = null;
            localStorage.removeItem('token');
            localStorage.removeItem('user');
        },
        
        async loadDashboard() {
            if (this.currentUser.role === 'admin') {
                await this.loadAdminDashboard();
            } else {
                await this.loadUserDashboard();
            }
        },
        
        async loadAdminDashboard() {
            try {
                const [lots, stats] = await Promise.all([
                    this.apiCall('GET', '/admin/parking-lots'),
                    this.apiCall('GET', '/admin/dashboard/stats')
                ]);
                
                this.parkingLots = lots;
                this.adminStats = [
                    { label: 'Total Lots', value: stats.total_parking_lots },
                    { label: 'Total Spots', value: stats.total_parking_spots },
                    { label: 'Available', value: stats.available_spots },
                    { label: 'Occupied', value: stats.occupied_spots }
                ];
                
                await this.loadUsers();
                await this.loadReservations();
            } catch (error) {
                console.error('Failed to load admin dashboard:', error);
            }
        },
        
        async loadUsers() {
            try {
                this.users = await this.apiCall('GET', '/admin/users');
            } catch (error) {
                console.error('Failed to load users:', error);
            }
        },
        
        async loadReservations() {
            try {
                this.reservations = await this.apiCall('GET', '/admin/reservations');
            } catch (error) {
                console.error('Failed to load reservations:', error);
            }
        },
        
        async loadUserDashboard() {
            try {
                const [stats, reservations, lots] = await Promise.all([
                    this.apiCall('GET', '/user/dashboard/stats'),
                    this.apiCall('GET', '/user/my-reservations'),
                    this.apiCall('GET', '/user/parking-lots/available')
                ]);
                
                this.userStats = stats;
                this.myReservations = reservations;
                this.availableLots = lots;
            } catch (error) {
                console.error('Failed to load user dashboard:', error);
            }
        },
        
        async submitLot() {
            try {
                if (this.editingLot) {
                    await this.apiCall('PUT', `/admin/parking-lots/${this.editingLot.id}`, this.lotForm);
                    alert('Parking lot updated successfully!');
                } else {
                    await this.apiCall('POST', '/admin/parking-lots', this.lotForm);
                    alert('Parking lot created successfully!');
                }
                
                this.closeModal();
                await this.loadAdminDashboard();
            } catch (error) {
                console.error('Failed to submit lot:', error);
            }
        },
        
        editLot(lot) {
            this.editingLot = lot;
            this.lotForm = { ...lot };
        },
        
        async deleteLot(lotId) {
            if (!confirm('Are you sure you want to delete this parking lot?')) {
                return;
            }
            
            try {
                await this.apiCall('DELETE', `/admin/parking-lots/${lotId}`);
                alert('Parking lot deleted successfully!');
                await this.loadAdminDashboard();
            } catch (error) {
                console.error('Failed to delete lot:', error);
            }
        },
        
        async viewSpots(lot) {
            try {
                this.currentViewingLot = lot;
                this.currentSpots = await this.apiCall('GET', `/admin/parking-spots/${lot.id}`);
                this.showSpotsModal = true;
            } catch (error) {
                console.error('Failed to load spots:', error);
            }
        },
        
        async bookSpot(lotId) {
            try {
                await this.apiCall('POST', '/user/book-spot', { lot_id: lotId });
                alert('Parking spot booked successfully!');
                this.showBookingModal = false;
                await this.loadUserDashboard();
            } catch (error) {
                console.error('Failed to book spot:', error);
            }
        },
        
        async releaseSpot(reservationId) {
            if (!confirm('Are you sure you want to release this spot?')) {
                return;
            }
            
            try {
                await this.apiCall('POST', `/user/release-spot/${reservationId}`);
                alert('Spot released successfully!');
                await this.loadUserDashboard();
            } catch (error) {
                console.error('Failed to release spot:', error);
            }
        },
        
        async exportCSV() {
            try {
                window.open(`${API_URL}/user/export-csv/download/${this.currentUser.id}`, '_blank');
            } catch (error) {
                console.error('Failed to export CSV:', error);
            }
        },
        
        closeModal() {
            this.showCreateLotModal = false;
            this.editingLot = null;
            this.lotForm = {
                prime_location_name: '',
                price_per_hour: '',
                address: '',
                pin_code: '',
                number_of_spots: ''
            };
        },
        
        formatDate(dateString) {
            if (!dateString) return 'N/A';
            const date = new Date(dateString);
            return date.toLocaleString();
        }
    }
}).mount('#app');

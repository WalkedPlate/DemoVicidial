from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import json
import pymysql
import threading
from config import Config
from vicidial_api import VicidialAPI
from vicidial_ami import VicidialAMI
from vicidial_realtime import VicidialRealtime

app = Flask(__name__)
app.config.from_object(Config)

# Configurar SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///crm_test.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configurar SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Instancias globales
vicidial_api = VicidialAPI()
vicidial_ami = VicidialAMI()
vicidial_realtime = VicidialRealtime(socketio)

def init_ami():
    """Inicializar conexión AMI"""
    if vicidial_ami.connect():
        print("🎯 AMI conectado en Flask")
        return True
    else:
        print("❌ Error conectando AMI en Flask")
        return False

def init_realtime():
    """Inicializar AMI en tiempo real en hilo separado"""
    def start_realtime():
        if vicidial_realtime.connect_ami():
            print("🚀 AMI Tiempo Real iniciado")
        else:
            print("❌ Error iniciando AMI Tiempo Real")

    # Ejecutar en hilo separado para no bloquear Flask
    thread = threading.Thread(target=start_realtime)
    thread.daemon = True
    thread.start()

# Modelos de base de datos
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)  # Quitamos unique=True

    # Campos Vicidial
    vicidial_user = db.Column(db.String(20), unique=True)
    vicidial_user_pass = db.Column(db.String(20))
    vicidial_phone_login = db.Column(db.String(20))
    vicidial_phone_pass = db.Column(db.String(20))
    vicidial_user_level = db.Column(db.Integer, default=1)
    vicidial_user_group = db.Column(db.String(20), default='ADMIN')
    vicidial_active = db.Column(db.Boolean, default=True)

    # Estados
    agent_status = db.Column(db.String(20), default='LOGOUT')
    is_logged_in_vicidial = db.Column(db.Boolean, default=False)
    current_session_id = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AgentSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_id = db.Column(db.String(50), nullable=False)
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    logout_time = db.Column(db.DateTime)
    campaign = db.Column(db.String(50))
    phone_login = db.Column(db.String(20))
    status = db.Column(db.String(20), default='ACTIVE')

# Rutas
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user = User.query.get(session['user_id'])
    agents = User.query.filter(User.vicidial_user.isnot(None)).all()

    return render_template('dashboard.html', user=user, agents=agents)

@app.route('/agent_panel/<int:user_id>')
def agent_panel(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('agent_panel.html', user=user)

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()

    if user:
        session['user_id'] = user.id
        flash('Login exitoso', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/create_agent', methods=['POST'])
def create_agent():
    try:
        data = request.get_json()

        # Verificar si ya existe el email o usuario Vicidial
        existing_user = User.query.filter(
            (User.email == data['email']) |
            (User.vicidial_user == data['vicidial_user'])
        ).first()

        if existing_user:
            return jsonify({
                'success': False,
                'message': f'Ya existe un usuario con ese email o usuario Vicidial'
            }), 400

        # Crear usuario en la base local
        new_user = User(
            name=data['name'],
            email=data['email'],
            vicidial_user=data['vicidial_user'],
            vicidial_user_pass=data['vicidial_user_pass'],
            vicidial_phone_login=data['vicidial_phone_login'],
            vicidial_phone_pass=data['vicidial_phone_pass'],
            vicidial_user_level=data.get('vicidial_user_level', 1),
            vicidial_user_group=data.get('vicidial_user_group', 'AGENTS')
        )

        db.session.add(new_user)
        db.session.commit()

        # Crear en Vicidial usando la API (usuario y teléfono)
        vicidial_response = vicidial_api.create_agent_complete(data)
        print(f"Respuesta completa de Vicidial: {vicidial_response}")  # Debug

        return jsonify({
            'success': True,
            'message': 'Agente creado exitosamente en base local',
            'user_id': new_user.id,
            'vicidial_response': vicidial_response,
            'debug': f"Respuesta Vicidial: {vicidial_response}"
        })

    except Exception as e:
        db.session.rollback()
        print(f"Error creando agente: {str(e)}")  # Debug
        return jsonify({
            'success': False,
            'message': f'Error al crear agente: {str(e)}'
        }), 500

@app.route('/agent_login', methods=['POST'])
def agent_login():
    try:
        data = request.get_json()
        user_id = data['user_id']
        user = User.query.get(user_id)

        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Login en Vicidial
        response = vicidial_api.agent_login(
            user.vicidial_user,
            user.vicidial_user_pass,
            user.vicidial_phone_login,
            user.vicidial_phone_pass,
            data.get('campaign')
        )

        if response and 'SUCCESS' in response:
            # Actualizar estado local
            user.is_logged_in_vicidial = True
            user.agent_status = 'READY'

            # Crear sesión
            session_record = AgentSession(
                user_id=user.id,
                session_id=f"session_{user.id}_{datetime.now().timestamp()}",
                campaign=data.get('campaign'),
                phone_login=user.vicidial_phone_login
            )

            db.session.add(session_record)
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Login exitoso en Vicidial',
                'response': response
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Error en login de Vicidial',
                'response': response
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@app.route('/agent_logout', methods=['POST'])
def agent_logout():
    try:
        data = request.get_json()
        user_id = data['user_id']
        user = User.query.get(user_id)

        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Logout en Vicidial
        response = vicidial_api.agent_logout(user.vicidial_user)

        # Actualizar estado local
        user.is_logged_in_vicidial = False
        user.agent_status = 'LOGOUT'

        # Cerrar sesión activa
        active_session = AgentSession.query.filter_by(
            user_id=user.id,
            status='ACTIVE'
        ).first()

        if active_session:
            active_session.logout_time = datetime.utcnow()
            active_session.status = 'CLOSED'

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Logout exitoso',
            'response': response
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@app.route('/get_agent_status/<int:user_id>')
def get_agent_status(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Obtener estado desde Vicidial
        vicidial_status = vicidial_api.get_agent_status(user.vicidial_user)

        return jsonify({
            'success': True,
            'local_status': {
                'agent_status': user.agent_status,
                'is_logged_in': user.is_logged_in_vicidial
            },
            'vicidial_status': vicidial_status
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/test_vicidial_connection')
def test_vicidial_connection():
    """Probar conexión con Vicidial"""
    try:
        # Probar obtener campañas
        campaigns = vicidial_api.get_campaigns()

        return jsonify({
            'success': True,
            'message': 'Conexión exitosa con Vicidial',
            'campaigns': campaigns
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error de conexión: {str(e)}'
        })

# Crear tablas al iniciar
def create_tables():
    with app.app_context():
        db.create_all()

        # Crear usuario de prueba si no existe
        if not User.query.first():
            test_user = User(
                name='Usuario Prueba',
                email='test@example.com'
            )
            db.session.add(test_user)
            db.session.commit()
            print("Usuario de prueba creado: test@example.com")

@app.route('/ami_agent_login', methods=['POST'])
def ami_agent_login():
    try:
        data = request.get_json()
        user_id = data['user_id']
        user = User.query.get(user_id)

        if not user or not user.vicidial_phone_login:
            return jsonify({'success': False, 'message': 'Usuario no encontrado o sin extensión'})

        # Login via AMI (función básica)
        response = vicidial_ami.agent_login_basic(
            user.vicidial_user,
            user.vicidial_phone_login
        )

        if response:
            # Actualizar estado local
            user.is_logged_in_vicidial = True
            user.agent_status = 'READY'
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Login exitoso via AMI',
                'response': str(response)
            })
        else:
            return jsonify({'success': False, 'message': 'Error en AMI login'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/ami_agent_logout', methods=['POST'])
def ami_agent_logout():
    try:
        data = request.get_json()
        user_id = data['user_id']
        user = User.query.get(user_id)

        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Logout via AMI
        response = vicidial_ami.agent_logout(
            user.vicidial_user,
            user.vicidial_phone_login,
            'DEMOIN'
        )

        # Actualizar estado local
        user.is_logged_in_vicidial = False
        user.agent_status = 'LOGOUT'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Logout exitoso via AMI',
            'response': str(response)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/ami_pause_agent', methods=['POST'])
def ami_pause_agent():
    try:
        data = request.get_json()
        user_id = data['user_id']
        reason = data.get('reason', 'Break')

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Pausar via AMI
        response = vicidial_ami.pause_agent(user.vicidial_phone_login, 'DEMOIN', reason)

        # Actualizar estado local
        user.agent_status = 'PAUSED'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Agente pausado: {reason}',
            'response': str(response)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/ami_unpause_agent', methods=['POST'])
def ami_unpause_agent():
    try:
        data = request.get_json()
        user_id = data['user_id']

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'Usuario no encontrado'})

        # Despausar via AMI
        response = vicidial_ami.unpause_agent(user.vicidial_phone_login, 'DEMOIN')

        # Actualizar estado local
        user.agent_status = 'READY'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Agente listo para recibir llamadas',
            'response': str(response)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/ami_queue_status')
def ami_queue_status():
    try:
        response = vicidial_ami.get_queue_status('DEMOIN')
        return jsonify({
            'success': True,
            'queue_status': str(response)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/test_ami_connection')
def test_ami_connection():
    try:
        if not vicidial_ami.connected:
            if not init_ami():
                return jsonify({'success': False, 'message': 'No se pudo conectar a AMI'})

        # Test con estado de cola
        response = vicidial_ami.get_queue_status('DEMOIN')

        return jsonify({
            'success': True,
            'message': 'AMI funcionando correctamente',
            'response': str(response)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error AMI: {str(e)}'})

@app.route('/debug_queues')
def debug_queues():
    try:
        response = vicidial_ami.show_queues()
        return jsonify({
            'success': True,
            'queues': str(response)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/debug_sip_peer/<extension>')
def debug_sip_peer(extension):
    try:
        # Actualizar la función para usar la extensión pasada
        response = vicidial_ami.manager.send_action({
            'Action': 'SIPshowpeer',
            'Peer': extension
        })
        return jsonify({
            'success': True,
            'sip_peer': str(response)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/agent_view/<int:agent_id>')
def agent_view(agent_id):
    user = User.query.get_or_404(agent_id)
    return render_template('agent_view.html', agent=user)

@app.route('/agent_calls/<int:agent_id>')
def agent_calls(agent_id):
    try:
        user = User.query.get_or_404(agent_id)

        # Conectar a BD Vicidial para obtener llamadas
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Obtener llamadas del agente
            cursor.execute("""
                SELECT uniqueid, lead_id, status, campaign_id, phone_number, start_time
                FROM vicidial_auto_calls 
                WHERE agent_user = %s 
                AND status IN ('LIVE', 'QUEUE', 'INCALL', 'RING')
                ORDER BY start_time DESC
                LIMIT 1
            """, (user.vicidial_user,))

            call_data = cursor.fetchone()
            calls = []

            if call_data:
                # Obtener información del cliente
                cursor.execute("""
                    SELECT first_name, last_name, city, state, address1
                    FROM vicidial_list 
                    WHERE lead_id = %s
                """, (call_data[1],))

                customer_data = cursor.fetchone()

                call = {
                    'uniqueid': call_data[0],
                    'lead_id': call_data[1],
                    'status': call_data[2],
                    'campaign_id': call_data[3],
                    'phone_number': call_data[4],
                    'start_time': call_data[5].strftime('%Y-%m-%d %H:%M:%S') if call_data[5] else None,
                    'first_name': customer_data[0] if customer_data else '',
                    'last_name': customer_data[1] if customer_data else '',
                    'city': customer_data[2] if customer_data else '',
                    'state': customer_data[3] if customer_data else '',
                    'address1': customer_data[4] if customer_data else ''
                }
                calls.append(call)

            # Obtener estado del agente
            cursor.execute("""
                SELECT status FROM vicidial_live_agents 
                WHERE user = %s
            """, (user.vicidial_user,))

            agent_status_result = cursor.fetchone()
            agent_status = agent_status_result[0] if agent_status_result else 'LOGOUT'

        connection.close()

        return jsonify({
            'success': True,
            'calls': calls,
            'agent_status': agent_status
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/agent_pause', methods=['POST'])
def agent_pause():
    try:
        data = request.get_json()
        # En desarrollo: actualizar estado en BD
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/agent_unpause', methods=['POST'])
def agent_unpause():
    try:
        data = request.get_json()
        # En desarrollo: actualizar estado en BD
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/vicidial_agent_login', methods=['POST'])
def vicidial_agent_login():
    """Login completo del agente en Vicidial usando la base de datos directamente"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        user = User.query.get_or_404(agent_id)

        # Conectar a BD Vicidial
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # 1. Verificar si el agente ya está logueado
            cursor.execute("""
                SELECT user FROM vicidial_live_agents 
                WHERE user = %s
            """, (user.vicidial_user,))

            if cursor.fetchone():
                return jsonify({
                    'success': False,
                    'message': 'Agente ya está logueado'
                })

            # 2. Insertar agente en vicidial_live_agents
            cursor.execute("""
                INSERT INTO vicidial_live_agents 
                (user, server_ip, conf_exten, status, lead_id, campaign_id,
                 uniqueid, callerid, channel, random_id, last_call_time,
                 last_call_finish, closer_campaigns, call_server_ip,
                 user_level, comments, calls_today, pause_code,
                 last_state_change, agent_log_id)
                VALUES 
                (%s, '195.26.249.9', %s, 'READY', 0, 'DEMOIN', 
                 '', '', '', FLOOR(RAND() * 10000000000), NOW(), 
                 NOW(), '', '195.26.249.9', 
                 %s, '', 0, '', 
                 NOW(), 0)
            """, (
                user.vicidial_user,
                user.vicidial_phone_login,
                user.vicidial_user_level or 1
            ))

            # 3. Registrar en vicidial_agent_log
            cursor.execute("""
                INSERT INTO vicidial_agent_log 
                (user, server_ip, event_time, campaign_id, pause_epoch,
                 pause_sec, wait_epoch, wait_sec, talk_epoch, talk_sec,
                 dispo_epoch, dispo_sec, status, lead_id, phone_number,
                 user_group, comments, sub_status)
                VALUES 
                (%s, '195.26.249.9', NOW(), 'DEMOIN', 0,
                 0, 0, 0, 0, 0,
                 0, 0, 'LOGIN', 0, '',
                 %s, 'CRM LOGIN', '')
            """, (
                user.vicidial_user,
                user.vicidial_user_group or 'ADMIN'
            ))

            connection.commit()

        connection.close()

        # 4. Actualizar estado local
        user.is_logged_in_vicidial = True
        user.agent_status = 'READY'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Agente {user.vicidial_user} logueado en DEMOIN como READY'
        })

    except Exception as e:
        print(f"Error en vicidial_agent_login: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/vicidial_agent_logout', methods=['POST'])
def vicidial_agent_logout():
    """Logout completo del agente de Vicidial"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        user = User.query.get_or_404(agent_id)

        # Conectar a BD Vicidial
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # 1. Eliminar de vicidial_live_agents
            cursor.execute("""
                DELETE FROM vicidial_live_agents 
                WHERE user = %s
            """, (user.vicidial_user,))

            # 2. Registrar logout en vicidial_agent_log
            cursor.execute("""
                INSERT INTO vicidial_agent_log 
                (user, server_ip, event_time, campaign_id, pause_epoch, 
                 pause_sec, wait_epoch, wait_sec, talk_epoch, talk_sec, 
                 dispo_epoch, dispo_sec, status, lead_id, phone_number, 
                 user_group, comments, sub_status)
                VALUES 
                (%s, '195.26.249.9', NOW(), 'DEMOIN', 0,
                 0, 0, 0, 0, 0,
                 0, 0, 'LOGOUT', 0, '',
                 %s, 'CRM LOGOUT', '')
            """, (
                user.vicidial_user,
                user.vicidial_user_group or 'ADMIN'
            ))

            connection.commit()

        connection.close()

        # 3. Actualizar estado local
        user.is_logged_in_vicidial = False
        user.agent_status = 'LOGOUT'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Agente {user.vicidial_user} deslogueado exitosamente'
        })

    except Exception as e:
        print(f"Error en vicidial_agent_logout: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/vicidial_agent_pause', methods=['POST'])
def vicidial_agent_pause():
    """Pausar agente en Vicidial"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        reason = data.get('reason', 'BREAK')
        user = User.query.get_or_404(agent_id)

        # Conectar a BD Vicidial
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Actualizar estado a PAUSED
            cursor.execute("""
                UPDATE vicidial_live_agents 
                SET status = 'PAUSED', pause_code = %s, last_state_change = NOW()
                WHERE user = %s
            """, (reason, user.vicidial_user))

            connection.commit()

        connection.close()

        # Actualizar estado local
        user.agent_status = 'PAUSED'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Agente pausado: {reason}'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/vicidial_agent_unpause', methods=['POST'])
def vicidial_agent_unpause():
    """Despausar agente en Vicidial"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        user = User.query.get_or_404(agent_id)

        # Conectar a BD Vicidial
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Actualizar estado a READY
            cursor.execute("""
                UPDATE vicidial_live_agents 
                SET status = 'READY', pause_code = '', last_state_change = NOW()
                WHERE user = %s
            """, (user.vicidial_user,))

            connection.commit()

        connection.close()

        # Actualizar estado local
        user.agent_status = 'READY'
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Agente listo para recibir llamadas'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/start_recording', methods=['POST'])
def start_recording():
    try:
        data = request.get_json()
        channel = data['channel']
        agent_id = data.get('agent_id', 'unknown')

        # Crear nombre único para grabación
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"manual_{agent_id}_{timestamp}"

        result = vicidial_realtime.start_recording(channel, filename)

        # Enviar evento WebSocket
        socketio.emit('recording_started', {
            'channel': channel,
            'filename': filename,
            'result': result
        })

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/stop_recording', methods=['POST'])
def stop_recording():
    try:
        data = request.get_json()
        channel = data['channel']

        result = vicidial_realtime.stop_recording(channel)

        # Enviar evento WebSocket
        socketio.emit('recording_stopped', {
            'channel': channel,
            'result': result
        })

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/transfer_call', methods=['POST'])
def transfer_call():
    try:
        data = request.get_json()
        channel = data['channel']
        target_extension = data['target_extension']

        result = vicidial_realtime.transfer_call(channel, target_extension)

        # Enviar evento WebSocket
        socketio.emit('call_transferred', {
            'channel': channel,
            'target': target_extension,
            'result': result
        })

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/hangup_call', methods=['POST'])
def hangup_call():
    try:
        data = request.get_json()
        channel = data['channel']

        result = vicidial_realtime.hangup_call(channel)

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

# Eventos WebSocket
@socketio.on('connect')
def on_connect():
    print(f"🔌 Cliente WebSocket conectado")

@socketio.on('disconnect')
def on_disconnect():
    print(f"🔌 Cliente WebSocket desconectado")

@socketio.on('join_agent')
def on_join_agent(data):
    """Agente se une a su sala específica para recibir eventos"""
    extension = data['extension']
    join_room(f'agent_{extension}')
    emit('joined', {'room': f'agent_{extension}'})
    print(f"👤 Agente {extension} se unió a su sala")

@socketio.on('leave_agent')
def on_leave_agent(data):
    """Agente sale de su sala"""
    extension = data['extension']
    leave_room(f'agent_{extension}')
    print(f"👤 Agente {extension} salió de su sala")

if __name__ == '__main__':
    create_tables()  # Llamar aquí
    init_ami()  # Inicializar AMI
    init_realtime()  # Inicializar AMI tiempo real
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
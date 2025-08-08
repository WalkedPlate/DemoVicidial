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

@app.route('/agent_view/<int:agent_id>')
def agent_view(agent_id):
    user = User.query.get_or_404(agent_id)
    return render_template('agent_view.html', agent=user)

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
               SELECT vac.uniqueid,
                      vac.lead_id,
                      vac.status,
                      vac.campaign_id,
                      vl.phone_number,
                      vac.start_time
               FROM vicidial_auto_calls vac
                        LEFT JOIN vicidial_list vl ON vac.lead_id = vl.lead_id
               WHERE vac.agent_user = %s
                 AND vac.status IN ('LIVE', 'QUEUE', 'INCALL', 'RING')
               ORDER BY vac.start_time DESC LIMIT 1
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
    """Login completo del agente en Vicidial con MeetMe automático"""
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
            # 1. Eliminar agente si ya existe (limpieza)
            cursor.execute("""
                           DELETE
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            # 2. Asignar sala MeetMe disponible
            meetme_room = assign_meetme_room(user.vicidial_user)

            # 3. Insertar agente en vicidial_live_agents CON estado READY
            cursor.execute("""
                           INSERT INTO vicidial_live_agents
                           (user, server_ip, conf_exten, status, lead_id, campaign_id,
                            uniqueid, callerid, channel, random_id, last_call_time,
                            last_call_finish, closer_campaigns, call_server_ip,
                            user_level, comments, calls_today, pause_code,
                            last_state_change, agent_log_id)
                           VALUES (%s, '195.26.249.9', %s, 'READY', 0, 'DEMOIN',
                                   '', '', '', FLOOR(RAND() * 10000000000), NOW(),
                                   NOW(), %s, '195.26.249.9',
                                   %s, %s, 0, '',
                                   NOW(), 0)
                           """, (
                               user.vicidial_user,
                               str(meetme_room),
                               ' colain ',  # IMPORTANTE: closer_campaigns con colain
                               user.vicidial_user_level or 1,
                               f'CRM AUTO LOGIN MeetMe {meetme_room}'
                           ))

            # 4. Registrar en vicidial_agent_log
            cursor.execute("""
                           INSERT INTO vicidial_agent_log
                           (user, server_ip, event_time, campaign_id, pause_epoch,
                            pause_sec, wait_epoch, wait_sec, talk_epoch, talk_sec,
                            dispo_epoch, dispo_sec, status, lead_id,
                            user_group, comments, sub_status)
                           VALUES (%s, '195.26.249.9', NOW(), 'DEMOIN', 0,
                                   0, 0, 0, 0, 0,
                                   0, 0, 'LOGIN', 0,
                                   %s, %s, '')
                           """, (
                               user.vicidial_user,
                               user.vicidial_user_group or 'ADMIN',
                               f'CRM AUTO LOGIN MeetMe {meetme_room}'
                           ))

            connection.commit()

        connection.close()

        # 5. Configurar agente para inbound calls
        setup_agent_for_inbound(user.vicidial_user)

        # 6. Conectar MicroSIP automáticamente a sala MeetMe
        connect_result = connect_agent_to_meetme(user.vicidial_phone_login, meetme_room)

        # 7. Actualizar estado local
        user.is_logged_in_vicidial = True
        user.agent_status = 'READY'
        db.session.commit()

        # 8. Verificar que quedó en READY (doble check)
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT status
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            final_status = cursor.fetchone()
            actual_status = final_status[0] if final_status else 'NOT_FOUND'

        connection.close()

        print(f"🎉 Login completo: {user.vicidial_user} → MeetMe {meetme_room} → Estado: {actual_status}")

        return jsonify({
            'success': True,
            'message': f'Agente {user.vicidial_user} logueado → MeetMe {meetme_room} → {actual_status}',
            'meetme_room': meetme_room,
            'final_status': actual_status,
            'ready_for_calls': actual_status == 'READY'
        })

    except Exception as e:
        print(f"Error en vicidial_agent_login: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })


def setup_agent_for_inbound(agent_user):
    """Configurar agente para recibir llamadas inbound de colain"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # 1. Verificar si el usuario existe en vicidial_users
            cursor.execute("""
                           SELECT user, closer_campaigns
                           FROM vicidial_users
                           WHERE user = %s
                           """, (agent_user,))

            user_data = cursor.fetchone()

            if user_data:
                current_campaigns = user_data[1] or ''

                # 2. Agregar 'colain' si no está en closer_campaigns
                if 'colain' not in current_campaigns:
                    new_campaigns = f'{current_campaigns} colain '.strip()

                    cursor.execute("""
                                   UPDATE vicidial_users
                                   SET closer_campaigns = %s,
                                       user_level       = 8
                                   WHERE user = %s
                                   """, (f' {new_campaigns} ', agent_user))

                    print(f"✅ Usuario {agent_user} configurado con closer_campaigns: {new_campaigns}")
                else:
                    print(f"✅ Usuario {agent_user} ya tiene 'colain' en closer_campaigns")

            else:
                print(f"⚠️ Usuario {agent_user} no existe en vicidial_users")

            # 3. Verificar/crear entrada en vicidial_user_groups si no existe
            cursor.execute("""
                           SELECT user_group
                           FROM vicidial_user_groups
                           WHERE user_group = 'ADMIN'
                           """)

            if not cursor.fetchone():
                cursor.execute("""
                               INSERT INTO vicidial_user_groups
                                   (user_group, group_name, allowed_campaigns, closer_campaigns)
                               VALUES ('ADMIN', 'Administrators', 'DEMOIN', ' colain ')
                               """)
                print("✅ Grupo ADMIN configurado con colain")

            connection.commit()
        connection.close()

        return True

    except Exception as e:
        print(f"❌ Error configurando agente para inbound: {e}")
        return False

@app.route('/vicidial_agent_logout', methods=['POST'])
def vicidial_agent_logout():
    """Logout completo del agente de Vicidial y MeetMe"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        user = User.query.get_or_404(agent_id)

        # Obtener sala MeetMe antes de eliminar
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        meetme_room = None
        with connection.cursor() as cursor:
            # Obtener sala MeetMe actual
            cursor.execute("""
                           SELECT conf_exten
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            result = cursor.fetchone()
            if result:
                meetme_room = result[0]

            # 1. Eliminar de vicidial_live_agents
            cursor.execute("""
                           DELETE
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            # 2. Registrar logout en vicidial_agent_log
            cursor.execute("""
                           INSERT INTO vicidial_agent_log
                           (user, server_ip, event_time, campaign_id, pause_epoch,
                            pause_sec, wait_epoch, wait_sec, talk_epoch, talk_sec,
                            dispo_epoch, dispo_sec, status, lead_id,
                            user_group, comments, sub_status)
                           VALUES (%s, '195.26.249.9', NOW(), 'DEMOIN', 0,
                                   0, 0, 0, 0, 0,
                                   0, 0, 'LOGOUT', 0,
                                   %s, %s, '')
                           """, (
                               user.vicidial_user,
                               user.vicidial_user_group or 'ADMIN',
                               f'CRM LOGOUT MeetMe {meetme_room}' if meetme_room else 'CRM LOGOUT'
                           ))

            connection.commit()

        connection.close()

        # 3. Desconectar de MeetMe
        if meetme_room:
            disconnect_agent_from_meetme(user.vicidial_phone_login, meetme_room)
            print(f"🔌 Agente {user.vicidial_user} desconectado de MeetMe {meetme_room}")

        # 4. Actualizar estado local
        user.is_logged_in_vicidial = False
        user.agent_status = 'LOGOUT'
        db.session.commit()

        print(f"👋 Logout completo: {user.vicidial_user}")

        return jsonify({
            'success': True,
            'message': f'Agente {user.vicidial_user} deslogueado de MeetMe {meetme_room}'
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


# NUEVAS RUTAS AGREGADAS PARA EL PANEL DE AGENTE MEJORADO

@app.route('/simulate_call/<int:agent_id>')
def simulate_call(agent_id):
    """Simular llamada para pruebas"""
    try:
        user = User.query.get_or_404(agent_id)

        fake_call = {
            'caller_id': '+51987654321',
            'phone_number': '+51987654321',
            'first_name': 'Cliente',
            'last_name': 'Prueba',
            'city': 'Lima',
            'state': 'Lima',
            'lead_id': '99999',
            'campaign_id': 'DEMOIN',
            'channel': f'SIP/{user.vicidial_phone_login}-00000001'
        }

        socketio.emit('incoming_call', fake_call, room=f'agent_{user.vicidial_phone_login}')

        return jsonify({
            'success': True,
            'message': 'Llamada simulada enviada',
            'call_data': fake_call
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })


@app.route('/get_agent_complete_status/<int:agent_id>')
def get_agent_complete_status(agent_id):
    """Estado completo del agente"""
    try:
        user = User.query.get_or_404(agent_id)

        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Estado del agente
            cursor.execute("""
                           SELECT status, campaign_id, calls_today, pause_code, last_state_change
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            agent_data = cursor.fetchone()

            # Llamadas del día
            cursor.execute("""
                           SELECT COUNT(*), COALESCE(SUM(length_in_sec), 0)
                           FROM vicidial_call_log
                           WHERE user = %s
                             AND start_time >= CURDATE()
                           """, (user.vicidial_user,))

            call_stats = cursor.fetchone()

        connection.close()

        return jsonify({
            'success': True,
            'agent_status': agent_data[0] if agent_data else 'LOGOUT',
            'campaign': agent_data[1] if agent_data else None,
            'calls_today': call_stats[0] if call_stats else 0,
            'talk_time_seconds': call_stats[1] if call_stats else 0,
            'logged_in': agent_data is not None,
            'last_change': agent_data[4].isoformat() if agent_data and agent_data[4] else None
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/force_microsip_config', methods=['POST'])
def force_microsip_config():
    """Configurar MicroSIP automáticamente (simulado)"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']
        user = User.query.get_or_404(agent_id)

        # Configuración SIP que enviarías a MicroSIP
        sip_config = {
            'server': '195.26.249.9',
            'username': user.vicidial_phone_login,
            'password': user.vicidial_phone_pass,
            'display_name': user.name
        }

        # Aquí normalmente escribirías archivo de config o usarías API de MicroSIP
        # Por ahora solo simulamos

        return jsonify({
            'success': True,
            'message': 'MicroSIP configurado automáticamente',
            'config': sip_config
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/sync_agent_status', methods=['POST'])
def sync_agent_status():
    """Sincronizar estado entre sistemas"""
    try:
        data = request.get_json()
        agent_id = data['agent_id']

        user = User.query.get_or_404(agent_id)

        # Obtener estado real de Vicidial
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT status
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            result = cursor.fetchone()

            if result:
                vicidial_status = result[0]
                user.is_logged_in_vicidial = True
                user.agent_status = vicidial_status
            else:
                user.is_logged_in_vicidial = False
                user.agent_status = 'LOGOUT'

            db.session.commit()

        connection.close()

        return jsonify({
            'success': True,
            'message': 'Estado sincronizado',
            'local_status': user.agent_status,
            'vicidial_status': vicidial_status if result else 'LOGOUT'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })


@app.route('/simulate_meetme_call/<int:agent_id>')
def simulate_meetme_call(agent_id):
    """Simular llamada que va directo a MeetMe del agente"""
    try:
        user = User.query.get_or_404(agent_id)

        result = simulate_incoming_call_to_meetme(
            user.vicidial_user,
            "+51987654321"
        )

        if result:
            # Notificar via WebSocket que hay llamada en MeetMe
            socketio.emit('meetme_call_connected', {
                'agent_user': user.vicidial_user,
                'caller_number': '+51987654321',
                'message': 'Llamada conectada directamente a MeetMe'
            }, room=f'agent_{user.vicidial_phone_login}')

            return jsonify({
                'success': True,
                'message': 'Llamada simulada conectada a MeetMe del agente'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Error simulando llamada a MeetMe'
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })


@app.route('/debug_inbound_config/<int:agent_id>')
def debug_inbound_config(agent_id):
    """Debug configuración inbound del agente"""
    try:
        user = User.query.get_or_404(agent_id)

        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        debug_info = {}

        with connection.cursor() as cursor:
            # 1. Estado en vicidial_live_agents (CORREGIDO)
            cursor.execute("""
                           SELECT campaign_id, closer_campaigns, status, conf_exten
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            live_agent = cursor.fetchone()
            debug_info['live_agent'] = {
                'campaign_id': live_agent[0] if live_agent else None,
                'closer_campaigns': live_agent[1] if live_agent else None,
                'status': live_agent[2] if live_agent else None,
                'conf_exten': live_agent[3] if live_agent else None
            }

            # 2. Configuración en vicidial_users (CORREGIDO)
            cursor.execute("""
                           SELECT user_level, user_group, closer_campaigns
                           FROM vicidial_users
                           WHERE user = %s
                           """, (user.vicidial_user,))

            user_config = cursor.fetchone()
            debug_info['user_config'] = {
                'user_level': user_config[0] if user_config else None,
                'user_group': user_config[1] if user_config else None,
                'closer_campaigns': user_config[2] if user_config else None
            }

            # 3. Configuración del grupo inbound
            cursor.execute("""
                           SELECT group_id, group_name, active
                           FROM vicidial_inbound_groups
                           WHERE group_id = 'colain'
                           """)

            inbound_group = cursor.fetchone()
            debug_info['inbound_group'] = {
                'group_id': inbound_group[0] if inbound_group else None,
                'group_name': inbound_group[1] if inbound_group else None,
                'active': inbound_group[2] if inbound_group else None
            }

        connection.close()

        # Análisis
        can_receive = False
        if live_agent:
            can_receive = (
                    live_agent[0] == 'DEMOIN' and  # campaign_id
                    live_agent[1] and  # closer_campaigns exists
                    'colain' in live_agent[1] and  # has colain
                    live_agent[2] == 'READY'  # status is READY
            )

        return jsonify({
            'success': True,
            'agent_user': user.vicidial_user,
            'debug_info': debug_info,
            'analysis': {
                'can_receive_calls': can_receive,
                'logged_in': live_agent is not None,
                'has_colain': live_agent and live_agent[1] and 'colain' in live_agent[1],
                'status_ready': live_agent and live_agent[2] == 'READY'
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/debug_inbound_calls')
def debug_inbound_calls():
    """Ver llamadas entrantes en tiempo real"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Llamadas en cola DEMOIN
            cursor.execute("""
                           SELECT uniqueid, lead_id, phone_number, status, start_time, agent_user
                           FROM vicidial_auto_calls
                           WHERE status IN ('LIVE', 'QUEUE', 'INCALL', 'RING')
                           ORDER BY start_time DESC LIMIT 10
                           """)

            active_calls = cursor.fetchall()

            # Agentes activos
            cursor.execute("""
                           SELECT user, status, campaign_id, closer_campaigns, conf_exten
                           FROM vicidial_live_agents
                           ORDER BY last_state_change DESC
                           """)

            agents = cursor.fetchall()

        connection.close()

        return jsonify({
            'success': True,
            'active_calls': active_calls,
            'agents': agents,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/debug_did_routing')
def debug_did_routing():
    """Debug del enrutamiento DID"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # DIDs configurados
            cursor.execute("""
                           SELECT did_pattern, did_route, group_id, extension, active
                           FROM vicidial_inbound_dids
                           WHERE did_pattern IN ('5114125924', 'default')
                           """)

            dids = cursor.fetchall()

            # Grupo inbound colain
            cursor.execute("""
                           SELECT *
                           FROM vicidial_inbound_groups
                           WHERE group_id = 'colain'
                           """)

            inbound_group = cursor.fetchone()

        connection.close()

        return jsonify({
            'success': True,
            'dids': dids,
            'inbound_group': inbound_group
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/monitor_real_calls')
def monitor_real_calls():
    """Monitorear llamadas reales que entran al sistema"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Llamadas de los últimos 5 minutos
            cursor.execute("""
                           SELECT vac.uniqueid,
                                  vac.lead_id,
                                  vac.phone_number,
                                  vac.status,
                                  vac.start_time,
                                  vac.agent_user,
                                  vac.campaign_id,
                                  vl.first_name,
                                  vl.last_name,
                                  vl.city,
                                  vl.state
                           FROM vicidial_auto_calls vac
                                    LEFT JOIN vicidial_list vl ON vac.lead_id = vl.lead_id
                           WHERE vac.start_time >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
                             AND vac.phone_number != '5551234567'  -- Filtrar llamadas de setup
                           ORDER BY vac.start_time DESC
                               LIMIT 20
                           """)

            recent_calls = cursor.fetchall()

            # Logs del sistema de los últimos minutos
            cursor.execute("""
                           SELECT event_time, user, status, comments
                           FROM vicidial_agent_log
                           WHERE event_time >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                           ORDER BY event_time DESC LIMIT 10
                           """)

            recent_logs = cursor.fetchall()

        connection.close()

        # Convertir datetime a string
        calls_data = []
        for call in recent_calls:
            call_dict = {
                'uniqueid': call[0],
                'lead_id': call[1],
                'phone_number': call[2],
                'status': call[3],
                'start_time': call[4].strftime('%Y-%m-%d %H:%M:%S') if call[4] else None,
                'agent_user': call[5],
                'campaign_id': call[6],
                'first_name': call[7],
                'last_name': call[8],
                'city': call[9],
                'state': call[10]
            }
            calls_data.append(call_dict)

        logs_data = []
        for log in recent_logs:
            log_dict = {
                'event_time': log[0].strftime('%Y-%m-%d %H:%M:%S') if log[0] else None,
                'user': log[1],
                'status': log[2],
                'comments': log[3]
            }
            logs_data.append(log_dict)

        return jsonify({
            'success': True,
            'recent_calls': calls_data,
            'recent_logs': logs_data,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/debug_call_assignment')
def debug_call_assignment():
    """Debug específico para asignación de llamadas"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # 1. Llamadas recientes del número que llamó
            cursor.execute("""
                           SELECT uniqueid,
                                  lead_id,
                                  phone_number,
                                  status,
                                  start_time,
                                  agent_user,
                                  campaign_id,
                                  queue_priority,
                                  call_type
                           FROM vicidial_auto_calls
                           WHERE phone_number = '928086980'
                             AND start_time >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                           ORDER BY start_time DESC LIMIT 5
                           """)

            caller_calls = cursor.fetchall()

            # 2. Estado actual de agentes para colain
            cursor.execute("""
                           SELECT user, status, campaign_id, closer_campaigns, conf_exten, last_state_change
                           FROM vicidial_live_agents
                           WHERE closer_campaigns LIKE '%colain%'
                              OR campaign_id = 'DEMOIN'
                           ORDER BY last_state_change DESC
                           """)

            available_agents = cursor.fetchall()

            # 3. Logs del AGI para el número
            cursor.execute("""
                           SELECT event_time, user, lead_id, campaign_id, status, phone_number, comments
                           FROM vicidial_log
                           WHERE phone_number = '928086980'
                             AND event_time >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
                           ORDER BY event_time DESC LIMIT 10
                           """)

            agi_logs = cursor.fetchall()

            # 4. Verificar configuración del grupo colain
            cursor.execute("""
                           SELECT group_id,
                                  group_name,
                                  active,
                                  campaign_id,
                                  agent_search_method,
                                  call_time_id,
                                  get_call_launch
                           FROM vicidial_inbound_groups
                           WHERE group_id = 'colain'
                           """)

            group_config = cursor.fetchone()

        connection.close()

        return jsonify({
            'success': True,
            'caller_calls': caller_calls,
            'available_agents': available_agents,
            'agi_logs': agi_logs,
            'group_config': group_config,
            'analysis': {
                'calls_created': len(caller_calls),
                'agents_ready': len([a for a in available_agents if a[1] == 'READY']),
                'agi_activity': len(agi_logs)
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/force_call_to_agent/<phone_number>/<int:agent_id>')
def force_call_to_agent(phone_number, agent_id):
    """Forzar asignación de llamada a agente específico"""
    try:
        user = User.query.get_or_404(agent_id)

        # Obtener sala MeetMe del agente
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Obtener conferencia del agente
            cursor.execute("""
                           SELECT conf_exten
                           FROM vicidial_live_agents
                           WHERE user = %s
                             AND status = 'READY'
                           """, (user.vicidial_user,))

            result = cursor.fetchone()
            if not result:
                return jsonify({
                    'success': False,
                    'message': 'Agente no está READY o no encontrado'
                })

            meetme_room = result[0]

            # Buscar llamada activa del número
            cursor.execute("""
                           SELECT uniqueid, lead_id
                           FROM vicidial_auto_calls
                           WHERE phone_number = %s
                             AND status IN ('LIVE', 'QUEUE', 'RING')
                           ORDER BY start_time DESC LIMIT 1
                           """, (phone_number,))

            call_data = cursor.fetchone()

            if call_data:
                # Actualizar llamada para asignarla al agente
                cursor.execute("""
                               UPDATE vicidial_auto_calls
                               SET agent_user = %s,
                                   status     = 'LIVE'
                               WHERE uniqueid = %s
                               """, (user.vicidial_user, call_data[0]))

                connection.commit()

                print(f"🎯 Llamada {phone_number} asignada a {user.vicidial_user}")

            # Crear llamada simulada en MeetMe
            if vicidial_ami.connected:
                # Originar llamada que conecte el número a la sala del agente
                connect_response = vicidial_ami.manager.send_action({
                    'Action': 'Originate',
                    'Channel': f'Local/{phone_number}@default',  # Canal del cliente
                    'Application': 'MeetMe',
                    'Data': f'{meetme_room},q',  # Conectar a sala del agente (modo quiet)
                    'CallerID': f'{phone_number}',
                    'Async': 'true',
                    'Timeout': '30000'
                })

                print(f"📞 Conectando {phone_number} a MeetMe {meetme_room}: {connect_response}")

        connection.close()

        # Notificar al agente vía WebSocket
        socketio.emit('real_call_connected', {
            'phone_number': phone_number,
            'meetme_room': meetme_room,
            'agent_user': user.vicidial_user,
            'message': f'Llamada {phone_number} conectada a MeetMe'
        }, room=f'agent_{user.vicidial_phone_login}')

        return jsonify({
            'success': True,
            'message': f'Llamada {phone_number} forzada a agente {user.vicidial_user}',
            'meetme_room': meetme_room
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/fix_inbound_group')
def fix_inbound_group():
    """Verificar y corregir configuración del grupo colain"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Verificar configuración actual
            cursor.execute("""
                           SELECT *
                           FROM vicidial_inbound_groups
                           WHERE group_id = 'colain'
                           """)

            current_config = cursor.fetchone()

            if current_config:
                # Actualizar configuración para asegurar funcionamiento
                cursor.execute("""
                               UPDATE vicidial_inbound_groups
                               SET active              = 'Y',
                                   get_call_launch     = 'NONE',
                                   agent_search_method = 'random',
                                   call_time_id        = '24hours',
                                   after_hours_action  = 'MESSAGE',
                                   no_agent_action     = 'MESSAGE'
                               WHERE group_id = 'colain'
                               """)

                connection.commit()
                print("✅ Configuración de grupo colain actualizada")

            # Verificar DID
            cursor.execute("""
                           SELECT *
                           FROM vicidial_inbound_dids
                           WHERE did_pattern = '5114125924'
                           """)

            did_config = cursor.fetchone()

        connection.close()

        return jsonify({
            'success': True,
            'current_config': current_config,
            'did_config': did_config,
            'message': 'Configuración verificada y actualizada'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/force_agent_ready/<int:agent_id>')
def force_agent_ready(agent_id):
    """Forzar agente a estado READY"""
    try:
        user = User.query.get_or_404(agent_id)

        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Verificar estado actual
            cursor.execute("""
                           SELECT user, status, campaign_id, closer_campaigns, conf_exten
                           FROM vicidial_live_agents
                           WHERE user = %s
                           """, (user.vicidial_user,))

            current_state = cursor.fetchone()

            if current_state:
                # Actualizar a READY
                cursor.execute("""
                               UPDATE vicidial_live_agents
                               SET status            = 'READY',
                                   last_state_change = NOW(),
                                   comments          = 'FORCED READY by CRM'
                               WHERE user = %s
                               """, (user.vicidial_user,))

                connection.commit()

                message = f"Agente {user.vicidial_user} forzado a READY"
                print(f"✅ {message}")

                # Actualizar estado local también
                user.agent_status = 'READY'
                db.session.commit()

            else:
                # Si no existe, crear entrada
                meetme_room = 8600051  # Usar sala por defecto

                cursor.execute("""
                               INSERT INTO vicidial_live_agents
                               (user, server_ip, conf_exten, status, lead_id, campaign_id,
                                uniqueid, callerid, channel, random_id, last_call_time,
                                last_call_finish, closer_campaigns, call_server_ip,
                                user_level, comments, calls_today, pause_code,
                                last_state_change, agent_log_id)
                               VALUES (%s, '195.26.249.9', %s, 'READY', 0, 'DEMOIN',
                                       '', '', '', FLOOR(RAND() * 10000000000), NOW(),
                                       NOW(), %s, '195.26.249.9',
                                       %s, %s, 0, '',
                                       NOW(), 0)
                               """, (
                                   user.vicidial_user,
                                   str(meetme_room),
                                   ' colain ',
                                   user.vicidial_user_level or 1,
                                   f'FORCED LOGIN READY'
                               ))

                connection.commit()
                message = f"Agente {user.vicidial_user} creado y puesto en READY"

        connection.close()

        return jsonify({
            'success': True,
            'message': message,
            'current_state': current_state,
            'agent_user': user.vicidial_user
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
@app.route('/debug_agent_sip/<int:agent_id>')
def debug_agent_sip(agent_id):
    """Debug completo del agente y SIP"""
    try:
        user = User.query.get_or_404(agent_id)
        extension = user.vicidial_phone_login

        debug_info = {
            'agent_user': user.vicidial_user,
            'extension': extension,
            'ami_connected': vicidial_ami.connected
        }

        if vicidial_ami.connected:
            # 1. Verificar si la extensión SIP existe
            sip_response = vicidial_ami.manager.send_action({
                'Action': 'SIPshowpeer',
                'Peer': extension
            })
            debug_info['sip_peer'] = str(sip_response)

            # 2. Verificar peers SIP registrados
            sip_peers = vicidial_ami.manager.send_action({
                'Action': 'SIPpeers'
            })
            debug_info['sip_peers'] = str(sip_peers)

            # 3. Verificar MeetMe disponible
            meetme_list = vicidial_ami.manager.send_action({
                'Action': 'MeetmeList'
            })
            debug_info['meetme_available'] = str(meetme_list)

            # 4. Test de MeetMe específico
            meetme_test = vicidial_ami.manager.send_action({
                'Action': 'MeetmeList',
                'Conference': '8600051'
            })
            debug_info['meetme_8600051'] = str(meetme_test)

        return jsonify({
            'success': True,
            'debug_info': debug_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


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


@socketio.on('agent_ready')
def on_agent_ready(data):
    """Agente se une a su sala"""
    extension = data['extension']
    join_room(f'agent_{extension}')
    emit('agent_joined', {'extension': extension})
    print(f"✅ Agente {extension} unido a sala WebSocket")


@socketio.on('test_call')
def on_test_call(data):
    """Enviar llamada de prueba"""
    extension = data['extension']

    fake_call = {
        'caller_id': '+51912345678',
        'phone_number': '+51912345678',
        'first_name': 'Juan',
        'last_name': 'Pérez',
        'city': 'Lima',
        'state': 'Lima',
        'lead_id': '12345',
        'campaign_id': 'DEMOIN'
    }

    emit('incoming_call', fake_call, room=f'agent_{extension}')
    print(f"📞 Llamada de prueba enviada a {extension}")


# ===== FUNCIONES MEETME PARA SIMULACIÓN VICIDIAL =====

def assign_meetme_room(agent_user):
    """Asignar sala MeetMe disponible"""
    try:
        # Buscar sala libre en rango 8600051-8600299
        for room in range(8600051, 8600100):  # Reducido para pruebas
            if is_meetme_room_free(room):
                print(f"🎯 Sala MeetMe {room} asignada a {agent_user}")
                return room

        # Si no hay salas libres, usar una por defecto
        fallback_room = 8600051
        print(f"⚠️ No hay salas libres, usando fallback: {fallback_room}")
        return fallback_room

    except Exception as e:
        print(f"❌ Error asignando sala MeetMe: {e}")
        return 8600051


def is_meetme_room_free(room_number):
    """Verificar si sala MeetMe está libre"""
    try:
        if not vicidial_ami.connected:
            print(f"⚠️ AMI no conectado, asumiendo sala {room_number} libre")
            return True

        # Verificar via AMI si la sala está en uso
        response = vicidial_ami.manager.send_action({
            'Action': 'MeetmeList',
            'Conference': str(room_number)
        })

        response_str = str(response)
        is_free = ('No active conferences' in response_str or
                   'No such conference' in response_str or
                   len(response_str) < 100)

        print(f"🔍 Sala {room_number}: {'LIBRE' if is_free else 'OCUPADA'}")
        return is_free

    except Exception as e:
        print(f"❌ Error verificando sala MeetMe {room_number}: {e}")
        return True  # Asumir que está libre si hay error


def connect_agent_to_meetme(extension, meetme_room):
    """Versión mejorada con fallbacks"""
    try:
        if not vicidial_ami.connected:
            print(f"⚠️ AMI no conectado, simulando conexión")
            return "SIMULATED"

        # Método 1: Originate directo
        print(f"🎯 Método 1: Originate directo SIP/{extension}")
        response1 = vicidial_ami.manager.send_action({
            'Action': 'Originate',
            'Channel': f'SIP/{extension}',
            'Context': 'default',
            'Exten': str(meetme_room),
            'Priority': '1',
            'CallerID': f'Conference <{extension}>',
            'Async': 'true',
            'Timeout': '15000'
        })
        print(f"📞 Respuesta Método 1: {response1}")

        if 'Error' not in str(response1):
            return response1

        # Método 2: Local channel
        print(f"🎯 Método 2: Local channel")
        response2 = vicidial_ami.manager.send_action({
            'Action': 'Originate',
            'Channel': f'Local/{extension}@from-internal',
            'Application': 'MeetMe',
            'Data': f'{meetme_room},M',
            'CallerID': f'Agent <{extension}>',
            'Async': 'true',
            'Timeout': '15000'
        })
        print(f"📞 Respuesta Método 2: {response2}")

        if 'Error' not in str(response2):
            return response2

        # Método 3: Simulación para desarrollo
        print(f"🎯 Método 3: Simulación (todos los métodos AMI fallaron)")

        # Emitir evento simulado
        socketio.emit('agent_auto_connected', {
            'extension': extension,
            'meetme_room': meetme_room,
            'method': 'simulated',
            'message': f'Agente {extension} "conectado" a MeetMe {meetme_room} (simulado)'
        })

        return "SIMULATED_SUCCESS"

    except Exception as e:
        print(f"❌ Error conectando {extension}: {e}")
        return False


def update_agent_conference(agent_user, meetme_room):
    """Actualizar BD con sala MeetMe asignada"""
    try:
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            # Actualizar conf_exten con el número de sala MeetMe
            cursor.execute("""
                           UPDATE vicidial_live_agents
                           SET conf_exten = %s,
                               comments   = %s
                           WHERE user = %s
                           """, (str(meetme_room), f'MeetMe {meetme_room} CRM', agent_user))

            connection.commit()
            print(f"✅ BD actualizada: Agente {agent_user} → MeetMe {meetme_room}")

        connection.close()

    except Exception as e:
        print(f"❌ Error actualizando conference en BD: {e}")


def disconnect_agent_from_meetme(extension, meetme_room=None):
    """Desconectar agente de sala MeetMe"""
    try:
        if not vicidial_ami.connected:
            print(f"⚠️ AMI no conectado, simulando desconexión de {extension}")
            return True

        # Opción 1: Hangup específico del canal SIP
        hangup_response = vicidial_ami.manager.send_action({
            'Action': 'Hangup',
            'Channel': f'SIP/{extension}',
            'Cause': '16'  # Normal call clearing
        })

        print(f"🔌 Agente {extension} desconectado de MeetMe")
        print(f"📞 Respuesta hangup: {hangup_response}")

        # Opción 2: Si tenemos el número de sala, kick del MeetMe
        if meetme_room:
            kick_response = vicidial_ami.manager.send_action({
                'Action': 'MeetmeKick',
                'Meetme': str(meetme_room),
                'Usernum': 'all'
            })
            print(f"👟 Kick de sala {meetme_room}: {kick_response}")

        return True

    except Exception as e:
        print(f"❌ Error desconectando {extension} de MeetMe: {e}")
        return False


def simulate_incoming_call_to_meetme(agent_user, caller_number="+51987654321"):
    """Simular llamada entrante que va directo a MeetMe del agente"""
    try:
        # Buscar en qué sala MeetMe está el agente
        connection = pymysql.connect(
            host='195.26.249.9',
            port=3306,
            user='custom',
            password='ldb0LBeham5VWkJ1shCbLNJIdX4',
            database='VIbdz0BWDgJBaoq',
            charset='utf8mb4'
        )

        with connection.cursor() as cursor:
            cursor.execute("""
                           SELECT conf_exten
                           FROM vicidial_live_agents
                           WHERE user = %s
                             AND status = 'READY'
                           """, (agent_user,))

            result = cursor.fetchone()

            if not result:
                print(f"❌ Agente {agent_user} no está READY o no encontrado")
                return False

            meetme_room = result[0]

        connection.close()

        if not meetme_room or meetme_room == '':
            print(f"❌ Agente {agent_user} no tiene sala MeetMe asignada")
            return False

        print(f"📞 Simulando llamada {caller_number} → MeetMe {meetme_room}")

        # Conectar llamada simulada a la sala MeetMe
        if vicidial_ami.connected:
            call_response = vicidial_ami.manager.send_action({
                'Action': 'Originate',
                'Channel': f'Local/{caller_number}@default',
                'Application': 'MeetMe',
                'Data': f'{meetme_room},q',  # Modo quiet (cliente solo habla)
                'CallerID': f'{caller_number}',
                'Async': 'true',
                'Timeout': '30000'
            })
            print(f"🎯 Llamada conectada a MeetMe: {call_response}")
        else:
            print(f"⚠️ AMI no conectado, simulando conexión a MeetMe {meetme_room}")

        return True

    except Exception as e:
        print(f"❌ Error simulando llamada a MeetMe: {e}")
        return False








if __name__ == '__main__':
    create_tables()  # Llamar aquí
    init_ami()  # Inicializar AMI
    init_realtime()  # Inicializar AMI tiempo real
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
import asterisk.manager
import threading
import time
from datetime import datetime
from flask_socketio import emit


class VicidialRealtime:
    def __init__(self, socketio):
        self.socketio = socketio
        self.ami = None
        self.connected = False
        self.active_calls = {}  # {channel: call_info}

    def connect_ami(self):
        """Conectar a AMI para eventos en tiempo real"""
        try:
            self.ami = asterisk.manager.Manager()
            self.ami.connect('195.26.249.9', 5038)
            self.ami.login('cron', '1234')
            self.connected = True

            # Registrar eventos importantes para call center
            self.ami.register_event('Newchannel', self.on_new_channel)
            self.ami.register_event('Hangup', self.on_hangup)
            self.ami.register_event('Bridge', self.on_bridge)
            self.ami.register_event('QueueMemberStatus', self.on_queue_member_status)

            print("✅ AMI Tiempo Real conectado")
            return True

        except Exception as e:
            print(f"❌ Error conectando AMI: {e}")
            return False

    def on_new_channel(self, event, manager):
        """Evento: Nuevo canal (llamada iniciando)"""
        channel = event.get('Channel', '')
        caller_id = event.get('CallerIDNum', '')
        context = event.get('Context', '')

        # Solo procesar llamadas de agentes SIP
        if 'SIP/' in channel and caller_id:
            extension = channel.split('/')[1].split('-')[0]

            call_info = {
                'channel': channel,
                'caller_id': caller_id,
                'extension': extension,
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'status': 'ringing'
            }

            self.active_calls[channel] = call_info

            # Enviar evento WebSocket al agente específico
            self.socketio.emit('incoming_call', call_info, room=f'agent_{extension}')
            print(f"📞 Nueva llamada: {caller_id} → Ext {extension}")

    def on_bridge(self, event, manager):
        """Evento: Llamada conectada (agente contestó)"""
        channel1 = event.get('Channel1', '')
        channel2 = event.get('Channel2', '')

        # Buscar cuál canal es del agente
        agent_channel = None
        if 'SIP/' in channel1:
            agent_channel = channel1
        elif 'SIP/' in channel2:
            agent_channel = channel2

        if agent_channel and agent_channel in self.active_calls:
            extension = agent_channel.split('/')[1].split('-')[0]

            self.active_calls[agent_channel]['status'] = 'connected'
            self.active_calls[agent_channel]['connect_time'] = datetime.now().strftime('%H:%M:%S')

            # Enviar evento de llamada conectada
            self.socketio.emit('call_connected', {
                'channel': agent_channel,
                'extension': extension,
                'status': 'connected',
                'connect_time': self.active_calls[agent_channel]['connect_time']
            }, room=f'agent_{extension}')

            print(f"✅ Llamada conectada: Ext {extension}")

    def on_hangup(self, event, manager):
        """Evento: Llamada terminada"""
        channel = event.get('Channel', '')
        cause = event.get('Cause', '')

        if channel in self.active_calls:
            call_info = self.active_calls[channel]
            extension = call_info['extension']

            # Enviar evento de llamada terminada
            self.socketio.emit('call_ended', {
                'channel': channel,
                'extension': extension,
                'cause': cause,
                'end_time': datetime.now().strftime('%H:%M:%S')
            }, room=f'agent_{extension}')

            # Remover de llamadas activas
            del self.active_calls[channel]
            print(f"📱 Llamada terminada: Ext {extension} (Causa: {cause})")

    def on_queue_member_status(self, event, manager):
        """Evento: Cambio de estado en cola"""
        interface = event.get('Interface', '')
        status = event.get('Status', '')

        if 'SIP/' in interface:
            extension = interface.split('/')[1]

            # Enviar cambio de estado
            self.socketio.emit('agent_status_change', {
                'extension': extension,
                'status': status,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })

            print(f"👤 Estado agente {extension}: {status}")

    def start_recording(self, channel, filename):
        """Iniciar grabación manual"""
        if not self.connected:
            return {'success': False, 'message': 'AMI no conectado'}

        try:
            response = self.ami.send_action({
                'Action': 'Monitor',
                'Channel': channel,
                'File': filename,
                'Mix': 'true',
                'Format': 'wav'
            })

            return {'success': True, 'message': f'Grabación iniciada: {filename}'}

        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}

    def stop_recording(self, channel):
        """Detener grabación"""
        if not self.connected:
            return {'success': False, 'message': 'AMI no conectado'}

        try:
            response = self.ami.send_action({
                'Action': 'StopMonitor',
                'Channel': channel
            })

            return {'success': True, 'message': 'Grabación detenida'}

        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}

    def transfer_call(self, channel, target_extension, context='default'):
        """Transferir llamada a otra extensión"""
        if not self.connected:
            return {'success': False, 'message': 'AMI no conectado'}

        try:
            response = self.ami.send_action({
                'Action': 'Transfer',
                'Channel': channel,
                'Exten': target_extension,
                'Context': context,
                'Priority': '1'
            })

            return {'success': True, 'message': f'Llamada transferida a {target_extension}'}

        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}

    def hangup_call(self, channel):
        """Colgar llamada específica"""
        if not self.connected:
            return {'success': False, 'message': 'AMI no conectado'}

        try:
            response = self.ami.send_action({
                'Action': 'Hangup',
                'Channel': channel
            })

            return {'success': True, 'message': 'Llamada colgada'}

        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}

    def get_active_channels(self):
        """Obtener canales activos"""
        if not self.connected:
            return []

        try:
            response = self.ami.send_action({
                'Action': 'CoreShowChannels'
            })

            # Procesar respuesta (esto es complejo, simplificado)
            return list(self.active_calls.values())

        except Exception as e:
            print(f"Error obteniendo canales: {e}")
            return []

    def disconnect(self):
        """Desconectar AMI"""
        if self.ami and self.connected:
            self.ami.close()
            self.connected = False
            print("🔌 AMI Tiempo Real desconectado")
import asterisk.manager
import threading
import time
from datetime import datetime


class VicidialAMI:
    def __init__(self):
        self.host = '195.26.249.9'
        self.port = 5038
        self.username = 'cron'
        self.secret = '1234'
        self.manager = None
        self.connected = False
        self.event_callbacks = {}

    def connect(self):
        """Conectar a Asterisk AMI"""
        try:
            self.manager = asterisk.manager.Manager()
            self.manager.connect(self.host, self.port)
            self.manager.login(self.username, self.secret)
            self.connected = True
            print(f"✅ Conectado a AMI: {self.host}:{self.port}")

            # Registrar eventos generales
            self.manager.register_event('*', self._event_handler)
            return True

        except Exception as e:
            print(f"❌ Error conectando AMI: {e}")
            return False

    def disconnect(self):
        """Desconectar de AMI"""
        if self.manager and self.connected:
            self.manager.close()
            self.connected = False
            print("🔌 Desconectado de AMI")

    def _event_handler(self, event, manager):
        """Manejar eventos entrantes"""
        event_name = event.name

        # Llamar callbacks específicos si existen
        if event_name in self.event_callbacks:
            for callback in self.event_callbacks[event_name]:
                callback(event)

        # Log de eventos importantes
        if event_name in ['Newchannel', 'Hangup', 'AgentConnect', 'QueueMemberStatus']:
            try:
                event_data = {}
                for key in event.headers:
                    event_data[key] = event[key]
                print(f"📡 Evento AMI: {event_name} - {event_data}")
            except Exception as e:
                print(f"📡 Evento AMI: {event_name} - Error parsing: {e}")

    def register_event_callback(self, event_name, callback):
        """Registrar callback para evento específico"""
        if event_name not in self.event_callbacks:
            self.event_callbacks[event_name] = []
        self.event_callbacks[event_name].append(callback)

    def agent_login(self, agent_user, extension, queue='DEMOIN'):
        """Login de agente en cola"""
        try:
            # Agregar agente a la cola
            response = self.manager.send_action({
                'Action': 'QueueAdd',
                'Queue': queue,
                'Interface': f'SIP/{extension}',
                'MemberName': agent_user,
                'Penalty': '1'
            })

            result_dict = dict(response) if hasattr(response, '__dict__') else response
            print(f"🔑 Login agente {agent_user} en {queue}: {result_dict}")

            # Verificar si fue exitoso
            if hasattr(response, 'get') and response.get('Response') == 'Success':
                return True
            elif str(response).lower().find('success') != -1:
                return True
            else:
                print(f"❌ Login falló: {result_dict}")
                return False

        except Exception as e:
            print(f"❌ Error login agente: {e}")
            return False

    def agent_logout(self, agent_user, extension, queue='DEMOIN'):
        """Logout de agente de cola"""
        try:
            response = self.manager.send_action({
                'Action': 'QueueRemove',
                'Queue': queue,
                'Interface': f'SIP/{extension}'
            })

            print(f"🚪 Logout agente {agent_user} de {queue}: {response}")
            return response

        except Exception as e:
            print(f"❌ Error logout agente: {e}")
            return None

    def pause_agent(self, extension, queue='DEMOIN', reason='Break'):
        """Pausar agente en cola"""
        try:
            response = self.manager.send_action({
                'Action': 'QueuePause',
                'Interface': f'SIP/{extension}',
                'Queue': queue,
                'Paused': 'true',
                'Reason': reason
            })

            print(f"⏸️ Agente {extension} pausado: {response}")
            return response

        except Exception as e:
            print(f"❌ Error pausar agente: {e}")
            return None

    def unpause_agent(self, extension, queue='DEMOIN'):
        """Despausar agente en cola"""
        try:
            response = self.manager.send_action({
                'Action': 'QueuePause',
                'Interface': f'SIP/{extension}',
                'Queue': queue,
                'Paused': 'false'
            })

            print(f"▶️ Agente {extension} despausado: {response}")
            return response

        except Exception as e:
            print(f"❌ Error despausar agente: {e}")
            return None

    def get_queue_status(self, queue='DEMOIN'):
        """Obtener estado de cola"""
        try:
            response = self.manager.send_action({
                'Action': 'QueueStatus',
                'Queue': queue
            })

            print(f"📊 Estado cola {queue}: {response}")
            return response

        except Exception as e:
            print(f"❌ Error estado cola: {e}")
            return None

    def originate_call(self, extension, number, context='default'):
        """Originar llamada desde extensión"""
        try:
            response = self.manager.send_action({
                'Action': 'Originate',
                'Channel': f'SIP/{extension}',
                'Exten': number,
                'Context': context,
                'Priority': '1',
                'CallerID': f'{extension} <{extension}>',
                'Timeout': '30000'
            })

            print(f"📞 Llamada iniciada {extension} → {number}: {response}")
            return response

        except Exception as e:
            print(f"❌ Error originar llamada: {e}")
            return None

    def hangup_call(self, channel):
        """Colgar llamada específica"""
        try:
            response = self.manager.send_action({
                'Action': 'Hangup',
                'Channel': channel
            })

            print(f"📱 Llamada colgada {channel}: {response}")
            return response

        except Exception as e:
            print(f"❌ Error colgar llamada: {e}")
            return None

    def get_channels(self):
        """Obtener canales activos"""
        try:
            response = self.manager.send_action({
                'Action': 'CoreShowChannels'
            })

            return response

        except Exception as e:
            print(f"❌ Error obtener canales: {e}")
            return None

    def start_monitor(self, channel, filename):
        """Iniciar grabación de llamada"""
        try:
            response = self.manager.send_action({
                'Action': 'Monitor',
                'Channel': channel,
                'File': filename,
                'Mix': 'true'
            })

            print(f"🎙️ Grabación iniciada {channel}: {filename}")
            return response

        except Exception as e:
            print(f"❌ Error iniciar grabación: {e}")
            return None

    def show_queues(self):
        """Mostrar todas las colas disponibles"""
        try:
            response = self.manager.send_action({
                'Action': 'QueueShow'
            })

            print(f"📋 Colas disponibles: {dict(response) if hasattr(response, '__dict__') else response}")
            return response

        except Exception as e:
            print(f"❌ Error mostrar colas: {e}")
            return None

    def show_sip_peers(self):
        """Mostrar peers SIP disponibles"""
        try:
            response = self.manager.send_action({
                'Action': 'SIPshowpeer',
                'Peer': '2000'
            })

            print(f"📞 Peer SIP 2000: {dict(response) if hasattr(response, '__dict__') else response}")
            return response

        except Exception as e:
            print(f"❌ Error mostrar SIP peer: {e}")
            return None


# Ejemplo de uso
if __name__ == "__main__":
    ami = VicidialAMI()

    if ami.connect():
        # Registrar callback para eventos de cola
        def queue_event_handler(event):
            print(f"🔔 Evento de cola: {event.name} - {dict(event)}")


        ami.register_event_callback('QueueMemberStatus', queue_event_handler)
        ami.register_event_callback('AgentConnect', queue_event_handler)

        # Ejemplo: Login de agente
        # ami.agent_login('carlos2025', '1080', 'DEMOIN')

        # Mantener conexión activa
        try:
            print("🎯 AMI activo. Presiona Ctrl+C para salir...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            ami.disconnect()
    else:
        print("❌ No se pudo conectar a AMI")
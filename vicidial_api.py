import requests
import json
from datetime import datetime
from config import Config


class VicidialAPI:
    def __init__(self):
        self.host = Config.VICIDIAL_HOST
        self.api_url = Config.VICIDIAL_API_URL
        self.agent_api_url = Config.VICIDIAL_AGENT_API_URL
        self.api_user = Config.VICIDIAL_API_USER
        self.api_pass = Config.VICIDIAL_API_PASS
        self.session = requests.Session()

    def _make_request(self, url, params):
        """Hacer petición a la API de Vicidial"""
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error en petición a Vicidial: {e}")
            return None

    def _build_query_string(self, params):
        """Helper para construir query string para debug"""
        return '&'.join([f"{k}={v}" for k, v in params.items()])

    def create_agent(self, agent_data):
        """Crear agente en Vicidial"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'add_user',
            'agent_user': agent_data['vicidial_user'],
            'agent_pass': agent_data['vicidial_user_pass'],
            'agent_user_level': agent_data.get('vicidial_user_level', 1),
            'agent_full_name': f"{agent_data.get('name', '')}",
            'agent_user_group': agent_data.get('vicidial_user_group', 'ADMIN'),
            'agent_phone_login': agent_data['vicidial_phone_login'],
            'agent_phone_pass': agent_data['vicidial_phone_pass'],
        }

        response = self._make_request(self.api_url, params)
        print(f"URL usuario: {self.api_url}?{self._build_query_string(params)}")
        return response

    def create_phone(self, phone_data):
        """Crear teléfono en Vicidial"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'add_phone',
            'extension': phone_data['vicidial_phone_login'],
            'dialplan_number': phone_data['vicidial_phone_login'],
            'voicemail_id': phone_data['vicidial_phone_login'],
            'phone_login': phone_data['vicidial_phone_login'],
            'phone_pass': phone_data['vicidial_phone_pass'],
            'server_ip': '195.26.249.9',
            'protocol': 'SIP',
            'registration_password': phone_data['vicidial_phone_pass'],
            'phone_full_name': f"Phone {phone_data['vicidial_phone_login']}",
            'local_gmt': '-5.00',
            'outbound_cid': '5551234567'
        }

        response = self._make_request(self.api_url, params)
        print(f"URL teléfono: {self.api_url}?{self._build_query_string(params)}")
        return response

    def create_agent_complete(self, agent_data):
        """Crear agente y teléfono en Vicidial"""
        # Crear usuario
        user_response = self.create_agent(agent_data)
        print(f"Respuesta usuario: {user_response}")

        # Crear teléfono
        phone_response = self.create_phone(agent_data)
        print(f"Respuesta teléfono: {phone_response}")

        # Actualizar usuario para agregar phone_login y phone_pass
        update_response = self.update_user_phone(agent_data)
        print(f"Respuesta actualización: {update_response}")

        return {
            'user_response': user_response,
            'phone_response': phone_response,
            'update_response': update_response
        }

    def update_user_phone(self, agent_data):
        """Actualizar usuario para agregar phone_login y phone_pass"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'update_user',
            'agent_user': agent_data['vicidial_user'],  # Obligatorio para identificar el usuario
            'phone_login': agent_data['vicidial_phone_login'],  # Campo a actualizar
            'phone_pass': agent_data['vicidial_phone_pass'],  # Campo a actualizar
            'full_name': f"{agent_data.get('name', '')}",
            'user_level': agent_data.get('vicidial_user_level', 1),
            'user_group': agent_data.get('vicidial_user_group', 'ADMIN'),
        }

        response = self._make_request(self.api_url, params)
        print(f"URL actualización: {self.api_url}?{self._build_query_string(params)}")
        return response

    def update_agent(self, agent_data):
        """Actualizar agente en Vicidial"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'update_user',
            'user_id': agent_data['vicidial_user'],
            'pass': agent_data['vicidial_user_pass'],
            'full_name': f"{agent_data.get('name', '')} {agent_data.get('lastName', '')}",
            'user_level': agent_data.get('vicidial_user_level', 1),
            'user_group': agent_data.get('vicidial_user_group', 'ADMIN'),
            'phone_login': agent_data['vicidial_phone_login'],
            'phone_pass': agent_data['vicidial_phone_pass'],
            'email': agent_data.get('email', ''),
            'custom_one': agent_data.get('id', ''),
        }

        return self._make_request(self.api_url, params)

    def delete_agent(self, user_id):
        """Eliminar agente de Vicidial"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'delete_user',
            'user_id': user_id
        }

        return self._make_request(self.api_url, params)

    def agent_login(self, user_id, password, phone_login, phone_pass, campaign=None):
        """Login de agente usando non_agent_api.php"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'external_login',
            'user_id': user_id,
            'password': password,
            'phone_login': phone_login,
            'phone_pass': phone_pass,
        }

        if campaign:
            params['campaign'] = campaign

        return self._make_request(self.api_url, params)

    def agent_logout(self, user_id):
        """Logout de agente usando non_agent_api.php"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'external_logout',
            'user_id': user_id
        }

        return self._make_request(self.api_url, params)

    def set_agent_status(self, user_id, status, pause_code=None):
        """Cambiar estado del agente (READY, PAUSED, etc.)"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'change_agent_status',
            'user_id': user_id,
            'status': status
        }

        if pause_code and status == 'PAUSED':
            params['pause_code'] = pause_code

        return self._make_request(self.api_url, params)

    def get_agent_status(self, user_id):
        """Obtener estado actual del agente"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'user_status',
            'user_id': user_id
        }

        return self._make_request(self.api_url, params)

    def get_campaigns(self):
        """Obtener lista de campañas"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'campaigns_list'
        }

        return self._make_request(self.api_url, params)

    def get_inbound_groups(self):
        """Obtener grupos de entrada (closer groups)"""
        params = {
            'version': '2.14',
            'source': 'crm',
            'user': self.api_user,
            'pass': self.api_pass,
            'function': 'inbound_group_list'
        }

        return self._make_request(self.api_url, params)
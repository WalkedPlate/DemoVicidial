import pymysql
import time
import json
from datetime import datetime
from config import Config

class VicidialCallMonitor:
    def __init__(self):
        self.host = Config.VICIDIAL_DB_HOST
        self.port = Config.VICIDIAL_DB_PORT
        self.user = Config.VICIDIAL_DB_USER
        self.password = Config.VICIDIAL_DB_PASS
        self.database = Config.VICIDIAL_DB_NAME
        self.connection = None

    def connect(self):
        """Conectar a la base de datos de Vicidial"""
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4'
            )
            print("✅ Conectado a base de datos Vicidial")
            return True
        except Exception as e:
            print(f"❌ Error conectando a BD: {e}")
            return False

    def get_live_agents(self):
        """Obtener agentes activos en tiempo real"""
        try:
            with self.connection.cursor() as cursor:
                query = """
                SELECT 
                    user,
                    status,
                    campaign_id,
                    conf_exten,
                    server_ip,
                    last_call_time,
                    calls_today,
                    pause_code,
                    last_state_change
                FROM vicidial_live_agents 
                WHERE status != 'LOGOUT'
                ORDER BY last_state_change DESC
                """
                cursor.execute(query)
                agents = cursor.fetchall()

                # Convertir a lista de diccionarios
                agent_list = []
                columns = [desc[0] for desc in cursor.description]
                for agent in agents:
                    agent_dict = dict(zip(columns, agent))
                    # Convertir datetime a string para JSON
                    for key, value in agent_dict.items():
                        if isinstance(value, datetime):
                            agent_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    agent_list.append(agent_dict)

                return agent_list
        except Exception as e:
            print(f"❌ Error obteniendo agentes: {e}")
            return []

    def get_live_calls(self):
        """Obtener llamadas activas en tiempo real"""
        try:
            with self.connection.cursor() as cursor:
                query = """
                SELECT 
                    vac.uniqueid,
                    vac.lead_id,
                    vac.agent_user,
                    vac.status,
                    vac.campaign_id,
                    vac.phone_number,
                    vac.server_ip,
                    vac.start_time,
                    vac.channel,
                    vl.first_name,
                    vl.last_name,
                    vl.city,
                    vl.state,
                    vl.address1
                FROM vicidial_auto_calls vac
                LEFT JOIN vicidial_list vl ON vac.lead_id = vl.lead_id
                WHERE vac.status IN ('LIVE', 'QUEUE', 'INCALL', 'RING')
                ORDER BY vac.start_time DESC
                """
                cursor.execute(query)
                calls = cursor.fetchall()

                # Convertir a lista de diccionarios
                call_list = []
                columns = [desc[0] for desc in cursor.description]
                for call in calls:
                    call_dict = dict(zip(columns, call))
                    # Convertir datetime a string para JSON
                    for key, value in call_dict.items():
                        if isinstance(value, datetime):
                            call_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    call_list.append(call_dict)

                return call_list
        except Exception as e:
            print(f"❌ Error obteniendo llamadas: {e}")
            return []

    def get_agent_calls(self, agent_user):
        """Obtener llamadas específicas de un agente"""
        try:
            with self.connection.cursor() as cursor:
                query = """
                SELECT 
                    vac.uniqueid,
                    vac.lead_id,
                    vac.status,
                    vac.campaign_id,
                    vac.phone_number,
                    vac.start_time,
                    vl.first_name,
                    vl.last_name,
                    vl.city,
                    vl.state
                FROM vicidial_auto_calls vac
                LEFT JOIN vicidial_list vl ON vac.lead_id = vl.lead_id
                WHERE vac.agent_user = %s 
                AND vac.status IN ('LIVE', 'QUEUE', 'INCALL', 'RING')
                ORDER BY vac.start_time DESC
                """
                cursor.execute(query, (agent_user,))
                calls = cursor.fetchall()

                call_list = []
                columns = [desc[0] for desc in cursor.description]
                for call in calls:
                    call_dict = dict(zip(columns, call))
                    for key, value in call_dict.items():
                        if isinstance(value, datetime):
                            call_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    call_list.append(call_dict)

                return call_list
        except Exception as e:
            print(f"❌ Error obteniendo llamadas de agente: {e}")
            return []

    def get_campaign_stats(self, campaign_id='DEMOIN'):
        """Obtener estadísticas de campaña"""
        try:
            with self.connection.cursor() as cursor:
                # Llamadas en cola
                cursor.execute("""
                    SELECT COUNT(*) as calls_in_queue
                    FROM vicidial_auto_calls 
                    WHERE campaign_id = %s AND status = 'QUEUE'
                """, (campaign_id,))
                queue_calls = cursor.fetchone()[0]

                # Agentes disponibles
                cursor.execute("""
                    SELECT COUNT(*) as available_agents
                    FROM vicidial_live_agents 
                    WHERE campaign_id = %s AND status = 'READY'
                """, (campaign_id,))
                available_agents = cursor.fetchone()[0]

                # Agentes en llamada
                cursor.execute("""
                    SELECT COUNT(*) as agents_in_call
                    FROM vicidial_live_agents
                    WHERE campaign_id = %s AND status = 'INCALL'
                """, (campaign_id,))
                agents_in_call = cursor.fetchone()[0]

                return {
                    'campaign_id': campaign_id,
                    'calls_in_queue': queue_calls,
                    'available_agents': available_agents,
                    'agents_in_call': agents_in_call,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
        except Exception as e:
            print(f"❌ Error obteniendo stats de campaña: {e}")
            return {}

    def get_recent_calls(self, limit=10):
        """Obtener llamadas recientes (últimas completadas)"""
        try:
            with self.connection.cursor() as cursor:
                query = """
                SELECT 
                    vcl.uniqueid,
                    vcl.lead_id,
                    vcl.user,
                    vcl.campaign_id,
                    vcl.phone_number,
                    vcl.start_time,
                    vcl.end_time,
                    vcl.length_in_sec,
                    vcl.status,
                    vl.first_name,
                    vl.last_name
                FROM vicidial_call_log vcl
                LEFT JOIN vicidial_list vl ON vcl.lead_id = vl.lead_id
                WHERE vcl.start_time >= CURDATE()
                ORDER BY vcl.start_time DESC
                LIMIT %s
                """
                cursor.execute(query, (limit,))
                calls = cursor.fetchall()

                call_list = []
                columns = [desc[0] for desc in cursor.description]
                for call in calls:
                    call_dict = dict(zip(columns, call))
                    for key, value in call_dict.items():
                        if isinstance(value, datetime):
                            call_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    call_list.append(call_dict)

                return call_list
        except Exception as e:
            print(f"❌ Error obteniendo llamadas recientes: {e}")
            return []

    def close(self):
        """Cerrar conexión"""
        if self.connection:
            self.connection.close()
            print("🔌 Conexión BD cerrada")

# Ejemplo de uso
if __name__ == "__main__":
    monitor = VicidialCallMonitor()

    if monitor.connect():
        print("🎯 Monitoreando llamadas...")

        while True:
            print(f"\n--- {datetime.now().strftime('%H:%M:%S')} ---")

            # Agentes activos
            agents = monitor.get_live_agents()
            print(f"👥 Agentes activos: {len(agents)}")
            for agent in agents:
                print(f"   {agent['user']}: {agent['status']} ({agent['campaign_id']})")

            # Llamadas en vivo
            calls = monitor.get_live_calls()
            print(f"📞 Llamadas activas: {len(calls)}")
            for call in calls:
                customer_name = f"{call.get('first_name', '')} {call.get('last_name', '')}"
                print(f"   {call['phone_number']} -> {call['agent_user']} ({customer_name})")

            # Stats de campaña
            stats = monitor.get_campaign_stats('DEMOIN')
            print(f"📊 DEMOIN: {stats.get('calls_in_queue', 0)} en cola, {stats.get('available_agents', 0)} disponibles")

            time.sleep(3)  # Actualizar cada 3 segundos
    else:
        print("❌ No se pudo conectar al monitor")
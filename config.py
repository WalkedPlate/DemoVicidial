import os


class Config:
    # Flask config
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database config
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'mysql://user:password@localhost/crm_vicidial'

    # Vicidial API config
    VICIDIAL_HOST = 'cc-demo.xyzconn.xyz'
    VICIDIAL_IP = '195.26.249.9'
    VICIDIAL_API_URL = f'https://{VICIDIAL_HOST}/vicidial/non_agent_api.php'
    VICIDIAL_AGENT_API_URL = f'https://{VICIDIAL_HOST}/vicidial/non_agent_api.php'  # Misma API

    # Database Vicidial (conexión directa)
    VICIDIAL_DB_HOST = '195.26.249.9'
    VICIDIAL_DB_NAME = 'VIbdz0BWDgJBaoq'
    VICIDIAL_DB_USER = 'custom'
    VICIDIAL_DB_PASS = 'ldb0LBeham5VWkJ1shCbLNJIdX4'
    VICIDIAL_DB_PORT = 3306

    # Credenciales de prueba Vicidial (usando el campo 'user' correcto)
    VICIDIAL_API_USER = 'agalindez'  # Campo 'user', no 'user_id'
    VICIDIAL_API_PASS = 'lkajsjkhasASASDIASOASoaisas'  # Password correcto

    # Configuración de agentes por defecto
    DEFAULT_USER_LEVEL = 1
    DEFAULT_USER_GROUP = 'ADMIN'  # Usar ADMIN ya que AGENTS no existe
    DEFAULT_PHONE_TIMEOUT = 25

    # Asterisk AMI (si necesitas funciones avanzadas)
    ASTERISK_HOST = VICIDIAL_HOST
    ASTERISK_AMI_PORT = 5038
    ASTERISK_AMI_USER = 'admin'  # Usuario AMI
    ASTERISK_AMI_SECRET = 'amp111'  # Secret AMI
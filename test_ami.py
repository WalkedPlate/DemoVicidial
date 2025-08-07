from vicidial_ami import VicidialAMI

ami = VicidialAMI()
if ami.connect():
    print("🎉 Conexión AMI exitosa!")

    # Probar estado de cola
    ami.get_queue_status('DEMOIN')

    ami.disconnect()
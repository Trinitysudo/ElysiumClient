import os
def get_info():
    return {
        'name': 'App Config',
        'description': 'Internal configuration for the client.',
        'category': 'system', # This is not displayed in the UI
        'execution_mode': 'system', # Tells the app to handle it differently
        'settings': {
            'minecraft_path': { 'default': os.path.join(os.getenv('APPDATA'), '.minecraft'), 'description': 'The path to your main .minecraft folder.' },
            'minecraft_version': { 'default': '1.21', 'description': 'Your Minecraft version.' },
            'mod_loader': { 'default': 'fabric', 'description': 'Your mod loader (fabric or forge).' }
        }
    }
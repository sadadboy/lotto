import zipfile
import os

def create_release_zip():
    files_to_include = [
        'Dockerfile',
        'docker-compose.yml',
        'requirements.txt',
        'main.py',
        'buy_lotto.py',
        'strategies.py',
        'auth.py',
        'notification.py',
        'security.py'
    ]
    
    dirs_to_include = [
        'dashboard'
    ]
    
    zip_filename = 'lotto-bot-release.zip'
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add individual files
        for file in files_to_include:
            if os.path.exists(file):
                zipf.write(file)
                print(f"Added: {file}")
            else:
                print(f"Warning: {file} not found!")
        
        # Add directories
        for directory in dirs_to_include:
            if os.path.exists(directory):
                for root, _, files in os.walk(directory):
                    for file in files:
                        if '__pycache__' in root:
                            continue
                        file_path = os.path.join(root, file)
                        zipf.write(file_path)
                        print(f"Added: {file_path}")
            else:
                print(f"Warning: {directory} not found!")
                
    print(f"\n✅ Created {zip_filename} successfully!")

if __name__ == "__main__":
    create_release_zip()

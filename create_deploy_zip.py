import zipfile
import os

def create_zip():
    zip_filename = "lotto_bot_deploy.zip"
    
    # Files to include
    include_files = [
        'main.py', 'auth.py', 'deposit.py', 'lotto.py', 'notification.py', 'security.py', 'strategies.py',
        'requirements.txt', 'Dockerfile', 'docker-compose.yml', 'config.json', 'secret.key', '.env'
    ]
    
    # Directories to include (recursive)
    include_dirs = ['dashboard']
    
    # Exclude patterns
    exclude_patterns = ['__pycache__', '.git', '.venv', '*.log', '*.png', '*.zip']

    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add individual files
        for file in include_files:
            if os.path.exists(file):
                print(f"Adding {file}...")
                zipf.write(file)
            else:
                print(f"Warning: {file} not found.")

        # Add directories
        for directory in include_dirs:
            if os.path.exists(directory):
                print(f"Adding directory {directory}...")
                for root, dirs, files in os.walk(directory):
                    # Filter out excluded directories
                    dirs[:] = [d for d in dirs if d not in exclude_patterns]
                    
                    for file in files:
                        if any(file.endswith(ext.replace('*', '')) for ext in exclude_patterns):
                            continue
                        
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.getcwd()) # Relative path in zip
                        # Ensure dashboard/ prefix is kept but not full absolute path
                        # Actually relpath does this correctly if we are in root.
                        # But we want 'dashboard/app.py' not 'dashboard/app.py' inside 'lotto' folder if we were outside.
                        # Since we run from root, arcname will be 'dashboard/app.py'.
                        print(f"Adding {file_path} as {arcname}")
                        zipf.write(file_path, arcname)
            else:
                print(f"Warning: Directory {directory} not found.")

    print(f"\n✅ Created {zip_filename} successfully!")

if __name__ == "__main__":
    create_zip()

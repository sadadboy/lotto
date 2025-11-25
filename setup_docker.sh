#!/bin/bash

# Update system
echo "📦 Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y

# Install prerequisites
echo "🛠️ Installing prerequisites..."
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common

# Install Docker
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add current user to docker group (to run without sudo)
echo "👤 Adding user to docker group..."
sudo usermod -aG docker $USER

# Install Docker Compose
echo "🐙 Installing Docker Compose..."
sudo apt-get install -y docker-compose-plugin

# Clean up
rm get-docker.sh

echo "✅ Docker installation complete!"
echo "⚠️ Please LOG OUT and LOG BACK IN for group changes to take effect."

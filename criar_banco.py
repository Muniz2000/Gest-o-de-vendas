# criar_banco.py
from app import app, db  # Importar tanto o app quanto o db

# Usar o contexto da aplicação para criar o banco de dados
with app.app_context():
    db.create_all()  # Cria as tabelas no banco de dados
    print("Banco de dados criado com sucesso!")

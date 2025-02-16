from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import os
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64

# Inicialização do app Flask
app = Flask(__name__)

# Configuração do banco de dados SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vendas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicialização do banco de dados
db = SQLAlchemy(app)

# Modelo da Tabela de Vendas
class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)

# Criar banco de dados (caso ainda não tenha sido criado)
with app.app_context():
    db.create_all()

# Caminho fixo da planilha
PLANILHA_PATH = r"C:\Users\Josep\Desktop\Trabalho PI\VENDAS.xlsx"

# Função para carregar os dados da planilha para o banco de dados
def carregar_dados():
    if not os.path.exists(PLANILHA_PATH):
        return "Erro: Planilha não encontrada."

    try:
        df = pd.read_excel(PLANILHA_PATH)

        # Verificar se a planilha tem as colunas corretas
        colunas_esperadas = {"Produto", "Quantidade", "Categoria"}
        if not colunas_esperadas.issubset(df.columns):
            return "Erro: A planilha não contém as colunas necessárias."

        # Exibir os dados da planilha para depuração
        print("Conteúdo da Planilha:")
        print(df.head())

        # Apagar os dados antigos antes de carregar os novos
        db.session.query(Venda).delete()
        db.session.commit()

        # Adicionar os dados ao banco
        for _, row in df.iterrows():
            nova_venda = Venda(produto=row["Produto"], quantidade=row["Quantidade"], categoria=row["Categoria"])
            db.session.add(nova_venda)

        db.session.commit()
        return "Dados carregados com sucesso!"
    
    except Exception as e:
        return f"Erro ao processar a planilha: {e}"

# Função para converter gráficos em Base64
def converter_grafico_para_base64(fig):
    img = io.BytesIO()
    fig.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode()

# Função para gerar gráfico de linhas
def gerar_grafico_linhas():
    vendas = Venda.query.all()
    if not vendas:
        return None

    produtos = [v.produto for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    plt.figure(figsize=(6, 4))
    sns.lineplot(x=produtos, y=quantidades, marker='o')
    plt.xticks(rotation=45)
    plt.xlabel('Produto')
    plt.ylabel('Quantidade')
    plt.title('Vendas por Produto')

    return converter_grafico_para_base64(plt)

# Função para gerar gráfico de barras
def gerar_grafico_barras():
    vendas = Venda.query.all()
    if not vendas:
        return None

    produtos = [v.produto for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    plt.figure(figsize=(6, 4))
    sns.barplot(x=produtos, y=quantidades)
    plt.xticks(rotation=45)
    plt.xlabel('Produto')
    plt.ylabel('Quantidade')
    plt.title('Vendas por Produto')

    return converter_grafico_para_base64(plt)

# Função para gerar gráfico de pizza
def gerar_grafico_pizza():
    vendas = Venda.query.all()
    if not vendas:
        return None

    categorias = [v.categoria for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    plt.figure(figsize=(6, 4))
    plt.pie(quantidades, labels=categorias, autopct='%1.1f%%', startangle=90)
    plt.title('Distribuição de Vendas')

    return converter_grafico_para_base64(plt)

# Rota principal - Exibe os dados cadastrados
@app.route('/')
def home():
    vendas = Venda.query.all()
    
    # Gerar gráficos
    grafico_linhas = gerar_grafico_linhas()
    grafico_barras = gerar_grafico_barras()
    grafico_pizza = gerar_grafico_pizza()

    # Teste: verificar se os gráficos estão sendo gerados
    print("Gráfico de Linhas:", grafico_linhas[:100])  # Mostra os primeiros 100 caracteres
    print("Gráfico de Barras:", grafico_barras[:100])  # Evita que o terminal fique poluído
    print("Gráfico de Pizza:", grafico_pizza[:100])  

    return render_template(
        'index.html',
        vendas=vendas,
        grafico_linhas=grafico_linhas,
        grafico_barras=grafico_barras,
        grafico_pizza=grafico_pizza
    )


# Rota para carregar os dados automaticamente da planilha para o banco
@app.route('/carregar', methods=['GET'])
def carregar():
    mensagem = carregar_dados()
    return render_template('index.html', vendas=Venda.query.all(), mensagem=mensagem)

# Rota para excluir uma venda da planilha e do banco de dados
@app.route('/excluir/<string:produto>', methods=['GET'])
def excluir(produto):
    if not os.path.exists(PLANILHA_PATH):
        return "Erro: Planilha não encontrada", 404

    try:
        df = pd.read_excel(PLANILHA_PATH)

        if "Produto" not in df.columns:
            return "Erro: A planilha não contém a coluna 'Produto'", 400

        # Verifica se o produto existe no banco antes de excluir
        venda = Venda.query.filter_by(produto=produto).first()
        if not venda:
            return "Erro: Produto não encontrado no banco de dados.", 404

        # Remove a venda do banco de dados
        db.session.delete(venda)
        db.session.commit()

        # Remove do Excel e salva novamente
        df = df[df["Produto"] != produto]
        df.to_excel(PLANILHA_PATH, index=False)

        return redirect(url_for('home'))
    except Exception as e:
        return f"Erro ao excluir venda: {e}", 500

# Executa o servidor Flask
if __name__ == '__main__':
    app.run(debug=True, port=5001)
# Definindo a constante no início do código
NAO_GERADO = "Não gerado"

# Importações e outras configurações
import matplotlib
matplotlib.use('Agg')  # Configuração do backend para evitar o erro com Tkinter
import matplotlib.pyplot as plt

from flask import Flask, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
import os
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64

# Caminho fixo da planilha
PLANILHA_PATH = r"C:\Users\Josep\Desktop\Trabalho PI\VENDAS.xlsx"

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

# Função para carregar os dados da planilha para o banco de dados
def carregar_dados():
    if not os.path.exists(PLANILHA_PATH):
        return "Erro: Planilha não encontrada."
    try:
        df = pd.read_excel(PLANILHA_PATH, engine='openpyxl')
        colunas_esperadas = {"Produto", "Quantidade", "Categoria"}
        if not colunas_esperadas.issubset(df.columns):
            return "Erro: A planilha não contém as colunas necessárias."
        db.session.query(Venda).delete()
        db.session.commit()
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
    fig.savefig(img, format='png', bbox_inches='tight')  # Evita corte do gráfico
    img.seek(0)
    plt.close(fig)  # Fecha a figura para evitar sobreposição de gráficos
    return base64.b64encode(img.getvalue()).decode()

# Função para gerar gráfico de linhas (Vendas por Produto)
def gerar_grafico_linhas():
    vendas = Venda.query.all()
    if not vendas:
        print(f"⚠ Aviso: Nenhuma venda encontrada para gerar o gráfico de linhas. {NAO_GERADO}")
        return NAO_GERADO

    produtos = [v.produto for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    fig, ax = plt.subplots(figsize=(6, 4))
    sns.lineplot(x=produtos, y=quantidades, marker='o', ax=ax)

    # Define ticks antes dos labels (corrige o UserWarning)
    ax.set_xticks(range(len(produtos)))
    ax.set_xticklabels(produtos, rotation=45, ha='right')

    ax.set_xlabel('Produto')
    ax.set_ylabel('Quantidade')
    ax.set_title('Vendas por Produto')

    return converter_grafico_para_base64(fig)


# Função para gerar gráfico de barras (Vendas por Produto)
def gerar_grafico_barras():
    vendas = Venda.query.all()
    if not vendas:
        print(f"⚠ Aviso: Nenhuma venda encontrada para gerar o gráfico de barras. {NAO_GERADO}")
        return NAO_GERADO

    produtos = [v.produto for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    # Paleta personalizada
    cores = sns.color_palette("husl", len(produtos))

    fig, ax = plt.subplots(figsize=(6, 4))

    # Usa hue para manter cores sem FutureWarning
    sns.barplot(
        x=produtos,
        y=quantidades,
        hue=produtos,
        legend=False,
        palette=cores,
        ax=ax
    )

    # Define ticks antes dos labels
    ax.set_xticks(range(len(produtos)))
    ax.set_xticklabels(produtos, rotation=45, ha='right')

    ax.set_xlabel('Produto')
    ax.set_ylabel('Quantidade')
    ax.set_title('Vendas por Produto')

    return converter_grafico_para_base64(fig)


# Usando uma paleta de cores para o gráfico de barras
    cores = sns.color_palette("husl", len(produtos))  # Pode substituir "Set2" por outras paletas

    fig, ax = plt.subplots(figsize=(6, 4))
    
    sns.barplot(x=produtos, y=quantidades, ax=ax, palette=cores)  # Aplicando a paleta de cores
    sns.barplot(x=produtos, y=quantidades, ax=ax)
    ax.set_xticklabels(produtos, rotation=45)
    ax.set_xlabel('Produto')
    ax.set_ylabel('Quantidade')
    ax.set_title('Vendas por Produto')

    return converter_grafico_para_base64(fig)

# Função para gerar gráfico de pizza (Distribuição de Vendas)
def gerar_grafico_pizza():
    vendas = Venda.query.all()
    if not vendas:
        print(f"⚠ Aviso: Nenhuma venda encontrada para gerar o gráfico de pizza. {NAO_GERADO}")
        return NAO_GERADO

    categorias = [v.categoria for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.pie(quantidades, labels=categorias, autopct='%1.1f%%', startangle=90)
    ax.set_title('Distribuição de Vendas')

    return converter_grafico_para_base64(fig)

@app.route('/')
def home():
    vendas = Venda.query.all()
    grafico_linhas = gerar_grafico_linhas()
    grafico_barras = gerar_grafico_barras()
    grafico_pizza = gerar_grafico_pizza()

    print("✅ Gráfico de Linhas:", "Gerado" if grafico_linhas != NAO_GERADO else NAO_GERADO)
    print("✅ Gráfico de Barras:", "Gerado" if grafico_barras != NAO_GERADO else NAO_GERADO)
    print("✅ Gráfico de Pizza:", "Gerado" if grafico_pizza != NAO_GERADO else NAO_GERADO)

    return render_template('index.html', vendas=vendas, grafico_linhas=grafico_linhas, grafico_barras=grafico_barras, grafico_pizza=grafico_pizza)

@app.route('/carregar', methods=['GET'])
def carregar():
    carregar_dados()
    return redirect(url_for('home'))

@app.route('/excluir/<string:produto>', methods=['GET'])
def excluir(produto):
    if not os.path.exists(PLANILHA_PATH):
        return "Erro: Planilha não encontrada", 404
    try:
        df = pd.read_excel(PLANILHA_PATH, engine='openpyxl')
        if "Produto" not in df.columns:
            return "Erro: A planilha não contém a coluna 'Produto'", 400
        venda = Venda.query.filter_by(produto=produto).first()
        if not venda:
            return "Erro: Produto não encontrado no banco de dados.", 404
        db.session.delete(venda)
        db.session.commit()
        df_filtrado = df[df["Produto"] != produto]
        df_filtrado.to_excel(PLANILHA_PATH, index=False, engine='openpyxl')
        return redirect(url_for('home'))
    except PermissionError:
        return "Erro: Permissão negada ao acessar o arquivo. Feche a planilha e tente novamente.", 500
    except Exception as e:
        return f"Erro ao excluir venda: {e}", 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
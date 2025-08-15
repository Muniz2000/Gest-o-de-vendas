from __future__ import annotations
from google.api_core.exceptions import NotFound

# =========================
# Config & Imports
# =========================
import io
import os
import logging
from typing import Tuple, Optional, List

import matplotlib
matplotlib.use("Agg")  # backend headless para servidores
import matplotlib.pyplot as plt

import pandas as pd
from flask import Flask, redirect, url_for, request, render_template, abort
from flask_sqlalchemy import SQLAlchemy
from google.cloud import storage

NAO_GERADO = "Não gerado"

# =========================
# Application Factory
# =========================
def create_app() -> Flask:
    app = Flask(__name__)

    # Config padrão (pode sobrescrever via env)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///vendas.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        GCS_BUCKET_NAME=os.getenv("GCS_BUCKET_NAME", "").strip(),
        GCS_BLOB_NAME=os.getenv("GCS_BLOB_NAME", "").strip(),
        SYNC_BACK_TO_GCS=os.getenv("SYNC_BACK_TO_GCS", "false").lower() == "true",
    )

    # Logs mais verbosos em dev
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    register_routes(app)
    return app

# =========================
# Database (SQLAlchemy)
# =========================
db = SQLAlchemy()


class Venda(db.Model):
    __tablename__ = "vendas"

    id = db.Column(db.Integer, primary_key=True)
    produto = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)

    def to_tuple(self) -> Tuple[str, int, str]:
        return (self.produto, self.quantidade, self.categoria)


# =========================
# GCS Helpers
# =========================
REQUIRED_COLS = {"Produto", "Quantidade", "Categoria"}


def _get_gcs_client() -> storage.Client:
    """
    Usa credenciais padrão do ambiente.
    Certifique-se de definir GOOGLE_APPLICATION_CREDENTIALS se necessário.
    """
    return storage.Client()


def read_xls_from_gcs(bucket_name: str, blob_name: str) -> pd.DataFrame:
    """
    Baixa um XLS/XLSX do GCS e retorna um DataFrame validado usando ADC.
    """
    if not bucket_name or not blob_name:
        raise ValueError("GCS_BUCKET_NAME e GCS_BLOB_NAME são obrigatórios.")

    client = _get_gcs_client()  # usa ADC automaticamente
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    try:
        data: bytes = blob.download_as_bytes(timeout=60)  # faz 1 chamada com auth ADC
    except NotFound:
        raise FileNotFoundError(f"Blob não encontrado: gs://{bucket_name}/{blob_name}")

    bio = io.BytesIO(data)
    df = pd.read_excel(bio)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"A planilha não contém as colunas necessárias: {sorted(missing)}")

    df["Produto"] = df["Produto"].astype(str).str.strip()
    df["Quantidade"] = pd.to_numeric(df["Quantidade"], errors="coerce").fillna(0).astype(int)
    df["Categoria"] = df["Categoria"].astype(str).str.strip()
    return df

def write_xls_to_gcs(df: pd.DataFrame, bucket_name: str, blob_name: str) -> None:
    """
    Sobrescreve o XLS no GCS com o conteúdo do DataFrame.
    Usado apenas quando SYNC_BACK_TO_GCS=true.
    """
    client = _get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    with io.BytesIO() as output:
        # Usa ExcelWriter para preservar formato Excel
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        blob.upload_from_file(output, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =========================
# Data Loaders
# =========================
def carregar_dados_do_gcs(app: Flask) -> int:
    """
    Carrega o XLS do GCS para o banco local.
    Retorna a quantidade de linhas inseridas.
    """
    bucket = app.config["GCS_BUCKET_NAME"]
    blob = app.config["GCS_BLOB_NAME"]
    app.logger.info("Carregando XLS do GCS: gs://%s/%s", bucket, blob)

    df = read_xls_from_gcs(bucket, blob)

    with app.app_context():
        # Tranca tabela e substitui (simples) — em produção considere upsert por chave
        db.session.query(Venda).delete()
        insert_count = 0
        for _, row in df.iterrows():
            v = Venda(
                produto=str(row["Produto"]),
                quantidade=int(row["Quantidade"]),
                categoria=str(row["Categoria"]),
            )
            db.session.add(v)
            insert_count += 1
        db.session.commit()

    app.logger.info("Carregamento concluído: %d registros", insert_count)
    return insert_count


def dump_db_to_dataframe() -> pd.DataFrame:
    """
    Exporta a tabela 'vendas' para DataFrame com as colunas esperadas.
    """
    vendas: List[Venda] = Venda.query.order_by(Venda.id.asc()).all()
    if not vendas:
        return pd.DataFrame(columns=list(REQUIRED_COLS))
    data = [{
        "Produto": v.produto,
        "Quantidade": v.quantidade,
        "Categoria": v.categoria
    } for v in vendas]
    return pd.DataFrame(data, columns=["Produto", "Quantidade", "Categoria"])


# =========================
# Plot Helpers
# =========================
def fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    import base64
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def grafico_barras() -> str:
    vendas: List[Venda] = Venda.query.all()
    if not vendas:
        return NAO_GERADO

    produtos = [v.produto for v in vendas]
    quantidades = [v.quantidade for v in vendas]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(produtos, quantidades)
    ax.set_xlabel("Produto")
    ax.set_ylabel("Quantidade")
    ax.set_title("Vendas por Produto")
    ax.set_xticklabels(produtos, rotation=45, ha="right")
    return fig_to_base64(fig)


def grafico_pizza() -> str:
    vendas: List[Venda] = Venda.query.all()
    if not vendas:
        return NAO_GERADO

    # Distribuição por categoria
    df = pd.DataFrame([v.to_tuple() for v in vendas], columns=["Produto", "Quantidade", "Categoria"])
    dist = df.groupby("Categoria")["Quantidade"].sum().sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(dist.values, labels=dist.index, autopct="%1.1f%%", startangle=90)
    ax.set_title("Distribuição de Vendas por Categoria")
    ax.axis("equal")
    return fig_to_base64(fig)


def register_routes(app: Flask) -> None:
    @app.route("/")
    def index():
        vendas = Venda.query.order_by(Venda.id.asc()).all()
        try:
            chart_barras = grafico_barras()
            chart_pizza = grafico_pizza()
        except Exception as e:
            app.logger.exception("Falha ao gerar gráficos")
            return render_template("index.html", vendas=vendas, chart_barras=chart_barras, chart_pizza=chart_pizza, error=None)

        return render_template("index.html", vendas=vendas, 
                               chart_barras=chart_barras, chart_pizza=chart_pizza, 
                               error=None)

    @app.route("/carregar", methods=["GET"])
    def carregar():
        try:
            n = carregar_dados_do_gcs(app)
            app.logger.info("Recarregado %d registros do GCS", n)
            return redirect(url_for("index"))
        except Exception as e:
            app.logger.exception("Erro ao carregar do GCS")
            vendas = Venda.query.order_by(Venda.id.asc()).all()
            chart_barras = grafico_barras()
            chart_pizza = grafico_pizza()
            return render_template("index.html", vendas=vendas,
                                chart_barras=chart_barras, chart_pizza=chart_pizza,
                                error=str(e)), 500


    @app.route("/excluir/<int:id>", methods=["GET"])
    def excluir(id: int):
        v = Venda.query.get(id)
        if not v:
            abort(404, description="Venda não encontrada")

        # Remove do banco
        db.session.delete(v)
        db.session.commit()
        app.logger.info("Removido ID=%s (%s)", id, v.produto)

        # Opcional: sincroniza de volta para o XLS no bucket
        if app.config["SYNC_BACK_TO_GCS"]:
            try:
                df = dump_db_to_dataframe()
                write_xls_to_gcs(
                    df=df,
                    bucket_name=app.config["GCS_BUCKET_NAME"],
                    blob_name=app.config["GCS_BLOB_NAME"],
                )
                app.logger.info("XLS atualizado no GCS após exclusão (SYNC_BACK_TO_GCS=true).")
            except Exception:
                app.logger.exception("Falha ao sincronizar XLS no GCS após exclusão.")

        return redirect(url_for("index"))

    @app.route("/healthz", methods=["GET"])
    def healthz():
        # Checagem simples de saúde do app e do DB
        try:
            db.session.execute(db.text("SELECT 1"))
            return {"status": "ok"}, 200
        except Exception as e:
            app.logger.exception("Healthcheck falhou")
            return {"status": "error", "detail": str(e)}, 500


# =========================
# Entrypoint
# =========================
app = create_app()

if __name__ == "__main__":
    # Porta padrão 5001 (como no teu código)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")

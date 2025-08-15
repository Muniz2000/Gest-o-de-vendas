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
    try:
        vendas: List[Venda] = Venda.query.all()
        if not vendas:
            return NAO_GERADO

        # --- base de dados
        df = pd.DataFrame(
            [(v.produto, v.quantidade) for v in vendas],
            columns=["Produto", "Quantidade"]
        )
        dist = (
            df.groupby("Produto")["Quantidade"]
              .sum()
              .sort_values(ascending=False)
        )

        # --- top N + "Outros"
        N_BARS = 12
        if len(dist) > N_BARS:
            top = dist.iloc[:N_BARS]
            outros_total = dist.iloc[N_BARS:].sum()
            if outros_total > 0:
                dist = pd.concat([top, pd.Series({"Outros": outros_total})])

        nomes = dist.index.tolist()
        valores = dist.values.tolist()
        total = int(sum(valores))

        # --- tema dark (consistente com seu CSS)
        bg = "#0A0A0A"       # body
        panel = "#111214"    # card/surface
        text = "#E5E7EB"     # texto claro
        line = "#23252B"     # borda/grid

        # paleta coerente com o gráfico de pizza
        palette = [
            "#60A5FA", "#34D399", "#A78BFA", "#38BDF8", "#F59E0B",
            "#F472B6", "#22D3EE", "#F87171", "#10B981", "#C084FC",
            "#93C5FD", "#2DD4BF", "#FB7185"
        ][:len(nomes)]

        # --- plot
        import numpy as np
        def _short(s: str, n: int = 18) -> str:
            return s if len(s) <= n else s[:n - 1] + "…"
        nomes_short = [_short(n) for n in nomes]
        x = np.arange(len(nomes_short))

        fig, ax = plt.subplots(figsize=(9.5, 5.6), facecolor=bg)
        ax.set_facecolor(panel)

        bars = ax.bar(
            x, valores,
            color=palette,
            edgecolor=line,
            linewidth=0.8
        )

        # grade sutil
        ax.yaxis.grid(True, which="major", linestyle="-", linewidth=0.7, color=line, alpha=0.55)
        ax.xaxis.grid(False)

        # rótulos e títulos
        ax.set_title("Quantidade por Produto", color=text, fontsize=12, pad=14, weight="600")
        ax.set_xlabel("Produto", color=text, labelpad=8)
        ax.set_ylabel("Quantidade", color=text, labelpad=8)

        ax.set_xticks(x)
        ax.set_xticklabels(nomes_short, rotation=35, ha="right", color=text, fontsize=10)
        ax.tick_params(axis="y", colors=text)

        # spines
        for spine in ax.spines.values():
            spine.set_color(line)

        # espaço no topo para os labels
        ax.margins(y=0.18)

        # labels de valor acima das barras (omite se barra muito pequena)
        ymax = max(valores) if valores else 1
        for rect, v in zip(bars, valores):
            if v <= 0:
                continue
            if v < ymax * 0.04:  # evita poluição visual
                continue
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_height() + (ymax * 0.02),
                f"{v}",
                ha="center", va="bottom",
                color=text, fontsize=10, fontweight="600"
            )

        fig.tight_layout(pad=1.2)
        return fig_to_base64(fig)

    except Exception:
        import traceback
        traceback.print_exc()
        return NAO_GERADO



def grafico_pizza() -> str:
    try:
        vendas: List[Venda] = Venda.query.all()
        if not vendas:
            return NAO_GERADO

        # DataFrame base
        df = pd.DataFrame([v.to_tuple() for v in vendas], columns=["Produto", "Quantidade", "Categoria"])
        dist = df.groupby("Categoria")["Quantidade"].sum().sort_values(ascending=False)

        # Agrupa a cauda longa em "Outros" (mantém os 7 mais representativos)
        if len(dist) > 7:
            top = dist.iloc[:7]
            outros_total = dist.iloc[7:].sum()
            if outros_total > 0:
                dist = pd.concat([top, pd.Series({"Outros": outros_total})])

        # Paleta pensada para dark (azuis/cianos/roxos/verdes/laranja)
        palette = [
            "#60A5FA", "#34D399", "#A78BFA", "#38BDF8", "#F59E0B",
            "#F472B6", "#22D3EE", "#F87171", "#10B981", "#C084FC"
        ][:len(dist)]

        total = int(dist.sum())

        # Cores e fundo combinando com seu CSS (dark)
        bg = "#0A0A0A"       # body
        panel = "#111214"    # card/surface
        text = "#E5E7EB"     # texto claro
        line = "#23252B"     # borda

        fig, ax = plt.subplots(figsize=(7, 7), facecolor=bg)
        ax.set_facecolor(panel)

        # função para mostrar porcentagem (e valor) apenas se o slice for relevante
        def _autopct(pct):
            if pct < 5:  # esconde rótulos muito pequenos
                return ""
            val = int(round(pct/100.0 * total))
            return f"{pct:.1f}%\n({val})"

        wedges, texts, autotexts = ax.pie(
            dist.values,
            # donut
            wedgeprops=dict(width=0.42, edgecolor=line, linewidth=0.8),
            startangle=90,
            colors=palette,
            # rótulos nos slices ficam limpos; legenda traz nomes/valores
            labels=None,
            autopct=_autopct,
            pctdistance=0.75,
            textprops=dict(color=text, fontsize=11, fontweight="600"),
        )

        # centro do donut com total
        ax.text(
            0, 0, f"Total\n{total}",
            ha="center", va="center",
            fontsize=13, fontweight="700", color=text
        )

        # Título neutro (sem “vendas”)
        ax.set_title("Distribuição por Categoria", color=text, fontsize=12, pad=16)
        ax.axis("equal")

        # Legenda à direita com categoria + soma
        legend_labels = [f"{cat} — {qty}" for cat, qty in dist.items()]
        leg = ax.legend(
            wedges, legend_labels,
            title="Categorias",
            title_fontsize=11, fontsize=10,
            loc="center left", bbox_to_anchor=(1.02, 0.5),
            frameon=True
        )
        # ajusta a moldura da legenda para o dark
        leg.get_frame().set_facecolor(panel)
        leg.get_frame().set_edgecolor(line)

        fig.tight_layout(pad=1.2)
        return fig_to_base64(fig)

    except Exception:
        import traceback
        print("Erro ao gerar gráfico de pizza:")
        traceback.print_exc()
        return NAO_GERADO




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
    
    @app.route("/adicionar", methods=["POST"])
    def adicionar():
        produto = request.form.get("produto", "").strip()
        quantidade_raw = request.form.get("quantidade", "").strip()
        categoria = request.form.get("categoria", "").strip()

        # validação simples
        if not produto or not categoria:
            app.logger.warning("Campos obrigatórios ausentes ao adicionar: produto/categoria")
            vendas = Venda.query.order_by(Venda.id.asc()).all()
            return render_template(
                "index.html",
                vendas=vendas,
                chart_barras=grafico_barras(),
                chart_pizza=grafico_pizza(),
                error="Produto e categoria são obrigatórios."
            ), 400

        try:
            quantidade = int(quantidade_raw)
            if quantidade < 1:
                raise ValueError("Quantidade deve ser >= 1")
        except Exception:
            vendas = Venda.query.order_by(Venda.id.asc()).all()
            return render_template(
                "index.html",
                vendas=vendas,
                chart_barras=grafico_barras(),
                chart_pizza=grafico_pizza(),
                error="Quantidade inválida."
            ), 400

        try:
            # grava no banco
            v = Venda(produto=produto, quantidade=quantidade, categoria=categoria)
            db.session.add(v)
            db.session.commit()
            app.logger.info("Adicionado ID=%s (%s)", v.id, v.produto)

            # sincroniza de volta para o XLS no bucket (opcional)
            if app.config["SYNC_BACK_TO_GCS"]:
                try:
                    df = dump_db_to_dataframe()  # banco -> DataFrame com colunas ["Produto","Quantidade","Categoria"]
                    write_xls_to_gcs(
                        df=df,
                        bucket_name=app.config["GCS_BUCKET_NAME"],
                        blob_name=app.config["GCS_BLOB_NAME"],
                    )
                    app.logger.info("XLS atualizado no GCS após inclusão (SYNC_BACK_TO_GCS=true).")
                except Exception:
                    app.logger.exception("Falha ao sincronizar XLS no GCS após inclusão.")

            return redirect(url_for("index"))

        except Exception as e:
            app.logger.exception("Erro ao adicionar produto")
            vendas = Venda.query.order_by(Venda.id.asc()).all()
            return render_template(
                "index.html",
                vendas=vendas,
                chart_barras=grafico_barras(),
                chart_pizza=grafico_pizza(),
                error=str(e)
            ), 500



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

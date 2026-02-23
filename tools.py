"""
Tools que consultam o CSV de defeitos de pintura e geram visualizações.
"""

import csv
import os
from collections import Counter

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "defeitos.csv")


def _ler_csv():
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def contar_defeitos(tipo_defeito=None):
    """Conta defeitos, opcionalmente filtrado por tipo."""
    rows = _ler_csv()
    if tipo_defeito:
        count = sum(1 for r in rows if r["tipo_defeito"] == tipo_defeito)
        return {"tipo_defeito": tipo_defeito, "total": count}
    counter = Counter(r["tipo_defeito"] for r in rows)
    return {"total": len(rows), "por_tipo": dict(counter.most_common())}


def top_defeitos(n=5):
    """Devolve os N defeitos mais frequentes (Pareto)."""
    rows = _ler_csv()
    counter = Counter(r["tipo_defeito"] for r in rows)
    top = counter.most_common(n)
    total = len(rows)
    return {
        "total_registos": total,
        "top": [
            {"tipo": t, "total": c, "percentagem": round(c / total * 100, 1)}
            for t, c in top
        ],
    }


def defeitos_por_turno(turno=None):
    """Conta defeitos agrupados por turno. Pode filtrar por turno específico."""
    rows = _ler_csv()
    if turno:
        rows = [r for r in rows if r["turno"] == turno]
    result = {}
    for r in rows:
        t = r["turno"]
        if t not in result:
            result[t] = Counter()
        result[t][r["tipo_defeito"]] += 1
    return {
        "por_turno": {
            k: {"total": sum(v.values()), "defeitos": dict(v.most_common())}
            for k, v in result.items()
        }
    }


# --- Render tools (pass-through, interceptadas pelo agent_engine) ---


def gerar_grafico(tipo: str, titulo: str, etiquetas: list, valores: list, dataset_label: str = ""):
    """Gera um gráfico no chat. Não faz computação, apenas passa dados ao frontend."""
    return {
        "widget": "chart",
        "tipo": tipo,
        "titulo": titulo,
        "etiquetas": etiquetas,
        "valores": valores,
        "dataset_label": dataset_label,
    }


def gerar_tabela(titulo: str, colunas: list, linhas: list):
    """Gera uma tabela formatada no chat."""
    return {
        "widget": "table",
        "titulo": titulo,
        "colunas": colunas,
        "linhas": linhas,
    }


def gerar_kpi(titulo: str, valor: str, unidade: str = "", variacao: str = ""):
    """Gera um cartão KPI no chat."""
    return {
        "widget": "kpi",
        "titulo": titulo,
        "valor": valor,
        "unidade": unidade,
        "variacao": variacao,
    }


def gerar_dashboard(titulo: str, html: str):
    """Gera um dashboard HTML completo acessível por link. O backend guarda e serve a página."""
    return {
        "widget": "dashboard",
        "titulo": titulo,
        "html": html,
    }

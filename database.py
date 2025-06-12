import sqlite3
from datetime import datetime

DB_PATH = "database.db"

def criar_tabela():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS historico_ponto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        acao TEXT NOT NULL,
        hora TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

def adicionar_acao(user_id: str, acao: str, hora: str = None):
    hora = hora or datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO historico_ponto (user_id, acao, hora) VALUES (?, ?, ?)", (user_id, acao, hora))
    conn.commit()
    conn.close()

def buscar_historico(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT acao, hora FROM historico_ponto WHERE user_id = ? ORDER BY id ASC", (user_id,))
    registros = c.fetchall()
    conn.close()
    return [{"acao": acao, "hora": hora} for acao, hora in registros]

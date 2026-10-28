"""Respaldo consistente de webui.db: corre dentro del contenedor de Open WebUI (ver bakers/README.md)."""
import sqlite3
src = sqlite3.connect("/app/backend/data/webui.db")
dst = sqlite3.connect("/tmp/webui-respaldo.db")
src.backup(dst)
n = dst.execute("select count(*) from chat").fetchone()[0]
dst.close(); src.close()
print("chats", n)

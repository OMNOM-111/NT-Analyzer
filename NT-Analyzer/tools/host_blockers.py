#!/usr/bin/env python3
"""Rows in RESTRICT-guarded tables that block deleting each non-owner account."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
CURRENT={"canary":"/home/stratforge/canary-current","production":"/home/stratforge/current"}
PROGRAMS={"canary":"api","production":"api-app"}
def load_env(e):
    out=subprocess.check_output(["sudo","-n","supervisorctl","-c",
        "/home/stratforge/production_data/config/supervisord.conf","status"],text=True,timeout=30)
    pid=0
    for line in out.splitlines():
        p=line.split()
        if len(p)>=4 and p[0]==PROGRAMS[e] and p[1]=="RUNNING": pid=int(p[3].rstrip(","))
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(bytes([0])):
        if item and b"=" in item:
            k,_,v=item.partition(b"="); os.environ[k.decode()]=v.decode("utf-8","replace")
env=sys.argv[1]; owner=int(sys.argv[2]); load_env(env); sys.path.insert(0,CURRENT[env])
import psycopg
with psycopg.connect(os.environ["STRATFORGE_DATABASE_URL"], autocommit=True) as conn:
    conn.execute("SET stratforge.service_scope='global'")
    fks=conn.execute("""
      select cl.relname, att.attname, con.confdeltype,
             (select typname from pg_type t where t.oid=att.atttypid)
      from pg_constraint con
      join pg_class cl on cl.oid=con.conrelid
      join pg_class pr on pr.oid=con.confrelid
      join unnest(con.conkey) k(attnum) on true
      join pg_attribute att on att.attrelid=cl.oid and att.attnum=k.attnum
      where con.contype='f' and pr.relname='sf_users' and con.confdeltype='r'
        and con.convalidated
      order by cl.relname
    """).fetchall()
    doomed=[r[0] for r in conn.execute(
        "select user_id from sf_users where user_id <> %s", (owner,)).fetchall()]
    print(f"owner={owner}  doomed={doomed}\n")
    print("RESTRICT-guarded tables (these block a delete):")
    for table,col,_d,typ in fks:
        if typ not in ("int4","int8","numeric"):
            continue
        rows=conn.execute(
            f"select {col}, count(*) from {table} where {col} = any(%s) group by {col}",
            (doomed,)).fetchall()
        total=conn.execute(f"select count(*) from {table}").fetchone()[0]
        held={int(u):int(n) for u,n in rows}
        flag=" <<< BLOCKS" if held else ""
        print(f"  {table:32}.{col:22} total={total:5} held_by_doomed={held}{flag}")
